"""상위 Agent의 직접 답변·병렬 조사 후 재진입을 실제 LangGraph와 Mock 모델로 검증한다."""

import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from langgraph.config import get_stream_writer
from pydantic import ValidationError

from backend.main import app
from stock_agent.agents.orchestrator import UpperDecision
from stock_agent.graph import build_graph
from stock_agent.state import ResearchPlan, ResearchTask


def research_decision(names=("business",)):
    """선택한 Worker에 대해 유효한 테스트용 조사 결정을 만든다."""
    return UpperDecision(intent="research", research_plan=ResearchPlan(
        planning_summary="필요한 조사", tasks=[ResearchTask(agent=n, objective="확인",
        questions=["무슨 변화인가?"], completion_criteria=["근거 확인"]) for n in names]))


def test_graph(input_error=None):
    """Parser·Worker만 대체하고 상위 Agent와 실제 병렬 분기를 유지한 그래프를 만든다."""
    parser = Mock(return_value={"input_error": input_error} if input_error else {
        "research_mandate": {"original_question": "질문", "corp_name": "삼성전자", "ticker": "005930"}})
    workers = {n: Mock(return_value={f"{n}_report": f"{n} 근거 보고서"})
               for n in ("business", "macro_sector", "event_catalyst")}
    with patch("stock_agent.graph.request_parsing_node", parser), \
         patch("stock_agent.graph.business_agent_node", workers["business"]), \
         patch("stock_agent.graph.macro_sector_agent_node", workers["macro_sector"]), \
         patch("stock_agent.graph.event_catalyst_agent_node", workers["event_catalyst"]):
        graph = build_graph()
    return graph, parser, workers


class UpperAgentTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5000))
        self.enterContext(patch("stock_agent.agents.orchestrator.read_user_memory", return_value=""))
        self.trace = self.enterContext(patch("stock_agent.graph.trajectory_run"))
        self.factory = self.enterContext(patch("stock_agent.agents.orchestrator.create_tool_agent"))
        self.answer = self.factory.return_value.invoke
        self.answer.return_value = {"structured_response": UpperDecision(intent="general", final_answer="일반 답변")}
        self.finish = self.enterContext(patch("stock_agent.agents.orchestrator.stream_agent_text", return_value="최종 조사 답변"))
        self.graph, self.parser, self.workers = test_graph()
        self.enterContext(patch("backend.main.graph", self.graph))

    def post(self, text="질문"):
        return self.client.post("/api/chat/stream", json={"message": text})

    def test_general_is_one_model_call_without_parser_or_workers(self):
        response = self.post()
        self.assertIn("일반 답변", response.text)
        self.factory.assert_called_once()
        self.parser.assert_not_called()
        self.finish.assert_not_called()
        self.trace.assert_not_called()
        for worker in self.workers.values():
            worker.assert_not_called()
        self.assertEqual(response.text.count("event: run.completed"), 1)

    def test_parallel_workers_return_to_same_agent_once(self):
        self.answer.return_value = {"structured_response": research_decision(tuple(self.workers))}
        response = self.post("삼성전자 분석")
        self.assertIn("최종 조사 답변", response.text)
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.factory.call_args_list[0].args[1], self.factory.call_args_list[1].args[1])
        for call in self.factory.call_args_list:
            self.assertEqual(call.kwargs["model_role"], "planner")
            self.assertEqual([tool.name for tool in call.args[0]], ["update_memory"])
        self.finish.assert_called_once()
        payload = str(self.finish.call_args.args[1])
        for name, worker in self.workers.items():
            worker.assert_called_once()
            self.assertIn(f"{name} 근거 보고서", payload)
        self.assertEqual(response.text.count('event: run.completed'), 1)
        self.assertEqual(response.text.count('event: run.started'), 1)
        self.assertNotIn('orchestrator_synthesis', response.text)

    def test_synthesis_stream_uses_upper_agent_id(self):
        self.answer.return_value = {"structured_response": research_decision()}
        def finish(*args):
            get_stream_writer()({"node": "upper_agent", "delta": "종합 중"})
            return "최종 답변"
        self.finish.side_effect = finish
        response = self.post()
        self.assertIn('event: node.delta', response.text)
        self.assertIn('"node":"upper_agent","delta":"종합 중"', response.text)
        self.assertEqual(response.text.count('event: run.completed'), 1)

    def test_only_selected_worker_runs(self):
        self.answer.return_value = {"structured_response": research_decision()}
        self.post()
        self.workers["business"].assert_called_once()
        self.workers["macro_sector"].assert_not_called()
        self.workers["event_catalyst"].assert_not_called()

    def test_invalid_input_stops_before_workers(self):
        self.answer.return_value = {"structured_response": research_decision()}
        graph, _, workers = test_graph("기업을 확인할 수 없습니다.")
        with patch("backend.main.graph", graph):
            response = self.post()
        self.assertIn("input_error", response.text)
        self.assertNotIn("event: run.completed", response.text)
        self.finish.assert_not_called()
        for worker in workers.values():
            worker.assert_not_called()

    def test_worker_failure_does_not_synthesize(self):
        self.answer.return_value = {"structured_response": research_decision()}
        self.workers["business"].side_effect = RuntimeError("private secret")
        response = self.post()
        self.assertIn("run.error", response.text)
        self.assertNotIn("private secret", response.text)
        self.finish.assert_not_called()

    def test_direct_research_endpoint(self):
        self.answer.return_value = {"structured_response": research_decision()}
        with patch("backend.main.trajectory_run"):
            response = self.client.post("/api/research/stream", json={"message": "삼성전자 분석"})
        self.assertIn("최종 조사 답변", response.text)
        self.assertTrue(self.parser.call_args.args[0]["research_only"])

    def test_decision_requires_exactly_one_result(self):
        for fields in ({"intent": "general"}, {"intent": "research"},
                       {"intent": "general", "final_answer": "답", "research_plan": research_decision().research_plan}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                UpperDecision(**fields)
