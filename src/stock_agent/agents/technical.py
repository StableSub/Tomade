"""technical Worker의 허용 도구와 실행 경계를 연결한다."""

from stock_agent.agents.worker import run_worker
from stock_agent.debug import trace_node_output
from stock_agent.state import StockAgentState
from stock_agent.tools.technical import make_technical_tool


@trace_node_output("technical")
async def technical_agent_node(state: StockAgentState) -> dict:
    """자기 작업·확정 조건으로 조사하고 technical_report를 반환한다.

    외부 호출과 보고서 검증은 공통 실행기가 수행한다. 다른 Worker의 보고서나
    사용자 기억은 모델에 전달하지 않는다. 취소는 호출자로 전파한다.
    """
    m = state["research_mandate"]
    return await run_worker(state, "technical", [make_technical_tool(m)])
