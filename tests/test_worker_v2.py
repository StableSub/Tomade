"""실제 Worker 실행기의 권한·예산·근거 계약을 외부 API 없이 검증한다."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
import requests

from stock_agent.agents.worker import run_worker
from stock_agent.state import ResearchPlan, ResearchTask, WorkerError, WorkerReport


def evidence(evidence_id="e1", **changes):
    item = {"evidence_id": evidence_id, "kind": "excerpt", "content": "코드가 수집한 원문",
            "source": {"provider": "official", "url": "https://example.org/disclosure"},
            "published_at": "2026-09-16", "retrieved_at": "2026-09-18T10:00:00+09:00"}
    return {**item, **changes}


def state_for(role="business", questions=None):
    return {
        "research_plan": ResearchPlan(planning_summary="PRIVATE_PLAN", tasks=[
            ResearchTask(agent=role, objective="배정 영역 확인", questions=questions or ["변화는?"],
                         completion_criteria=["근거와 한계 확인"]),
            ResearchTask(agent="sentiment" if role != "sentiment" else "business",
                         objective="PRIVATE_OTHER_TASK", questions=["다른 영역 질문"],
                         completion_criteria=["다른 기준"])]),
        "research_mandate": {"original_question": "삼성전자 변화는?", "research_question": "변화는?",
            "ticker": "005930", "corp_name": "삼성전자", "corp_code": "00126380",
            "as_of_date": "2026-09-17", "period_days": 30, "query_start_date": "2026-08-19",
            "query_end_date": "2026-09-17", "investment_horizon": None,
            "purpose": "리서치", "constraints": ["기준일 이후 제외"]},
        "short_term_summary": "PRIVATE_MEMORY", "recent_messages": [("user", "PRIVATE_CHAT")],
        "memory_enabled": True, "business_report": "PRIVATE_PREVIOUS_REPORT",
    }


def draft(*, ids=None, status="complete", unanswered=None):
    return {"status": status, "findings": [{"question_index": 0, "statement": "원문에 따른 확인",
            "kind": "fact", "evidence_ids": ids or ["e1"]}],
            "unanswered_questions": unanswered or [], "limitations": []}


def response(*calls):
    return AIMessage(content="", tool_calls=[{"id": f"call-{i}", "name": name,
                     "args": args, "type": "tool_call"} for i, (name, args) in enumerate(calls)])


def fake_tool(name, result=None, error=None, started=None):
    calls = []

    async def invoke(query: str = "") -> str:
        calls.append(query)
        if started is not None:
            started.set()
            await asyncio.Future()
        if error is not None:
            raise error
        return json.dumps(result or {"status": "complete", "evidence": [evidence()]}, ensure_ascii=False)

    return StructuredTool.from_function(coroutine=invoke, name=name, description="검증용 자료 조회"), calls


class WorkerContractTest(unittest.IsolatedAsyncioTestCase):
    def models(self, responses=(), report=None):
        investigation = Mock(ainvoke=AsyncMock(side_effect=list(responses)))
        writer = Mock(ainvoke=AsyncMock(return_value=draft() if report is None else report))
        model = Mock()
        model.bind_tools.return_value = investigation
        model.with_structured_output.return_value = writer
        self.enterContext(patch("stock_agent.agents.worker.get_chat_model", return_value=model))
        return model, investigation, writer

    async def test_real_worker_preserves_collected_evidence_and_hides_private_context(self):
        original = evidence(content="직접 확보한 원문 및 수치 123", source={"provider": "DART", "rcept_no": "20260101000123"})
        tool, _ = fake_tool("search_disclosure_evidence", {"status": "complete", "evidence": [original]})
        _, investigator, writer = self.models([
            response((tool.name, {"query": "사업 변화"})), response()])
        result = await run_worker(state_for(), "business", [tool])

        report = result["business_report"]
        self.assertIsInstance(report, WorkerReport)
        self.assertEqual(report.evidence[0].content, original["content"])
        self.assertEqual(report.evidence[0].source, original["source"])
        for call in [*investigator.ainvoke.call_args_list, *writer.ainvoke.call_args_list]:
            supplied = "\n".join(message.content for message in call.args[0])
            for secret in ("PRIVATE_PLAN", "PRIVATE_OTHER_TASK", "PRIVATE_MEMORY", "PRIVATE_CHAT", "PRIVATE_PREVIOUS_REPORT"):
                self.assertNotIn(secret, supplied)
            self.assertIn("배정 영역 확인", supplied)

    async def test_wrong_tool_binding_is_rejected_before_model_or_external_call(self):
        tool, calls = fake_tool("get_technical_evidence")
        model, _, _ = self.models()
        with self.assertRaises(ValueError):
            await run_worker(state_for(), "business", [tool])
        self.assertEqual(calls, [])
        model.bind_tools.assert_not_called()

    async def test_model_cannot_execute_unbound_tool_or_repeat_same_arguments(self):
        tool, calls = fake_tool("search_web")
        self.models([response(("get_financial_evidence", {}),
                             ("search_web", {"query": "금리"}),
                             ("search_web", {"query": "금리"})), response()])
        result = await run_worker(state_for("macro_sector"), "macro_sector", [tool])
        self.assertEqual(calls, ["금리"])
        self.assertEqual(result["macro_sector_report"].status, "complete")
        self.assertTrue(result["macro_sector_report"].limitations)

    async def test_per_tool_and_total_budget_are_enforced_inside_a_model_batch(self):
        disclosure, disclosure_calls = fake_tool("search_disclosure_evidence")
        web, web_calls = fake_tool("search_web")
        market, market_calls = fake_tool("get_market_evidence")
        self.models([response(*[(disclosure.name, {"query": str(i)}) for i in range(4)],
                              *[(web.name, {"query": str(i)}) for i in range(3)],
                              (market.name, {}))])
        result = await run_worker(state_for("event_catalyst"), "event_catalyst", [disclosure, web, market])
        self.assertIsInstance(result["event_catalyst_report"], WorkerReport)
        self.assertEqual(disclosure_calls, ["0", "1", "2"])
        self.assertEqual(web_calls, ["0", "1"])
        self.assertEqual(market_calls, [])

    async def test_technical_prefetches_once_then_only_writes_a_report(self):
        tool, calls = fake_tool("get_technical_evidence")
        model, investigator, writer = self.models()
        result = await run_worker(state_for("technical"), "technical", [tool])
        self.assertIsInstance(result["technical_report"], WorkerReport)
        self.assertEqual(calls, [""])
        model.bind_tools.assert_not_called()
        investigator.ainvoke.assert_not_called()
        writer.ainvoke.assert_awaited_once()

    async def test_sentiment_collects_without_giving_model_any_tools(self):
        collect = Mock(return_value={"status": "complete", "evidence": [evidence(kind="comment")]})
        model, _, writer = self.models()
        state = state_for("sentiment")
        result = await run_worker(state, "sentiment", [], collect=collect)
        self.assertIsInstance(result["sentiment_report"], WorkerReport)
        collect.assert_called_once_with(state["research_mandate"])
        model.bind_tools.assert_not_called()
        writer.ainvoke.assert_awaited_once()

    async def test_incomplete_question_coverage_and_fabricated_ids_are_rejected(self):
        bad_reports = [(draft(), ["가격 위치?", "거래량 변화?"]),
                       (draft(ids=["invented"]), ["가격 위치?"]),
                       ({**draft(), "evidence": [evidence(content="모델이 바꾼 원문")]}, ["가격 위치?"]),
                       ({**draft(), "unanswered_questions": [{"question_index": 5, "reason": "없는 질문"}], "status": "partial"}, ["가격 위치?"])]
        for invalid, questions in bad_reports:
            with self.subTest(report=invalid):
                tool, _ = fake_tool("get_technical_evidence")
                self.models(report=invalid)
                result = await run_worker(state_for("technical", questions), "technical", [tool])
                self.assertIsInstance(result["technical_report"], WorkerError)

    async def test_partial_report_covers_unanswered_question_without_fabrication(self):
        tool, _ = fake_tool("get_technical_evidence")
        self.models(report=draft(status="partial", unanswered=[{"question_index": 1, "reason": "거래량 자료 부족"}]))
        report = (await run_worker(state_for("technical", ["가격 위치?", "거래량 변화?"]), "technical", [tool]))["technical_report"]
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.unanswered_questions[0].question_index, 1)
        self.assertEqual([item.evidence_id for item in report.evidence], ["e1"])

    async def test_future_and_undated_documents_never_reach_the_writer(self):
        items = [evidence(), evidence("future", published_at="2026-09-18"),
                 evidence("unknown", published_at=None),
                 evidence("future-price", kind="metric", published_at=None, observation_end="2026-09-18")]
        tool, _ = fake_tool("get_technical_evidence", {"status": "complete", "evidence": items})
        _, _, writer = self.models()
        report = (await run_worker(state_for("technical"), "technical", [tool]))["technical_report"]
        payload = json.loads(writer.ainvoke.call_args.args[0][1].content)
        self.assertEqual([item["evidence_id"] for item in payload["evidence"]], ["e1"])
        self.assertTrue(report.limitations)

    async def test_publication_timestamp_uses_korean_cutoff_not_utc_date_prefix(self):
        items = [evidence("e1", published_at="2026-09-17T14:59:00+00:00"),
                 evidence("next-korean-day", published_at="2026-09-17T15:30:00+00:00")]
        tool, _ = fake_tool("get_technical_evidence", {"status": "complete", "evidence": items})
        _, _, writer = self.models()
        await run_worker(state_for("technical"), "technical", [tool])
        payload = json.loads(writer.ainvoke.call_args.args[0][1].content)
        self.assertEqual([item["evidence_id"] for item in payload["evidence"]], ["e1"])

    async def test_conflicting_content_for_same_evidence_id_is_rejected(self):
        tool, _ = fake_tool("get_technical_evidence", {"status": "complete", "evidence": [evidence(), evidence(content="다른 원문")]})
        _, _, writer = self.models()
        result = await run_worker(state_for("technical"), "technical", [tool])
        self.assertIsInstance(result["technical_report"], WorkerError)
        writer.ainvoke.assert_not_called()

    async def test_tool_failure_keeps_other_evidence_and_records_partial_answer(self):
        disclosure, _ = fake_tool("search_disclosure_evidence")
        financials, _ = fake_tool("get_financial_evidence", error=requests.Timeout("PRIVATE_API_SECRET"))
        self.models([response((disclosure.name, {"query": "사업"}), (financials.name, {})), response()],
                    draft(status="partial", unanswered=[{"question_index": 1, "reason": "재무 조회 실패"}]))
        report = (await run_worker(state_for(questions=["사업 변화?", "영업이익? "]), "business", [disclosure, financials]))["business_report"]
        self.assertIsInstance(report, WorkerReport)
        self.assertEqual(report.status, "partial")
        self.assertEqual(len(report.evidence), 1)
        self.assertIn("실행 실패", " ".join(report.limitations))
        self.assertNotIn("PRIVATE_API_SECRET", report.model_dump_json())

    async def test_collection_error_and_no_data_are_distinct_without_model_judgment(self):
        for result, expected in [({"status": "unavailable", "evidence": [], "reason": "기간 내 자료 없음"}, WorkerReport),
                                 ({"status": "error", "evidence": [], "error": {"code": "auth", "message": "인증 필요"}}, WorkerError)]:
            with self.subTest(status=result["status"]):
                model, _, writer = self.models()
                report = (await run_worker(state_for("sentiment"), "sentiment", [], collect=lambda _: result))["sentiment_report"]
                self.assertIsInstance(report, expected)
                self.assertEqual(report.status, "unavailable" if expected is WorkerReport else "error")
                writer.ainvoke.assert_not_called()
                model.bind_tools.assert_not_called()

    async def test_invalid_model_calls_have_a_finite_investigation_budget(self):
        tool, calls = fake_tool("search_web")
        _, investigator, writer = self.models([response(("unavailable_tool", {})) for _ in range(6)])
        report = (await run_worker(state_for("macro_sector"), "macro_sector", [tool]))["macro_sector_report"]
        self.assertEqual(report.status, "unavailable")
        self.assertEqual(calls, [])
        self.assertEqual(investigator.ainvoke.await_count, 6)
        writer.ainvoke.assert_not_called()

    async def test_cancellation_propagates_instead_of_returning_an_error_report(self):
        started = asyncio.Event()
        tool, _ = fake_tool("get_technical_evidence", started=started)
        self.models()
        task = asyncio.create_task(run_worker(state_for("technical"), "technical", [tool]))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_model_timeout_ends_worker_with_execution_error(self):
        tool, _ = fake_tool("get_technical_evidence")
        _, _, writer = self.models()

        async def stalled(*args, **kwargs):
            await asyncio.Future()

        writer.ainvoke.side_effect = stalled
        with patch("stock_agent.agents.worker.MODEL_SECONDS", 0.01):
            report = (await run_worker(state_for("technical"), "technical", [tool]))["technical_report"]
        self.assertIsInstance(report, WorkerError)
        self.assertEqual(report.code, "TimeoutError")

    async def test_investigation_timeout_still_writes_report_from_collected_evidence(self):
        tool, calls = fake_tool("search_disclosure_evidence")
        _, investigator, writer = self.models(report=draft(status="partial", unanswered=[
            {"question_index": 1, "reason": "추가 조사 시간 한도 도달"}]))

        async def investigate(*args, **kwargs):
            if not calls:
                return response((tool.name, {"query": "사업 변화"}))
            await asyncio.Future()

        investigator.ainvoke.side_effect = investigate
        with patch("stock_agent.agents.worker.MODEL_SECONDS", 0.01):
            report = (await run_worker(state_for(questions=["사업 변화?", "추가 위험? "]),
                                       "business", [tool]))["business_report"]

        self.assertIsInstance(report, WorkerReport)
        self.assertEqual(report.status, "partial")
        self.assertEqual(calls, ["사업 변화"])
        writer.ainvoke.assert_awaited_once()
        payload = json.loads(writer.ainvoke.call_args.args[0][1].content)
        self.assertEqual(payload["evidence"][0]["evidence_id"], "e1")
        self.assertEqual(report.evidence[0].content, "코드가 수집한 원문")
        self.assertTrue(any("시간 한도" in limitation for limitation in report.limitations))
