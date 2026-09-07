"""Business Worker Agent — 기업·공시·기초 재무 분석 담당."""

from stock_agent.agents._task import format_task, get_assigned_task
from stock_agent.debug import trace_node_output
from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.state import StockAgentState
from stock_agent.tools.disclosure import get_disclosure

SYSTEM_PROMPT = """당신은 한국 상장사를 조사하는 Business Worker Agent입니다.
Orchestrator가 배정한 사업·재무·공시 질문을 Tool 근거로 조사합니다.

## 전문 역할
- 최근 주요 공시를 분류하고 중요한 변화를 찾는다.
- 실적·배당·자사주·경영 변화 등 확인 가능한 기업 정보를 설명한다.
- 공식 공시의 날짜와 원문 URL을 유지한다.

## 조사 절차
1. 배정된 모든 핵심 질문을 확인한다.
2. 필요한 경우 같은 Business 영역 안에서 보조 질문을 만든다.
3. get_disclosure를 호출해 공식 근거를 수집한다.
4. 질문별 답변과 완료 기준 충족 여부를 작성한다.

## 금지 사항
- 공시 제목만으로 원문 세부 내용을 추측하지 않는다.
- 공시에 없는 수치나 사실을 만들지 않는다.
- 가격 차트나 거시경제를 분석하지 않는다.
- 배정된 범위를 다른 전문 영역으로 확장하지 않는다.
- 근거 없는 전망이나 가치평가를 하지 않는다.

## 출력
마크다운으로 질문별 답변, 주요 공시, 원문 출처, 미확인 사항과 한계를 작성한다."""


@trace_node_output("business")
def business_agent_node(state: StockAgentState) -> dict:
    """배정된 기업·재무·공시 질문을 Business Worker로 조사한다.

    Args:
        state: ResearchPlan, ResearchMandate와 회사 식별 정보가 담긴 공유 상태.

    Returns:
        출처가 포함된 `business_report` 상태 업데이트.
    """
    task = get_assigned_task(state, "business")
    mandate = state["research_mandate"]
    agent = create_tool_agent(
        [get_disclosure],
        SYSTEM_PROMPT,
        model_role="worker",
        trace_node_name="business",
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
        "business",
    )
    return {"business_report": report}
