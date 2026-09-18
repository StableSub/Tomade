"""단일 자연어 입력을 구조화하고 결정적으로 검증하는 Request Parsing 노드."""

import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent
from stock_agent.prompts.builder import build_system_prompt
from stock_agent.state import ParsedRequest, ResearchMandate, StockAgentState
from stock_agent.vendors import dart_client


@trace_node_output("request_parser")
def request_parsing_node(state: StockAgentState) -> dict:
    """경량 LLM 추출 결과를 DART·날짜·기간 규칙으로 검증한다.

    Args:
        state: 사용자의 단일 자연어 입력인 `raw_user_input`이 포함된 상태.

    Returns:
        성공하면 ParsedRequest와 검증된 `ResearchMandate`를 반환한다. 모호하거나
        유효하지 않으면 `input_error`를 반환해 후속 노드를 중단시킨다.
    """
    raw_user_input = state["raw_user_input"].strip()
    today = datetime.datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    parser = create_tool_agent(
        [],
        build_system_prompt("request_parser", current_date=today),
        model_role="parser",
        response_format=ParsedRequest,
        trace_node_name="request_parser",
    )
    result = parser.invoke(
        {
            "messages": [
                ("user", raw_user_input)
            ]
        }
    )
    parsed = result["structured_response"]
    return _validate_parsed_request(raw_user_input, parsed)


def _validate_parsed_request(raw_input: str, parsed: ParsedRequest) -> dict:
    """LLM 후보를 실제 상장사와 유효한 날짜·기간으로 정규화한다."""
    if parsed.needs_clarification:
        reason = parsed.clarification_reason or "입력 대상을 명확히 확인할 수 없습니다."
        return {"parsed_request": parsed, "input_error": reason}

    resolved_companies: set[tuple[str, str]] = set()
    invalid_candidates = []

    for company_name in dict.fromkeys(parsed.company_candidates):
        ticker = dart_client.find_ticker_by_name(company_name.strip())
        if ticker is None:
            invalid_candidates.append(company_name)
            continue
        resolved_companies.add((company_name.strip(), ticker))

    if invalid_candidates:
        candidates = ", ".join(str(candidate) for candidate in invalid_candidates)
        return {
            "parsed_request": parsed,
            "input_error": f"상장 회사명으로 확인할 수 없습니다: {candidates}",
        }
    if not resolved_companies:
        return {
            "parsed_request": parsed,
            "input_error": "상장 회사명을 찾지 못했습니다. 정확한 회사명을 포함해 질문해주세요.",
        }
    if len(resolved_companies) > 1:
        companies = ", ".join(
            f"{name}({ticker})" for name, ticker in sorted(resolved_companies)
        )
        return {
            "parsed_request": parsed,
            "input_error": f"현재는 한 번에 한 종목만 지원합니다: {companies}",
        }

    corp_name, ticker = resolved_companies.pop()
    as_of_date, date_error = _resolve_as_of_date(parsed.as_of_date)
    if date_error:
        return {"parsed_request": parsed, "input_error": date_error}

    period_days = 30 if parsed.period_days is None else parsed.period_days
    if period_days < 1 or period_days > 3650:
        return {
            "parsed_request": parsed,
            "input_error": "분석 기간은 1일 이상 3650일 이하여야 합니다.",
        }

    research_question = parsed.research_question.strip()
    if not research_question:
        return {
            "parsed_request": parsed,
            "input_error": "종목 외에 알고 싶은 내용을 함께 입력해주세요.",
        }

    corp_code = dart_client.find_corp_code(corp_name)
    if not corp_code:
        return {"parsed_request": parsed, "input_error": "DART 회사 식별자를 확인할 수 없습니다."}

    mandate: ResearchMandate = {
        "original_question": raw_input,
        "research_question": research_question,
        "ticker": ticker,
        "corp_name": corp_name,
        "corp_code": corp_code,
        "as_of_date": as_of_date,
        "period_days": period_days,
        "query_start_date": (datetime.date.fromisoformat(as_of_date) - datetime.timedelta(days=period_days - 1)).isoformat(),
        "query_end_date": as_of_date,
        "investment_horizon": parsed.investment_horizon,
        "purpose": "근거 기반 종목 리서치와 투자 판단 지원",
        "constraints": [
            "투자 의견에는 근거, 판단 조건, 반대 요인과 불확실성을 함께 제시한다.",
            "수익을 보장하거나 자동 주문을 실행하지 않는다.",
            "확인된 사실과 해석을 구분한다.",
            "분석 기준일 이후의 정보를 사용하지 않는다.",
        ],
    }
    return {"parsed_request": parsed, "research_mandate": mandate}


def _resolve_as_of_date(value: str | None) -> tuple[str, str | None]:
    """Parser의 날짜 후보를 ISO 날짜로 검증하고 미래 날짜를 거부한다."""
    today = datetime.datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not value:
        return today.isoformat(), None
    try:
        parsed_date = datetime.date.fromisoformat(value)
    except ValueError:
        return "", "분석 기준일은 YYYY-MM-DD 형식이어야 합니다."
    if parsed_date > today:
        return "", "분석 기준일은 오늘보다 미래일 수 없습니다."
    return parsed_date.isoformat(), None


def route_parsed_request(state: StockAgentState) -> Literal["plan", "end"]:
    """입력 검증 성공 여부에 따라 조사 계획 실행 또는 조기 종료를 선택한다."""
    return "end" if state.get("input_error") else "plan"
