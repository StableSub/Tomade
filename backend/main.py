"""FastAPI 서버와 LangGraph Research Streaming API."""

import json
import logging
from contextlib import aclosing, asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Depends
from starlette.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stock_agent.graph import graph
from stock_agent.trajectory import TrajectoryRecorder, trajectory_run
from backend.portfolio import router as portfolio_router, require_local
from backend import conversations
from backend.short_term_memory import prepare_short_term_memory
from backend.model_settings import router as model_settings_router
from stock_agent.gateways.llm import model_configuration, model_session

logger = logging.getLogger(__name__)
WORKER_NODES = {"business", "macro_sector", "event_catalyst"}


class ResearchRequest(BaseModel):
    """사용자가 Chat에서 전송하는 단일 종목 리서치 요청."""

    message: str = Field(min_length=1, max_length=300)


class ChatRequest(ResearchRequest):
    """선택한 대화방에 저장할 질문. ID 생략 시 기존 독립 실행을 유지한다."""

    conversation_id: UUID | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """단일 서버 시작 시 대화 DB를 초기화한다. 초기화 오류는 시작 실패로 전달한다."""
    await run_in_threadpool(conversations.initialize_database)
    yield


app = FastAPI(title="stock_agent API", version="0.1.0", lifespan=lifespan)
app.include_router(portfolio_router)
app.include_router(conversations.router)
app.include_router(model_settings_router)


@app.post("/api/chat/stream", dependencies=[Depends(require_local)])
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    """상위 Chat Graph를 실행하고 일반 답변·종목 조사 SSE를 반환한다.

    message는 1~300자이며 공백은 422로 거부한다. 대화 기록 보호를 위해 로컬 접근만 허용한다.
    conversation_id가 있으면 질문·답변을 저장한다. 세션 요약과 최근 완료된 10턴을 상위 Agent에 전달한다.
    없는 대화는 404, 같은 대화의 실행 중 요청은 409로 거부한다.
    """
    message = request.message.strip()
    if not message:
        raise HTTPException(422, "질문을 입력하세요.")
    events = _stream_chat_events(message)
    if request.conversation_id is not None:
        message_id = await run_in_threadpool(conversations.begin_turn, str(request.conversation_id), message)
        events = _stream_saved_chat_events(message, message_id)
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def _stream_saved_chat_events(message: str, message_id: int) -> AsyncIterator[str]:
    """종료 SSE를 전달하기 전에 답변을 저장하고 연결 중단은 별도 상태로 기록한다."""
    finished = False
    try:
        async with aclosing(_stream_chat_events(message, message_id=message_id)) as events:
            async for frame in events:
                if frame.startswith(("event: run.completed\n", "event: run.error\n")):
                    data = json.loads(frame.split("\ndata: ", 1)[1])
                    success = frame.startswith("event: run.completed\n")
                    await run_in_threadpool(conversations.finish_turn, message_id,
                                            data["final_answer"] if success else data["message"],
                                            "completed" if success else "error")
                    finished = True
                yield frame
    finally:
        if not finished:
            # 취소된 async scope에서도 중단 상태를 남기기 위해 짧은 로컬 쓰기를 수행한다.
            conversations.finish_turn(message_id, "연결이 끊겨 응답이 중단되었습니다. 다시 질문해주세요.", "interrupted")


async def _stream_chat_events(message: str, *, message_id: int | None = None) -> AsyncIterator[str]:
    """Chat Graph 이벤트를 SSE로 변환한다. 실행 분기는 LangGraph가 담당한다."""
    with model_session():
        async with aclosing(_stream_research_events_traced(message, str(uuid4()), None, chat=True, message_id=message_id)) as events:
            async for event in events:
                yield event


@app.post("/api/research/stream")
async def stream_research(request: ResearchRequest) -> StreamingResponse:
    """하나의 질문을 실행하고 노드 상태·Token·결과를 SSE로 반환한다.

    Args:
        request: 종목과 질문이 포함된 1~300자의 자연어 메시지.

    Returns:
        LangGraph 실행을 `run.*`, `node.*` SSE 이벤트로 변환하는 StreamingResponse.

    Raises:
        HTTPException: 공백만 있는 메시지가 전달된 경우 Graph 실행 전에 발생한다.
    """
    message = request.message.strip()
    if not message:
        raise HTTPException(
            status_code=422,
            detail="message는 1자 이상 300자 이하여야 합니다.",
        )

    return StreamingResponse(
        _stream_research_events(message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_research_events(message: str, *, run_id: str | None = None) -> AsyncIterator[str]:
    """실행별 Trajectory 파일을 생성하며 브라우저용 SSE를 반환한다."""
    run_id = run_id or str(uuid4())
    with model_session(), trajectory_run(run_id) as trajectory:
        async for event in _stream_research_events_traced(
            message,
            run_id,
            trajectory,
        ):
            yield event


async def _stream_research_events_traced(
    message: str,
    run_id: str,
    trajectory: TrajectoryRecorder | None,
    *, chat: bool = False, message_id: int | None = None,
) -> AsyncIterator[str]:
    """LangGraph의 custom·update Stream을 SSE와 파일 Trace로 변환한다."""
    first_node = "upper_agent"
    started_nodes = {first_node}
    selected_workers: set[str] = set()
    completed_workers: set[str] = set()
    active_node = first_node
    final_answer: str | None = None

    yield _sse("run.started", {"run_id": run_id, "connection": model_configuration()})
    yield _sse(
        "node.started",
        {"run_id": run_id, "node": first_node},
    )

    try:
        context = await run_in_threadpool(prepare_short_term_memory, message_id) if message_id is not None else {}
        async for namespace, mode, chunk in graph.astream(
            {"raw_user_input": message, "research_only": not chat, "run_id": run_id, "memory_enabled": chat, **context},
            stream_mode=["custom", "updates"], subgraphs=True,
        ):
            if mode == "custom":
                node = chunk["node"]
                if node not in started_nodes:
                    started_nodes.add(node)
                    yield _sse(
                        "node.started",
                        {"run_id": run_id, "node": node},
                    )
                yield _sse(
                    "node.delta",
                    {
                        "run_id": run_id,
                        "node": node,
                        "delta": chunk["delta"],
                    },
                )
                continue

            for node, output in chunk.items():
                if node not in {"upper_agent", "request_parser", *WORKER_NODES}:
                    continue
                active_node = node
                if node not in started_nodes:
                    started_nodes.add(node)
                    yield _sse(
                        "node.started",
                        {"run_id": run_id, "node": node},
                    )

                yield _sse(
                    "node.completed",
                    {
                        "run_id": run_id,
                        "node": node,
                        "output": jsonable_encoder(output),
                    },
                )

                if node == "upper_agent":
                    if output.get("final_answer"):
                        final_answer = output["final_answer"]
                        if not selected_workers:
                            for skipped in ("request_parser", *sorted(WORKER_NODES)):
                                yield _sse("node.skipped", {"run_id": run_id, "node": skipped})
                    else:
                        selected_workers = _selected_worker_names(output)
                        active_node = "request_parser"
                        started_nodes.add(active_node)
                        yield _sse("node.started", {"run_id": run_id, "node": active_node})
                elif node == "request_parser":
                    if input_error := output.get("input_error"):
                        if trajectory:
                            trajectory.mark_status("input_error")
                        yield _sse("run.error", {"run_id": run_id, "node": node,
                                                "code": "input_error", "message": input_error})
                        return
                    for worker in sorted(WORKER_NODES):
                        event = "node.started" if worker in selected_workers else "node.skipped"
                        if worker in selected_workers:
                            started_nodes.add(worker)
                        yield _sse(event, {"run_id": run_id, "node": worker})
                elif node in WORKER_NODES:
                    completed_workers.add(node)
                    if selected_workers and completed_workers >= selected_workers:
                        active_node = "upper_agent"
                        started_nodes.add(active_node)
                        yield _sse(
                            "node.started",
                            {"run_id": run_id, "node": active_node},
                        )


        if final_answer is None:
            if trajectory:
                trajectory.record_run_failure(RuntimeError("최종 답변이 생성되지 않았습니다."), node_name=active_node)
            yield _sse(
                "run.error",
                {
                    "run_id": run_id,
                    "node": active_node,
                    "code": "missing_final_answer",
                    "message": "최종 답변이 생성되지 않았습니다.",
                },
            )
            return

        if trajectory:
            trajectory.mark_status("completed")
        yield _sse(
            "run.completed",
            {"run_id": run_id, "final_answer": final_answer},
        )
    except Exception as error:
        if trajectory:
            trajectory.record_run_failure(error, node_name=active_node)
            logger.exception("Research Run failed: %s", run_id)
        else:
            logger.warning("Research failed node=%s type=%s", active_node, type(error).__name__)
        yield _sse(
            "run.error",
            {
                "run_id": run_id,
                "node": active_node,
                "code": "node_execution_failed",
                "message": "대화 실행 중 오류가 발생했습니다." if chat else "리서치 실행 중 오류가 발생했습니다.",
            },
        )


def _selected_worker_names(output: dict[str, Any]) -> set[str]:
    """ResearchPlan State Update에서 선택된 Worker 이름을 추출한다."""
    plan = output["research_plan"]
    tasks = plan.tasks if hasattr(plan, "tasks") else plan["tasks"]
    return {
        task.agent if hasattr(task, "agent") else task["agent"]
        for task in tasks
    }


def _sse(event: str, data: dict[str, Any]) -> str:
    """이벤트 이름과 JSON 데이터를 SSE 프레임 하나로 직렬화한다."""
    payload = json.dumps(jsonable_encoder(data), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


web_dist = Path(__file__).parents[1] / "frontend" / "dist"
if web_dist.exists():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
