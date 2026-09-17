"""로컬 설정 창용 호출 방식 조회·전환과 Codex 기기 로그인을 제공한다."""

from dataclasses import dataclass, field
import os
from threading import RLock
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.portfolio import require_local
from stock_agent.gateways.codex_auth import CodexAuth, CodexAuthError, CodexDeviceLogin, DEVICE_VERIFICATION_URL
from stock_agent.gateways.llm import (
    CODEX_MODEL_OPTIONS, CodexRoleSettings, model_configuration,
    set_model_provider, set_codex_role_settings,
)

router = APIRouter(prefix="/api/settings", dependencies=[Depends(require_local)])
_login_lock = RLock()


@dataclass
class LoginSession:
    """단일 서버의 진행 중 로그인. 비밀은 내부에만 두고 공개 상태만 직렬화한다."""
    device: CodexDeviceLogin = field(repr=False)
    auth: CodexAuth = field(repr=False)
    id: str = field(default_factory=lambda: str(uuid4()))
    state: str = "pending"
    message: str = "브라우저에서 로그인을 완료해주세요."
    next_poll: float = 0

    def public(self) -> dict:
        """표시할 코드·고정 로그인 URL·대기 간격만 반환한다. 토큰·서버 식별자는 제외한다."""
        if self.state == "pending" and time.monotonic() >= self.device.deadline:
            self.state, self.message = "expired", "로그인 시간이 만료되었습니다. 다시 시작하세요."
        return {"id": self.id, "state": self.state, "message": self.message,
                "user_code": self.device.user_code if self.state == "pending" else None,
                "verification_url": DEVICE_VERIFICATION_URL,
                "interval": self.device.interval,
                "expires_in": max(0, int(self.device.deadline - time.monotonic()))}


_login: LoginSession | None = None


def _codex_status() -> dict:
    try:
        saved = CodexAuth().status()
    except CodexAuthError:
        return {"state": "error", "message": "저장된 인증을 읽지 못했습니다. 경로·권한을 확인하거나 다시 로그인하세요."}
    if saved is None:
        return {"state": "signed_out", "message": "이 프로젝트에 저장된 구독 로그인이 없습니다."}
    if saved.expires_at <= time.time():
        return {"state": "expired", "message": "로그인이 저장돼 있습니다. 다음 호출에서 토큰을 갱신합니다."}
    return {"state": "signed_in", "message": "구독 로그인이 저장돼 있습니다."}


@router.get("/models")
def settings() -> dict:
    """실행 중 서버의 공급자·모델·키 유무·로그인 상태를 반환한다. 외부 검증 호출은 없다."""
    with _login_lock:
        return {**model_configuration(), "api_keys": {
                    "openai": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                    "openrouter": bool(os.environ.get("OPENROUTER_API_KEY", "").strip())},
                "codex": _codex_status(), "login": _login.public() if _login else None,
                "codex_model_options": CODEX_MODEL_OPTIONS}


@router.put("/codex/models")
def select_role_models(selection: CodexRoleSettings) -> dict:
    """구독의 역할별 모델·추론을 저장한다. 실행 중/다른 공급자는 409, 저장 실패는 500이다."""
    try:
        set_codex_role_settings(selection)
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from None
    except OSError:
        raise HTTPException(500, "모델 설정을 저장하지 못했습니다. 서버 설정 파일의 권한을 확인하세요.") from None
    return settings()


class ProviderSelection(BaseModel):
    """설정 창에서 선택한 공급자. 키·모델 ID는 이 API로 변경하지 않는다."""
    provider: Literal["openai", "openrouter", "openai_codex"]


@router.put("/models")
def select_provider(selection: ProviderSelection) -> dict:
    """저장된 인증이 있는 공급자를 다음 요청부터 적용한다. 실행 중은 409, 저장 실패는 500이다."""
    provider = selection.provider
    if provider == "openai_codex":
        if _codex_status()["state"] not in {"signed_in", "expired"}:
            raise HTTPException(409, "먼저 ChatGPT 구독 로그인을 완료하세요.")
    elif not os.environ.get("OPENAI_API_KEY" if provider == "openai" else "OPENROUTER_API_KEY", "").strip():
        raise HTTPException(409, "해당 API 키가 설정되어 있지 않습니다. 서버의 .env를 확인하세요.")
    try:
        set_model_provider(provider)
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from None
    except OSError:
        raise HTTPException(500, "호출 방식을 저장하지 못했습니다. 서버 설정 파일의 권한을 확인하세요.") from None
    return settings()


@router.post("/codex/login")
def start_login() -> dict:
    """기기 로그인을 시작하거나 진행 중 요청을 재사용한다. 발급 오류는 비밀 없이 502로 반환한다."""
    global _login
    with _login_lock:
        if _login and _login.public()["state"] == "pending":
            return _login.public()
        auth = CodexAuth()
        try:
            device = auth.start_login()
        except CodexAuthError as error:
            raise HTTPException(502, str(error)) from None
        _login = LoginSession(device=device, auth=auth, next_poll=time.monotonic() + device.interval)
        return _login.public()


@router.post("/codex/login/{login_id}/poll")
def poll_login(login_id: str) -> dict:
    """정해진 간격 이후에만 승인 여부를 조회한다. 성공 시 인증을 저장하고 공급자는 유지한다."""
    with _login_lock:
        if _login is None or _login.id != login_id:
            raise HTTPException(404, "로그인 요청이 없거나 서버가 재시작되었습니다. 다시 시작하세요.")
        if _login.public()["state"] != "pending" or time.monotonic() < _login.next_poll:
            return _login.public()
        try:
            credentials = _login.auth.poll_login(_login.device)
        except CodexAuthError as error:
            _login.state, _login.message = "error", str(error)
        else:
            if credentials is not None:
                _login.state, _login.message = "completed", "로그인 완료. 구독을 선택하고 ‘이 방식 사용’을 눌러 적용하세요."
        _login.next_poll = time.monotonic() + _login.device.interval
        return _login.public()


@router.delete("/codex/login/{login_id}")
def cancel_login(login_id: str) -> dict:
    """진행 중 로그인 조회를 종료한다. 이미 저장된 인증이나 활성 공급자는 변경하지 않는다."""
    global _login
    with _login_lock:
        if _login is None or _login.id != login_id:
            raise HTTPException(404, "로그인 요청이 없습니다.")
        _login = None
    return {"cancelled": True}
