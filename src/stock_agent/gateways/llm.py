"""모델 공급자와 역할별 Chat Model 생성 로직을 격리한다."""

import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

load_dotenv()

ModelRole = Literal["parser", "planner", "worker", "reviewer", "summary"]


@lru_cache(maxsize=5)
def get_chat_model(role: ModelRole = "worker") -> BaseChatModel:
    """공급자 설정에 맞는 역할별 Chat Model을 생성하고 캐시한다.

    Args:
        role: `parser`, `planner`, `worker`, `reviewer`, `summary` 중 사용할 모델 역할.

    Returns:
        OpenAI API, Codex 구독 또는 OpenRouter에 연결된 LangChain `BaseChatModel`.

    Raises:
        ValueError: 공급자 이름이 잘못됐거나 필요한 API 키가 없는 경우.

    summary는 SUMMARY_MODEL 또는 gpt-5.6-luna를 사용하며 공통 기본값을 따르지 않는다.
    나머지 역할별 모델 환경변수가 없으면 공통 `LLM_MODEL`로 대체한다. Parser는
    `PARSER_MODEL`이 없을 때 `WORKER_MODEL`도 fallback으로 사용한다.
    """
    provider = _resolve_provider()
    model = _resolve_model(provider, role)

    if provider == "openai_codex":
        from stock_agent.gateways.codex import create_codex_model

        return create_codex_model(model)

    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=_required_env("OPENAI_API_KEY"),
            use_responses_api=True,
        )

    return ChatOpenAI(
        model=model,
        api_key=_required_env("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )


def _resolve_model(provider: str, role: ModelRole) -> str:
    """역할별 모델명과 공통 fallback을 결정한다."""
    role_env = {
        "parser": "PARSER_MODEL",
        "planner": "PLANNER_MODEL",
        "worker": "WORKER_MODEL",
        "reviewer": "REVIEWER_MODEL",
        "summary": "SUMMARY_MODEL",
    }[role]
    configured = os.environ.get(role_env)
    if role == "summary":
        return configured or ("openai/gpt-5.6-luna" if provider == "openrouter" else "gpt-5.6-luna")
    if role == "parser" and not configured:
        configured = os.environ.get("WORKER_MODEL")
    configured = configured or os.environ.get("LLM_MODEL")
    if configured:
        return configured
    if provider == "openai_codex":
        return "gpt-5.6-luna"
    if provider == "openai":
        return "gpt-4o-mini"
    return "openai/gpt-4o-mini"


def _resolve_provider() -> str:
    """환경변수와 API 키를 바탕으로 사용할 공급자를 결정한다."""
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider:
        if provider not in {"openai", "openai_codex", "openrouter"}:
            raise ValueError("LLM_PROVIDER는 'openai', 'openai_codex' 또는 'openrouter'여야 합니다.")
        return provider

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"

    raise ValueError(".env에 OPENAI_API_KEY 또는 OPENROUTER_API_KEY를 설정하세요.")


def _required_env(name: str) -> str:
    """필수 환경변수를 반환하고, 없으면 설정 오류를 발생시킨다."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"필수 환경변수가 없습니다: {name}")
    return value
