"""실행 Trajectory의 모델·Tool·Evidence·지연·오류 상태 저장을 검증한다."""

import contextlib
import datetime
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from stock_agent.debug import trace_node_output
from stock_agent.trajectory import (
    current_trajectory_callback,
    trajectory_run,
)


class TrajectoryRecorderTest(unittest.TestCase):
    """실행별 pretty JSON Trace의 필수 필드와 종료 상태를 검증한다."""

    def test_records_worker_activity_and_node_timing(self) -> None:
        """Worker의 모델·Tool·Evidence와 노드 지연 시간을 함께 저장한다."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_root = Path(temporary_directory)
            with trajectory_run("run-success", trace_root=trace_root) as recorder:
                callback = current_trajectory_callback("business")
                self.assertIsNotNone(callback)
                assert callback is not None

                callback.on_chat_model_start({}, [], run_id=uuid4())
                tool_call_id = uuid4()
                callback.on_tool_start(
                    {"name": "get_disclosure"},
                    "",
                    run_id=tool_call_id,
                    inputs={"corp_name": "삼성전자", "days": 30},
                )
                callback.on_tool_end(
                    "공시 Evidence",
                    run_id=tool_call_id,
                )
                started_at = datetime.datetime.now().astimezone()
                started_perf = time.perf_counter()
                recorder.record_node_timing(
                    "business",
                    started_at,
                    started_perf,
                    status="completed",
                    state_before={"research_plan": "plan"},
                    output={"business_report": "report"},
                )

            trace = json.loads(recorder.path.read_text(encoding="utf-8"))
            self.assertEqual(trace["status"], "completed")
            self.assertEqual(trace["model_call_counts"], {"business": 1})
            self.assertEqual(len(trace["node_timings"]), 1)
            self.assertEqual(trace["node_timings"][0]["node"], "business")

            worker = trace["workers"]["business"]
            self.assertEqual(len(worker["tool_calls"]), 1)
            tool_call = worker["tool_calls"][0]
            self.assertEqual(tool_call["tool"], "get_disclosure")
            self.assertEqual(
                tool_call["arguments"],
                {"corp_name": "삼성전자", "days": 30},
            )
            self.assertEqual(tool_call["result"], "공시 Evidence")
            self.assertEqual(tool_call["status"], "completed")
            self.assertEqual(
                worker["evidence_tool_call_ids"],
                [str(tool_call_id)],
            )

    def test_records_state_before_node_error(self) -> None:
        """노드 예외가 발생하면 해당 노드 입력 상태를 failure에 보존한다."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_root = Path(temporary_directory)
            with trajectory_run("run-error", trace_root=trace_root) as recorder:
                started_at = datetime.datetime.now().astimezone()
                started_perf = time.perf_counter()
                recorder.record_node_timing(
                    "event_catalyst",
                    started_at,
                    started_perf,
                    status="error",
                    state_before={
                        "research_mandate": {"ticker": "005930"},
                        "research_plan": "plan",
                    },
                    error=RuntimeError("worker failed"),
                )

            trace = json.loads(recorder.path.read_text(encoding="utf-8"))
            self.assertEqual(trace["status"], "error")
            self.assertEqual(trace["failure"]["node"], "event_catalyst")
            self.assertEqual(trace["failure"]["type"], "RuntimeError")
            self.assertEqual(trace["failure"]["message"], "worker failed")
            self.assertEqual(
                trace["failure"]["state_before_error"]["research_mandate"],
                {"ticker": "005930"},
            )

    def test_node_decorator_records_failure_state(self) -> None:
        """실제 노드 Decorator가 예외 직전 입력 상태를 Recorder에 전달한다."""

        @trace_node_output("failing_node")
        def failing_node(state: dict) -> dict:
            raise ValueError(f"invalid state: {state['step']}")

        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_root = Path(temporary_directory)
            with trajectory_run("decorator-error", trace_root=trace_root) as recorder:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError, "invalid state"):
                        failing_node({"step": "worker"})

            trace = json.loads(recorder.path.read_text(encoding="utf-8"))
            self.assertEqual(trace["failure"]["node"], "failing_node")
            self.assertEqual(
                trace["failure"]["state_before_error"],
                {"step": "worker"},
            )

    def test_preserves_first_failure_snapshot(self) -> None:
        """병렬 완료와 외부 오류가 뒤따라도 최초 노드 오류 상태를 바꾸지 않는다."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_root = Path(temporary_directory)
            with trajectory_run("first-failure", trace_root=trace_root) as recorder:
                recorder.record_node_timing(
                    "business",
                    datetime.datetime.now().astimezone(),
                    time.perf_counter(),
                    status="error",
                    state_before={"failed_worker": "business"},
                    error=RuntimeError("business failed"),
                )
                recorder.record_node_timing(
                    "macro_sector",
                    datetime.datetime.now().astimezone(),
                    time.perf_counter(),
                    status="completed",
                    state_before={"completed_worker": "macro_sector"},
                    output={"macro_sector_report": "report"},
                )
                recorder.record_run_failure(
                    ValueError("outer failure"),
                    node_name="macro_sector",
                )

            trace = json.loads(recorder.path.read_text(encoding="utf-8"))
            self.assertEqual(trace["failure"]["node"], "business")
            self.assertEqual(trace["failure"]["type"], "RuntimeError")
            self.assertEqual(trace["failure"]["message"], "business failed")
            self.assertEqual(
                trace["failure"]["state_before_error"],
                {"failed_worker": "business"},
            )

    def test_persistence_failure_does_not_break_execution(self) -> None:
        """Trace 경로를 쓸 수 없어도 Recorder 사용과 제품 실행은 계속된다."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            blocked_root = Path(temporary_directory) / "not-a-directory"
            blocked_root.write_text("blocked", encoding="utf-8")

            with self.assertLogs("stock_agent.trajectory", level="ERROR"):
                with trajectory_run("write-failure", trace_root=blocked_root) as recorder:
                    recorder.record_model_start("request_parser", uuid4())
                    recorder.mark_status("completed")

            self.assertFalse(recorder.path.exists())


if __name__ == "__main__":
    unittest.main()
