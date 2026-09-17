"""모델 공급자와 역할별 Chat Model 생성 로직을 격리한다."""

import os
import tempfile
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from dotenv import load_dotenv, set_key
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, model_validator

load_dotenv()

ModelRole = Literal["parser", "planner", "worker", "reviewer", "summary"]
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_settings_lock = RLock()
_active_sessions = 0
CONFIGURABLE_ROLES = ("planner", "parser", "worker", "summary")
# 문서상 지원 목록이며 계정별 접근 권한을 조회한 결과는 아니다.
CODEX_MODEL_OPTIONS = {
    "gpt-6-astra": ["low", "medium", "high", "xhigh", "max"],
    **{f"gpt-5.6-{name}": ["none", "low", "medium", "high", "xhigh", "max"]
       for name in ("sol", "terra", "luna")},
}


class RoleModelSettings(BaseModel):
    """UI의 모델·추론 선택. 지원 조합만 허용하며 null은 공급자 기본 추론을 뜻한다."""
    model_config = ConfigDict(extra="forbid")
    model: Literal["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = None

    @model_validator(mode="after")
    def validate_effort(self):
        """모델별 지원 추론 단계를 검사하고 잘못된 조합이면 검증 오류를 반환한다."""
        if self.reasoning_effort and self.reasoning_effort not in CODEX_MODEL_OPTIONS[self.model]:
            raise ValueError("이 모델이 지원하지 않는 추론 깊이입니다.")
        return self


class CodexRoleSettings(BaseModel):
    """부장·Parser·공유 Worker·요약의 설정 전체를 한 번에 저장하는 계약."""
    model_config = ConfigDict(extra="forbid")
    planner: RoleModelSettings
    parser: RoleModelSettings
    worker: RoleModelSettings
    summary: RoleModelSettings


def model_configuration() -> dict:
    """서버 프로세스가 실제 선택하는 공급자·역할별 모델만 반환한다. 비밀·외부 호출은 없다."""
    with _settings_lock:
        try:
            provider = _resolve_provider()
        except ValueError:
            return {"provider": None, "auth_mode": None, "models": {}, "reasoning_efforts": {}, "busy": bool(_active_sessions)}
        return {"provider": provider, "auth_mode": "subscription" if provider == "openai_codex" else "api_key",
                "models": {role: _resolve_model(provider, role) for role in CONFIGURABLE_ROLES},
                "reasoning_efforts": {role: _resolve_effort(role) if provider == "openai_codex" else None
                                      for role in CONFIGURABLE_ROLES},
                "busy": bool(_active_sessions)}


@contextmanager
def model_session():
    """요청 실행 중 공급자 변경을 막는다. 오류·취소 시에도 실행 카운트를 해제한다."""
    global _active_sessions
    with _settings_lock:
        _active_sessions += 1
    try:
        yield
    finally:
        with _settings_lock:
            _active_sessions -= 1


def set_model_provider(provider: str) -> None:
    """공급자를 .env와 현재 서버에 반영한다. 실행 중에는 RuntimeError, 저장 실패는 OSError다.

    역할별 모델·키는 변경하지 않는다. 성공 후 캐시를 비워 다음 요청부터 적용한다.
    이 설정 API는 기존 서버와 같이 단일 프로세스를 대상으로 한다.
    """
    if provider not in {"openai", "openrouter", "openai_codex"}:
        raise ValueError("지원하지 않는 공급자입니다.")
    with _settings_lock:
        if _active_sessions:
            raise RuntimeError("진행 중인 답변 또는 포트폴리오 진단이 끝난 뒤 변경하세요.")
        set_key(ENV_PATH, "LLM_PROVIDER", provider)
        os.environ["LLM_PROVIDER"] = provider
        get_chat_model.cache_clear()


def set_codex_role_settings(selection: CodexRoleSettings) -> None:
    """구독 역할 설정을 .env에 원자적으로 저장하고 캐시를 비워 다음 요청부터 적용한다.

    실행 중·다른 공급자이면 RuntimeError, 파일 실패는 OSError다. 실패 시 기존 파일과
    프로세스 설정을 유지한다. API 키·주석·다른 환경변수는 보존한다.
    """
    values = {}
    for role, setting in selection.model_dump().items():
        values[f"{role.upper()}_MODEL"] = setting["model"]
        values[f"CODEX_{role.upper()}_REASONING_EFFORT"] = setting["reasoning_effort"] or ""
    with _settings_lock:
        if _active_sessions:
            raise RuntimeError("진행 중인 답변 또는 포트폴리오 진단이 끝난 뒤 변경하세요.")
        if model_configuration()["provider"] != "openai_codex":
            raise RuntimeError("먼저 Codex 구독 인증 방식을 적용하세요.")
        # 여러 키를 변경하므로 완성한 임시 파일을 한 번만 교체한다.
        with tempfile.NamedTemporaryFile(dir=ENV_PATH.parent, prefix=".model-settings-", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            temporary.write_bytes(ENV_PATH.read_bytes() if ENV_PATH.exists() else b"")
            for key, value in values.items():
                set_key(temporary, key, value)
            os.replace(temporary, ENV_PATH)
        finally:
            temporary.unlink(missing_ok=True)
        os.environ.update(values)
        get_chat_model.cache_clear()


def _resolve_effort(role: ModelRole) -> str | None:
    return os.environ.get(f"CODEX_{role.upper()}_REASONING_EFFORT", "").strip() or None


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

        effort = _resolve_effort(role)
        if effort is not None:
            if model not in CODEX_MODEL_OPTIONS or effort not in CODEX_MODEL_OPTIONS[model]:
                raise ValueError("설정된 구독 모델·추론 깊이 조합을 확인하세요.")
            return create_codex_model(model, reasoning_effort=effort)
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
