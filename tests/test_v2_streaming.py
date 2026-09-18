"""외부 호출 없이 v2 Worker 결과·공개 출력 경계를 두 SSE API에서 검증한다."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.main import app


class ExampleTask(BaseModel):
    agent: str
    objective: str = "근거 확인"
    questions: list[str] = ["확인할 수 있는 내용은?"]
    completion_criteria: list[str] = ["근거와 한계 반환"]


class ExamplePlan(BaseModel):
    planning_summary: str = "기술 지표와 댓글 표본 조사"
    tasks: list[ExampleTask]


class ExampleEvidence(BaseModel):
    evidence_id: str
    source: dict[str, str]
    value: float


class ExampleReport(BaseModel):
    agent: str
    status: str
    summary: str
    evidence: list[ExampleEvidence]
    missing_items: list[str] = []


class ExampleFailure(BaseModel):
    agent: str
    status: str = "error"
    error: dict[str, str | bool]


class V2StreamingTest(unittest.TestCase):
    """상태 모델의 변경과 독립적으로 SSE의 전달·직렬화 계약을 검증한다."""

    endpoints = ("/api/chat/stream", "/api/research/stream")
    worker_names = {"business", "macro_sector", "event_catalyst", "technical", "sentiment"}
    private_state = {
        "short_term_summary": "PRIVATE_SUMMARY_DO_NOT_STREAM",
        "recent_messages": [{"role": "user", "content": "PRIVATE_HISTORY_DO_NOT_STREAM"}],
        "memory_enabled": True,
    }

    def setUp(self):
        self.client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5000))
        self.enterContext(patch("backend.main.trajectory_run"))
        self.enterContext(patch("backend.main.model_configuration", return_value={"provider": "mock"}))

    def post_events(self, endpoint, updates):
        async def stream():
            for update in updates:
                yield update

        with patch("backend.main.graph.astream", return_value=stream()) as astream:
            response = self.client.post(endpoint, json={"message": "삼성전자 기술 지표와 댓글 반응"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        frames = []
        for frame in response.text.strip().split("\n\n"):
            event, data = frame.split("\ndata: ", 1)
            frames.append((event.removeprefix("event: "), json.loads(data)))
        graph_input = astream.call_args.args[0]
        self.assertEqual(graph_input["research_only"], endpoint == "/api/research/stream")
        self.assertEqual(graph_input["memory_enabled"], endpoint == "/api/chat/stream")
        self.assertEqual(astream.call_args.kwargs, {
            "stream_mode": ["custom", "updates"], "subgraphs": True,
        })
        self.assertNotIn("PRIVATE_SUMMARY_DO_NOT_STREAM", response.text)
        self.assertNotIn("PRIVATE_HISTORY_DO_NOT_STREAM", response.text)
        return frames

    def updates(self, technical, sentiment, *, as_models):
        plan = ExamplePlan(tasks=[ExampleTask(agent="technical"), ExampleTask(agent="sentiment")])
        encode = lambda value: value if as_models else value.model_dump()
        return [
            ((), "updates", {"upper_agent": {
                "intent": "research", "research_plan": encode(plan), **self.private_state,
            }}),
            (("research:mock",), "updates", {"request_parser": {
                "parsed_request": {"company_candidates": ["삼성전자"], "research_question": "기술 지표와 댓글 반응"},
                "research_mandate": {"ticker": "005930", "corp_name": "삼성전자", "as_of_date": "2026-09-17"},
                "input_error": None, **self.private_state,
            }}),
            (("research:mock",), "custom", {"node": "technical", "delta": "기술 지표 확인"}),
            (("research:mock",), "updates", {"technical": {
                "technical_report": encode(technical), "sentiment_report": "NOT_OWN_REPORT",
                **self.private_state,
            }}),
            (("research:mock",), "updates", {"sentiment": {
                "sentiment_report": encode(sentiment), "technical_report": "NOT_OWN_REPORT",
                **self.private_state,
            }}),
            ((), "updates", {"upper_agent": {
                "final_answer": "기술 지표와 댓글 자료의 확보 상황을 반영한 최종 답변", **self.private_state,
            }}),
        ]

    @staticmethod
    def report(agent, status):
        return ExampleReport(agent=agent, status=status, summary=f"{agent} 확인 결과",
                             evidence=[] if status == "unavailable" else [ExampleEvidence(
                                 evidence_id=f"{agent}:1", value=1.25,
                                 source={"url": "https://example.com/source", "provider": "fixture"})],
                             missing_items=[] if status == "complete" else ["일부 자료 부족"])

    def test_selected_v2_reports_are_serialized_with_only_public_node_fields(self):
        for endpoint in self.endpoints:
            for as_models in (False, True):
                with self.subTest(endpoint=endpoint, as_models=as_models):
                    technical = self.report("technical", "complete")
                    sentiment = self.report("sentiment", "partial")
                    frames = self.post_events(endpoint, self.updates(technical, sentiment, as_models=as_models))
                    completed = [data for event, data in frames if event == "node.completed"]
                    self.assertEqual([item["node"] for item in completed],
                                     ["upper_agent", "request_parser", "technical", "sentiment", "upper_agent"])
                    self.assertEqual(set(completed[0]["output"]), {"intent", "research_plan"})
                    self.assertEqual(set(completed[1]["output"]), {"parsed_request", "research_mandate", "input_error"})
                    self.assertEqual(completed[2]["output"], {"technical_report": technical.model_dump()})
                    self.assertEqual(completed[3]["output"], {"sentiment_report": sentiment.model_dump()})
                    self.assertEqual(completed[2]["status"], "complete")
                    self.assertEqual(completed[3]["status"], "partial")
                    self.assertEqual(set(completed[4]["output"]), {"final_answer"})
                    skipped = {data["node"] for event, data in frames if event == "node.skipped"}
                    self.assertEqual(skipped, self.worker_names - {"technical", "sentiment"})
                    started = [data["node"] for event, data in frames if event == "node.started"]
                    self.assertEqual(started.count("technical"), 1)
                    self.assertEqual(started.count("sentiment"), 1)
                    self.assertEqual(started.count("upper_agent"), 2)
                    self.assertTrue(any(event == "node.delta" and data["node"] == "technical" for event, data in frames))
                    self.assert_successful_final(frames)

    def test_unavailable_or_failed_worker_still_allows_upper_final_answer(self):
        for endpoint in self.endpoints:
            for status in ("unavailable", "error"):
                for as_models in (False, True):
                    with self.subTest(endpoint=endpoint, status=status, as_models=as_models):
                        sentiment = (ExampleFailure(agent="sentiment", error={
                            "code": "upstream_timeout", "message": "댓글 수집 시간 초과", "retryable": True,
                        }) if status == "error" else self.report("sentiment", status))
                        frames = self.post_events(endpoint, self.updates(
                            self.report("technical", "complete"), sentiment, as_models=as_models,
                        ))
                        result = next(data for event, data in frames
                                      if event == "node.completed" and data["node"] == "sentiment")
                        self.assertEqual(result["status"], status)
                        self.assertEqual(result["output"], {"sentiment_report": sentiment.model_dump()})
                        self.assert_successful_final(frames)

    def test_direct_answer_skips_parser_and_all_five_workers(self):
        for endpoint in self.endpoints:
            with self.subTest(endpoint=endpoint):
                frames = self.post_events(endpoint, [((), "updates", {"upper_agent": {
                    "intent": "general", "final_answer": "안녕하세요.", **self.private_state,
                }})])
                skipped = [data["node"] for event, data in frames if event == "node.skipped"]
                self.assertEqual(set(skipped), {"request_parser", *self.worker_names})
                self.assertEqual(len(skipped), 6)
                completed = [data for event, data in frames if event == "node.completed"]
                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0]["output"], {"intent": "general", "final_answer": "안녕하세요."})
                self.assert_successful_final(frames, final_answer="안녕하세요.")

    def assert_successful_final(self, frames, final_answer="기술 지표와 댓글 자료의 확보 상황을 반영한 최종 답변"):
        self.assertFalse(any(event == "run.error" for event, _ in frames))
        self.assertEqual(sum(event == "run.started" for event, _ in frames), 1)
        completed = [data for event, data in frames if event == "run.completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["final_answer"], final_answer)


if __name__ == "__main__":
    unittest.main()
