"""Event 시세 Tool의 단일 날짜 수익률과 장중 근거를 검증한다."""

import json
import unittest
from unittest.mock import patch

from stock_agent.tools.price import make_market_tool


class MarketV2Test(unittest.TestCase):
    def test_single_daily_bar_preserves_daily_change_and_adds_intraday_evidence(self):
        mandate = {"ticker": "005930", "as_of_date": "2026-09-17", "period_days": 1,
                   "query_start_date": "2026-09-17", "query_end_date": "2026-09-17"}
        daily = [{"date": "2026-09-17", "close": 98, "volume": 600, "change_pct": -2.0}]
        intraday = [
            {"timestamp": "2026-09-17T09:00:00+09:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"timestamp": "2026-09-17T09:01:00+09:00", "open": 100, "high": 100, "low": 97, "close": 98, "volume": 200},
            {"timestamp": "2026-09-17T09:30:00+09:00", "open": 98, "high": 99, "low": 97, "close": 98, "volume": 300},
        ]
        with patch("stock_agent.tools.price.toss_client.get_ohlcv", return_value=daily) as get_daily, \
             patch("stock_agent.tools.price.toss_client.get_intraday_ohlcv", return_value=intraday) as get_intraday:
            result = json.loads(make_market_tool(mandate).invoke({}))

        get_daily.assert_called_once_with("005930", days=0, end_date="2026-09-17")
        get_intraday.assert_called_once_with("005930", "2026-09-17")
        self.assertEqual(result["status"], "complete")
        content = result["evidence"][0]["content"]
        self.assertIsNone(content["period_return_pct"])
        self.assertEqual(content["latest_daily_change_pct"], -2.0)
        self.assertEqual(content["observed_bars"], 1)
        self.assertEqual(content["intraday_buckets"], [
            {"timestamp": "2026-09-17T09:00:00+09:00", "open": 100, "high": 101, "low": 97, "close": 98, "volume": 300},
            {"timestamp": "2026-09-17T09:30:00+09:00", "open": 98, "high": 99, "low": 97, "close": 98, "volume": 300},
        ])
        self.assertTrue(any("전 거래일 대비" in item for item in result["limitations"]))
