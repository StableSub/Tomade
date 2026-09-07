"""전문 Agent가 자신에게 배정된 ResearchTask를 찾는 공통 함수."""

from stock_agent.state import AgentName, ResearchTask, StockAgentState


def get_assigned_task(state: StockAgentState, agent_name: AgentName) -> ResearchTask:
    """ResearchPlan에서 지정된 Worker의 조사 작업을 찾는다.

    Args:
        state: 구조화된 `research_plan`이 포함된 그래프 상태.
        agent_name: 찾으려는 전문 Agent의 고정 식별자.

    Returns:
        조건부 edge가 해당 Agent를 선택할 때 함께 계획된 `ResearchTask`.
    """
    plan = state["research_plan"]
    return next(task for task in plan.tasks if task.agent == agent_name)


def format_task(task: ResearchTask) -> str:
    """구조화된 조사 작업을 Worker가 읽을 프롬프트 문장으로 변환한다.

    Args:
        task: Planner가 생성한 목표·질문·완료 기준을 가진 작업.

    Returns:
        배정 목표, 필수 조사 질문, 완료 기준을 구분한 일반 텍스트.
        원본 질문과 Mandate는 호출하는 Worker가 별도로 추가한다.
    """
    questions = "\n".join(f"- {question}" for question in task.questions)
    criteria = "\n".join(f"- {criterion}" for criterion in task.completion_criteria)
    return (
        f"배정 목표: {task.objective}\n\n"
        f"필수 조사 질문:\n{questions}\n\n"
        f"완료 기준:\n{criteria}"
    )
