"""LangGraph에서 공유하는 입력, 계획, 전문 Agent 산출물 정의."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

AgentName = Literal["business", "macro_sector", "event_catalyst", "technical", "sentiment"]
WORKER_NAMES = ("business", "macro_sector", "event_catalyst", "technical", "sentiment")


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
    investment_horizon: str | None = Field(default=None, description="사용자가 밝힌 투자 기간. 자료 조회 기간과 구분, 없으면 null")
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
    corp_code: str
    as_of_date: str
    period_days: int
    query_start_date: str
    query_end_date: str
    investment_horizon: str | None
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

    @field_validator("objective")
    @classmethod
    def nonempty_objective(cls, value: str) -> str:
        """공백뿐인 배정 목표를 거부한다."""
        if not value.strip():
            raise ValueError("배정 목표는 비어 있을 수 없습니다.")
        return value.strip()

    @field_validator("questions", "completion_criteria")
    @classmethod
    def nonempty_items(cls, values: list[str]) -> list[str]:
        """목록 길이가 있어도 내용이 빈 질문·완료 기준은 거부한다."""
        if any(not value.strip() for value in values):
            raise ValueError("질문·완료 기준은 비어 있을 수 없습니다.")
        return [value.strip() for value in values]


class ResearchPlan(BaseModel):
    """Planning Agent가 생성하는 구조화된 조사 계획."""

    planning_summary: str = Field(description="Agent 선택과 조사 방향에 대한 짧은 설명")
    tasks: list[ResearchTask] = Field(
        min_length=1,
        description="활성화할 전문 Agent와 배정할 작업",
    )


class Evidence(BaseModel):
    """코드가 확보한 원문·수치·댓글과 출처. 모델이 생성하는 출력이 아니다."""

    evidence_id: str = Field(min_length=1)
    kind: Literal["excerpt", "metric", "comment"]
    content: str | dict[str, Any]
    source: dict[str, Any]
    published_at: str | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    retrieved_at: str
    limitations: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """질문 하나에 대한 판단과 실제 확보한 근거의 참조."""

    model_config = ConfigDict(extra="forbid")
    question_index: int = Field(ge=0)
    statement: str = Field(min_length=1)
    kind: Literal["fact", "inference"]
    evidence_ids: list[str] = Field(min_length=1)


class UnansweredQuestion(BaseModel):
    """미확인 또는 부분 답변 질문과 이유."""

    model_config = ConfigDict(extra="forbid")
    question_index: int = Field(ge=0)
    reason: str = Field(min_length=1)


class WorkerDraft(BaseModel):
    """모델이 작성하는 판단 부분. 원본 Evidence는 코드가 별도로 붙인다."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["complete", "partial", "unavailable"]
    findings: list[Finding]
    unanswered_questions: list[UnansweredQuestion]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_status(self):
        """완료 상태와 답변·미확인 항목의 구조적 모순을 거부한다."""
        if self.status == "complete" and (self.unanswered_questions or not self.findings):
            raise ValueError("complete에는 근거 있는 답변이 필요하고 미확인 질문이 없어야 합니다.")
        if self.status == "partial" and (not self.findings or not self.unanswered_questions):
            raise ValueError("partial에는 일부 답변과 미확인 질문이 모두 필요합니다.")
        if self.status == "unavailable" and (self.findings or not self.unanswered_questions):
            raise ValueError("unavailable에는 답변 대신 미확인 질문을 기록해야 합니다.")
        return self


class WorkerReport(WorkerDraft):
    """검증된 판단과 코드가 보존한 인용 근거를 종합 단계에 전달한다."""

    agent: AgentName
    evidence: list[Evidence]


class WorkerError(BaseModel):
    """정상적인 자료 부족과 구분하는 Worker 실행 실패."""

    agent: AgentName
    status: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False


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
    business_report: WorkerReport | WorkerError
    macro_sector_report: WorkerReport | WorkerError
    event_catalyst_report: WorkerReport | WorkerError
    technical_report: WorkerReport | WorkerError
    sentiment_report: WorkerReport | WorkerError

    # 사용자용 최종 산출물
    final_answer: str
