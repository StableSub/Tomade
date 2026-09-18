"""웹 원문·시간 경계·안전한 외부 오류에 대한 회귀 검증."""

import json
import unittest
from unittest.mock import Mock, patch

import requests

from stock_agent.tools.search import make_web_search_tool
from stock_agent.vendors import tavily_client

MANDATE = {"as_of_date": "2026-09-17", "period_days": 7}


def candidate(url="https://example.com/a", published="2026-09-16T10:00:00Z", body="검색 결과 발췌"):
    return {"url": url, "title": "산업 정책", "published_date": published, "content": body}


class WebEvidenceTests(unittest.TestCase):
    def invoke(self, query="반도체 수출 정책", **kwargs):
        return json.loads(make_web_search_tool(MANDATE).invoke({"query": query, **kwargs}))

    @patch("stock_agent.tools.search.tavily_client.extract_web")
    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_period_filter_and_original_are_not_front_summary(self, search, extract):
        search.return_value = [candidate(), candidate("https://example.com/unknown", None),
                               candidate("https://example.com/future", "2026-09-18T00:00:00Z")]
        extract.return_value = {"results": [{"url": "https://example.com/a", "raw_content": "질문과 관련된 본문 중간 문단"}]}
        result = self.invoke()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["evidence"]), 1)
        evidence = result["evidence"][0]
        self.assertEqual(evidence["content"], "질문과 관련된 본문 중간 문단")
        self.assertEqual(evidence["source"]["retrieval_type"], "original_excerpt")
        self.assertFalse(evidence["source"]["point_in_time_verified"])
        search.assert_called_once_with("반도체 수출 정책", max_results=5, start_date="2026-09-11", end_date="2026-09-17")
        self.assertEqual({x["reason"] for x in result["excluded_sources"]}, {"publication_date_unknown", "publication_date_outside_period"})

    @patch("stock_agent.tools.search.tavily_client.extract_web")
    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_extraction_cap_snippet_labels_and_unique_ids(self, search, extract):
        search.return_value = [candidate(f"https://example.com/{i}") for i in range(5)]
        extract.return_value = {"results": [{"url": "https://example.com/0", "raw_content": "원문"}]}
        first, second = self.invoke(), self.invoke()
        self.assertEqual(len(extract.call_args.args[0]), 3)
        self.assertEqual(first["evidence"][1]["source"]["retrieval_type"], "search_snippet")
        self.assertNotEqual(first["evidence"][0]["evidence_id"], second["evidence"][0]["evidence_id"])
        self.assertEqual(first["status"], "partial")

    @patch("stock_agent.tools.search.tavily_client.extract_web")
    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_unknown_dates_and_private_urls_never_extracted(self, search, extract):
        search.return_value = [candidate("http://127.0.0.1/admin"), candidate("https://example.com/u", None)]
        result = self.invoke()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["evidence"], [])
        extract.assert_not_called()

    @patch("stock_agent.tools.search.tavily_client.extract_web")
    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_rfc_date_filters_using_kst_day(self, search, extract):
        search.return_value = [candidate(published="Thu, 17 Sep 2026 16:00:00 GMT")]
        result = self.invoke()
        self.assertEqual(result["status"], "unavailable")
        extract.assert_not_called()

    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_invalid_input_does_not_call_provider(self, search):
        result = self.invoke(query="", max_results=7)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "invalid_input")
        search.assert_not_called()

    @patch("stock_agent.tools.search.tavily_client.extract_web")
    @patch("stock_agent.tools.search.tavily_client.search_web")
    def test_extract_failure_keeps_labeled_snippets(self, search, extract):
        search.return_value = [candidate()]
        extract.side_effect = tavily_client.TavilyError("network_error", "연결 실패", True)
        result = self.invoke()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["evidence"][0]["source"]["retrieval_type"], "search_snippet")

    @patch("stock_agent.vendors.tavily_client._get_client")
    def test_vendor_dates_extraction_options_and_sanitized_error(self, get_client):
        client = get_client.return_value
        client.search.return_value = {"results": []}
        tavily_client.search_web("정책", start_date="2026-09-11", end_date="2026-09-17")
        args = client.search.call_args.kwargs
        self.assertTrue(args["include_published_date"])
        self.assertEqual(args["end_date"], "2026-09-18")
        self.assertEqual(args["timeout"], 15)
        client.extract.return_value = {"results": []}
        tavily_client.extract_web(["https://example.com/a"], "정책")
        self.assertEqual(client.extract.call_args.kwargs["query"], "정책")
        self.assertEqual(client.extract.call_args.kwargs["chunks_per_source"], 3)
        client.search.side_effect = requests.ConnectionError("api_key=secret-do-not-show")
        with self.assertRaises(tavily_client.TavilyError) as raised:
            tavily_client.search_web("정책", start_date="2026-09-11", end_date="2026-09-17")
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
