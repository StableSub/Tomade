"""임시 인증·설정 파일로 UI 설정 API를 검증한다. 실제 계정·모델 호출은 없다."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from backend.main import app, _stream_chat_events, _stream_research_events
from backend import model_settings
from stock_agent.gateways import llm, codex_auth
from tests.test_codex_auth import _token_response


class ModelSettingsTest(unittest.TestCase):
    def role_payload(self):
        return {role: {"model": "gpt-6-astra" if role in {"planner", "worker"} else "gpt-5.6-terra",
                       "reasoning_effort": "high" if role in {"planner", "worker"} else "low"}
                for role in llm.CONFIGURABLE_ROLES}

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.env_path = Path(directory) / ".env"
        self.env_path.write_text("OPENAI_API_KEY=keep-secret\nOTHER_SETTING=keep-me\n")
        self.auth_path = Path(directory) / "auth" / "session.json"
        self.enterContext(patch.dict(os.environ, {"OPENAI_API_KEY": "keep-secret", "LLM_PROVIDER": "openai",
                                                 "CODEX_AUTH_PATH": str(self.auth_path)}, clear=True))
        self.enterContext(patch.object(llm, "ENV_PATH", self.env_path))
        self.enterContext(patch.object(model_settings, "_login", None))
        llm.get_chat_model.cache_clear()
        self.addCleanup(llm.get_chat_model.cache_clear)
        self.client = self.enterContext(TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5000)))

    def start(self):
        with patch.object(codex_auth, "_post", return_value=httpx.Response(200, json={
            "device_auth_id": "private-device-id", "user_code": "DISPLAY-CODE", "interval": 5,
        })) as post:
            response = self.client.post("/api/settings/codex/login")
            again = self.client.post("/api/settings/codex/login")
        post.assert_called_once()
        self.assertEqual(response.json(), again.json())
        self.assertNotIn("private-device-id", response.text)
        return response.json()["id"]

    def complete(self, login_id):
        model_settings._login.next_poll = 0
        with patch.object(codex_auth, "_post", side_effect=[
            httpx.Response(200, json={"authorization_code": "private-code", "code_verifier": "private-verifier"}),
            _token_response(),
        ]):
            return self.client.post(f"/api/settings/codex/login/{login_id}/poll")

    def test_status_reports_server_mode_and_no_secrets_or_network(self):
        with patch.object(codex_auth, "_post") as post:
            response = self.client.get("/api/settings/models")
        post.assert_not_called()
        data = response.json()
        self.assertEqual(data["provider"], "openai")
        self.assertEqual(data["auth_mode"], "api_key")
        self.assertEqual(data["codex"]["state"], "signed_out")
        self.assertTrue(data["api_keys"]["openai"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("keep-secret", response.text)
        self.assertNotIn(str(self.auth_path), response.text)

    def test_stream_reports_mode_and_releases_switch_guard_on_close(self):
        async def check():
            for factory in (_stream_chat_events, _stream_research_events):
                with patch("backend.main.trajectory_run"):
                    stream = factory("모델을 호출하기 전에 중단")
                    try:
                        event = await anext(stream)
                        data = json.loads(event.split("data: ", 1)[1])
                        self.assertEqual(data["connection"]["provider"], "openai")
                        self.assertEqual(data["connection"]["auth_mode"], "api_key")
                        self.assertTrue(llm.model_configuration()["busy"])
                        with self.assertRaises(RuntimeError):
                            llm.set_model_provider("openai_codex")
                    finally:
                        await stream.aclose()
                    self.assertFalse(llm.model_configuration()["busy"])
        asyncio.run(check())

    def test_login_then_explicit_switch_persists_without_touching_other_settings(self):
        login_id = self.start()
        response = self.complete(login_id)
        self.assertEqual(response.json()["state"], "completed")
        for private in ("private-code", "private-verifier", "new-refresh-secret", "access_token"):
            self.assertNotIn(private, response.text)
        self.assertTrue(self.auth_path.exists())
        self.assertEqual(llm._resolve_provider(), "openai", "Login alone must not change billing")
        with patch.object(llm.get_chat_model, "cache_clear") as clear:
            response = self.client.put("/api/settings/models", json={"provider": "openai_codex"})
        clear.assert_called_once()
        self.assertEqual(response.json()["auth_mode"], "subscription")
        self.assertEqual(llm._resolve_provider(), "openai_codex")
        self.assertIn("LLM_PROVIDER='openai_codex'", self.env_path.read_text())
        self.assertIn("OTHER_SETTING=keep-me", self.env_path.read_text())
        self.assertIn("OPENAI_API_KEY=keep-secret", self.env_path.read_text())

    def test_missing_credentials_and_unknown_provider_are_rejected(self):
        for provider in ("openai_codex", "openrouter"):
            response = self.client.put("/api/settings/models", json={"provider": provider})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.put("/api/settings/models", json={"provider": "other"}).status_code, 422)
        self.assertEqual(llm._resolve_provider(), "openai")

    def test_switch_blocked_during_request_and_guard_released_after_error(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "unused"}):
            with self.assertRaises(ValueError):
                with llm.model_session():
                    self.assertTrue(self.client.get("/api/settings/models").json()["busy"])
                    self.assertEqual(self.client.put("/api/settings/models", json={"provider": "openrouter"}).status_code, 409)
                    raise ValueError("test cancellation")
            self.assertFalse(self.client.get("/api/settings/models").json()["busy"])
            self.assertEqual(self.client.put("/api/settings/models", json={"provider": "openrouter"}).status_code, 200)

    def test_poll_throttles_then_cancel_prevents_more_auth_calls(self):
        login_id = self.start()
        with patch.object(codex_auth, "_post") as post:
            self.assertEqual(self.client.post(f"/api/settings/codex/login/{login_id}/poll").json()["state"], "pending")
            self.assertEqual(self.client.delete(f"/api/settings/codex/login/{login_id}").status_code, 200)
            self.assertEqual(self.client.post(f"/api/settings/codex/login/{login_id}/poll").status_code, 404)
        post.assert_not_called()
        self.assertFalse(self.auth_path.exists())

    def test_expiry_and_denial_are_visible_without_leaking_upstream_body(self):
        login_id = self.start()
        model_settings._login.device.deadline = 0
        with patch.object(codex_auth, "_post") as post:
            self.assertEqual(self.client.post(f"/api/settings/codex/login/{login_id}/poll").json()["state"], "expired")
        post.assert_not_called()
        login_id = self.start()
        model_settings._login.next_poll = 0
        with patch.object(codex_auth, "_post", return_value=httpx.Response(403, json={"error": "access_denied", "secret": "upstream-secret"})):
            response = self.client.post(f"/api/settings/codex/login/{login_id}/poll")
        self.assertEqual(response.json()["state"], "error")
        self.assertNotIn("upstream-secret", response.text)

    def test_disk_error_does_not_change_live_provider(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "unused"}), \
             patch.object(llm, "set_key", side_effect=OSError("private path")):
            response = self.client.put("/api/settings/models", json={"provider": "openrouter"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private path", response.text)
        self.assertEqual(llm._resolve_provider(), "openai")

    def test_foreign_origin_and_nonlocal_client_cannot_read_or_change_settings(self):
        for method, path in (("GET", "/models"), ("POST", "/codex/login")):
            response = self.client.request(method, "/api/settings" + path, headers={"Origin": "https://example.com"})
            self.assertEqual(response.status_code, 403)
        with TestClient(app, base_url="http://localhost", client=("203.0.113.2", 9999)) as client:
            self.assertEqual(client.get("/api/settings/models").status_code, 403)

    def test_role_models_persist_reload_and_clear_cache(self):
        os.environ["LLM_PROVIDER"] = "openai_codex"
        with patch.object(llm.get_chat_model, "cache_clear") as clear:
            response = self.client.put("/api/settings/codex/models", json=self.role_payload())
        self.assertEqual(response.status_code, 200)
        clear.assert_called_once()
        self.assertEqual(response.json()["models"]["planner"], "gpt-6-astra")
        self.assertEqual(response.json()["reasoning_efforts"]["planner"], "high")
        saved = dotenv_values(self.env_path)
        self.assertEqual(saved["OPENAI_API_KEY"], "keep-secret")
        self.assertEqual(saved["OTHER_SETTING"], "keep-me")
        with patch.dict(os.environ, saved, clear=True):
            self.assertEqual(llm._resolve_model("openai_codex", "parser"), "gpt-5.6-terra")
            self.assertEqual(llm._resolve_effort("parser"), "low")
        payload = self.role_payload()
        payload["planner"]["reasoning_effort"] = None
        self.assertEqual(self.client.put("/api/settings/codex/models", json=payload).status_code, 200)
        self.assertIsNone(llm._resolve_effort("planner"))

    def test_role_validation_busy_provider_and_origin(self):
        url = "/api/settings/codex/models"
        payload = self.role_payload()
        self.assertEqual(self.client.put(url, json=payload).status_code, 409)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.put(url, json=payload).status_code, 409)
        os.environ["LLM_PROVIDER"] = "openai_codex"
        with llm.model_session():
            self.assertEqual(self.client.put(url, json=payload).status_code, 409)
        self.assertEqual(self.client.put(url, json=payload, headers={"Origin": "https://example.com"}).status_code, 403)
        for field, invalid in (("model", "unverified-model"), ("reasoning_effort", "ultra"), ("reasoning_effort", "none")):
            wrong = self.role_payload()
            wrong["planner"][field] = invalid
            self.assertEqual(self.client.put(url, json=wrong).status_code, 422)
        self.assertEqual(self.client.put(url, json={"planner": payload["planner"]}).status_code, 422)
        self.assertNotIn("PLANNER_MODEL", self.env_path.read_text())

    def test_role_write_failure_preserves_file_and_runtime(self):
        os.environ["LLM_PROVIDER"] = "openai_codex"
        before = self.env_path.read_bytes()
        real_set_key = llm.set_key
        calls = 0
        def fail_midway(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("private path")
            return real_set_key(*args)
        with patch.object(llm, "set_key", side_effect=fail_midway):
            response = self.client.put("/api/settings/codex/models", json=self.role_payload())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private path", response.text)
        self.assertEqual(self.env_path.read_bytes(), before)
        self.assertNotIn("PLANNER_MODEL", os.environ)
        self.assertEqual(list(self.env_path.parent.glob(".model-settings-*")), [])
