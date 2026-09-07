"""LLM용 공시·재무 조회 tool."""

from typing import Annotated

from langchain_core.tools import tool

from stock_agent.vendors import dart_client


@tool
def get_disclosure(
    corp_name: Annotated[str, "정확한 한국 회사명 (예: '삼성전자', 'SK하이닉스')"],
    days: Annotated[int, "조회할 기간(일). 기본값 30"] = 30,
) -> str:
    """DART에서 기업의 최근 공시를 조회해 공식 사건과 변화를 확인한다.

    Args:
        corp_name: DART 회사 목록에서 식별 가능한 정확한 한국 회사명.
        days: 오늘을 기준으로 조회할 기간의 일수.

    Returns:
        공시 날짜·제목·원문 URL을 담은 마크다운 문자열. 공시가 없으면 그 사실을
        명시하고, 회사 식별이나 API 호출이 실패하면 예외 대신 재시도 안내가
        포함된 오류 문자열을 반환한다.
    """
    try:
        # vendor 내부에서 회사명 → 고유번호 변환과 API 호출을 모두 처리
        disclosures = dart_client.get_disclosures(corp_name, days=days)
    except ValueError:
        # 회사를 못 찾은 경우: LLM이 이름을 고쳐서 재시도할 수 있게 안내
        return f"DART에서 '{corp_name}'을 찾을 수 없습니다. 법인명 전체로 다시 시도하세요 (예: '삼성전자' → '삼성전자' 확인, 'LG전자')."
    except Exception as e:
        return f"공시 조회 중 오류가 발생했습니다 ({type(e).__name__}). 잠시 후 재시도하세요."

    if not disclosures:
        return f"'{corp_name}'의 최근 {days}일간 공시가 없습니다. 기간을 늘려 재시도할 수 있습니다."

    # LLM이 읽기 좋은 목록 형식으로 변환. 각 항목에 공시 원문 URL을 출처로 포함
    lines = [f"'{corp_name}' 최근 {days}일간 공시 {len(disclosures)}건:"]
    for d in disclosures:
        lines.append(f"- [{d['date']}] {d['title']} (출처: {d['url']})")

    return "\n".join(lines)
