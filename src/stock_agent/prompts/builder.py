"""고정 Markdown 지침과 준비된 실행 값을 역할별 시스템 프롬프트로 조립한다."""

from pathlib import Path
import re
from typing import Literal

PromptAgent = Literal["orchestrator", "request_parser", "business", "macro_sector", "event_catalyst"]
PROMPT_DIR = Path(__file__).parent
_AGENTS = {"orchestrator", "request_parser", "business", "macro_sector", "event_catalyst"}
_COMMON_KEYS = {"common_constraints", "worker_constraints", "worker_behavior"}
_VARIABLE = re.compile(r"\{([a-z_]+)\}")


def build_system_prompt(agent: PromptAgent, **context: str) -> str:
    """역할별 파일·공통 지침을 읽고 동적 값을 한 번만 삽입한다.

    Args:
        agent: 코드에서 지정한 다섯 역할 중 하나. 임의 파일 경로는 허용하지 않는다.
        context: 상위 Agent는 current_date·execution_stage(initial/synthesis)가 필수이며
            user_memory·short_term_summary는 생략하면 빈 문자열이다. Parser는
            current_date만 받는다. Worker의 작업 조건은 별도 메시지로 전달한다.
    Returns:
        공통 문구와 실행 값이 치환된 시스템 프롬프트. 삽입된 텍스트는 재해석하지 않는다.
    Raises:
        ValueError: 미지원 역할·단계, 누락된 공통 구역·변수 또는 불필요한 입력 변수.
        OSError, UnicodeError: 필수 파일 읽기 실패. 기본 프롬프트로 대체하지 않는다.
    Note:
        매 호출 파일을 읽는다. DB·사용자 기억 조회, 모델·Tool 호출과 파일 쓰기는 없다.
    """
    if agent not in _AGENTS:
        raise ValueError(f"지원하지 않는 프롬프트 역할: {agent}")
    template = (PROMPT_DIR / f"{agent}.md").read_text(encoding="utf-8")
    common = (PROMPT_DIR / "common.md").read_text(encoding="utf-8")

    def insert_common(match: re.Match) -> str:
        key = match[1]
        if key not in _COMMON_KEYS:
            return match[0]
        section = re.search(rf"(?ms)^## {key} —[^\n]*\n(.*?)(?=^## |\Z)", common)
        if section is None:
            raise ValueError(f"공통 프롬프트 구역 누락: {key}")
        return section[1].strip()

    template = _VARIABLE.sub(insert_common, template)
    if agent == "orchestrator":
        context.setdefault("user_memory", "")
        context.setdefault("short_term_summary", "")
    required = set(_VARIABLE.findall(template))
    if missing := required - context.keys():
        raise ValueError(f"프롬프트 변수 누락: {', '.join(sorted(missing))}")
    if extra := context.keys() - required:
        raise ValueError(f"허용하지 않는 프롬프트 변수: {', '.join(sorted(extra))}")
    if agent == "orchestrator" and context["execution_stage"] not in {"initial", "synthesis"}:
        raise ValueError("실행 단계는 initial 또는 synthesis여야 합니다.")
    return _VARIABLE.sub(lambda match: context[match[1]], template)
