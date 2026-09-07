"""단일 자연어 입력을 구조화하고 결정적으로 검증하는 Request Parsing 노드."""

import datetime
from typing import Literal

from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent
from stock_agent.state import ParsedRequest, ResearchMandate, StockAgentState
from stock_agent.vendors import dart_client

SYSTEM_PROMPT = """당신은 한국 주식 리서치 요청을 구조화하는 Request Parser입니다.
사용자의 한 문장에서 회사 후보, 실제 조사 질문, 기준일, 기간을 추출합니다.

## 출력 원칙
- company_candidates에는 가능한 한 DART에서 사용하는 정식 상장 회사명을 작성합니다.
- '삼전'은 '삼성전자', '하닉'은 'SK하이닉스', '현차'는 '현대차'처럼 명확한 별칭은 정식명으로 변환합니다.
- research_question에는 회사명·날짜·기간 표현을 제거하고 사용자가 실제로 알고 싶은 내용을 보존합니다.
- 추출 대상은 user 메시지의 사용자 요청뿐입니다. 시스템에서 제공하는 기준 날짜는 상대 날짜 계산용이며 사용자가 지정한 날짜나 기간이 아닙니다.
- 사용자 요청에 상대 날짜가 명시된 경우에만 시스템의 기준 날짜로 계산합니다.
- YYYY-MM-DD 날짜는 그대로 as_of_date에 작성합니다.
- '오늘', '어제', '그제', 'N일 전'은 ISO 날짜로 변환해 as_of_date에 작성합니다.
- '오늘', '어제', '그제', 'N일 전'처럼 특정 날짜 하나가 지정되면 질문 주제와 관계없이 period_days는 1로 작성합니다.
- '최근 N일', 'N주', 'N개월', 'N년'은 각각 1·7·30·365일 기준으로 period_days에 변환하며, 특정 날짜와 기간이 함께 있으면 명시된 기간을 우선합니다.
- 사용자 요청에 날짜와 기간이 모두 없으면 as_of_date와 period_days를 null로 둡니다. 기본 기준일과 30일 기간은 Python에서 적용하므로 추측해 채우지 않습니다.
- 여러 회사를 비교하거나 대상이 모호하면 모든 후보를 기록하고 needs_clarification을 true로 설정합니다.
- 회사나 종목을 확인할 수 없으면 needs_clarification을 true로 설정합니다.
- 금융 분석, Agent 선택, 사실 조사, 투자 판단은 수행하지 않습니다.
"""


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
    today = datetime.date.today().isoformat()
    parser = create_tool_agent(
        [],
        SYSTEM_PROMPT + f"\n상대 날짜 계산용 기준 날짜: {today}\n",
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

    period_days = parsed.period_days or 30
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

    mandate: ResearchMandate = {
        "original_question": raw_input,
        "research_question": research_question,
        "ticker": ticker,
        "corp_name": corp_name,
        "as_of_date": as_of_date,
        "period_days": period_days,
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
    today = datetime.date.today()
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
