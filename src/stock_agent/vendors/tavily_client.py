"""Tavily 웹 검색 클라이언트."""

import os

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    """환경변수의 API 키로 TavilyClient를 한 번 생성해 재사용한다."""
    global _client
    if _client is None:
        api_key = os.environ["TAVILY_API_KEY"]
        _client = TavilyClient(api_key=api_key)
    return _client


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Tavily 웹 검색 결과를 Vendor 공통 형식으로 정규화한다.

    Args:
        query: Tavily에 전달할 검색어.
        max_results: 요청할 최대 검색 결과 수.

    Returns:
        제목·URL·본문 요약을 가진 딕셔너리 목록. 결과가 없으면 빈 목록.

    Raises:
        Tavily SDK의 인증·네트워크·응답 오류를 그대로 전달한다. Tool 계층이
        이를 예외가 아닌 재시도 안내 문자열로 변환한다.
    """
    response = _get_client().search(query, max_results=max_results)
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
