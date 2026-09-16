"""Request Parser가 생성하는 ResearchMandate의 제품 범위를 검증한다."""

import unittest
import datetime
from unittest.mock import patch

from stock_agent.prompts.builder import build_system_prompt
from stock_agent.control.request_parser import _validate_parsed_request, request_parsing_node
from stock_agent.state import ParsedRequest


class ParserDateContextTest(unittest.TestCase):
    """기준 날짜의 메시지 경계와 추출 이후 기간 처리를 검증한다."""

    @patch("stock_agent.control.request_parser.dart_client.find_ticker_by_name")
    @patch("stock_agent.control.request_parser.create_tool_agent")
    def test_reference_date_is_not_part_of_user_request(self, create_agent, find_ticker):
        find_ticker.return_value = "005380"
        create_agent.return_value.invoke.return_value = {
            "structured_response": ParsedRequest(
                company_candidates=["현대차"], research_question="환율 영향을 알려줘"
            )
        }
        raw = "현차 환율 영향을 알려줘"
        result = request_parsing_node({"raw_user_input": raw})

        self.assertEqual(
            create_agent.return_value.invoke.call_args.args[0],
            {"messages": [("user", raw)]},
        )
        self.assertIn(
            "상대 날짜 계산용 기준 날짜: " + datetime.date.today().isoformat(),
            create_agent.call_args.args[1],
        )
        self.assertEqual(result["research_mandate"]["period_days"], 30)
        self.assertEqual(
            result["research_mandate"]["as_of_date"], datetime.date.today().isoformat()
        )

    @patch("stock_agent.control.request_parser.dart_client.find_ticker_by_name")
    def test_explicit_period_is_preserved(self, find_ticker):
        find_ticker.return_value = "005380"
        for raw, days in [("현대차 오늘 주가", 1), ("현대차 최근 30일 주가", 30)]:
            with self.subTest(raw=raw):
                parsed = ParsedRequest(
                    company_candidates=["현대차"], research_question="주가",
                    as_of_date="2026-08-25", period_days=days,
                )
                result = _validate_parsed_request(raw, parsed)
                self.assertEqual(result["research_mandate"]["period_days"], days)
                self.assertEqual(result["research_mandate"]["as_of_date"], "2026-08-25")


class ResearchMandateScopeTest(unittest.TestCase):
    """검증된 Mandate가 근거 기반 투자 의견을 허용하는지 확인한다."""

    @patch("stock_agent.control.request_parser.dart_client.find_ticker_by_name")
    def test_allows_grounded_investment_opinion_without_order_execution(
        self,
        find_ticker_by_name,
    ) -> None:
        """투자 의견은 허용하고 수익 보장과 자동 주문은 제한한다."""
        find_ticker_by_name.return_value = "005930"
        parsed = ParsedRequest(
            company_candidates=["삼성전자"],
            research_question="매수해도 될지 근거와 함께 알려줘",
        )

        result = _validate_parsed_request(
            "삼성전자 매수해도 될지 근거와 함께 알려줘",
            parsed,
        )

        mandate = result["research_mandate"]
        self.assertEqual(
            mandate["purpose"],
            "근거 기반 종목 리서치와 투자 판단 지원",
        )
        self.assertIn(
            "투자 의견에는 근거, 판단 조건, 반대 요인과 불확실성을 함께 제시한다.",
            mandate["constraints"],
        )
        self.assertIn(
            "수익을 보장하거나 자동 주문을 실행하지 않는다.",
            mandate["constraints"],
        )
        self.assertFalse(
            any(
                "투자 조언 또는 Buy/Hold/Sell 판단을 생성하지 않는다" in constraint
                for constraint in mandate["constraints"]
            )
        )

    def test_synthesis_allows_grounded_buy_hold_sell_opinion(self) -> None:
        """Synthesis가 근거 기반 투자 의견을 금지하지 않고 조건부로 허용한다."""
        prompt = build_system_prompt("orchestrator", current_date="2026-09-13",
                                     execution_stage="synthesis")
        self.assertIn("투자 판단을 요청받은 경우에만 Buy/Hold/Sell 의견", prompt)
        self.assertIn("근거·반대 요인·성립 조건", prompt)
        self.assertIn("투자 수익을 보장하거나 주문을 실행하지 않는다", prompt)



if __name__ == "__main__":
    unittest.main()
