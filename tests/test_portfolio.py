"""개인 계좌·유료 모델에 접속하지 않는 포트폴리오 계약 검증."""

import json
import requests
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from stock_agent.portfolio.schemas import Holding, PortfolioExplanation, SectorAssignments
from stock_agent.portfolio.analysis import calculate_diagnosis, prepare_holdings
from stock_agent.portfolio.service import diagnose_portfolio, PortfolioExecutionError
from stock_agent.vendors import toss_client


def raw_item(symbol="005930", amount="4000000", currency="KRW", country="KR"):
    return {"symbol": symbol, "name": "테스트 기업 " + symbol, "currency": currency,
            "marketCountry": country, "marketValue": {"amount": amount, "purchaseAmount": "3000000"}}


def assignments(symbols, sector="정보기술"):
    return SectorAssignments(items=[{"symbol": s, "sector": sector, "reason": "추정"} for s in symbols])


class PortfolioCalculationTest(unittest.TestCase):
    def test_exact_concentration_and_scenario(self):
        holdings = [Holding(symbol=str(i), name=str(i), amount=amount, purchase_amount=amount)
                    for i, amount in enumerate([4000000, 3000000, 2000000, 1000000])]
        result = calculate_diagnosis(holdings, assignments([h.symbol for h in holdings]))
        self.assertEqual(result["total_amount"], "10000000")
        self.assertEqual(Decimal(result["top_one_pct"]), Decimal(40))
        self.assertEqual(Decimal(result["top_three_pct"]), Decimal(90))
        self.assertEqual(Decimal(result["scenario"]["impact_amount"]), Decimal(-800000))
        self.assertEqual(Decimal(result["scenario"]["impact_pct"]), Decimal(-8))
        self.assertEqual(Decimal(result["sectors"][0]["weight_pct"]), Decimal(100))

    def test_single_unknown_sector(self):
        result = calculate_diagnosis([Holding(symbol="A", name="A", amount="10", purchase_amount=0)], assignments(["A"], "미분류"))
        self.assertIsNone(result["total_profit_loss_pct"])
        self.assertIsNone(result["holdings"][0]["profit_loss_pct"])
        self.assertEqual(result["top_three_pct"], "100")
        self.assertEqual(result["sectors"][0]["sector"], "미분류")

    def test_sector_coverage_and_zero_rejected(self):
        h = [Holding(symbol="A", name="A", amount="10", purchase_amount=10)]
        for symbols in ([], ["B"], ["A", "A"], ["A", "B"]):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                calculate_diagnosis(h, assignments(symbols))
        with self.assertRaises(ValueError):
            calculate_diagnosis([Holding(symbol="A", name="A", amount=0, purchase_amount=10)], assignments(["A"]))
        with self.assertRaises(ValidationError):
            assignments(["A"], "반도체")

    def test_filter_and_merge_without_cash(self):
        raw = {"cashBuyingPower": "999999999", "items": [raw_item(), raw_item(amount="1.5"),
               raw_item("AAPL", "200", "USD", "US"), raw_item("ETF"), raw_item("UNKNOWN")]}
        stocks = [{"symbol": "005930", "securityType": "STOCK"}, {"symbol": "ETF", "securityType": "ETF"}]
        holdings, excluded = prepare_holdings(raw, stocks)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].amount, Decimal("4000001.5"))
        self.assertEqual(holdings[0].purchase_amount, Decimal("6000000"))
        self.assertEqual(len(excluded), 3)
        for amount in ("NaN", "Infinity", "-1"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                prepare_holdings({"items": [raw_item(amount=amount)]}, stocks)

    @patch("stock_agent.vendors.toss_client.requests.get")
    @patch("stock_agent.vendors.toss_client._get_access_token", return_value="test-token")
    def test_account_header_and_existing_price_path(self, token, get):
        get.return_value.json.return_value = {"result": {"items": []}}
        toss_client.get_holdings(42)
        self.assertEqual(get.call_args.kwargs["headers"]["X-Tossinvest-Account"], "42")
        toss_client._get("/api/v1/prices", {"symbols": "005930"})
        self.assertNotIn("X-Tossinvest-Account", get.call_args.kwargs["headers"])

    @patch("stock_agent.vendors.toss_client._get")
    def test_stock_info_batches(self, get):
        get.return_value = []
        toss_client.get_stock_info([str(i) for i in range(201)])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(get.call_args_list[0].args[1]["symbols"].split(",")), 200)

    @patch("stock_agent.portfolio.service.get_chat_model")
    @patch("stock_agent.portfolio.service.toss_client.get_stock_info")
    @patch("stock_agent.portfolio.service.toss_client.get_holdings")
    @patch("stock_agent.portfolio.service.toss_client.get_accounts")
    def test_service_privacy_and_separate_runtime(self, accounts, holdings, stocks, model):
        accounts.return_value = [{"accountSeq": 42, "accountNo": "secret-account", "accountType": "BROKERAGE"}]
        holdings.return_value = {"items": [raw_item()], "private": "private-raw-response"}
        stocks.return_value = [{"symbol": "005930", "securityType": "STOCK"}]
        worker, planner = Mock(), Mock()
        worker.with_structured_output.return_value.invoke.return_value = assignments(["005930"])
        planner.with_structured_output.return_value.invoke.return_value = PortfolioExplanation(
            summary="한 기업에 집중되어 있습니다.", observations=[], limitations=["AI 추정 업종입니다."]
        )
        model.side_effect = lambda role: worker if role == "worker" else planner
        with patch("stock_agent.graph.graph.invoke", side_effect=AssertionError("Research forbidden")):
            result = diagnose_portfolio(None, "집중도를 설명해줘")
        accounts.assert_called_once()
        holdings.assert_called_once_with(42)
        self.assertEqual(result["top_one_pct"], "100")
        calls = str(worker.mock_calls) + str(planner.mock_calls)
        for private in ("secret-account", "private-raw-response", "accountSeq", "account_seq", "4000000", "3000000"):
            self.assertNotIn(private, calls)
        self.assertNotIn("secret-account", json.dumps(result))
        model.reset_mock()
        with self.assertRaises(ValueError):
            diagnose_portfolio(99, "질문")
        model.assert_not_called()

    def test_profit_loss_uses_aggregate_cost_not_average_rates(self):
        holdings = [Holding(symbol="A", name="A", amount=150, purchase_amount=100),
                    Holding(symbol="B", name="B", amount=720, purchase_amount=900)]
        result = calculate_diagnosis(holdings, assignments(["A", "B"]))
        self.assertEqual(result["total_purchase_amount"], "1000")
        self.assertEqual(result["total_profit_loss"], "-130")
        self.assertEqual(Decimal(result["total_profit_loss_pct"]), Decimal(-13))
        rates = {row["symbol"]: Decimal(row["profit_loss_pct"]) for row in result["holdings"]}
        self.assertEqual(rates, {"A": Decimal(50), "B": Decimal(-20)})
        for invalid in ("NaN", "-1", "Infinity"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                Holding(symbol="A", name="A", amount=1, purchase_amount=invalid)
        with self.assertRaises(KeyError):
            prepare_holdings({"items": [{**raw_item(), "marketValue": {"amount": "10"}}]},
                             [{"symbol": "005930", "securityType": "STOCK"}])


class PortfolioApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5000))

    @patch("backend.portfolio.toss_client.get_accounts")
    @patch.dict("os.environ", {"TOSS_CLIENT_ID": "test", "TOSS_CLIENT_SECRET": "test"})
    def test_account_list_redacted_and_not_cached(self, accounts):
        accounts.return_value = [{"accountNo": "secret", "accountSeq": 42, "accountType": "BROKERAGE"}]
        response = self.client.get("/api/portfolio/accounts")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.json()["configured"])

    @patch("backend.portfolio.toss_client.get_accounts")
    @patch.dict("os.environ", {"TOSS_CLIENT_ID": "", "TOSS_CLIENT_SECRET": ""})
    def test_missing_keys_skip_external_connection(self, accounts):
        response = self.client.get("/api/portfolio/accounts")
        self.assertEqual(response.json(), {"configured": False, "accounts": []})
        accounts.assert_not_called()

    @patch("backend.portfolio.toss_client.get_accounts")
    @patch.dict("os.environ", {"TOSS_CLIENT_ID": "mock", "TOSS_CLIENT_SECRET": "mock"})
    def test_configuration_never_queries_accounts(self, accounts):
        response = self.client.get("/api/portfolio/configuration")
        self.assertEqual(response.json(), {"configured": True})
        accounts.assert_not_called()

    @patch("backend.portfolio.diagnose_portfolio")
    def test_auto_selection_and_sanitized_stage_log(self, diagnose):
        diagnose.return_value = {"scope": "test"}
        self.assertEqual(self.client.post("/api/portfolio/diagnose", json={}).status_code, 200)
        self.assertIsNone(diagnose.call_args.args[0])
        response = requests.Response()
        response.status_code = 429
        error = requests.HTTPError("secret-account-token", response=response)
        diagnose.side_effect = PortfolioExecutionError("toss.accounts", error)
        with self.assertLogs("backend.portfolio", level="WARNING") as logs:
            result = self.client.post("/api/portfolio/diagnose", json={})
        self.assertEqual(result.status_code, 429)
        self.assertIn("toss.accounts", result.text)
        self.assertIn("429", " ".join(logs.output))
        self.assertNotIn("secret-account-token", result.text + " ".join(logs.output))

    @patch("backend.portfolio.diagnose_portfolio")
    def test_post_success_and_sanitized_error(self, diagnose):
        diagnose.return_value = {"scope": "test"}
        response = self.client.post("/api/portfolio/diagnose", json={"account_seq": 42, "message": "질문"})
        self.assertEqual(response.json(), {"scope": "test"})
        diagnose.side_effect = RuntimeError("private-account-and-token")
        response = self.client.post("/api/portfolio/diagnose", json={"account_seq": 42})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private", response.text)

    @patch("backend.portfolio.diagnose_portfolio")
    def test_empty_input_and_external_origin_do_not_execute(self, diagnose):
        self.assertEqual(self.client.post("/api/portfolio/diagnose", json={"account_seq": 42, "message": " "}).status_code, 422)
        self.assertEqual(self.client.post("/api/portfolio/diagnose", json={"account_seq": 42}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/portfolio/accounts", headers={"Host": "evil.example"}).status_code, 403)
        remote = TestClient(app, base_url="http://localhost", client=("192.0.2.1", 5000))
        self.assertEqual(remote.get("/api/portfolio/accounts").status_code, 403)
        diagnose.assert_not_called()


class TossTokenRecoveryTest(unittest.TestCase):
    @patch("stock_agent.vendors.toss_client.requests.get")
    @patch("stock_agent.vendors.toss_client._get_access_token", side_effect=["old", "new"])
    def test_401_retries_once_with_account_header(self, token, get):
        first = Mock(status_code=401)
        second = Mock(status_code=200)
        second.json.return_value = {"result": {"items": []}}
        get.side_effect = [first, second]
        self.assertEqual(toss_client.get_holdings(42), {"items": []})
        token.assert_called_with("old")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs["headers"]["X-Tossinvest-Account"], "42")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer new")

    @patch("stock_agent.vendors.toss_client.requests.get")
    @patch("stock_agent.vendors.toss_client._get_access_token", return_value="mock")
    def test_no_infinite_retry_or_429_token_refresh(self, token, get):
        for status, count in [(401, 2), (429, 1)]:
            with self.subTest(status=status):
                token.reset_mock()
                get.reset_mock()
                response = Mock(status_code=status)
                response.raise_for_status.side_effect = requests.HTTPError("mock")
                get.return_value = response
                with self.assertRaises(requests.HTTPError):
                    toss_client.get_holdings(42)
                self.assertEqual(get.call_count, count)
                self.assertEqual(token.call_count, count)

    @patch("stock_agent.vendors.toss_client.requests.post")
    def test_other_request_refreshed_token_is_reused(self, post):
        with patch.object(toss_client, "_token", "fresh"), patch.object(toss_client, "_token_expires_at", float("inf")):
            self.assertEqual(toss_client._get_access_token("stale"), "fresh")
            post.assert_not_called()
            post.return_value.json.return_value = {"access_token": "replacement", "expires_in": 3600}
            self.assertEqual(toss_client._get_access_token("fresh"), "replacement")
            post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
