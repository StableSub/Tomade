"""취소·기한이 지난 호출의 후속 HTTP·임베딩 배치 중단 검증."""

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stock_agent.control.external_budget import check_external_budget, external_call_scope
from stock_agent.rag.service import embed_texts, ensure_disclosures_ready
from stock_agent.vendors import dart_client, financials_client, tavily_client, toss_client, youtube_client
from tests.test_disclosure_rag import REPORT, archive


class BudgetTest(unittest.TestCase):
    def test_no_scope_is_noop_and_expired_scope_restores_previous(self):
        check_external_budget()
        with patch("stock_agent.control.external_budget.time.monotonic", return_value=100) as clock:
            with external_call_scope(2):
                clock.return_value = 101
                check_external_budget()
                clock.return_value = 102
                with self.assertRaises(TimeoutError):
                    check_external_budget()
        check_external_budget()

    def test_nested_scope_respects_parent_and_does_not_cancel_it_on_normal_exit(self):
        with external_call_scope(5) as outer:
            with external_call_scope(10) as inner:
                self.assertEqual(inner.deadline, outer.deadline)
            check_external_budget()
            with external_call_scope(10):
                outer.cancel()
                with self.assertRaises(TimeoutError):
                    check_external_budget()

    def test_invalid_duration(self):
        for seconds in (0, -1, float("inf"), float("nan")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                with external_call_scope(seconds):
                    pass

    def test_scope_exit_cancels_copied_to_thread_context_before_next_request(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def blocking_request_sequence():
            check_external_budget()
            calls.append("first")
            started.set()
            if not release.wait(2):
                raise AssertionError("test release missing")
            check_external_budget()
            calls.append("second")

        async def scenario():
            with external_call_scope(5):
                task = asyncio.create_task(asyncio.to_thread(blocking_request_sequence))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
            release.set()
            with self.assertRaises(TimeoutError):
                await task

        asyncio.run(scenario())
        self.assertEqual(calls, ["first"])

    @patch("stock_agent.rag.service.OpenAI")
    def test_embedding_does_not_start_next_batch_after_cancellation(self, openai):
        with external_call_scope(5) as budget:
            def first_batch(**kwargs):
                budget.cancel()
                return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0, 0.0])
                                             for i in range(len(kwargs["input"]))])
            create = openai.return_value.embeddings.create
            create.side_effect = first_batch
            with self.assertRaises(TimeoutError):
                embed_texts(["sample"] * 65)
        self.assertEqual(create.call_count, 1)
        openai.assert_called_once_with(timeout=30, max_retries=0)

    @patch("stock_agent.rag.service.parse_archive")
    @patch("stock_agent.rag.service.download_disclosure_original")
    def test_cancelled_download_preserves_original_without_starting_parse(self, download, parse):
        with tempfile.TemporaryDirectory() as tmp, external_call_scope(5) as budget:
            def current_download(receipt):
                budget.cancel()
                return archive()
            download.side_effect = current_download
            with self.assertRaises(TimeoutError):
                ensure_disclosures_ready([REPORT], Path(tmp), embed=Mock())
            self.assertTrue((Path(tmp) / "raw" / REPORT["corp_code"] / REPORT["rcept_no"] / "source.zip").exists())
            parse.assert_not_called()

    @patch("stock_agent.vendors.dart_client._get_api_key", return_value="fixture")
    @patch("stock_agent.vendors.dart_client.requests.get")
    def test_dart_pagination_stops_after_current_response(self, get, key):
        with external_call_scope(5) as budget:
            def first_response():
                budget.cancel()
                return {"status": "000", "total_page": 2, "list": [REPORT]}
            get.return_value = Mock(json=first_response)
            with self.assertRaises(TimeoutError):
                dart_client.list_disclosure_reports("00126380", "2026-01-01", "2026-03-10")
        self.assertEqual(get.call_count, 1)

    @patch("stock_agent.vendors.toss_client._get_access_token")
    @patch("stock_agent.vendors.toss_client.requests.get")
    def test_toss_rechecks_after_token_work_before_retry(self, get, token):
        with external_call_scope(5) as budget:
            def access_token(rejected_token=None):
                if rejected_token is not None:
                    budget.cancel()
                return "fixture"
            token.side_effect = access_token
            get.return_value = Mock(status_code=401)
            with self.assertRaises(TimeoutError):
                toss_client._get("/api/v1/candles", {})
        self.assertEqual(get.call_count, 1)
        self.assertEqual(token.call_count, 2)

    @patch.dict("os.environ", {"DART_OPENAPI_KEY": "fixture", "YOUTUBE_API_KEY": "fixture",
                               "TOSS_CLIENT_ID": "fixture", "TOSS_CLIENT_SECRET": "fixture"})
    def test_cancelled_budget_blocks_each_vendor_boundary(self):
        cases = [
            ("dart", "stock_agent.vendors.dart_client.requests.get",
             lambda: dart_client.download_disclosure_original("20260310002820")),
            ("financial", "stock_agent.vendors.financials_client.requests.get",
             lambda: financials_client._request("list", {})),
            ("youtube", "stock_agent.vendors.youtube_client.requests.get",
             lambda: youtube_client._get("search", {})),
            ("tavily", "stock_agent.vendors.tavily_client._get_client",
             lambda: tavily_client._request("search", query="sample")),
            ("toss_auth", "stock_agent.vendors.toss_client.requests.post",
             lambda: toss_client._get_access_token()),
        ]
        for name, boundary, invoke in cases:
            with self.subTest(vendor=name), patch(boundary) as request, patch.object(toss_client, "_token", None):
                with external_call_scope(5) as budget:
                    budget.cancel()
                    with self.assertRaises(TimeoutError):
                        invoke()
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
