"""v2 공시 발견·정정 차단·부분 준비 재개와 공통 근거 계약 회귀 검증."""

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from stock_agent.rag.discovery import discover_disclosures
from stock_agent.rag.parser import VERSION
from stock_agent.rag.service import ensure_disclosures_ready, prepare_report, search_evidence
from stock_agent.tools.disclosure import make_disclosure_search_tool
from stock_agent.vendors.dart_client import list_disclosure_reports
from tests.test_disclosure_rag import REPORT, archive, fake_embed


class DiscoveryTest(unittest.TestCase):
    @patch("stock_agent.rag.discovery.list_disclosure_reports")
    def test_business_periodic_baseline_outside_event_range(self, listing):
        older_period_corrected_later = dict(REPORT, rcept_no="20260910000001", rcept_dt="20260910",
                                             report_nm="[기재정정]사업보고서 (2025.12)")
        latest = dict(REPORT, rcept_no="20260814000001", rcept_dt="20260814",
                      report_nm="반기보고서 (2026.06)")
        future = dict(REPORT, rcept_no="20260920000001", rcept_dt="20260920",
                      report_nm="[기재정정]반기보고서 (2026.06)")
        listing.return_value = [older_period_corrected_later, latest, future]
        result = discover_disclosures("00126380", "2026-09-18", "2026-09-01", "2026-09-18", "business")
        self.assertEqual(result["reports"], [latest])
        self.assertTrue(any("기간 밖" in item for item in result["limitations"]))
        self.assertEqual(listing.call_args.kwargs["disclosure_type"], "A")
        self.assertLess(listing.call_args.args[1], "2026-09-01")

    @patch("stock_agent.rag.discovery.list_disclosure_reports")
    def test_event_never_expands_period_or_substitutes_corrected_original(self, listing):
        outside = dict(REPORT, rcept_dt="20260814", rcept_no="20260814000001")
        original = dict(REPORT, report_nm="주요사항보고서(유상증자)", rcept_no="20260901000001", rcept_dt="20260901")
        correction = dict(original, rcept_no="20260902000001", rcept_dt="20260902",
                          report_nm="[기재정정]주요사항보고서(유상증자)")
        unrelated = dict(original, rcept_no="20260903000001", rcept_dt="20260903", report_nm="현금배당결정")
        listing.return_value = [outside, original, correction, unrelated]
        result = discover_disclosures("00126380", "2026-09-18", "2026-09-01", "2026-09-18", "event")
        self.assertEqual(result["reports"], [unrelated])
        self.assertEqual(listing.call_args.args[1:3], ("2026-09-01", "2026-09-18"))
        self.assertIsNone(listing.call_args.kwargs["disclosure_type"])

    @patch("stock_agent.rag.discovery.list_disclosure_reports")
    def test_latest_ambiguous_is_not_replaced_with_older_period(self, listing):
        latest = dict(REPORT, rcept_no="20260814000001", rcept_dt="20260814", report_nm="반기보고서 (2026.06)", rm="정")
        listing.return_value = [REPORT, latest]
        result = discover_disclosures("00126380", "2026-09-18", "2026-09-01", "2026-09-18", "business")
        self.assertEqual(result["reports"], [])
        self.assertEqual(result["reason"], "unresolved_correction")

    @patch("stock_agent.rag.discovery.list_disclosure_reports")
    def test_event_two_document_cap_is_explicit(self, listing):
        listing.return_value = [dict(REPORT, rcept_no=f"2026090{i}000001", rcept_dt=f"2026090{i}", report_nm=f"사건{i}")
                                for i in range(1, 4)]
        result = discover_disclosures("00126380", "2026-09-18", "2026-09-01", "2026-09-18", "event")
        self.assertEqual(len(result["reports"]), 2)
        self.assertEqual(result["reports"][0]["rcept_dt"], "20260903")
        self.assertTrue(any("최신 2건" in item for item in result["limitations"]))

    @patch("stock_agent.vendors.dart_client._get_api_key", return_value="secret")
    @patch("stock_agent.vendors.dart_client.requests.get")
    def test_discovery_page_bound_never_returns_partial_list(self, get, key):
        get.return_value = Mock(json=lambda: {"status": "000", "total_page": 20, "list": [REPORT]})
        with self.assertRaisesRegex(RuntimeError, "한도"):
            list_disclosure_reports("00126380", "2026-01-01", "2026-03-10", max_pages=2)
        self.assertEqual(get.call_count, 2)


class PreparationTest(unittest.TestCase):
    @patch("stock_agent.rag.service.download_disclosure_original", return_value=archive())
    def test_failed_embedding_resumes_parsed_without_download(self, download):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError):
                ensure_disclosures_ready([REPORT], root, embed=Mock(side_effect=RuntimeError("offline")))
            with sqlite3.connect(root / "catalog.sqlite") as db:
                # Catalog may not exist before parsed-stage success on first preparation.
                tables = db.execute("SELECT name FROM sqlite_master WHERE name='reports'").fetchall()
                self.assertFalse(tables)
            with patch("stock_agent.rag.service.parse_archive", side_effect=AssertionError("must reuse parse")):
                result = ensure_disclosures_ready([REPORT], root, embed=fake_embed)
            self.assertFalse(result[0]["cached"])
            download.assert_called_once()
            self.assertTrue(search_evidence("차입금", "00126380", "2026-03-10", root, embed=fake_embed))

    @patch("stock_agent.rag.service.download_disclosure_original", return_value=archive())
    def test_missing_fts_resumes_existing_vectors(self, download):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_report(REPORT, root, embed=fake_embed)
            with sqlite3.connect(root / "catalog.sqlite") as db:
                db.execute("DELETE FROM chunks_fts")
            result = ensure_disclosures_ready([REPORT], root, embed=Mock(side_effect=AssertionError("no re-embedding")))
            self.assertFalse(result[0]["cached"])
            self.assertTrue(prepare_report(REPORT, root, embed=Mock(side_effect=AssertionError))["cached"])
            download.assert_called_once()

    @patch("stock_agent.rag.service.download_disclosure_original", return_value=archive())
    def test_missing_parsed_artifact_does_not_claim_ready(self, download):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_report(REPORT, root, embed=fake_embed)
            (root / "parsed" / REPORT["rcept_no"] / VERSION / "blocks.jsonl").unlink()
            result = prepare_report(REPORT, root, embed=Mock(side_effect=AssertionError("vectors reusable")))
            self.assertFalse(result["cached"])
            self.assertTrue((root / "parsed" / REPORT["rcept_no"] / VERSION / "blocks.jsonl").exists())
            download.assert_called_once()

    @patch("stock_agent.rag.service.download_disclosure_original", return_value=archive())
    def test_concurrent_preparation_rechecks_under_lock(self, download):
        with tempfile.TemporaryDirectory() as tmp:
            embed = Mock(side_effect=fake_embed)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: ensure_disclosures_ready([REPORT], Path(tmp), embed=embed), range(2)))
            self.assertEqual(sorted(result[0]["cached"] for result in results), [False, True])
            self.assertEqual(embed.call_count, 1)
            download.assert_called_once()


class ToolContractTest(unittest.TestCase):
    @patch("stock_agent.tools.disclosure.discover_disclosures")
    @patch("stock_agent.tools.disclosure.ensure_disclosures_ready")
    @patch("stock_agent.tools.disclosure.retrieve_evidence")
    def test_refreshed_correction_blocks_cached_receipt(self, search, ready, discovery):
        discovery.return_value = {"reports": [], "limitations": ["정정 관계 미확인"], "reason": "unresolved_correction"}
        tool = make_disclosure_search_tool("00126380", "2026-03-10")
        result = json.loads(tool.invoke({"question": "반도체 사업"}))
        self.assertEqual(result["reason"], "unresolved_correction")
        self.assertEqual(result["status"], "unavailable")
        ready.assert_not_called()
        search.assert_not_called()

    @patch("stock_agent.tools.disclosure.discover_disclosures", side_effect=requests.Timeout("https://bad/?key=secret"))
    def test_error_is_not_no_documents_and_never_leaks_exception_url(self, discovery):
        tool = make_disclosure_search_tool("00126380", "2026-03-10")
        result = tool.invoke({"question": "사업 내용"})
        self.assertNotIn("secret", result)
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "error")
        self.assertTrue(parsed["error"]["retryable"])

    @patch("stock_agent.tools.disclosure.retrieve_evidence")
    @patch("stock_agent.tools.disclosure.ensure_disclosures_ready")
    @patch("stock_agent.tools.disclosure.discover_disclosures")
    def test_common_evidence_retains_date_location_and_unique_ids(self, discovery, ready, search):
        discovery.return_value = {"reports": [REPORT], "limitations": [], "reason": None}
        search.return_value = [{"receipt_id": REPORT["rcept_no"], "text": "반도체 사업", "context": "원문 문맥",
            "context_truncated": False, "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + REPORT["rcept_no"],
            "member": "report.xml", "source_line": 3, "section": "사업의 내용", "range": [0, 6], "kind": "p", "chunk_id": "test-chunk"}]
        tool = make_disclosure_search_tool("00126380", "2026-03-10")
        first = json.loads(tool.invoke({"question": "사업 내용"}))
        second = json.loads(tool.invoke({"question": "사업 내용"}))
        evidence = first["evidence"][0]
        self.assertEqual(evidence["published_at"], "2026-03-10")
        self.assertEqual(evidence["source"]["location"]["line"], 3)
        self.assertEqual(evidence["content"]["text"], "반도체 사업")
        self.assertNotEqual(evidence["evidence_id"], second["evidence"][0]["evidence_id"])
        self.assertEqual(search.call_args.kwargs["receipt_ids"], [REPORT["rcept_no"]])


if __name__ == "__main__":
    unittest.main()
