"""stock-agent 전용 Codex OAuth 세션과 기기 코드 로그인 CLI."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Any, Iterator

import httpx
from dotenv import load_dotenv


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE_URL = "https://auth.openai.com"
DEVICE_VERIFICATION_URL = f"{AUTH_BASE_URL}/codex/device"
DEVICE_LOGIN_TIMEOUT = 15 * 60
REFRESH_SKEW_SECONDS = 60
LOCK_TIMEOUT_SECONDS = 60
LOGIN_COMMAND = "python -m stock_agent.gateways.codex_auth login"


class CodexAuthError(RuntimeError):
    """토큰과 서버 본문을 포함하지 않는 인증·저장소 오류."""


@dataclass(frozen=True)
class CodexCredentials:
    """모델 요청용 토큰·계정·만료 시각이며 repr에는 토큰을 표시하지 않는다."""

    access_token: str = field(repr=False)
    account_id: str
    expires_at: float


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise CodexAuthError("Codex 인증 정보의 필수 필드가 올바르지 않습니다.")
    return value


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise CodexAuthError("Codex 인증 정보의 시간 값이 올바르지 않습니다.") from None
    if isinstance(value, bool) or not math.isfinite(result) or result < 0:
        raise CodexAuthError("Codex 인증 정보의 시간 값이 올바르지 않습니다.")
    return result


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, UnicodeError):
        raise CodexAuthError("Codex 인증 서버 응답을 읽을 수 없습니다.") from None
    if not isinstance(data, dict):
        raise CodexAuthError("Codex 인증 서버 응답 형식이 올바르지 않습니다.")
    return data


def _post(path: str, *, timeout: float = 30, **kwargs: Any) -> httpx.Response:
    try:
        return httpx.post(f"{AUTH_BASE_URL}{path}", timeout=timeout, **kwargs)
    except httpx.HTTPError:
        raise CodexAuthError("Codex 인증 서버 연결에 실패했습니다. 네트워크를 확인한 뒤 다시 시도하세요.") from None


def _token_record(response: httpx.Response, refresh_token: str | None = None) -> dict[str, Any]:
    if not response.is_success:
        raise CodexAuthError(
            f"Codex 인증 갱신 또는 로그인에 실패했습니다 (HTTP {response.status_code}). "
            f"다시 로그인하세요: {LOGIN_COMMAND}"
        )
    data = _json(response)
    access_token = _string(data, "access_token")
    try:
        payload = access_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        account_id = _string(claims["https://api.openai.com/auth"], "chatgpt_account_id")
    except (ValueError, UnicodeError, IndexError, KeyError, TypeError, AttributeError):
        raise CodexAuthError("Codex 토큰에서 계정을 확인할 수 없습니다. 다시 로그인하세요.") from None
    return {
        "access_token": access_token,
        "refresh_token": _string({"refresh_token": data.get("refresh_token", refresh_token)}, "refresh_token"),
        "account_id": account_id,
        "expires_at": time.time() + _number(data.get("expires_in")),
    }


def _credentials(record: dict[str, Any]) -> CodexCredentials:
    return CodexCredentials(
        access_token=_string(record, "access_token"),
        account_id=_string(record, "account_id"),
        expires_at=_number(record.get("expires_at")),
    )


class CodexAuth:
    """다른 앱과 분리된 OAuth 파일을 읽고 잠금 아래에서 토큰을 갱신한다.

    path를 생략하면 CODEX_AUTH_PATH 또는 ~/.config/stock-agent/codex-auth.json을
    사용한다. 네트워크·파일 오류는 비밀 값이 없는 CodexAuthError로 전달한다.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("CODEX_AUTH_PATH") or "~/.config/stock-agent/codex-auth.json").expanduser()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        # flock은 각각 연 파일 디스크립터 사이의 스레드·프로세스 갱신을 직렬화한다.
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise CodexAuthError("Codex 인증 저장소 잠금을 열 수 없습니다. 경로와 권한을 확인하세요.") from None
        try:
            os.fchmod(fd, 0o600)
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise CodexAuthError("다른 Codex 인증 작업의 잠금 대기 시간이 초과되었습니다. 잠시 후 다시 시도하세요.") from None
                    time.sleep(0.05)
            yield
        except OSError:
            raise CodexAuthError("Codex 인증 파일 작업에 실패했습니다. 경로와 권한을 확인하세요.") from None
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any] | None:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise CodexAuthError("Codex 인증 파일은 현재 사용자 소유의 일반 파일이며 권한이 600이어야 합니다.")
                record = json.load(file)
            if not isinstance(record, dict):
                raise ValueError
            _credentials(record)
            _string(record, "refresh_token")
            return record
        except FileNotFoundError:
            return None
        except (OSError, ValueError, UnicodeError):
            raise CodexAuthError(f"Codex 인증 파일을 읽을 수 없습니다. 다시 로그인하세요: {LOGIN_COMMAND}") from None

    def _save(self, record: dict[str, Any]) -> None:
        # 동일 디렉터리에서 600 임시 파일을 교체해 중간 내용이 노출되지 않게 한다.
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".codex-auth-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                os.fchmod(file.fileno(), 0o600)
                json.dump(record, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise CodexAuthError("Codex 인증 정보를 저장할 수 없습니다. 경로와 권한을 확인하세요.") from None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)

    def credentials(
        self, *, force_refresh: bool = False, rejected_access_token: str | None = None,
    ) -> CodexCredentials:
        """최신 파일의 자격 증명을 반환하고 만료 임박 시 한 번 갱신·저장한다.

        force_refresh는 서버가 토큰을 거부했을 때 사용한다. rejected_access_token과
        현재 저장 토큰이 다르면 다른 요청의 갱신 결과를 재사용한다. 인증 누락,
        잠금 시간 초과, 갱신 실패는 CodexAuthError이며 API Key로 전환하지 않는다.
        """
        with self._lock():
            record = self._read()
            if record is None:
                raise CodexAuthError(f"Codex 구독 로그인이 필요합니다: {LOGIN_COMMAND}")
            current = _credentials(record)
            rejected = force_refresh and (
                rejected_access_token is None or rejected_access_token == current.access_token
            )
            if current.expires_at > time.time() + REFRESH_SKEW_SECONDS and not rejected:
                return current
            refreshed = _token_record(
                _post("/oauth/token", data={
                    "grant_type": "refresh_token",
                    "refresh_token": record["refresh_token"],
                    "client_id": CLIENT_ID,
                }),
                refresh_token=record["refresh_token"],
            )
            self._save(refreshed)
            return _credentials(refreshed)

    def status(self) -> CodexCredentials | None:
        """파일만 읽어 저장된 자격 증명 또는 None을 반환하며 갱신·네트워크 호출은 하지 않는다."""
        record = self._read()
        return _credentials(record) if record is not None else None

    def logout(self) -> None:
        """잠금 아래에서 이 프로젝트의 로컬 토큰만 삭제하며 서버의 세션은 폐기하지 않는다."""
        with self._lock():
            self.path.unlink(missing_ok=True)

    def login(self) -> CodexCredentials:
        """기기 코드·URL을 터미널에 출력하고 최대 15분 기다린 뒤 별도 세션을 저장한다.

        Ctrl-C로 취소할 수 있다. 로그인 실패·만료 시 기존 파일을 보존하며
        CodexAuthError를 전달한다. 성공 시 모델 요청에 쓸 자격 증명을 반환한다.
        """
        deadline = time.monotonic() + DEVICE_LOGIN_TIMEOUT
        response = _post("/api/accounts/deviceauth/usercode", json={"client_id": CLIENT_ID})
        if not response.is_success:
            raise CodexAuthError(
                f"Codex 기기 코드 발급 실패 (HTTP {response.status_code}). "
                "ChatGPT 보안 설정 또는 워크스페이스에서 기기 코드 로그인을 활성화하세요."
            )
        device = _json(response)
        device_id = _string(device, "device_auth_id")
        user_code = _string(device, "user_code")
        interval = max(1.0, _number(device.get("interval", 5)))
        print(f"브라우저에서 {DEVICE_VERIFICATION_URL} 를 열고 기기 코드를 입력하세요: {user_code}", flush=True)
        print("로그인 대기 중입니다. 취소: Ctrl-C (최대 15분)", flush=True)
        while time.monotonic() < deadline:
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            response = _post("/api/accounts/deviceauth/token", timeout=min(30, remaining), json={
                "device_auth_id": device_id, "user_code": user_code,
            })
            if response.is_success:
                authorization = _json(response)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                record = _token_record(_post("/oauth/token", timeout=min(30, remaining), data={
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "code": _string(authorization, "authorization_code"),
                    "code_verifier": _string(authorization, "code_verifier"),
                    "redirect_uri": f"{AUTH_BASE_URL}/deviceauth/callback",
                }))
                with self._lock():
                    self._save(record)
                return _credentials(record)
            try:
                error = _json(response).get("error")
            except CodexAuthError:
                error = None
            if isinstance(error, dict):
                error = error.get("code")
            if error in ("authorization_pending", "deviceauth_authorization_pending"):
                continue
            if error == "slow_down":
                interval += 5
                continue
            if response.status_code in (403, 404) and error is None:
                continue
            raise CodexAuthError(f"Codex 기기 코드 로그인이 거부되었거나 만료되었습니다 (HTTP {response.status_code}). 다시 로그인하세요.")
        raise CodexAuthError("Codex 기기 코드 로그인 대기 시간이 만료되었습니다. 다시 로그인하세요.")


def main() -> int:
    """login/status/logout CLI를 실행하며 비밀 없는 상태 출력과 종료 코드를 반환한다."""
    parser = argparse.ArgumentParser(description="stock-agent 전용 Codex 구독 인증")
    parser.add_argument("command", choices=("login", "status", "logout"))
    args = parser.parse_args()
    load_dotenv()
    auth = CodexAuth()
    try:
        if args.command == "login":
            auth.login()
            print("stock-agent용 Codex 구독 로그인이 저장되었습니다.")
        elif args.command == "logout":
            auth.logout()
            print("stock-agent용 로컬 Codex 인증 정보를 삭제했습니다.")
        else:
            saved = auth.status()
            if saved is None:
                print(f"로그인 없음. 로그인: {LOGIN_COMMAND}")
            else:
                print("로그인 저장됨 (만료됨; 다음 호출에서 갱신)" if saved.expires_at <= time.time() else "로그인 저장됨 (유효)")
        return 0
    except CodexAuthError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Codex 로그인을 취소했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
