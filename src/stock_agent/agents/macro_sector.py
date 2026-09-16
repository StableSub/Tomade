"""Macro and Sector Worker Agent — 거시경제·산업 환경 분석 담당."""

from stock_agent.agents._task import format_task, get_assigned_task
from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.prompts.builder import build_system_prompt
from stock_agent.state import StockAgentState
from stock_agent.tools.search import search_web


@trace_node_output("macro_sector")
def macro_sector_agent_node(state: StockAgentState) -> dict:
    """배정된 거시경제·산업 질문을 Macro/Sector Worker로 조사한다.

    Args:
        state: ResearchPlan, ResearchMandate와 종목 정보가 담긴 공유 상태.

    Returns:
        출처가 포함된 `macro_sector_report` 상태 업데이트.
    """
    task = get_assigned_task(state, "macro_sector")
    mandate = state["research_mandate"]
    agent = create_tool_agent(
        [search_web],
        build_system_prompt("macro_sector"),
        model_role="worker",
        trace_node_name="macro_sector",
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
                    ),
                )
            ]
        },
        "macro_sector",
    )
    return {"macro_sector_report": report}
