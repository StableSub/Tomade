"""LangGraph에서 공유하는 입력, 계획, 전문 Agent 산출물 정의."""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

AgentName = Literal["business", "macro_sector", "event_catalyst"]


class ParsedRequest(BaseModel):
    """Request Parsing LLM이 단일 사용자 문장에서 추출한 후보 정보."""

    company_candidates: list[str] = Field(
        default_factory=list,
        description="입력에서 식별한 정식 상장 회사명 후보",
    )
    research_question: str = Field(
        description="회사명·날짜·기간 표현을 정리한 실제 조사 질문",
    )
    as_of_date: str | None = Field(
        default=None,
        description="명시된 ISO 분석 기준일. 없으면 null",
    )
    period_days: int | None = Field(
        default=None,
        description="명시된 분석 기간을 일수로 변환한 값. 없으면 null",
    )
    needs_clarification: bool = Field(
        default=False,
        description="복수 종목이나 모호한 입력으로 사용자 확인이 필요한지 여부",
    )
    clarification_reason: str | None = Field(
        default=None,
        description="확인이 필요한 이유. 필요하지 않으면 null",
    )


class ResearchMandate(TypedDict):
    """모든 전문 Agent가 공유하는 동적 분석 조건."""

    original_question: str
    research_question: str
    ticker: str
    corp_name: str
    as_of_date: str
    period_days: int
    purpose: str
    constraints: list[str]


class ResearchTask(BaseModel):
    """Planning Agent가 전문 Agent 하나에 배정하는 조사 작업."""

    agent: AgentName
    objective: str = Field(description="해당 Agent가 달성해야 할 조사 목표")
    questions: list[str] = Field(
        min_length=1,
        description="Agent가 반드시 답해야 할 핵심 조사 질문",
    )
    completion_criteria: list[str] = Field(
        min_length=1,
        description="조사가 완료됐다고 판단할 수 있는 기준",
    )


class ResearchPlan(BaseModel):
    """Planning Agent가 생성하는 구조화된 조사 계획."""

    planning_summary: str = Field(description="Agent 선택과 조사 방향에 대한 짧은 설명")
    tasks: list[ResearchTask] = Field(
        min_length=1,
        description="활성화할 전문 Agent와 배정할 작업",
    )


class StockAgentState(TypedDict, total=False):
    """각 노드가 필요한 필드를 읽고 자신의 산출물만 병합하는 공유 상태."""

    # 사용자 요청과 Parser 산출물
    memory_enabled: bool
    short_term_summary: str
    recent_messages: list[tuple[str, str]]
    raw_user_input: str
    intent: Literal["general", "research"]
    research_only: bool
    run_id: str
    parsed_request: ParsedRequest
    input_error: str
    research_mandate: ResearchMandate
    research_plan: ResearchPlan

    # 전문 Agent 산출물
    business_report: str
    macro_sector_report: str
    event_catalyst_report: str

    # 사용자용 최종 산출물
    final_answer: str
