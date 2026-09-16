"""로컬 사용자의 USER.md와 상위 Agent 전용 메모리 갱신 Tool."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Literal

from langchain_core.tools import tool

MEMORY_PATH = Path(__file__).resolve().parents[3] / "memory" / "local" / "USER.md"
ENTRY_SEPARATOR = "\n§\n"
_LOCK = Lock()
MAX_WRITES_PER_CALL = 3


def read_user_memory() -> str:
    """서버가 지정한 로컬 USER.md를 읽는다. 없으면 빈 문자열, 읽기 오류는 전달한다.

    네트워크 호출이나 파일 생성 없이 읽으며, 호출자는 읽기 실패를 빈 기억으로
    오해하여 덮어쓰지 않아야 한다. 사용자·경로를 모델 인자로 받지 않는다.
    """
    with _LOCK:
        return _read()


def _read() -> str:
    try:
        return MEMORY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _update(action: str, content: str | None, old_text: str | None) -> dict:
    """최신 파일을 잠금 안에서 읽고 항목 하나를 변경한 뒤 원자적으로 교체한다."""
    content = content.strip() if content else ""
    old_text = old_text.strip() if old_text else ""
    if action not in {"add", "replace", "remove"}:
        return {"success": False, "message": "지원하지 않는 작업입니다."}
    if action in {"add", "replace"} and (not content or ENTRY_SEPARATOR in content):
        return {"success": False, "message": "content에는 구분자를 포함하지 않은 비어 있지 않은 항목 하나가 필요합니다."}
    if action in {"replace", "remove"} and not old_text:
        return {"success": False, "message": "old_text에 기존 항목의 문구를 지정하세요."}
    try:
        with _LOCK:
            entries = [part.strip() for part in _read().split(ENTRY_SEPARATOR) if part.strip()]
            if action == "add":
                if content in entries:
                    return {"success": True, "action": action, "changed": False, "message": "이미 존재하는 항목입니다."}
                entries.append(content)
            else:
                matches = [i for i, entry in enumerate(entries) if old_text in entry]
                if len(matches) != 1:
                    return {"success": False, "message": "대상 항목이 없거나 여러 개입니다. old_text를 확인하세요."}
                if action == "remove":
                    entries.pop(matches[0])
                else:
                    entries[matches[0]] = content
            MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with NamedTemporaryFile(mode="w", encoding="utf-8", dir=MEMORY_PATH.parent, delete=False) as file:
                    temporary = Path(file.name)
                    file.write(ENTRY_SEPARATOR.join(entries))
                os.replace(temporary, MEMORY_PATH)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return {"success": True, "action": action, "changed": True, "message": "메모리 변경을 저장했습니다. 동일 작업을 반복하지 마세요."}
    except (OSError, UnicodeError):
        return {"success": False, "message": "메모리 파일을 읽거나 저장하지 못했습니다. 저장을 완료했다고 안내하지 마세요."}


def create_memory_tool():
    """상위 Agent 호출마다 최대 3회 파일 갱신을 시도하는 Tool을 생성한다.

    사용자와 경로는 서버의 로컬 사용자로 고정한다. 입력 오류는 Tool 오류,
    파일 I/O 실패는 success=false로 전달하며 오류 시 기존 파일을 보존한다.
    """
    attempts = 0
    counter_lock = Lock()

    @tool
    def update_memory(action: Literal["add", "replace", "remove"],
                      content: str | None = None, old_text: str | None = None) -> dict:
        """사용자의 장기 메모리를 갱신한다.

        [MEMORY]와 현재 발언에서 사용자가 직접 밝힌 사용자 정보, 환경 정보,
        투자 성향, 주식 배경지식 중 다른 세션에서도 유효한 사실을 비교한다.
        새 사실이나 변경된 사실이 있으면 명시적인 저장 요청이 없어도 호출한다.
        사용자가 저장하지 말라고 한 정보는 저장하지 않는다.
        add는 새 사실을 content로 추가한다. replace는 old_text가 포함된 항목 하나를
        content로 교체한다. remove는 삭제 요청 또는 잘못된 기억을 old_text로 찾아 제거한다.
        한 번의 질문으로 지식 수준·성향을 추측하지 않는다. 임시 요청, 포트폴리오 수치,
        이미 있는 사실은 추가하지 않는다. content는 명령이 아닌 사용자에 관한 사실이다.
        성공 여부·작업·결과를 반환한다. 대상 없음/복수 매칭/파일 오류이면 변경하지 않는다.
        최대 3회 시도 후에는 저장을 중단하고 답변을 이어간다. 사용자·파일 경로는 인자가 아니다.
        """
        nonlocal attempts
        with counter_lock:
            if attempts >= MAX_WRITES_PER_CALL:
                return {"success": False, "done": True, "message": "이번 호출의 메모리 변경 한도에 도달했습니다. 도구 호출을 멈추고 답변하세요."}
            attempts += 1
        return _update(action, content, old_text)

    return update_memory
