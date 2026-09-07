"""LangChain Agent 생성 API와 역할별 모델 선택을 격리한다."""

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer

from stock_agent.gateways.llm import ModelRole, get_chat_model
from stock_agent.trajectory import current_trajectory_callback


def create_tool_agent(
    tools: Sequence[BaseTool],
    system_prompt: str,
    *,
    model_role: ModelRole = "worker",
    response_format: type[Any] | None = None,
    trace_node_name: str,
) -> Any:
    """LangChain Agent 생성 세부사항을 감싼 실행 가능한 Agent를 반환한다.

    Args:
        tools: 해당 Agent에 코드 수준으로 허용할 LangChain Tool 목록.
        system_prompt: Agent의 고정 역할, 조사 절차, 금지 사항.
        model_role: Planner·Worker·Reviewer 중 사용할 모델 설정 역할.
        response_format: Structured Output이 필요할 때 사용할 스키마 타입.
        trace_node_name: 모델·Tool Callback을 연결할 상위 LangGraph 노드 이름.

    Returns:
        `invoke`와 `stream`으로 실행할 수 있는 컴파일된 LangChain Agent 그래프.
    """
    agent = create_agent(
        model=get_chat_model(model_role),
        tools=list(tools),
        system_prompt=system_prompt,
        response_format=response_format,
    )
    callback = current_trajectory_callback(trace_node_name)
    if callback is None:
        return agent
    return agent.with_config({"callbacks": [callback]})


def stream_agent_text(agent: Any, payload: dict[str, Any], node_name: str) -> str:
    """내부 Agent의 자연어 Token을 외부 LangGraph Stream으로 전달한다.

    Args:
        agent: `create_agent`가 반환한 실행 가능한 Agent 그래프.
        payload: Agent에 전달할 messages 입력 객체.
        node_name: API가 Token을 분리할 상위 Worker 또는 Synthesis 노드 이름.

    Returns:
        Tool loop가 끝난 뒤 Agent State에 남은 최종 AI 메시지의 텍스트.

    Note:
        Tool Call과 ToolMessage는 전달하지 않는다. 외부 그래프가 일반 `invoke`로
        실행될 때 Stream writer는 출력 없이 동작하므로 비-Streaming 실행도 지원한다.
    """
    writer = get_stream_writer()
    final_state: dict[str, Any] | None = None

    for mode, chunk in agent.stream(
        payload,
        stream_mode=["messages", "values"],
    ):
        if mode == "values":
            final_state = chunk
            continue

        message, _metadata = chunk
        text = _message_text(message)
        if text and not getattr(message, "tool_call_chunks", None):
            writer({"node": node_name, "delta": text})

    if final_state is None or not final_state.get("messages"):
        raise ValueError(f"{node_name} Agent가 최종 메시지를 생성하지 않았습니다.")
    return _message_text(final_state["messages"][-1])


def _message_text(message: BaseMessage) -> str:
    """문자열 또는 Content Block 메시지에서 사용자에게 보여줄 텍스트를 꺼낸다."""
    if isinstance(message.content, str):
        return message.content
    return "".join(
        str(block.get("text", ""))
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text"
    )
