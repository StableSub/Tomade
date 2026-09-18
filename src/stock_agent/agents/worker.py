"""Worker 공통 실행: 제한된 조사, 코드 보존 근거, 검증된 보고서."""

import asyncio
import datetime as dt
import json
import time
from collections import Counter
from zoneinfo import ZoneInfo

import httpx
import requests
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from openai import OpenAIError
from pydantic import ValidationError

from stock_agent.agents._task import get_assigned_task
from stock_agent.control.external_budget import external_call_scope
from stock_agent.gateways.llm import get_chat_model
from stock_agent.prompts.builder import build_system_prompt
from stock_agent.state import (AgentName, Evidence, ResearchTask, StockAgentState,
                               WorkerDraft, WorkerError, WorkerReport)
from stock_agent.trajectory import current_trajectory_callback

TOOL_LIMITS = {
    "business": {"search_disclosure_evidence": 3, "get_financial_evidence": 2},
    "macro_sector": {"search_web": 3},
    "event_catalyst": {"search_disclosure_evidence": 3, "search_web": 3, "get_market_evidence": 1},
    "technical": {"get_technical_evidence": 1},
    "sentiment": {},
}
TOTAL_CALLS = {"business": 5, "macro_sector": 3, "event_catalyst": 5, "technical": 1, "sentiment": 0}
WORKER_SECONDS = {"business": 600, "event_catalyst": 600, "macro_sector": 180, "technical": 180, "sentiment": 180}
MODEL_SECONDS = 120
MODEL_STEPS = 6


def worker_input(state: StockAgentState, role: AgentName) -> dict:
    """자기 작업과 공통 조사 조건만 선택한다. 사용자 기억·다른 보고서는 복사하지 않는다."""
    return {"task": get_assigned_task(state, role).model_dump(), "mandate": dict(state["research_mandate"])}


class EvidenceLedger:
    """Tool 경계에서 원본 근거를 보존하고 모델 입력량과 날짜를 제한한다."""

    def __init__(self, role: AgentName, as_of_date: str):
        self.role = role
        self.as_of_date = dt.date.fromisoformat(as_of_date)
        self.items: dict[str, Evidence] = {}
        self.limitations: list[str] = []
        self.failures: list[dict] = []

    def accept(self, result: dict) -> dict:
        """정규화된 Tool 결과를 검증·제한하고 실제로 제공한 근거만 반환한다."""
        if result.get("status") not in {"complete", "partial", "unavailable", "error"}:
            raise ValueError("지원하지 않는 Tool 결과 상태")
        self.limitations.extend(str(v) for v in result.get("limitations", []))
        if result.get("error"):
            self.failures.append(result["error"])
        if result.get("reason"):
            self.limitations.append(str(result["reason"]))
        accepted = []
        maximum, chars = (40, 600) if self.role == "sentiment" else (24 if self.role == "business" else 12, 4000)
        for item in result.get("evidence", []):
            evidence = Evidence.model_validate(item)
            if not self._eligible(evidence):
                self.limitations.append("기준일을 벗어나거나 시점을 확인할 수 없는 근거 제외")
                continue
            if evidence.evidence_id in self.items:
                if self.items[evidence.evidence_id] != evidence:
                    raise ValueError("동일한 근거 ID에 서로 다른 내용")
                continue
            if len(self.items) >= maximum:
                self.limitations.append(f"모델 입력 근거 최대 {maximum}개 제한 적용")
                break
            content = evidence.content
            if isinstance(content, str) and len(content) > chars:
                evidence = evidence.model_copy(update={"content": content[:chars],
                    "limitations": [*evidence.limitations, f"본문 {chars}자에서 제한, 전체 원문 아님"]})
            elif isinstance(content, dict) and len(json.dumps(content, ensure_ascii=False)) > chars:
                # 수치를 잘라 깨진 JSON으로 만들지 않고 큰 항목 자체를 제외한다.
                self.limitations.append("입력 한도를 넘은 구조화 근거 제외")
                continue
            self.items[evidence.evidence_id] = evidence
            accepted.append(evidence.model_dump())
        return {"status": result["status"], "evidence": accepted,
                "limitations": list(dict.fromkeys(self.limitations)), "error": result.get("error")}

    def _eligible(self, evidence: Evidence) -> bool:
        # 가격 시계열은 공개일 대신 관측 종료일을 확인하고 PIT 조정 한계를 별도 유지한다.
        if evidence.published_at:
            published = _source_date(evidence.published_at)
            if published > self.as_of_date:
                return False
        elif evidence.kind != "metric" or not evidence.observation_end:
            return False
        if evidence.observation_end and _source_date(evidence.observation_end) > self.as_of_date:
            return False
        return True


def _source_date(value: str) -> dt.date:
    """날짜 정밀도는 유지하고 시간대가 있는 시각은 KST 날짜로 비교한다."""
    if len(value) == 10:
        return dt.date.fromisoformat(value)
    timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("근거 시각에 시간대 정보가 필요합니다.")
    return timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()


def finish_report(role: AgentName, task: ResearchTask, draft: WorkerDraft,
                  ledger: EvidenceLedger) -> WorkerReport:
    """질문 누락·허위 근거 참조를 거부하고 코드가 확보한 인용 근거를 붙인다."""
    expected = set(range(len(task.questions)))
    referenced = {idx for finding in draft.findings for idx in finding.evidence_ids}
    if not referenced <= ledger.items.keys():
        raise ValueError("확보하지 않은 근거 ID를 인용했습니다.")
    answered = {finding.question_index for finding in draft.findings}
    unanswered = {question.question_index for question in draft.unanswered_questions}
    if answered | unanswered != expected:
        raise ValueError("배정 질문을 빠짐없이 답변 또는 미확인으로 분류해야 합니다.")
    limitations = list(dict.fromkeys([*draft.limitations, *ledger.limitations,
                                    *(str(f.get("message", f.get("code", "Tool 오류"))) for f in ledger.failures)]))
    return WorkerReport(**draft.model_dump(exclude={"limitations"}), agent=role,
                        evidence=[e for eid, e in ledger.items.items() if eid in referenced],
                        limitations=limitations)


async def run_worker(state: StockAgentState, role: AgentName, tools: list[BaseTool],
                     *, collect=None) -> dict:
    """배정 Worker를 한도 안에서 실행하고 정상 보고서 또는 WorkerError를 반환한다.

    Args: state는 확정 조건·계획, role은 고정 역할, tools는 역할별 허용 목록,
        collect는 Sentiment의 동기 수집 함수다. 외부 자료·모델 호출은 여기서 발생한다.
    Returns: 자기 역할의 *_report 상태 업데이트. 형식 오류·외부 실패는 오류 결과로 격리한다.
    Raises: 취소는 그대로 전파한다. 이미 진행 중인 동기 HTTP의 즉시 종료는 보장하지 않는다.
    """
    task = get_assigned_task(state, role)
    ledger = EvidenceLedger(role, state["research_mandate"]["as_of_date"])
    deadline = time.monotonic() + WORKER_SECONDS[role]
    report_reserve = min(120, WORKER_SECONDS[role] / 3)
    research_deadline = deadline - report_reserve
    writing_report = False
    callback = current_trajectory_callback(role)
    config = {"callbacks": [callback]} if callback else {}
    calls: Counter = Counter()
    seen: set[str] = set()
    tools_by_name = {tool.name: tool for tool in tools}
    if not tools_by_name.keys() <= TOOL_LIMITS[role].keys():
        raise ValueError("Worker에 허용되지 않은 Tool이 연결됐습니다.")

    async def within(awaitable, seconds):
        remaining = (deadline if writing_report else research_deadline) - time.monotonic()
        try:
            return await asyncio.wait_for(awaitable, timeout=max(0, min(seconds, remaining)))
        except TimeoutError:
            raise TimeoutError("Worker 실행 시간 한도 도달") from None

    async def execute(name: str, args: dict) -> dict:
        signature = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
        remaining = research_deadline - time.monotonic()
        if (name not in tools_by_name or sum(calls.values()) >= TOTAL_CALLS[role]
                or calls[name] >= TOOL_LIMITS[role].get(name, 0) or signature in seen or remaining <= 0):
            ledger.limitations.append("허용되지 않은 호출·호출 한도·동일 인자 반복 중 하나를 차단")
            return {"status": "unavailable", "evidence": [], "reason": "호출을 종료하고 확보한 근거로 보고"}
        calls[name] += 1
        seen.add(signature)
        tool = tools_by_name[name]
        try:
            seconds = 480 if name == "search_disclosure_evidence" else 90
            with external_call_scope(min(seconds, remaining)):
                raw = await within(tool.ainvoke(args, config=config), seconds)
            result = json.loads(raw) if isinstance(raw, str) else raw
            return ledger.accept(result)
        except (requests.RequestException, httpx.HTTPError, OpenAIError, OSError, TimeoutError) as exc:
            error = {"code": type(exc).__name__, "message": f"{name} 실행 실패. 인증·연결·시간 한도 확인 필요", "retryable": False}
            ledger.failures.append(error)
            return {"status": "error", "evidence": [], "error": error}

    try:
        payload = worker_input(state, role)
        system = build_system_prompt(role)
        messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        if collect is not None:
            with external_call_scope(max(0, min(90, research_deadline - time.monotonic()))):
                result = await within(asyncio.to_thread(collect, state["research_mandate"]), 90)
            ledger.accept(result)
        elif role == "technical":
            await execute("get_technical_evidence", {})
        else:
            model = get_chat_model("worker").bind_tools(tools)
            for _ in range(MODEL_STEPS):
                if time.monotonic() >= research_deadline:
                    ledger.limitations.append("조사 시간 한도 도달, 남겨둔 보고서 예산으로 확보 근거 정리")
                    break
                if sum(calls.values()) >= TOTAL_CALLS[role]:
                    ledger.limitations.append("조사 호출 한도 도달, 확보한 자료 범위로 보고")
                    break
                try:
                    response = await within(model.ainvoke(messages, config=config), MODEL_SECONDS)
                except (TimeoutError, OpenAIError, httpx.HTTPError) as exc:
                    ledger.limitations.append("조사 모델 호출 실패 또는 시간 한도 도달, 확보한 근거로 보고")
                    ledger.failures.append({"code": type(exc).__name__, "message": "조사 모델 연결·시간 한도 확인 필요", "retryable": False})
                    break
                messages.append(response)
                if not response.tool_calls:
                    break
                for call in response.tool_calls:
                    result = await execute(call["name"], call["args"])
                    messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]))
            else:
                ledger.limitations.append("모델 조사 판단 6회 한도 도달")

        if not ledger.items:
            if ledger.failures:
                failure = ledger.failures[0]
                report = WorkerError(agent=role, code=str(failure.get("code", "tool_error")),
                                     message=str(failure.get("message", "자료 수집 실행 실패")),
                                     retryable=bool(failure.get("retryable", False)))
            else:
                report = WorkerReport(agent=role, status="unavailable", findings=[], evidence=[],
                    unanswered_questions=[{"question_index": i, "reason": "기준일에 사용 가능한 근거 미확보"}
                                          for i in range(len(task.questions))],
                    limitations=list(dict.fromkeys(ledger.limitations)))
            return {f"{role}_report": report}

        writing_report = True
        report_prompt = (
            "조사는 종료되었습니다. 제공한 Evidence만 사용하여 WorkerDraft를 작성하세요. "
            "질문 번호는 task.questions의 0부터 시작합니다. 모든 질문을 findings 또는 unanswered_questions에 포함하세요. "
            "각 finding은 실제 evidence_id를 하나 이상 인용해야 합니다. 근거 없는 사실·가정은 만들지 말고 미확인으로 표시하세요. "
            "부분 답변 질문은 findings와 unanswered_questions 양쪽에 포함할 수 있습니다. "
            "complete는 모든 질문·완료 기준 충족, partial은 일부 답변과 미확인 질문 모두 존재, "
            "unavailable은 답변 없이 모든 질문이 미확인일 때 사용하세요. 지표만으로 매수 우위·추세 전환을 단정하지 마세요."
        )
        # Responses 스트림은 유효한 JSON 본문만 주고 SDK의 parsed 메타데이터를
        # 생략할 수 있다. JSON Schema를 전송하고 본문 파싱 후 아래에서 Pydantic 검증.
        draft_model = get_chat_model("worker").with_structured_output(
            WorkerDraft.model_json_schema(), method="json_schema", strict=True)
        draft = await within(draft_model.ainvoke([
            SystemMessage(content=system + "\n\n" + report_prompt),
            HumanMessage(content=json.dumps({**payload, "evidence": [e.model_dump() for e in ledger.items.values()],
                "limitations": ledger.limitations, "collection_errors": ledger.failures}, ensure_ascii=False))
        ], config=config), MODEL_SECONDS)
        report = finish_report(role, task, WorkerDraft.model_validate(draft), ledger)
    except (ValidationError, ValueError, KeyError, requests.RequestException, httpx.HTTPError,
            OpenAIError, OSError, TimeoutError) as exc:
        report = WorkerError(agent=role, code=type(exc).__name__,
                             message="조사·보고서 생성 실패. 입력 계약·연결·시간 한도 확인 필요", retryable=False)
    return {f"{role}_report": report}
