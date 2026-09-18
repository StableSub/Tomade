"""검증된 조사 조건에 묶인 웹 검색 및 원문 근거 Tool."""

import ipaddress
import json
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from stock_agent.vendors import tavily_client

_KST = ZoneInfo("Asia/Seoul")


def _publication_date(value: object) -> tuple[str | None, date | None]:
    """Tavily ISO/RFC 날짜를 보존하고 KST 기준 비교 날짜를 반환한다."""
    if not isinstance(value, str) or not value.strip():
        return None, None
    try:
        if len(value) == 10:
            parsed_day = date.fromisoformat(value)
            return parsed_day.isoformat(), parsed_day
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            return None, None
        return stamp.isoformat(), stamp.astimezone(_KST).date()
    except (TypeError, ValueError, OverflowError):
        return None, None


def _public_url(url: str) -> bool:
    """공개 HTTP URL만 Extract에 전달한다. 직접 HTTP 요청은 하지 않는다."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def make_web_search_tool(mandate: dict):
    """회사 조사 기간을 코드로 고정한 search_web Tool을 생성한다.

    Args:
        mandate: 검증된 as_of_date·period_days 또는 query_start_date·query_end_date.

    Returns:
        검색어와 결과 수만 모델에 노출하는 Tool. JSON 문자열에 근거·제외 사유·
        한계를 반환하고 외부 오류를 안전한 error로 전달한다. 생성 시 네트워크 없음.
    """
    conditions = dict(mandate)

    @tool
    def search_web(query: str, max_results: int = 5) -> str:
        """정책·산업·사건의 웹 근거와 질문 관련 원문 발췌를 검색한다.

        Args:
            query: 조사 질문을 반영한 구체적인 검색어. 1~500자.
            max_results: 검색 후보 수. 1~5개, 원문 조회는 상위 3개 한도.

        Returns:
            JSON 형식의 근거·출처·추정 공개일·수집일·원문 확보 여부. 조사 기간은
            코드로 고정되며 공개일 불명·기간 밖 결과는 제외. search_snippet은 원문
            확인이 아니고, 추정 공개일과 현재 본문은 과거 당시 본문을 보장하지 않음.
            인증·통신 오류는 error로 반환하며 자료 없음과 구분. 자동 재시도 없음.
        """
        result = {"status": "unavailable", "evidence": [], "limitations": [],
                  "excluded_sources": [], "error": None}
        try:
            as_of = date.fromisoformat(conditions["as_of_date"])
            end = date.fromisoformat(conditions.get("query_end_date") or as_of.isoformat())
            days = int(conditions["period_days"])
            start = date.fromisoformat(conditions.get("query_start_date") or (
                end - timedelta(days=days - 1)).isoformat())
            if not query.strip() or len(query) > 500 or not 1 <= max_results <= 5:
                raise ValueError("invalid query")
            if not 1 <= days <= 3650 or start > end or end > as_of or as_of > datetime.now(_KST).date():
                raise ValueError("invalid period")
        except (KeyError, TypeError, ValueError, OverflowError):
            result.update(status="error", error={"code": "invalid_input", "message": "검증된 날짜·조회 기간과 검색어(1~500자)·결과 수(1~5) 확인 필요", "retryable": False})
            return json.dumps(result, ensure_ascii=False)
        result.update(query=query, query_start_date=start.isoformat(), query_end_date=end.isoformat())
        try:
            candidates = tavily_client.search_web(
                query, max_results=max_results, start_date=start.isoformat(), end_date=end.isoformat(),
            )
        except tavily_client.TavilyError as exc:
            result.update(status="error", error={"code": exc.code, "message": exc.message, "retryable": exc.retryable})
            return json.dumps(result, ensure_ascii=False)
        eligible, seen = [], set()
        for item in candidates[:max_results]:
            url = item["url"]
            published_at, published_day = _publication_date(item.get("published_date"))
            reason = None
            if not _public_url(url):
                reason = "invalid_public_url"
            elif published_day is None:
                reason = "publication_date_unknown"
            elif not start <= published_day <= end:
                reason = "publication_date_outside_period"
            if reason:
                result["excluded_sources"].append({"url": url, "reason": reason})
            elif url not in seen:
                seen.add(url)
                eligible.append({**item, "published_at": published_at})
        extracted = {}
        extract_error = None
        if eligible:
            try:
                response = tavily_client.extract_web([item["url"] for item in eligible[:3]], query)
                for item in response["results"]:
                    if isinstance(item.get("raw_content"), str) and item["raw_content"].strip():
                        extracted[item.get("url")] = item["raw_content"].strip()[:1600]
            except tavily_client.TavilyError as exc:
                extract_error = {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
                result["limitations"].append("original_extraction_failed: " + exc.message)
        call_id = uuid4().hex
        for index, item in enumerate(eligible):
            original = extracted.get(item["url"])
            body = original or item["content"][:1600]
            if not body.strip():
                result["excluded_sources"].append({"url": item["url"], "reason": "empty_content"})
                continue
            limits = ["공개일은 제공처의 게시일 또는 수정일 추정값", "현재 확보한 본문의 과거 당시 버전은 미검증"]
            if original is None:
                limits.append("원문 미확보. 검색 발췌만으로 사실·인과 확정 금지")
            result["evidence"].append({
                "evidence_id": f"web:{call_id}:{index}", "kind": "excerpt",
                "content": body,
                "source": {"provider": "Tavily", "url": item["url"], "title": item["title"],
                           "retrieval_type": "original_excerpt" if original else "search_snippet",
                           "publication_date_basis": "tavily_estimate", "point_in_time_verified": False},
                "published_at": item["published_at"], "observation_start": None,
                "observation_end": None, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "limitations": limits,
            })
        if result["evidence"]:
            partial = result["excluded_sources"] or any(
                e["source"]["retrieval_type"] == "search_snippet" for e in result["evidence"])
            result["status"] = "partial" if partial else "complete"
        elif extract_error:
            result.update(status="error", error=extract_error)
        if result["excluded_sources"]:
            result["limitations"].append("공개일 불명·조회 기간 밖·내용 없는 후보는 근거에서 제외")
        result["limitations"].append("공식 지표의 관측 기간은 자동 확인하지 않음. 본문에서 별도 확인 필요")
        return json.dumps(result, ensure_ascii=False)

    return search_web
