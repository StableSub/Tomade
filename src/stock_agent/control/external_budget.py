"""비동기 호출의 취소·기한을 외부 요청을 수행하는 스레드까지 전달."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Iterator


@dataclass
class ExternalCallBudget:
    """진행 중 HTTP를 끊지 않고 다음 외부 호출을 막는 실행 범위."""

    deadline: float
    cancelled: threading.Event = field(default_factory=threading.Event)
    parent: "ExternalCallBudget | None" = None

    def cancel(self) -> None:
        """같은 범위를 복사받은 모든 스레드에 취소 표시. 외부 호출 부작용 없음."""
        self.cancelled.set()

    def check(self) -> None:
        """취소되었거나 단조 시계 기준 기한이 지났으면 TimeoutError 발생."""
        if self.parent is not None:
            self.parent.check()
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError("외부 호출의 실행 시간이 끝났거나 요청이 취소되었습니다.")


_active_budget: ContextVar[ExternalCallBudget | None] = ContextVar("external_call_budget", default=None)


@contextmanager
def external_call_scope(seconds: float) -> Iterator[ExternalCallBudget]:
    """외부 호출 기한을 설정하고 공유 취소 핸들을 반환한다.

    Args: seconds는 양의 유한 제한 시간. 중첩 범위는 상위 기한·취소도 준수한다.
    Yields: cancel()로 asyncio.to_thread에 복사된 범위도 중단 표시 가능한 핸들.
    Exit: 범위를 취소하고 이전 ContextVar 복구. 잘못된 시간은 ValueError.
    이미 전송된 HTTP를 강제로 종료하지 않으며 다음 check에서 중단한다.
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("외부 호출 제한 시간은 양의 유한 값이어야 합니다.")
    parent = _active_budget.get()
    deadline = time.monotonic() + seconds
    budget = ExternalCallBudget(min(deadline, parent.deadline) if parent else deadline, parent=parent)
    token = _active_budget.set(budget)
    try:
        yield budget
    finally:
        budget.cancel()
        _active_budget.reset(token)


def check_external_budget() -> None:
    """활성 범위의 취소·기한 검사. 범위 없는 CLI 호출은 그대로 허용."""
    budget = _active_budget.get()
    if budget is not None:
        budget.check()
