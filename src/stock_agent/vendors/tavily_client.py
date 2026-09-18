"""Tavily의 검색·원문 추출 API와 안전한 오류 경계."""

import os

import requests
from dotenv import load_dotenv
from tavily import TavilyClient
from tavily.errors import (
    BadRequestError, ForbiddenError, InvalidAPIKeyError, TimeoutError,
    UsageLimitExceededError,
)

load_dotenv()
_client: TavilyClient | None = None


class TavilyError(RuntimeError):
    """키·응답 본문·요청 URL을 노출하지 않는 외부 연동 오류."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        key = os.getenv("TAVILY_API_KEY", "").strip()
        if not key:
            raise TavilyError("missing_credentials", "TAVILY_API_KEY 설정 필요")
        _client = TavilyClient(api_key=key, api_base_url="https://api.tavily.com")
    return _client


def _request(method: str, **kwargs) -> dict:
    try:
        result = getattr(_get_client(), method)(**kwargs, timeout=15)
    except InvalidAPIKeyError:
        raise TavilyError("auth_error", "Tavily 인증 설정 확인 필요") from None
    except (ForbiddenError, UsageLimitExceededError):
        raise TavilyError("quota_or_access_error", "Tavily 이용 한도·접근 권한 확인 필요") from None
    except BadRequestError:
        raise TavilyError("invalid_request", "Tavily 요청 조건 확인 필요") from None
    except (TimeoutError, requests.RequestException):
        raise TavilyError("network_error", "Tavily 요청 실패. 연결 상태 확인 후 재시도 가능", True) from None
    except ValueError:
        raise TavilyError("invalid_response", "Tavily 응답 형식 확인 필요") from None
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise TavilyError("invalid_response", "Tavily 결과 목록 형식 확인 필요")
    if any(not isinstance(item, dict) for item in result["results"]):
        raise TavilyError("invalid_response", "Tavily 결과 항목 형식 확인 필요")
    return result


def search_web(
    query: str, max_results: int = 5, *, start_date: str, end_date: str,
) -> list[dict]:
    """고정 조회 기간의 검색 후보를 최대 5개 반환한다.

    Args:
        query: 조사 검색어.
        max_results: 1~5개의 결과 수.
        start_date: 포함할 시작일. Tool에서 검증된 ISO 날짜.
        end_date: 포함할 종료일. Tool에서 검증된 ISO 날짜.

    Returns:
        제목·URL·검색 발췌·제공처 추정 공개일을 가진 후보 목록. 무일자 결과도
        남겨 Tool이 제외 사유를 보고한다. 날짜의 최종 검증은 Tool에서 수행한다.

    Raises:
        TavilyError: 인증·한도·통신·응답 형식 오류. 자동 재시도 없음.
    """
    # API의 날짜 경계와 시간대 해석 차이는 Tool의 KST 필터로 다시 검증한다.
    from datetime import date, timedelta
    response = _request(
        "search", query=query, max_results=max(1, min(max_results, 5)),
        topic="general", search_depth="basic", chunks_per_source=3,
        start_date=(date.fromisoformat(start_date) - timedelta(days=1)).isoformat(),
        end_date=(date.fromisoformat(end_date) + timedelta(days=1)).isoformat(),
        include_published_date=True, filter_by_published_date=False,
        include_answer=False, include_raw_content=False,
    )
    return [{
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "content": str(item.get("content") or ""),
        "published_date": item.get("published_date"),
    } for item in response["results"][:5]]


def extract_web(urls: list[str], query: str) -> dict:
    """검색 후보 최대 3개의 원문에서 질문 관련 발췌를 확보한다.

    Args:
        urls: Tool이 검색 결과에서 선택·검증한 URL 목록.
        query: 원문 청크 관련성 정렬에 사용할 조사 검색어.

    Returns:
        results의 URL·raw_content와 failed_results를 가진 응답. 질문 관련
        원문 3개 청크를 요청하며 임의 URL을 로컬 서버가 직접 방문하지 않는다.

    Raises:
        TavilyError: 인증·통신·응답 오류. 자동 재시도 없음.
    """
    if not urls:
        return {"results": [], "failed_results": []}
    return _request(
        "extract", urls=urls[:3], query=query, chunks_per_source=3,
        extract_depth="basic", format="text", include_images=False,
    )
