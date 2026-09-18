"""Technical 지표 산식·기간·자료 경계의 로컬 회귀 검증."""

import datetime
import json
import math
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import exchange_calendars
import requests

from stock_agent.tools.technical import collect_technical_evidence, make_technical_tool
from stock_agent.vendors import toss_client

_KST = ZoneInfo("Asia/Seoul")
_NOW = datetime.datetime(2026, 9, 18, 16, tzinfo=_KST)
_MANDATE = {"ticker": "005930", "as_of_date": "2026-09-17"}


def records(count=60, end="2026-09-17"):
    calendar = exchange_calendars.get_calendar("XKRX", start="2024-12-01", end="2026-12-31")
    dates = calendar.sessions_in_range("2025-01-01", end)[-count:]
    return [
        {"date": day.date().isoformat(), "close": str(index + 1), "volume": str((index + 1) * 2)}
        for index, day in enumerate(dates)
    ]


def metrics(result):
    return {metric.name: metric for metric in result.metrics}


class TechnicalTests(unittest.TestCase):
    def collect(self, data, mandate=None):
        with patch("stock_agent.tools.technical.toss_client.get_daily_series", return_value=data) as query:
            result = collect_technical_evidence(mandate or _MANDATE, now=_NOW)
        return result, query

    def test_complete_values_windows_and_evidence(self):
        result, query = self.collect(records())
        values = metrics(result)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.latest_close, 60)
        self.assertEqual(result.latest_volume, 120)
        self.assertEqual(values["sma_20"].value, 50.5)
        self.assertEqual(values["sma_60"].value, 30.5)
        self.assertAlmostEqual(values["distance_sma_20_pct"].value, 18.81188118811881)
        self.assertAlmostEqual(values["distance_sma_60_pct"].value, 96.72131147540983)
        self.assertAlmostEqual(values["volume_ratio_20"].value, 120 / 99)
        self.assertEqual(values["volume_ratio_20"].observation_count, 21)
        self.assertEqual(values["sma_60"].observation_count, 60)
        self.assertEqual(query.call_count, 1)
        self.assertEqual(len(result.evidence), 8)
        self.assertEqual(len({item["evidence_id"] for item in result.evidence}), 8)
        self.assertFalse(result.source["point_in_time_verified"])
        self.assertFalse(result.source["adjustment_verified"])
        self.assertTrue(all(item["retrieved_at"].endswith("+09:00") for item in result.evidence))

    def test_sample_volatility_is_not_population_or_annualized(self):
        data = records()
        price = 100.0
        for offset in range(21):
            if offset:
                price *= 1.01 if offset % 2 else 0.99
            data[-21 + offset]["close"] = str(price)
        result, _ = self.collect(data)
        self.assertAlmostEqual(metrics(result)["daily_volatility_20_pct"].value, math.sqrt(20 / 19), places=10)

    def test_today_uses_kst_and_excludes_even_completed_today_bar(self):
        data = records(end="2026-09-18")
        with patch("stock_agent.tools.technical.toss_client.get_daily_series", return_value=data) as query:
            result = collect_technical_evidence(
                {**_MANDATE, "as_of_date": "2026-09-18"},
                now=datetime.datetime(2026, 9, 17, 16, tzinfo=datetime.timezone.utc),
            )
        self.assertEqual(result.effective_date, "2026-09-17")
        self.assertTrue(all(call.args[2] == "2026-09-17" for call in query.call_args_list))
        self.assertTrue(all(item["observation_end"] < "2026-09-18" for item in result.evidence))

    def test_short_history_extends_once_and_keeps_partial_values(self):
        result, query = self.collect(records(35))
        self.assertEqual([call.args[1] for call in query.call_args_list], [120, 365])
        self.assertEqual(result.status, "partial")
        self.assertIsNotNone(metrics(result)["sma_20"].value)
        self.assertEqual(metrics(result)["sma_60"].reason, "insufficient_history")
        self.assertIsNone(metrics(result)["sma_60"].evidence_id)
        self.assertTrue(any("sma_60 계산 불가" in item for item in result.limitations))

    def test_empty_data_is_unavailable_not_neutral_or_error(self):
        result, query = self.collect([])
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.error)
        self.assertEqual(result.evidence, [])
        self.assertEqual(query.call_count, 2)
        self.assertTrue(all(metric.value is None for metric in result.metrics))

    def test_invalid_volume_does_not_discard_price_metrics(self):
        data = records()
        data[-3]["volume"] = "NaN"
        result, _ = self.collect(data)
        self.assertEqual(result.status, "partial")
        self.assertIsNotNone(metrics(result)["sma_60"].value)
        self.assertIsNotNone(metrics(result)["daily_volatility_20_pct"].value)
        self.assertEqual(metrics(result)["volume_ratio_20"].reason, "invalid_volume")

    def test_invalid_middle_price_is_not_skipped_to_fill_window(self):
        for value in ("0", "-1", "NaN", "Infinity"):
            with self.subTest(value=value):
                data = records(65)
                data[-5]["close"] = value
                result, _ = self.collect(data)
                self.assertEqual(metrics(result)["sma_20"].reason, "invalid_close")
                self.assertIsNone(metrics(result)["daily_volatility_20_pct"].value)
                self.assertIsNotNone(metrics(result)["volume_ratio_20"].value)

    def test_duplicate_order_cannot_select_conflicting_close(self):
        data = records()
        duplicate = {**data[-5], "close": "999"}
        for duplicated in (data + [dict(data[-5])], data + [duplicate, dict(data[-5])], [duplicate] + data):
            result, _ = self.collect(duplicated)
            if duplicate not in duplicated:
                self.assertEqual(result.status, "complete")
            else:
                self.assertEqual(metrics(result)["sma_20"].reason, "conflicting_close")
                self.assertIsNotNone(metrics(result)["volume_ratio_20"].value)

    def test_missing_expected_session_is_not_assumed_holiday(self):
        data = records(61)
        del data[-5]
        result, _ = self.collect(data)
        self.assertEqual(result.status, "unavailable")
        self.assertTrue(all(metric.reason == "unverified_gap" for metric in result.metrics))
        self.assertIsNotNone(result.latest_close)

    def test_known_krx_holiday_does_not_break_window(self):
        data = records(end="2026-03-10")
        self.assertNotIn("2026-03-02", {row["date"] for row in data})
        result, _ = self.collect(data, {**_MANDATE, "as_of_date": "2026-03-10"})
        self.assertEqual(result.status, "complete")

    def test_unknown_calendar_range_cannot_claim_continuity(self):
        with patch("stock_agent.tools.technical._sessions", return_value=None):
            result, _ = self.collect(records())
        self.assertTrue(all(metric.reason == "unverified_gap" for metric in result.metrics))

    def test_zero_baseline_volume_cannot_be_divided(self):
        data = records()
        for row in data[-21:-1]:
            row["volume"] = "0"
        result, _ = self.collect(data)
        self.assertEqual(metrics(result)["volume_ratio_20"].reason, "zero_average_volume")
        self.assertEqual(result.status, "partial")

    def test_finite_prices_with_overflowing_returns_do_not_crash(self):
        data = records()
        data[-2]["close"] = "1e-300"
        data[-1]["close"] = "1e300"
        result, _ = self.collect(data)
        self.assertEqual(metrics(result)["daily_volatility_20_pct"].reason, "numeric_range_exceeded")
        self.assertEqual(result.status, "partial")

    def test_bad_input_never_calls_provider(self):
        for mandate in ({**_MANDATE, "ticker": "삼성전자"}, {**_MANDATE, "as_of_date": "2026-09-19"},
                        {**_MANDATE, "as_of_date": "20260917"}, {**_MANDATE, "as_of_date": None}):
            with self.subTest(mandate=mandate):
                result, query = self.collect([], mandate)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.error["code"], "invalid_input")
                query.assert_not_called()

    def test_provider_failure_and_malformed_response_are_errors(self):
        for failure, expected in ((requests.Timeout("secret-url"), "provider_error"),
                                  (KeyError("TOSS_CLIENT_SECRET"), "missing_credentials")):
            with patch("stock_agent.tools.technical.toss_client.get_daily_series", side_effect=failure):
                result = collect_technical_evidence(_MANDATE, now=_NOW)
            self.assertEqual(result.status, "error")
            self.assertEqual(result.error["code"], expected)
            self.assertNotIn("secret-url", result.model_dump_json())
        result, _ = self.collect([{"date": "bad", "close": "10", "volume": "10"}])
        self.assertEqual(result.error["code"], "invalid_response")

    def test_factory_freezes_validated_mandate_and_exposes_no_arguments(self):
        mandate = dict(_MANDATE)
        bound = make_technical_tool(mandate)
        mandate["ticker"] = "123456"
        self.assertEqual(bound.name, "get_technical_evidence")
        self.assertEqual(bound.args_schema.model_json_schema()["properties"], {})
        with patch("stock_agent.tools.technical.toss_client.get_daily_series", return_value=records()) as query:
            response = json.loads(bound.invoke({}))
        self.assertEqual(response["ticker"], "005930")
        self.assertEqual(query.call_args.args[0], "005930")


class TechnicalVendorTests(unittest.TestCase):
    def test_new_series_preserves_decimals_and_conflicting_duplicates(self):
        candles = [
            {"timestamp": "2026-09-17T15:30:00+09:00", "closePrice": "100.125", "volume": "200"},
            {"timestamp": "2026-09-17T15:30:00+09:00", "closePrice": "100.25", "volume": "200"},
        ]
        with patch.object(toss_client, "_get", return_value={"candles": candles}):
            result = toss_client.get_daily_series("005930", 120, "2026-09-17")
        self.assertEqual([row["close"] for row in result], ["100.125", "100.25"])
        self.assertEqual([row["date"] for row in result], ["2026-09-17"] * 2)

    def test_existing_candle_call_keeps_original_deduplication(self):
        candles = [
            {"timestamp": "2026-09-17T15:30:00+09:00", "closePrice": "100.125"},
            {"timestamp": "2026-09-17T15:30:00+09:00", "closePrice": "100.25"},
        ]
        with patch.object(toss_client, "_get", return_value={"candles": candles}):
            result = toss_client._get_candles("005930", "1d", _NOW - datetime.timedelta(days=2), _NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["closePrice"], "100.25")


if __name__ == "__main__":
    unittest.main()
