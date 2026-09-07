"""포트폴리오 입력과 AI 구조화 출력 스키마."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


Sector = Literal[
    "정보기술", "커뮤니케이션", "경기소비재", "필수소비재", "금융", "산업재",
    "소재", "에너지", "헬스케어", "유틸리티", "부동산", "미분류",
]


class SectorAssignment(BaseModel):
    """공식 분류가 아닌 회사별 대표 업종 추정."""

    symbol: str
    sector: Sector
    reason: str = Field(min_length=1, max_length=300)


class SectorAssignments(BaseModel):
    """입력 종목당 정확히 하나를 요구하는 분류 결과."""

    items: list[SectorAssignment]


class PortfolioExplanation(BaseModel):
    """수치 표와 분리해 표시할 AI 해설."""

    summary: str = Field(min_length=1, max_length=2000)
    observations: list[str] = Field(max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=5)


class Holding(BaseModel):
    """계좌 식별자 없이 계산용 원화 평가금액·매입금액을 보존한다."""

    symbol: str
    name: str
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    purchase_amount: Decimal = Field(ge=0, allow_inf_nan=False)
