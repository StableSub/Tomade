"""상위 Agent: 직접 답변, 조사 계획과 Worker 결과 종합을 담당한다."""

import datetime
import json
from typing import Literal, TypeVar

from pydantic import BaseModel, model_validator

from stock_agent.gateways.agent import create_tool_agent, stream_agent_text
from stock_agent.tools.user_memory import create_memory_tool, read_user_memory
from stock_agent.prompts.builder import build_system_prompt
from stock_agent.state import ResearchPlan, ResearchTask, StockAgentState

T = TypeVar("T")


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
        state: 원본 질문, 세션 요약·최근 대화와 선택적인 조사 조건·계획·Worker 보고서.
    Returns:
        첫 호출은 intent와 답변 또는 계획, 조사 후 호출은 final_answer.
    Raises:
        ValueError: 출력 계약 위반, 필요한 Worker 결과 누락 또는 빈 최종 응답.
    Note:
        모든 단계에서 같은 프롬프트 템플릿과 planner 모델을 사용하며 실행 단계는 구분한다.
        Chat에는 메모리 갱신 Tool만 제공하며 모델 호출 오류는 전달한다.
    """
    memory_enabled = state.get("memory_enabled", False)
    system_prompt = build_system_prompt(
        "orchestrator",
        current_date=datetime.date.today().isoformat(),
        execution_stage="synthesis" if state.get("research_mandate") is not None else "initial",
        user_memory=read_user_memory() if memory_enabled else "",
        short_term_summary=state.get("short_term_summary", ""),
    )
    tools = [create_memory_tool()] if memory_enabled else []
    recent = state.get("recent_messages", [])
    if state.get("research_mandate") is not None:
        plan = state["research_plan"]
        for task in plan.tasks:
            if not state.get(f"{task.agent}_report"):
                raise ValueError(f"{task.agent} 조사 결과가 없습니다.")
        agent = create_tool_agent(tools, system_prompt, model_role="planner", trace_node_name="upper_agent")
        if tools:
            agent = agent.with_config({"recursion_limit": 16})
        answer = stream_agent_text(agent, {"messages": [*recent,
            ("user", state["raw_user_input"]),
            ("assistant", "다음 계획에 따라 조사를 진행합니다.\n" + plan.model_dump_json()),
            ("user", "실행 결과를 바탕으로 최종 답변을 작성하세요.\n조사 조건:\n"
             + json.dumps(state["research_mandate"], ensure_ascii=False)
             + "\nWorker 결과:\n" + _format_worker_reports(state, plan)),
        ]}, "upper_agent")
        if not answer.strip():
            raise ValueError("상위 Agent의 최종 응답이 비어 있습니다.")
        return {"final_answer": answer}

    agent = create_tool_agent(tools, system_prompt, model_role="planner",
                              response_format=UpperDecision, trace_node_name="upper_agent")
    messages = [*recent, ("user", state["raw_user_input"])]
    if state.get("research_only"):
        messages.insert(0, ("user", "이 요청은 종목 조사 전용입니다. research 계획을 작성하세요."))
    result = agent.invoke({"messages": messages}, config={"recursion_limit": 16})
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
