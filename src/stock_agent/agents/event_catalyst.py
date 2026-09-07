"""Event and Catalyst Worker Agent — 뉴스·공시 사건 분석 담당."""

from stock_agent.agents._task import format_task, get_assigned_task
from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.state import StockAgentState
from stock_agent.tools.disclosure import get_disclosure
from stock_agent.tools.price import get_market_evidence
from stock_agent.tools.search import search_web

SYSTEM_PROMPT = """당신은 한국 주식 시장의 Event and Catalyst Worker Agent입니다.
Orchestrator가 배정한 사건·Catalyst 질문을 가격·뉴스·공시 Tool 근거로 조사합니다.

## 전문 역할
- 가격 데이터를 먼저 조회해 주요 급등락 날짜를 찾는다.
- 급등락 날짜 주변의 뉴스와 공시를 조사한다.
- 사건 발생일과 가격 변동일을 비교한다.
- 긍정·부정 Catalyst와 대안적 설명을 구분한다.
- 모든 핵심 주장에 URL 출처를 붙인다.

## 조사 절차
1. 배정된 모든 핵심 질문을 확인한다.
2. get_market_evidence로 가격 흐름과 주요 급등락 날짜를 확인한다.
3. 변동 원인이나 사건 조사가 필요한 질문일 때만 search_web과 get_disclosure를 호출한다.
4. 가격 질문에는 결정적 Market Evidence로 답하고, 사건 질문에는 가능한 영향과 대안적 설명을 추가한다.

## 금지 사항
- 같은 날짜에 발생했다는 이유만으로 인과관계를 확정하지 않는다.
- Tool 결과에 없는 사건이나 출처를 만들지 않는다.
- 분석 기준일 이후의 사건을 사용하지 않는다.
- 배정된 범위를 다른 전문 영역으로 확장하지 않는다.
- 사건 근거만으로 전체 Buy/Hold/Sell 결론을 단정하지 않고, Catalyst의 방향과 불확실성을 Synthesis에 전달한다.

## 출력
마크다운으로 질문별 답변, 변동 날짜, 사건, 출처, 가능한 영향, 대안적 설명과 한계를 작성한다."""


@trace_node_output("event_catalyst")
def event_catalyst_agent_node(state: StockAgentState) -> dict:
    """가격 조회부터 사건 확인까지 하나의 복합 Worker 안에서 수행한다.

    Args:
        state: ResearchPlan, ResearchMandate와 종목 정보가 담긴 공유 상태.

    Returns:
        가격 변동·사건·출처·대안 설명이 포함된 `event_catalyst_report` 상태 업데이트.

    Note:
        선행 Market Agent 없이 공유 `get_market_evidence` Tool을 직접 사용한다.
    """
    task = get_assigned_task(state, "event_catalyst")
    mandate = state["research_mandate"]
    agent = create_tool_agent(
        [get_market_evidence, search_web, get_disclosure],
        SYSTEM_PROMPT,
        model_role="worker",
        trace_node_name="event_catalyst",
    )
    report = stream_agent_text(
        agent,
        {
            "messages": [
                (
                    "user",
                    (
                        f"원본 입력: {mandate['original_question']}\n"
                        f"정리된 조사 질문: {mandate['research_question']}\n"
                        f"회사: {mandate['corp_name']} ({mandate['ticker']})\n"
                        f"분석 기준일: {mandate['as_of_date']}\n"
                        f"분석 기간: 최근 {mandate['period_days']}일\n\n"
                        f"{format_task(task)}\n\n"
                        "Market Evidence를 먼저 조회하세요. 배정된 질문이 변동 원인이나 "
                        "사건을 요구할 때만 뉴스와 공시를 추가 조사하세요."
                    )
                )
            ]
        },
        "event_catalyst",
    )
    return {"event_catalyst_report": report}
