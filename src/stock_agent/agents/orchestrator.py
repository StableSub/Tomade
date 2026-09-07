"""상위 Agent: 직접 답변, 조사 계획과 Worker 결과 종합을 담당한다."""

import json
from typing import Literal, TypeVar

from pydantic import BaseModel, model_validator

from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.state import ResearchPlan, ResearchTask, StockAgentState

T = TypeVar("T")

SYSTEM_PROMPT = (
    "당신은 사용자와 대화하고 전문 Worker를 지휘하는 상위 주식 리서치 Agent입니다.\n"
    "일반 질문에는 직접 답하고, 근거 조사가 필요하면 계획을 작성해 하위 Agent에 배정합니다. "
    "조사 결과가 돌아오면 같은 사용자 요청과 최초 계획에 맞춰 최종 답변을 작성합니다.\n"
    "일반 답변: 인사·지식·금융 개념·사용법을 한국어로 간결하게 설명합니다. "
    "현재 이전 대화·메모리·계좌 조회 Tool은 없습니다. 확인하지 않은 최신 시세·뉴스·계좌 정보를 만들지 않습니다.\n"
    "조사 계획: business는 사업·재무·DART 공시, macro_sector는 산업·금리·환율·경쟁 환경, "
    "event_catalyst는 가격·거래량·변동 원인·사건을 조사합니다. "
    "필요한 Worker만 선택하고 각각 목표·1~4개의 구체적인 질문·완료 기준을 배정합니다. "
    "종합 분석에는 세 Worker를 선택합니다. Worker의 Tool 호출 순서는 직접 정하지 않습니다. "
    "회사와 날짜 검증은 실행 코드에 맡깁니다. 계획 단계에서 투자 결론을 미리 만들지 않습니다.\n"
    "조사 후 답변: 제공된 조사 조건·최초 계획·Worker 결과만 사용하고 핵심 주장에 기존 URL을 유지합니다. "
    "새로운 사실·수치·출처를 추가하지 않습니다. 사실과 해석, 상충하는 근거, 미확인 사항을 구분합니다. "
    "사용자가 투자 판단을 요청한 경우에만 Buy/Hold/Sell 의견과 근거·반대 요인·성립 조건·Confidence·불확실성을 제시합니다. "
    "수익을 보장하거나 주문을 실행하지 않습니다. 전문 용어는 쉽게 설명하고 조사하지 않은 영역의 빈 섹션은 생략합니다."
)


class UpperDecision(BaseModel):
    """첫 호출에서 직접 답변 또는 조사 계획 중 하나를 반환하는 계약."""

    intent: Literal["general", "research"]
    final_answer: str | None = None
    research_plan: ResearchPlan | None = None

    @model_validator(mode="after")
    def validate_action(self):
        """직접 답변은 비어 있지 않은 응답, 조사는 계획만 허용한다."""
        if self.intent == "general":
            if not self.final_answer or not self.final_answer.strip() or self.research_plan is not None:
                raise ValueError("일반 답변에는 응답만 필요합니다.")
        elif self.research_plan is None or self.final_answer is not None:
            raise ValueError("종목 조사에는 조사 계획만 필요합니다.")
        return self


def upper_agent_node(state: StockAgentState) -> dict:
    """현재 질문에 답하거나 조사 계획을 만들고, Worker 결과가 있으면 종합한다.

    Args:
        state: 원본 질문과 선택적으로 검증된 조사 조건·계획·Worker 보고서.
    Returns:
        첫 호출은 intent와 답변 또는 계획, 조사 후 호출은 final_answer.
    Raises:
        ValueError: 출력 계약 위반, 필요한 Worker 결과 누락 또는 빈 최종 응답.
    Note:
        모든 단계에서 같은 시스템 프롬프트와 planner 모델을 사용한다.
        조사·메모리 Tool은 제공하지 않으며 모델 호출 오류는 전달한다.
    """
    if state.get("research_mandate") is not None:
        plan = state["research_plan"]
        for task in plan.tasks:
            if not state.get(f"{task.agent}_report"):
                raise ValueError(f"{task.agent} 조사 결과가 없습니다.")
        agent = create_tool_agent([], SYSTEM_PROMPT, model_role="planner", trace_node_name="upper_agent")
        answer = stream_agent_text(agent, {"messages": [
            ("user", state["raw_user_input"]),
            ("assistant", "다음 계획에 따라 조사를 진행합니다.\n" + plan.model_dump_json()),
            ("user", "실행 결과를 바탕으로 최종 답변을 작성하세요.\n조사 조건:\n"
             + json.dumps(state["research_mandate"], ensure_ascii=False)
             + "\nWorker 결과:\n" + _format_worker_reports(state, plan)),
        ]}, "upper_agent")
        if not answer.strip():
            raise ValueError("상위 Agent의 최종 응답이 비어 있습니다.")
        return {"final_answer": answer}

    agent = create_tool_agent([], SYSTEM_PROMPT, model_role="planner",
                              response_format=UpperDecision, trace_node_name="upper_agent")
    messages = [("user", state["raw_user_input"])]
    if state.get("research_only"):
        messages.insert(0, ("user", "이 요청은 종목 조사 전용입니다. research 계획을 작성하세요."))
    result = agent.invoke({"messages": messages})
    decision = UpperDecision.model_validate(result["structured_response"])
    if state.get("research_only") and decision.intent != "research":
        raise ValueError("종목 조사 전용 요청에는 조사 계획이 필요합니다.")
    if decision.intent == "general":
        return {"intent": "general", "final_answer": decision.final_answer}
    return {"intent": "research", "research_plan": _normalize_plan(decision.research_plan)}


def _format_worker_reports(state: StockAgentState, plan: ResearchPlan) -> str:
    """선택된 Worker의 리포트만 Synthesis 입력 형식으로 조합한다."""
    report_fields = {
        "business": ("Business Worker", "business_report"),
        "macro_sector": ("Macro and Sector Worker", "macro_sector_report"),
        "event_catalyst": ("Event and Catalyst Worker", "event_catalyst_report"),
    }
    sections = []
    for task in plan.tasks:
        title, field = report_fields[task.agent]
        report = state.get(field, "조사 결과 없음")
        sections.append(f"=== {title} ===\n{report}")
    return "\n\n".join(sections)


def _normalize_plan(plan: ResearchPlan) -> ResearchPlan:
    """같은 Worker에 중복 배정된 질문과 완료 기준을 병합한다."""
    unique_tasks: dict[str, ResearchTask] = {}
    for task in plan.tasks:
        if task.agent not in unique_tasks:
            unique_tasks[task.agent] = task.model_copy(
                update={
                    "questions": _unique(task.questions)[:4],
                    "completion_criteria": _unique(task.completion_criteria)[:4],
                }
            )
            continue

        existing = unique_tasks[task.agent]
        unique_tasks[task.agent] = existing.model_copy(
            update={
                "questions": _unique(existing.questions + task.questions)[:4],
                "completion_criteria": _unique(
                    existing.completion_criteria + task.completion_criteria
                )[:4],
            }
        )

    order = ["business", "macro_sector", "event_catalyst"]
    tasks = [unique_tasks[name] for name in order if name in unique_tasks]
    return ResearchPlan(planning_summary=plan.planning_summary, tasks=tasks)


def _unique(values: list[T]) -> list[T]:
    """입력 순서를 유지하며 중복 값을 제거한다."""
    return list(dict.fromkeys(values))
