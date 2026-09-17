"""모델 공급자·역할 선택을 외부 호출 없이 검증한다."""

import os
import unittest
from unittest.mock import patch

from stock_agent.gateways.llm import _resolve_model, _resolve_provider, get_chat_model


class ModelProviderTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        get_chat_model.cache_clear()
        self.addCleanup(get_chat_model.cache_clear)

    def test_subscription_is_explicit_and_does_not_require_an_api_key(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_codex"}), \
             patch("stock_agent.gateways.codex.create_codex_model") as factory:
            model = get_chat_model("planner")
            self.assertIs(model, factory.return_value)
            factory.assert_called_once_with("gpt-5.6-luna")
            self.assertIs(get_chat_model("planner"), model)
        with self.assertRaises(ValueError):
            _resolve_provider()

    def test_subscription_error_does_not_fall_back_to_configured_api_key(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_codex", "OPENAI_API_KEY": "unused"}), \
             patch("stock_agent.gateways.codex.create_codex_model", side_effect=RuntimeError("login required")), \
             patch("stock_agent.gateways.llm.ChatOpenAI") as api_model:
            with self.assertRaisesRegex(RuntimeError, "login required"):
                get_chat_model()
            api_model.assert_not_called()

    def test_role_overrides_and_independent_summary_are_preserved(self):
        with patch.dict(os.environ, {"LLM_MODEL": "common", "WORKER_MODEL": "worker"}):
            self.assertEqual(_resolve_model("openai_codex", "parser"), "worker")
            self.assertEqual(_resolve_model("openai_codex", "planner"), "common")
            self.assertEqual(_resolve_model("openai_codex", "summary"), "gpt-5.6-luna")
            with patch.dict(os.environ, {"PARSER_MODEL": "parser", "SUMMARY_MODEL": "summary"}):
                self.assertEqual(_resolve_model("openai_codex", "parser"), "parser")
                self.assertEqual(_resolve_model("openai_codex", "summary"), "summary")

    def test_existing_api_providers_keep_their_defaults_and_selection(self):
        for provider, expected in (("openai", "gpt-4o-mini"), ("openrouter", "openai/gpt-4o-mini")):
            self.assertEqual(_resolve_model(provider, "planner"), expected)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "unused"}):
            self.assertEqual(_resolve_provider(), "openrouter")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "unused"}):
                self.assertEqual(_resolve_provider(), "openai")
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}), self.assertRaises(ValueError):
            _resolve_provider()

    def test_role_effort_only_reaches_subscription_provider(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_codex", "PLANNER_MODEL": "gpt-6-astra",
                                     "CODEX_PLANNER_REASONING_EFFORT": "high"}), \
             patch("stock_agent.gateways.codex.create_codex_model") as factory:
            get_chat_model("planner")
            factory.assert_called_once_with("gpt-6-astra", reasoning_effort="high")
        get_chat_model.cache_clear()
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "unused",
                                     "CODEX_PLANNER_REASONING_EFFORT": "high"}), \
             patch("stock_agent.gateways.llm.ChatOpenAI") as factory:
            get_chat_model("planner")
            self.assertNotIn("reasoning", factory.call_args.kwargs)
        get_chat_model.cache_clear()
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_codex", "PLANNER_MODEL": "gpt-6-astra",
                                     "CODEX_PLANNER_REASONING_EFFORT": "none"}):
            with self.assertRaises(ValueError):
                get_chat_model("planner")
