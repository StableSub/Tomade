"""YouTube 댓글 표본의 기간·관련성·호출 상한·부분 실패 검증."""

import unittest
from unittest.mock import Mock, patch

from stock_agent.tools.sentiment import collect_sentiment_evidence
from stock_agent.vendors import youtube_client

MANDATE = {"corp_name": "삼성전자", "ticker": "005930", "as_of_date": "2026-09-17", "period_days": 7}


def video(i="v0", title="삼성전자 주가와 실적"):
    return {"video_id": i, "title": title, "description": "기업 투자 분석", "published_at": "2024-01-01T00:00:00Z", "url": f"https://www.youtube.com/watch?v={i}"}


def comment(i="c0", text="삼성전자 실적 기대", published="2026-09-16T00:00:00Z", updated=None, vid="v0"):
    return {"comment_id": i, "video_id": vid, "text": text, "published_at": published, "updated_at": updated or published}


class SentimentCollectionTests(unittest.TestCase):
    @patch("stock_agent.tools.sentiment.youtube_client.list_comments")
    @patch("stock_agent.tools.sentiment.youtube_client.search_videos")
    def test_old_video_recent_comments_temporal_filter_and_dedup(self, search, comments):
        search.return_value = [video()]
        comments.return_value = {"items": [
            comment(), comment("duplicate", " 삼성전자  실적 기대! "),
            comment("future", published="2026-09-17T16:00:00Z"),
            comment("edited", "삼성전자 매수", updated="2026-09-18T00:00:00Z"),
            comment("old", published="2026-09-10T00:00:00Z"),
            comment("irrelevant", "안녕하세요 잘보고 갑니다"),
            comment("context", "주가 상승 기대"),
        ], "next_page_token": None}
        result = collect_sentiment_evidence(MANDATE)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["selected_videos"][0]["published_at"], "2024-01-01T00:00:00Z")
        self.assertNotIn("published_after", search.call_args.kwargs)
        self.assertEqual(result["excluded_counts"]["updated_after_as_of"], 1)
        self.assertEqual(result["excluded_counts"]["duplicate"], 1)
        self.assertEqual(result["evidence"][1]["source"]["relevance_basis"], "video_context_and_finance_keyword")

    @patch("stock_agent.tools.sentiment.youtube_client.list_comments")
    @patch("stock_agent.tools.sentiment.youtube_client.search_videos")
    def test_bounded_balanced_sample_and_truncation(self, search, comments):
        search.return_value = [video(f"v{i}") for i in range(6)]
        def page(vid, page_token=None, max_results=25):
            offset = 25 if page_token else 0
            return {"items": [comment(f"{vid}-{i}", f"삼성전자 {vid} 주가 {i} " + "본문" * 400, vid=vid)
                              for i in range(offset, offset + 25)], "next_page_token": "next"}
        comments.side_effect = page
        result = collect_sentiment_evidence(MANDATE)
        self.assertEqual(len(result["selected_videos"]), 3)
        self.assertEqual(comments.call_count, 6)
        self.assertEqual(result["scanned_comment_count"], 150)
        self.assertEqual(result["sample_count"], 40)
        self.assertEqual([x["source"]["video_id"] for x in result["evidence"][:3]], ["v0", "v1", "v2"])
        self.assertTrue(all(len(e["content"]) == 600 and e["source"]["truncated"] for e in result["evidence"]))
        self.assertEqual(result["status"], "partial")

    @patch("stock_agent.tools.sentiment.youtube_client.list_comments")
    @patch("stock_agent.tools.sentiment.youtube_client.search_videos")
    def test_unrelated_and_future_videos_are_not_sampled(self, search, comments):
        future = video("v2")
        future["published_at"] = "2026-09-18T00:00:00Z"
        search.return_value = [video("v1", "새 휴대폰 언박싱"), future]
        result = collect_sentiment_evidence(MANDATE)
        comments.assert_not_called()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["sample_count"], 0)
        self.assertTrue(any("중립" in text for text in result["limitations"]))

    @patch("stock_agent.tools.sentiment.youtube_client.list_comments")
    @patch("stock_agent.tools.sentiment.youtube_client.search_videos")
    def test_collection_error_is_not_neutral_or_unavailable(self, search, comments):
        search.return_value = [video()]
        comments.side_effect = youtube_client.ProviderError("comments_disabled", "댓글 비활성화")
        result = collect_sentiment_evidence(MANDATE)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "comments_disabled")
        self.assertEqual(result["evidence"], [])

    @patch.dict("os.environ", {}, clear=True)
    @patch("stock_agent.vendors.youtube_client.requests.get")
    def test_missing_credentials_is_error_without_network(self, get):
        result = collect_sentiment_evidence(MANDATE)
        self.assertEqual(result["error"]["code"], "missing_credentials")
        self.assertEqual(result["status"], "error")
        get.assert_not_called()

    @patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-secret"})
    @patch("stock_agent.vendors.youtube_client.requests.get")
    def test_vendor_comment_contract_excludes_replies(self, get):
        get.return_value = Mock(status_code=200)
        get.return_value.json.return_value = {"items": [{"snippet": {"topLevelComment": {
            "id": "c", "snippet": {"textDisplay": "삼성전자", "publishedAt": "2026-09-16T00:00:00Z", "updatedAt": "2026-09-16T00:00:00Z"}
        }}, "replies": {"comments": [{"id": "excluded"}]}}], "nextPageToken": "next"}
        result = youtube_client.list_comments("v", page_token="previous", max_results=25)
        self.assertEqual([c["comment_id"] for c in result["items"]], ["c"])
        self.assertEqual(result["next_page_token"], "next")
        args = get.call_args.kwargs
        self.assertEqual(args["params"]["order"], "time")
        self.assertEqual(args["params"]["textFormat"], "plainText")
        self.assertEqual(args["params"]["pageToken"], "previous")
        self.assertEqual(args["timeout"], 15)
        self.assertFalse(args["allow_redirects"])
        get.return_value = Mock(status_code=403)
        get.return_value.json.return_value = {"error": {"message": "test-secret", "errors": [{"reason": "quotaExceeded"}]}}
        with self.assertRaises(youtube_client.ProviderError) as raised:
            youtube_client.list_comments("v")
        self.assertNotIn("test-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
