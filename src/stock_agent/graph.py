"""상위 Agent가 직접 답하거나 전문 Worker에게 조사를 맡기는 LangGraph."""

from langgraph.graph import END, START, StateGraph

from stock_agent.agents.business import business_agent_node
from stock_agent.agents.event_catalyst import event_catalyst_agent_node
from stock_agent.agents.macro_sector import macro_sector_agent_node
from stock_agent.agents.orchestrator import upper_agent_node
from stock_agent.control.request_parser import request_parsing_node
from stock_agent.state import StockAgentState
from stock_agent.trajectory import trajectory_run


def route_upper_agent(state: StockAgentState) -> str:
    """최종 답변이 있으면 종료하고, 조사 계획을 만들었으면 입력 검증으로 연결한다."""
    return "end" if state.get("final_answer") else "research"


def route_research_workers(state: StockAgentState) -> list[str]:
    """검증 실패 시 종료하고, 성공 시 계획에 선택된 Worker를 병렬 실행한다."""
    if state.get("input_error"):
        return [END]
    return [task.agent for task in state["research_plan"].tasks]


def build_graph():
    """상위 Agent → 직접 종료 또는 검증·Worker → 같은 상위 Agent 흐름을 컴파일한다.

    일반 답변에는 Parser·Worker를 호출하지 않는다. 조사에서는 입력 검증 후
    선택된 Worker가 모두 끝나면 상위 Agent가 결과를 종합한다. 외부 호출은 실행 시 발생한다.
    """
    workers = StateGraph(StockAgentState)
    workers.add_node("request_parser", request_parsing_node)
    workers.add_node("business", business_agent_node)
    workers.add_node("macro_sector", macro_sector_agent_node)
    workers.add_node("event_catalyst", event_catalyst_agent_node)
    workers.add_edge(START, "request_parser")
    workers.add_conditional_edges("request_parser", route_research_workers,
                                  {name: name for name in ("business", "macro_sector", "event_catalyst", END)})
    for worker in ("business", "macro_sector", "event_catalyst"):
        workers.add_edge(worker, END)
    worker_graph = workers.compile()

    async def research(state: StockAgentState) -> dict:
        """검증·병렬 조사 결과를 반환한다. Chat 조사 Trace를 저장하고 외부 오류는 전달한다."""
        if state.get("research_only"):
            return await worker_graph.ainvoke(state)
        with trajectory_run(state["run_id"]) as trajectory:
            result = await worker_graph.ainvoke(state)
            trajectory.mark_status("input_error" if result.get("input_error") else "completed")
            return result

    builder = StateGraph(StockAgentState)
    builder.add_node("upper_agent", upper_agent_node)
    builder.add_node("research", research)
    builder.add_edge(START, "upper_agent")
    builder.add_conditional_edges("upper_agent", route_upper_agent,
                                  {"end": END, "research": "research"})
    builder.add_conditional_edges("research", lambda state: "end" if state.get("input_error") else "answer",
                                  {"end": END, "answer": "upper_agent"})
    return builder.compile()


graph = build_graph()
