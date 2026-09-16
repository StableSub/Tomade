"""Event and Catalyst Worker Agent — 뉴스·공시 사건 분석 담당."""

from stock_agent.agents._task import format_task, get_assigned_task
from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.prompts.builder import build_system_prompt
from stock_agent.state import StockAgentState
from stock_agent.tools.disclosure import get_disclosure
from stock_agent.tools.price import get_market_evidence
from stock_agent.tools.search import search_web


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
        build_system_prompt("event_catalyst"),
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
                        f"{format_task(task)}"
                    )
                )
            ]
        },
        "event_catalyst",
    )
    return {"event_catalyst_report": report}
