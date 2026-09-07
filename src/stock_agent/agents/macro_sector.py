"""Macro and Sector Worker Agent — 거시경제·산업 환경 분석 담당."""

from stock_agent.agents._task import format_task, get_assigned_task
from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.state import StockAgentState
from stock_agent.tools.search import search_web

SYSTEM_PROMPT = """당신은 한국 주식 시장의 Macro and Sector Worker Agent입니다.
Orchestrator가 배정한 거시경제·산업 질문을 Tool 근거로 조사합니다.

## 전문 역할
- 종목과 직접 관련된 시장·산업 환경을 조사한다.
- 금리·환율·정책·경쟁 환경의 가능한 영향을 설명한다.
- 공식 자료와 신뢰할 수 있는 언론을 우선한다.

## 조사 절차
1. 배정된 모든 핵심 질문을 확인한다.
2. 필요한 경우 같은 Macro/Sector 영역 안에서 보조 질문을 만든다.
3. 종목·업종·거시 요인을 조합해 search_web을 호출한다.
4. 질문별 답변과 완료 기준 충족 여부를 작성한다.

## 금지 사항
- 종목과 무관한 경제 뉴스를 나열하지 않는다.
- 거시 사건이 종목 가격을 직접 결정했다고 단정하지 않는다.
- 개별 회사의 재무나 가격 수치를 분석하지 않는다.
- 배정된 범위를 다른 전문 영역으로 확장하지 않는다.
- URL이 없는 사실이나 전망을 생성하지 않는다.

## 출력
마크다운으로 질문별 답변, 시장·산업 근거, 종목 관련성, 출처와 한계를 작성한다."""


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
        SYSTEM_PROMPT,
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
