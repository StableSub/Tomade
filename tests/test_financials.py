"""실제 API 없이 재무 공개시점·회계범위·Decimal 산식·실패 구분 검증."""

import json
import unittest
from unittest.mock import Mock, patch

import requests

from stock_agent.tools.financials import make_financial_tool
from stock_agent.vendors.financials_client import FinancialAPIError, _request, get_financial_snapshot

CORP = "00126380"
RECEIPT = "20260310002820"
ANNUAL = {"corp_code": CORP, "rcept_no": RECEIPT, "rcept_dt": "20260310",
          "report_nm": "사업보고서 (2025.12)", "rm": "연"}


def rows(year="2025", code="11011", receipt=RECEIPT):
    """독립적인 합성 수치. 실제 기업의 실적이 아님."""
    return [{"corp_code": CORP, "rcept_no": receipt, "bsns_year": year, "reprt_code": code,
             "sj_div": div, "account_id": account_id, "account_nm": name, "currency": "KRW",
             "thstrm_amount": current, "frmtrm_amount": previous,
             "thstrm_nm": "제 57 기", "frmtrm_nm": "제 56 기"}
            for div, account_id, name, current, previous in [
                ("IS", "ifrs-full_Revenue", "매출액", "1,000", "800"),
                ("IS", "dart_OperatingIncomeLoss", "영업이익", "200", "100"),
                ("IS", "ifrs-full_ProfitLoss", "당기순이익", "100", "50"),
                ("BS", "ifrs-full_Assets", "자산총계", "1600", "1400"),
                ("BS", "ifrs-full_Liabilities", "부채총계", "600", "600"),
                ("BS", "ifrs-full_Equity", "자본총계", "1000", "800"),
                ("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "300", "200"),
            ]]


def snapshot(data=None, basis="CFS", month=12):
    return {"rows": data if data is not None else rows(), "basis": basis, "limitations": [],
            "report": {**ANNUAL, "year": 2025, "month": month, "period_end": f"2025-{month:02d}-{'31' if month == 12 else '30'}",
                       "published_at": "2026-03-10", "report_code": "11011" if month == 12 else "11012"}}


class FinancialVendorTests(unittest.TestCase):
    @patch("stock_agent.vendors.financials_client._request")
    def test_cutoff_blocks_unpublished_and_old_correction_does_not_replace_latest_period(self, request):
        newer = {**ANNUAL, "rcept_no": "20260815000001", "rcept_dt": "20260815", "report_nm": "반기보고서 (2026.06)"}
        old_correction = {**ANNUAL, "rcept_no": "20260401000001", "rcept_dt": "20260401", "report_nm": "[기재정정]사업보고서 (2024.12)"}
        request.side_effect = [{"status": "000", "total_page": 1, "list": [newer, old_correction, ANNUAL]},
                               {"status": "000", "list": rows()}]
        result = get_financial_snapshot(CORP, "2026-04-15")
        self.assertEqual(result["report"]["rcept_no"], RECEIPT)
        self.assertEqual(request.call_args_list[0].args[1]["end_de"], "20260415")
        self.assertEqual(request.call_args_list[0].args[1]["last_reprt_at"], "N")
        self.assertEqual(request.call_args.args[1]["bsns_year"], "2025")

    @patch("stock_agent.vendors.financials_client._request")
    def test_future_restatement_and_period_mismatch_are_not_used(self, request):
        for changes in ({"rcept_no": "20261010000001"}, {"reprt_code": "11012"}, {"fs_div": "OFS"}):
            with self.subTest(changes=changes):
                invalid_rows = rows()
                invalid_rows[0].update(changes)
                request.side_effect = [{"status": "000", "total_page": 1, "list": [ANNUAL]},
                                       {"status": "000", "list": invalid_rows}]
                result = get_financial_snapshot(CORP, "2026-04-15")
                self.assertEqual(result["rows"], [])
                self.assertTrue(result["limitations"])

    @patch("stock_agent.vendors.financials_client._request")
    def test_only_no_cfs_data_falls_back_to_whole_ofs_snapshot(self, request):
        request.side_effect = [{"status": "000", "total_page": 1, "list": [ANNUAL]},
                               {"status": "013"}, {"status": "000", "list": rows()}]
        result = get_financial_snapshot(CORP, "2026-04-15")
        self.assertEqual(result["basis"], "OFS")
        self.assertEqual(request.call_args_list[1].args[1]["fs_div"], "CFS")
        self.assertEqual(request.call_args_list[2].args[1]["fs_div"], "OFS")
        request.reset_mock()
        request.side_effect = [{"status": "000", "total_page": 1, "list": [ANNUAL]},
                               FinancialAPIError("dart_020", "할당량 초과", True)]
        with self.assertRaises(FinancialAPIError):
            get_financial_snapshot(CORP, "2026-04-15")
        self.assertEqual(request.call_count, 2)

    @patch("stock_agent.vendors.financials_client._request")
    def test_bounded_pages_and_unsupported_fiscal_year(self, request):
        request.side_effect = [{"status": "000", "total_page": 3, "list": [ANNUAL]},
                               {"status": "000", "total_page": 3, "list": []},
                               {"status": "000", "list": rows()}]
        result = get_financial_snapshot(CORP, "2026-04-15")
        self.assertEqual(request.call_count, 3)
        self.assertIn("200건", result["limitations"][0])
        request.reset_mock()
        request.side_effect = [{"status": "000", "total_page": 1, "list": [{**ANNUAL, "report_nm": "사업보고서 (2025.03)"}]}]
        self.assertEqual(get_financial_snapshot(CORP, "2026-04-15")["rows"], [])
        self.assertEqual(request.call_count, 1)

    @patch.dict("os.environ", {"DART_OPENAPI_KEY": "secret-test-key"})
    @patch("stock_agent.vendors.financials_client.requests.get")
    def test_no_data_api_failure_and_http_errors_stay_distinct_and_safe(self, get):
        get.return_value = Mock(json=lambda: {"status": "013"})
        self.assertEqual(_request("list", {})["status"], "013")
        get.return_value = Mock(json=lambda: {"status": "010", "message": "secret-test-key"})
        with self.assertRaises(FinancialAPIError) as caught:
            _request("list", {})
        self.assertEqual(caught.exception.code, "dart_010")
        self.assertNotIn("secret-test-key", str(caught.exception))
        get.side_effect = requests.Timeout("URL contains secret-test-key")
        with self.assertRaises(FinancialAPIError) as caught:
            _request("list", {})
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret-test-key", str(caught.exception))


class FinancialToolTests(unittest.TestCase):
    def invoke(self):
        return json.loads(make_financial_tool({"corp_code": CORP, "as_of_date": "2026-04-15"}).invoke({}))

    @patch("stock_agent.tools.financials.get_financial_snapshot")
    def test_decimal_ratios_source_and_fixed_contract(self, get):
        get.return_value = snapshot()
        result = self.invoke()
        evidence = {item["content"]["metric"]: item for item in result["evidence"]}
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(evidence), 13)
        self.assertEqual(evidence["operating_margin_pct"]["content"]["value"], "20.0")
        self.assertEqual(evidence["liabilities_to_equity_pct"]["content"]["value"], "60.0")
        self.assertEqual(evidence["revenue_yoy_pct"]["content"]["value"], "25.00")
        self.assertEqual(evidence["operating_cash_flow_yoy_pct"]["content"]["value"], "50.0")
        self.assertEqual(evidence["total_assets"]["observation_start"], "2025-12-31")
        self.assertEqual(evidence["revenue"]["published_at"], "2026-03-10")
        self.assertEqual(evidence["revenue"]["source"]["receipt_id"], RECEIPT)
        self.assertTrue(all(item["evidence_id"].startswith("financial:") for item in evidence.values()))
        get.assert_called_once_with(CORP, "2026-04-15")
        self.assertEqual(make_financial_tool({}).args, {})

    @patch("stock_agent.tools.financials.get_financial_snapshot")
    def test_half_year_uses_cumulative_not_three_month_amounts(self, get):
        data = rows(code="11012")
        for row in data:
            row.update(thstrm_add_amount="2000", frmtrm_add_amount="1000", thstrm_nm="제 57 기 반기", frmtrm_nm="제 56 기 반기", frmtrm_q_nm="제 56 기 반기")
        get.return_value = snapshot(data, month=6)
        result = self.invoke()
        evidence = {item["content"]["metric"]: item["content"] for item in result["evidence"]}
        self.assertEqual(evidence["revenue"]["value"], "2000")
        self.assertEqual(evidence["revenue"]["period_semantics"], "year_to_date")
        self.assertEqual(evidence["revenue_yoy_pct"]["value"], "100")
        self.assertEqual(evidence["operating_cash_flow"]["value"], "300")
        self.assertEqual(evidence["operating_cash_flow_yoy_pct"]["value"], "50.0")
        data[0]["thstrm_add_amount"] = ""
        data[-1]["frmtrm_nm"] = "제 56 기"
        get.return_value = snapshot(data, month=6)
        result = self.invoke()
        names = {item["content"]["metric"] for item in result["evidence"]}
        self.assertNotIn("revenue", names)
        self.assertNotIn("operating_cash_flow_yoy_pct", names)
        self.assertEqual(result["status"], "partial")

    @patch("stock_agent.tools.financials.get_financial_snapshot")
    def test_zero_negative_currency_and_duplicate_conflict_do_not_form_ratios(self, get):
        data = rows()
        data[0]["currency"] = "USD"
        data[1]["frmtrm_amount"] = "-100"
        data[5]["thstrm_amount"] = "0"
        data.append({**data[2], "thstrm_amount": "999"})
        get.return_value = snapshot(data)
        result = self.invoke()
        names = {item["content"]["metric"] for item in result["evidence"]}
        for name in ("operating_margin_pct", "liabilities_to_equity_pct", "operating_income_yoy_pct", "net_income"):
            self.assertNotIn(name, names)
        self.assertEqual(result["status"], "partial")

    @patch("stock_agent.tools.financials.get_financial_snapshot")
    def test_missing_and_error_and_invalid_input(self, get):
        get.return_value = {"rows": [], "report": None, "basis": None, "limitations": ["자료 없음"]}
        self.assertEqual(self.invoke()["status"], "unavailable")
        get.side_effect = FinancialAPIError("dart_020", "할당량 초과", True)
        result = self.invoke()
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["error"]["retryable"])
        get.reset_mock()
        result = json.loads(make_financial_tool({"corp_code": CORP, "as_of_date": "9999-01-01"}).invoke({}))
        self.assertEqual(result["error"]["code"], "invalid_input")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
