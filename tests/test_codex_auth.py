"""실제 계정 없이 Codex OAuth·동시 갱신·로컬 토큰 보호를 검증한다."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

import httpx

from stock_agent.gateways import codex_auth
from stock_agent.gateways.codex_auth import CodexAuth, CodexAuthError


def _token(label="original"):
    payload = base64.urlsafe_b64encode(json.dumps({
        "https://api.openai.com/auth": {"chatgpt_account_id": "test-account"},
    }).encode()).decode().rstrip("=")
    return f"header.{payload}.{label}"


def _token_response(label="refreshed", refresh="new-refresh-secret"):
    data = {"access_token": _token(label), "expires_in": 3600}
    if refresh is not None:
        data["refresh_token"] = refresh
    return httpx.Response(200, json=data)


def _process_refresh(path, calls_path, ready, results):
    def request(*args, **kwargs):
        with open(calls_path, "a") as file:
            file.write("refresh\n")
        time.sleep(0.05)
        return _token_response()

    ready.wait(5)
    with patch.object(codex_auth, "_post", side_effect=request):
        results.put(CodexAuth(path).credentials().access_token)


class CodexAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "stock-agent" / "codex-auth.json"
        self.auth = CodexAuth(self.path)

    def save(self, *, expires_at=None, token=None):
        record = {
            "access_token": token or _token(),
            "refresh_token": "original-refresh-secret",
            "account_id": "test-account",
            "expires_at": time.time() + 3600 if expires_at is None else expires_at,
        }
        with self.auth._lock():
            self.auth._save(record)
        return record

    def login_responses(self, *responses):
        return patch.object(codex_auth, "_post", side_effect=[
            httpx.Response(200, json={"device_auth_id": "device-secret", "user_code": "TEST-CODE", "interval": "1"}),
            *responses,
        ])

    def test_device_pending_slow_down_then_success_saves_private_session(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        output = io.StringIO()
        with self.login_responses(
            httpx.Response(403),
            httpx.Response(400, json={"error": {"code": "deviceauth_authorization_pending"}}),
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(200, json={"authorization_code": "auth-code-secret", "code_verifier": "verifier-secret"}),
            _token_response(),
        ) as post, patch.object(codex_auth.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(codex_auth.time, "sleep", side_effect=sleep), redirect_stdout(output):
            credentials = self.auth.login()

        self.assertEqual(credentials.access_token, _token("refreshed"))
        self.assertEqual(sleeps, [1, 1, 1, 6])
        self.assertEqual(post.call_args.kwargs["data"]["redirect_uri"], "https://auth.openai.com/deviceauth/callback")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(str(self.path) + ".lock").stat().st_mode), 0o600)
        self.assertIn("TEST-CODE", output.getvalue())
        for secret in (credentials.access_token, "new-refresh-secret", "device-secret", "auth-code-secret", "verifier-secret"):
            self.assertNotIn(secret, output.getvalue())
        self.assertNotIn(credentials.access_token, repr(credentials))

    def test_failed_or_malformed_login_keeps_existing_file_and_hides_body(self):
        self.save()
        original = self.path.read_bytes()
        for response in (
            httpx.Response(403, json={"error": "access_denied", "detail": "server-secret"}),
            httpx.Response(400, json={"error": "expired_token", "detail": "server-secret"}),
            httpx.Response(200, json={"authorization_code": "server-secret"}),
        ):
            with self.subTest(status=response.status_code), self.login_responses(response), \
                    patch.object(codex_auth.time, "sleep"), redirect_stdout(io.StringIO()):
                with self.assertRaises(CodexAuthError) as raised:
                    self.auth.login()
                self.assertNotIn("server-secret", str(raised.exception))
                self.assertEqual(self.path.read_bytes(), original)

    def test_device_login_timeout_does_not_poll_or_write_after_deadline(self):
        now = [0.0]
        with self.login_responses() as post, patch.object(codex_auth, "DEVICE_LOGIN_TIMEOUT", 1), \
                patch.object(codex_auth.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(codex_auth.time, "sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(CodexAuthError, "만료"):
                self.auth.login()
        self.assertEqual(post.call_count, 1)
        self.assertFalse(self.path.exists())

    def test_expired_token_refresh_is_serialized_across_threads(self):
        self.save(expires_at=0)

        def request(*args, **kwargs):
            time.sleep(0.02)
            return _token_response()

        with patch.object(codex_auth, "_post", side_effect=request) as post:
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: CodexAuth(self.path).credentials(), range(8)))
        self.assertEqual(post.call_count, 1)
        self.assertEqual({result.access_token for result in results}, {_token("refreshed")})
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "new-refresh-secret")

    def test_expired_token_refresh_is_serialized_across_processes(self):
        self.save(expires_at=0)
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        results = context.Queue()
        calls_path = Path(self.directory.name) / "requests.txt"
        workers = [context.Process(target=_process_refresh, args=(self.path, calls_path, ready, results)) for _ in range(3)]
        try:
            for worker in workers:
                worker.start()
            ready.set()
            values = [results.get(timeout=5) for _ in workers]
            for worker in workers:
                worker.join(timeout=5)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(calls_path.read_text().splitlines(), ["refresh"])
            self.assertEqual(set(values), {_token("refreshed")})
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=5)
            results.close()

    def test_force_refresh_reuses_other_requests_rotated_token(self):
        self.save()
        with patch.object(codex_auth, "_post", return_value=_token_response()) as post:
            first = self.auth.credentials(force_refresh=True, rejected_access_token=_token())
            second = self.auth.credentials(force_refresh=True, rejected_access_token=_token())
        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)

    def test_every_request_observes_current_file_and_does_not_refresh_valid_token(self):
        self.save()
        with patch.object(codex_auth, "_post") as post:
            self.assertEqual(self.auth.credentials().access_token, _token())
            self.save(token=_token("other-process"))
            self.assertEqual(self.auth.credentials().access_token, _token("other-process"))
        post.assert_not_called()

    def test_status_is_read_only_and_never_refreshes(self):
        with patch.object(codex_auth, "_post") as post:
            self.assertIsNone(self.auth.status())
            self.assertFalse(self.path.parent.exists())
            self.save(expires_at=0)
            before = self.path.stat().st_mtime_ns
            self.assertEqual(self.auth.status().expires_at, 0)
            self.assertEqual(self.path.stat().st_mtime_ns, before)
        post.assert_not_called()

    def test_refresh_failure_hides_server_body_and_preserves_file(self):
        self.save(expires_at=0)
        before = self.path.read_bytes()
        with patch.object(codex_auth, "_post", return_value=httpx.Response(400, text="original-refresh-secret")):
            try:
                self.auth.credentials()
            except CodexAuthError:
                error_text = traceback.format_exc()
            else:
                self.fail("Expected authentication error")
        self.assertNotIn("original-refresh-secret", error_text)
        self.assertIn("login", error_text)
        self.assertEqual(self.path.read_bytes(), before)

    def test_network_failure_has_no_underlying_exception_or_request_secrets(self):
        self.save(expires_at=0)
        with patch.object(codex_auth.httpx, "post", side_effect=httpx.ConnectError("original-refresh-secret")):
            try:
                self.auth.credentials()
            except CodexAuthError:
                error_text = traceback.format_exc()
            else:
                self.fail("Expected network error")
        self.assertNotIn("original-refresh-secret", error_text)
        self.assertNotIn("ConnectError", error_text)

    def test_refresh_can_keep_existing_refresh_token_if_server_omits_it(self):
        self.save(expires_at=0)
        with patch.object(codex_auth, "_post", return_value=_token_response(refresh=None)):
            self.auth.credentials()
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "original-refresh-secret")

    def test_lock_wait_has_a_deadline(self):
        with self.auth._lock(), patch.object(codex_auth, "LOCK_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(CodexAuthError, "잠금 대기"):
                self.auth.credentials()

    def test_insecure_or_symlink_storage_is_rejected(self):
        self.save()
        self.path.chmod(0o644)
        with self.assertRaisesRegex(CodexAuthError, "600"):
            self.auth.status()
        self.path.chmod(0o600)
        linked = self.path.with_name("linked.json")
        linked.symlink_to(self.path)
        with self.assertRaises(CodexAuthError):
            CodexAuth(linked).status()

    def test_failed_atomic_replace_keeps_previous_file_and_removes_temporary(self):
        self.save(expires_at=0)
        before = self.path.read_bytes()
        with patch.object(codex_auth, "_post", return_value=_token_response()), \
                patch.object(codex_auth.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(CodexAuthError):
                self.auth.credentials()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob(".codex-auth-*")), [])

    def test_custom_path_logout_only_removes_this_session(self):
        self.save()
        unrelated = Path(self.directory.name) / "unrelated.json"
        unrelated.write_text("untouched")
        with patch.dict(os.environ, {"CODEX_AUTH_PATH": str(self.path)}):
            CodexAuth().logout()
        self.assertFalse(self.path.exists())
        self.assertEqual(unrelated.read_text(), "untouched")
        self.assertTrue(Path(str(self.path) + ".lock").exists())

    def test_missing_login_never_uses_api_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "api-key-secret"}), patch.object(codex_auth, "_post") as post:
            with self.assertRaisesRegex(CodexAuthError, "구독 로그인이 필요"):
                self.auth.credentials()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
