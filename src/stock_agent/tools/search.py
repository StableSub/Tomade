"""LLM용 웹 검색 tool."""

from typing import Annotated

from langchain_core.tools import tool

from stock_agent.vendors import tavily_client


@tool
def search_web(
    query: Annotated[str, "검색어. 종목명과 이슈 키워드를 조합하면 좋음 (예: '삼성전자 자기주식 취득')"],
    max_results: Annotated[int, "가져올 결과 수. 기본값 5 권장"] = 5,
) -> str:
    """Tavily로 뉴스와 웹 자료를 검색해 사건·시장·산업 근거를 수집한다.

    Args:
        query: 종목명과 조사 주제를 포함한 구체적인 검색어.
        max_results: 반환할 최대 검색 결과 수.

    Returns:
        결과별 제목·URL·본문 요약이 포함된 마크다운 문자열. 결과가 없거나 API
        호출이 실패하면 예외 대신 검색어 수정 또는 재시도 방법을 설명하는
        문자열을 반환한다.
    """
    try:
        # vendor에 실제 검색을 위임 (tool은 인터페이스 역할만)
        results = tavily_client.search_web(query, max_results=max_results)
    except Exception as e:
        # 예외가 그래프로 새면 전체 실행이 죽으므로,
        # 원인 요약 + 재시도 힌트를 LLM에게 전달한다
        return f"검색 중 오류가 발생했습니다 ({type(e).__name__}). 잠시 후 같은 검색어로 재시도하거나, 다른 키워드를 사용하세요."

    # 결과가 없으면 LLM이 스스로 재시도할 수 있도록 안내 메시지를 반환
    # (예외를 던지면 LLM이 대응을 못 하므로, 항상 문자열로 응답)
    if not results:
        return "검색 결과가 없습니다. 키워드를 단순화하거나 다른 표현으로 재시도하세요."

    # dict 목록을 LLM이 읽기 좋은 마크다운 형식으로 변환
    # (본문은 토큰 절약을 위해 앞부분만 잘라 사용)
    lines = []
    for r in results:
        lines.append(f"### {r['title']}\n출처: {r['url']}\n{r['content'][:300]}")

    return "\n\n".join(lines)
