"""개발 중 LangGraph 노드의 출력과 오류를 터미널에 표시한다."""

import datetime
import json
import time
from collections.abc import Callable
from functools import wraps
from contextvars import ContextVar
from contextlib import contextmanager
from threading import Lock
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel

from stock_agent.trajectory import record_node_timing

P = ParamSpec("P")
R = TypeVar("R", bound=dict[str, Any])
_PRINT_LOCK = Lock()
_PRIVATE_RUN = ContextVar("private_node_run", default=False)


@contextmanager
def private_node_run():
    """현재 실행의 노드 stdout·추적을 끈다. 계좌 유래 조사에 사용하며 종료 시 복원한다."""
    token = _PRIVATE_RUN.set(True)
    try:
        yield
    finally:
        _PRIVATE_RUN.reset(token)


def trace_node_output(node_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """그래프 노드의 반환 상태 또는 예외를 보기 쉽게 출력하는 데코레이터다.

    Args:
        node_name: 디버그 구분선에 표시할 LangGraph 노드 이름.

    Returns:
        원래 함수의 인자·반환값·예외 동작을 유지하면서 성공 출력과 오류를
        터미널에 표시하는 동기 함수 데코레이터.

    Note:
        병렬 Worker의 출력이 서로 섞이지 않도록 출력 구간에 Lock을 사용한다.
        현재는 개발 편의를 위해 항상 출력하며 추후 로깅 계층으로 교체할 수 있다.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        """대상 노드 함수를 출력 추적 wrapper로 감싼다."""

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """노드를 실행하고 결과 또는 예외를 출력한 뒤 원래 동작을 유지한다."""
            if _PRIVATE_RUN.get():
                return func(*args, **kwargs)
            started_at = datetime.datetime.now().astimezone()
            started_perf = time.perf_counter()
            state_before = args[0] if args else kwargs.get("state")
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                record_node_timing(
                    node_name,
                    started_at,
                    started_perf,
                    status="error",
                    state_before=state_before,
                    error=error,
                )
                with _PRINT_LOCK:
                    _print_header(node_name, "ERROR")
                    print(f"{type(error).__name__}: {error}")
                    print("=" * 72, flush=True)
                raise

            record_node_timing(
                node_name,
                started_at,
                started_perf,
                status="completed",
                state_before=state_before,
                output=result,
            )
            with _PRINT_LOCK:
                _print_header(node_name, "OUTPUT")
                _print_result(result)
                print("=" * 72, flush=True)
            return result

        return wrapper

    return decorator


def _print_header(node_name: str, status: str) -> None:
    """한 노드의 디버그 출력 시작을 나타내는 구분선을 출력한다."""
    print(f"\n{'=' * 24} {node_name} {status} {'=' * 24}")


def _print_result(result: dict[str, Any]) -> None:
    """상태 업데이트의 문자열과 구조화 객체를 사람이 읽기 좋게 출력한다."""
    if not result:
        print("(빈 상태 업데이트: 선택되지 않아 실행을 건너뜀)")
        return

    for key, value in result.items():
        print(f"\n[{key}]")
        if isinstance(value, str):
            print(value)
            continue
        print(json.dumps(_to_json_value(value), ensure_ascii=False, indent=2))


def _to_json_value(value: Any) -> Any:
    """Pydantic과 중첩 컨테이너를 JSON 직렬화 가능한 값으로 변환한다."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    return value
