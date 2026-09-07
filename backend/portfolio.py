"""로컬 개인용 포트폴리오 조회·진단 API. 계좌 데이터는 캐시·로그로 저장하지 않는다."""

from urllib.parse import urlparse
import os
import logging

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from stock_agent.portfolio.service import PortfolioExecutionError, diagnose_portfolio
from stock_agent.vendors import toss_client


def require_local(request: Request, response: Response) -> None:
    """Request의 접속 주소·Host·Origin을 로컬로 제한하고 응답 캐싱을 금지한다.

    개인 계좌를 서비스하는 인증 없는 초기 API의 외부 접근을 403으로 거부한다.
    프록시 뒤 공개 배포를 위한 사용자 인증을 대체하지 않는다.
    """
    local = {"localhost", "127.0.0.1", "::1"}
    origin = request.headers.get("origin")
    if (not request.client or request.client.host not in local
            or request.url.hostname not in local
            or (origin is not None and urlparse(origin).hostname not in local)):
        raise HTTPException(403, "포트폴리오 API는 로컬 개인 실행에서만 사용할 수 있습니다.")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/portfolio", dependencies=[Depends(require_local)])
logger = logging.getLogger(__name__)


@router.get("/configuration")
def configuration() -> dict:
    """키 존재 여부만 반환한다. 인자·외부 호출·계좌 조회·비밀 반환은 없다."""
    return {"configured": all(os.environ.get(key, "").strip() for key in ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"))}


class PortfolioRequest(BaseModel):
    """진단 대상 계좌와 원본 질문. 계좌 식별자는 LLM에 전달하지 않는다."""

    account_seq: int | None = Field(default=None, gt=0)
    message: str = Field(default="내 보유 주식의 집중도를 진단해줘", min_length=1, max_length=300)


@router.get("/accounts")
def list_accounts() -> dict:
    """Toss 계좌 목록을 읽고 계좌번호 없이 선택용 ID·유형만 반환한다.

    키가 없으면 configured=false로 반환하고 외부 호출하지 않는다.
    인증·조회 실패는 민감한 원문 없이 502로 반환한다.
    """
    if not all(os.environ.get(key, "").strip() for key in ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET")):
        return {"configured": False, "accounts": []}
    try:
        return {"configured": True, "accounts": [
            {"account_seq": item["accountSeq"], "account_type": item["accountType"]}
            for item in toss_client.get_accounts() if item["accountType"] == "BROKERAGE"
        ]}
    except KeyError:
        raise HTTPException(503, "Toss 설정 또는 응답 필드를 확인하세요.") from None
    except (requests.RequestException, ValueError):
        raise HTTPException(502, "계좌 조회에 실패했습니다. Toss 인증·허용 IP를 확인하세요.") from None


@router.post("/diagnose")
def diagnose(request: PortfolioRequest) -> dict:
    """선택 계좌의 독립 진단 보고서를 반환한다. 외부 조회와 유료 LLM 호출을 수행한다.

    공백 질문은 422로 거부한다. 실행 경계에서 공급자 오류 원문과 계좌 정보의 노출을
    막기 위해 실패 응답을 정제하며, 종목 조사 Graph·Trajectory에는 연결하지 않는다.
    """
    if not request.message.strip():
        raise HTTPException(422, "질문을 입력하세요.")
    try:
        return diagnose_portfolio(request.account_seq, request.message.strip())
    except PortfolioExecutionError as error:
        logger.warning("Portfolio failed stage=%s type=%s upstream_status=%s",
                       error.stage, error.error_type, error.upstream_status)
        code = 429 if error.upstream_status == 429 else 502
        hint = "호출 제한입니다. 잠시 후 다시 시도하세요." if code == 429 else "인증·연결·모델 설정을 확인하세요."
        raise HTTPException(code, f"{error.stage} 단계 실패 (상태: {error.upstream_status or '확인 불가'}). {hint}") from None
    except ValueError:
        raise HTTPException(422, "계좌 선택·지원 대상 잔고 또는 AI 업종 분류 결과를 확인하세요.") from None
    except KeyError:
        raise HTTPException(503, "API 설정 또는 공급자 응답 필드를 확인하세요.") from None
    except Exception as error:
        logger.warning("Portfolio failed stage=processing type=%s", type(error).__name__)
        # 개인 계좌를 다루는 외부 실행 경계: 공급자 예외 원문을 반환·로그하지 않는다.
        raise HTTPException(502, "진단에 실패했습니다. Toss·LLM 연결 설정을 확인한 뒤 다시 시도하세요.") from None
