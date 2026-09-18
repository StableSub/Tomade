"""Agent 실행의 Tool, Evidence, 모델 호출, 노드 지연과 오류 상태를 파일에 기록한다."""

import datetime
import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TRACE_ROOT = _PROJECT_ROOT / "traces"
_WORKER_NODES = frozenset({"business", "macro_sector", "event_catalyst", "technical", "sentiment"})
_CURRENT_TRAJECTORY: ContextVar["TrajectoryRecorder | None"] = ContextVar(
    "stock_agent_trajectory",
    default=None,
)


class TrajectoryRecorder:
    """실행 하나의 관측 가능한 Trajectory를 pretty JSON 파일로 유지한다.

    모델 내부 추론이나 Token delta는 저장하지 않는다. 각 변경은 임시 파일을
    거쳐 원자적으로 반영하므로 실행 도중 프로세스가 종료되어도 마지막으로
    완료된 모델·Tool·노드 이벤트까지 확인할 수 있다.

    Args:
        run_id: API 실행과 Trace 파일을 연결할 고유 식별자.
        trace_root: 날짜별 Trace 디렉터리를 만들 상위 경로. 기본값은 프로젝트의
            `traces/`이며 테스트에서는 임시 디렉터리를 지정할 수 있다.
    """

    def __init__(self, run_id: str, trace_root: Path | None = None) -> None:
        started_at = _now()
        safe_run_id = re.sub(r"[^A-Za-z0-9._-]", "-", run_id).strip("-.")
        if not safe_run_id:
            raise ValueError("run_id에 파일명으로 사용할 문자가 필요합니다.")

        root = trace_root or _DEFAULT_TRACE_ROOT
        self.path = root / started_at.date().isoformat() / f"{safe_run_id}.json"
        self._lock = threading.RLock()
        self._closed = False
        self._persistence_disabled = False
        self._seen_model_runs: set[str] = set()
        self._tool_started_at: dict[str, float] = {}
        self._latest_state: Any = None
        self._data: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="milliseconds"),
            "finished_at": None,
            "status": "running",
            "model_call_counts": {},
            "workers": {},
            "node_timings": [],
            "failure": None,
        }
        with self._lock:
            self._flush_locked()

    def record_model_start(self, node_name: str, run_id: UUID | str) -> None:
        """중복 Callback을 제외하고 노드별 모델 호출 횟수를 증가시킨다."""
        model_run_id = str(run_id)
        with self._lock:
            if self._closed or model_run_id in self._seen_model_runs:
                return
            self._seen_model_runs.add(model_run_id)
            counts = self._data["model_call_counts"]
            counts[node_name] = counts.get(node_name, 0) + 1
            self._flush_locked()

    def record_tool_start(
        self,
        node_name: str,
        tool_call_id: UUID | str,
        tool_name: str,
        arguments: Any,
    ) -> None:
        """Worker 내부 Tool 이름과 정규화된 호출 인자를 기록한다."""
        if node_name not in _WORKER_NODES:
            return
        call_id = str(tool_call_id)
        started_at = _now()
        with self._lock:
            if self._closed:
                return
            worker = self._worker_locked(node_name)
            worker["tool_calls"].append(
                {
                    "tool_call_id": call_id,
                    "tool": tool_name,
                    "arguments": _json_value(arguments),
                    "result": None,
                    "status": "running",
                    "started_at": started_at.isoformat(timespec="milliseconds"),
                    "finished_at": None,
                    "latency_ms": None,
                    "error": None,
                }
            )
            self._tool_started_at[call_id] = time.perf_counter()
            self._flush_locked()

    def record_tool_end(
        self,
        node_name: str,
        tool_call_id: UUID | str,
        output: Any,
    ) -> None:
        """Tool 결과를 저장하고 해당 호출을 Worker Evidence로 연결한다."""
        if node_name not in _WORKER_NODES:
            return
        call_id = str(tool_call_id)
        with self._lock:
            if self._closed:
                return
            worker = self._worker_locked(node_name)
            tool_call = self._find_tool_call_locked(worker, call_id)
            if tool_call is None:
                return
            tool_call["result"] = _tool_output_value(output)
            tool_call["status"] = "completed"
            tool_call["finished_at"] = _now().isoformat(timespec="milliseconds")
            tool_call["latency_ms"] = self._tool_latency_locked(call_id)
            if call_id not in worker["evidence_tool_call_ids"]:
                worker["evidence_tool_call_ids"].append(call_id)
            self._flush_locked()

    def record_tool_error(
        self,
        node_name: str,
        tool_call_id: UUID | str,
        error: BaseException,
    ) -> None:
        """실패한 Tool 호출의 오류와 실패 시점까지의 지연 시간을 기록한다."""
        if node_name not in _WORKER_NODES:
            return
        call_id = str(tool_call_id)
        with self._lock:
            if self._closed:
                return
            worker = self._worker_locked(node_name)
            tool_call = self._find_tool_call_locked(worker, call_id)
            if tool_call is None:
                return
            tool_call["status"] = "error"
            tool_call["finished_at"] = _now().isoformat(timespec="milliseconds")
            tool_call["latency_ms"] = self._tool_latency_locked(call_id)
            tool_call["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            self._flush_locked()

    def record_node_timing(
        self,
        node_name: str,
        started_at: datetime.datetime,
        started_perf: float,
        *,
        status: str,
        state_before: Any,
        output: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """상위 LangGraph 노드의 지연 시간과 실패 직전 공유 상태를 기록한다."""
        finished_at = _now()
        with self._lock:
            if self._closed:
                return
            self._data["node_timings"].append(
                {
                    "node": node_name,
                    "status": status,
                    "started_at": started_at.isoformat(timespec="milliseconds"),
                    "finished_at": finished_at.isoformat(timespec="milliseconds"),
                    "latency_ms": round((time.perf_counter() - started_perf) * 1000, 2),
                }
            )
            self._latest_state = _merged_state(state_before, output)
            if error is not None:
                self._set_failure_locked(error, node_name, state_before)
            self._flush_locked()

    def record_run_failure(
        self,
        error: BaseException,
        *,
        node_name: str | None = None,
        state_before: Any = None,
    ) -> None:
        """그래프 외부에서 감지된 실행 오류와 가장 최근 상태를 기록한다."""
        with self._lock:
            if self._closed:
                return
            self._set_failure_locked(error, node_name, state_before)
            self._data["status"] = "error"
            self._flush_locked()

    def mark_status(self, status: str) -> None:
        """정상 완료, 입력 오류 같은 실행 종료 상태를 기록한다."""
        with self._lock:
            if self._closed:
                return
            self._data["status"] = status
            self._flush_locked()

    def close(self) -> None:
        """Trace 종료 시각과 최종 상태를 기록하고 추가 변경을 막는다."""
        with self._lock:
            if self._closed:
                return
            if self._data["status"] == "running":
                self._data["status"] = "completed"
            self._data["finished_at"] = _now().isoformat(timespec="milliseconds")
            self._flush_locked()
            self._closed = True

    def _worker_locked(self, node_name: str) -> dict[str, Any]:
        """호출자가 Lock을 보유한 상태에서 Worker Trace 컨테이너를 반환한다."""
        workers = self._data["workers"]
        if node_name not in workers:
            workers[node_name] = {
                "tool_calls": [],
                "evidence_tool_call_ids": [],
            }
        return workers[node_name]

    @staticmethod
    def _find_tool_call_locked(
        worker: dict[str, Any],
        call_id: str,
    ) -> dict[str, Any] | None:
        """Worker Trace에서 Tool 호출 ID가 일치하는 항목을 찾는다."""
        return next(
            (
                tool_call
                for tool_call in worker["tool_calls"]
                if tool_call["tool_call_id"] == call_id
            ),
            None,
        )

    def _tool_latency_locked(self, call_id: str) -> float | None:
        """Tool 시작 시각이 있으면 경과 밀리초를 계산하고 시작 기록을 제거한다."""
        started_perf = self._tool_started_at.pop(call_id, None)
        if started_perf is None:
            return None
        return round((time.perf_counter() - started_perf) * 1000, 2)

    def _set_failure_locked(
        self,
        error: BaseException,
        node_name: str | None,
        state_before: Any,
    ) -> None:
        """호출자가 Lock을 보유한 상태에서 최초 오류 Snapshot을 보존한다."""
        if self._data.get("failure") is not None:
            return
        failure_state = state_before if state_before is not None else self._latest_state
        self._data["failure"] = {
            "node": node_name,
            "type": type(error).__name__,
            "message": str(error),
            "state_before_error": _json_value(failure_state),
            "recorded_at": _now().isoformat(timespec="milliseconds"),
        }
        self._data["status"] = "error"

    def _flush_locked(self) -> None:
        """현재 Trace를 원자적으로 저장하며 실패하면 기록만 비활성화한다."""
        if self._persistence_disabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except Exception:
            self._persistence_disabled = True
            logger.exception(
                "Trajectory 저장을 비활성화합니다: %s",
                self.path,
            )


class TrajectoryCallbackHandler(BaseCallbackHandler):
    """LangChain 모델·Tool Callback을 현재 실행의 파일 Trace로 변환한다."""

    def __init__(self, recorder: TrajectoryRecorder, node_name: str) -> None:
        self._recorder = recorder
        self._node_name = node_name

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Chat Model 호출을 노드별 횟수에 반영한다."""
        del serialized, messages, kwargs
        self._recorder.record_model_start(self._node_name, run_id)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """문자열 기반 LLM 호출도 같은 모델 호출 횟수에 반영한다."""
        del serialized, prompts, kwargs
        self._recorder.record_model_start(self._node_name, run_id)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Worker Tool 이름과 호출 인자를 기록한다."""
        del kwargs
        tool_name = str(serialized.get("name") or "unknown")
        arguments = inputs if inputs is not None else _parse_tool_input(input_str)
        self._recorder.record_tool_start(
            self._node_name,
            run_id,
            tool_name,
            arguments,
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Worker Tool 결과를 저장하고 Evidence 참조에 추가한다."""
        del kwargs
        self._recorder.record_tool_end(self._node_name, run_id, output)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Worker Tool 실행 오류를 해당 Tool 호출에 기록한다."""
        del kwargs
        self._recorder.record_tool_error(self._node_name, run_id, error)


@contextmanager
def trajectory_run(
    run_id: str,
    *,
    trace_root: Path | None = None,
) -> Iterator[TrajectoryRecorder]:
    """현재 실행에 Recorder를 연결하고 종료 시 Trace 파일을 완성한다.

    Args:
        run_id: API와 Trace 파일에서 공유할 실행 ID.
        trace_root: 기본 `traces/` 대신 사용할 저장 경로.

    Yields:
        실행 상태와 오류를 추가로 기록할 수 있는 Recorder.
    """
    recorder = TrajectoryRecorder(run_id, trace_root=trace_root)
    token = _CURRENT_TRAJECTORY.set(recorder)
    try:
        yield recorder
    except Exception as error:
        recorder.record_run_failure(error)
        raise
    finally:
        recorder.close()
        _CURRENT_TRAJECTORY.reset(token)


def current_trajectory_callback(node_name: str) -> TrajectoryCallbackHandler | None:
    """활성 실행이 있으면 지정 노드용 LangChain Callback을 반환한다."""
    recorder = _CURRENT_TRAJECTORY.get()
    if recorder is None:
        return None
    return TrajectoryCallbackHandler(recorder, node_name)


def record_node_timing(
    node_name: str,
    started_at: datetime.datetime,
    started_perf: float,
    *,
    status: str,
    state_before: Any,
    output: Any = None,
    error: BaseException | None = None,
) -> None:
    """활성 실행이 있을 때 상위 노드 지연과 오류 상태를 Recorder에 전달한다."""
    recorder = _CURRENT_TRAJECTORY.get()
    if recorder is None:
        return
    recorder.record_node_timing(
        node_name,
        started_at,
        started_perf,
        status=status,
        state_before=state_before,
        output=output,
        error=error,
    )


def _now() -> datetime.datetime:
    """명시적 로컬 UTC offset을 포함한 현재 시각을 반환한다."""
    return datetime.datetime.now().astimezone()


def _parse_tool_input(input_str: str) -> Any:
    """Tool Callback의 문자열 인자를 JSON이면 객체로, 아니면 원문으로 보존한다."""
    try:
        return json.loads(input_str)
    except json.JSONDecodeError:
        return input_str


def _tool_output_value(output: Any) -> Any:
    """ToolMessage 계열은 Agent가 실제로 받은 content만 저장한다."""
    if hasattr(output, "content"):
        return _json_value(output.content)
    return _json_value(output)


def _merged_state(state_before: Any, output: Any) -> Any:
    """최근 공유 상태에 성공한 노드 상태 업데이트를 병합한다."""
    if not isinstance(state_before, dict):
        return _json_value(state_before)
    merged = dict(state_before)
    if isinstance(output, dict):
        merged.update(output)
    return _json_value(merged)


def _json_value(value: Any) -> Any:
    """Trace 값에서 Pydantic과 중첩 객체를 JSON 직렬화 가능한 값으로 바꾼다."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
