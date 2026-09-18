"""YouTube 댓글 표본을 준비하는 일반 Python 수집기. LLM Tool로 노출하지 않음."""

import re
import unicodedata
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from itertools import zip_longest
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

from stock_agent.vendors import youtube_client

_KST = ZoneInfo("Asia/Seoul")
_FINANCE_TERMS = (
    "주가", "주식", "투자", "실적", "배당", "증시", "매수", "매도", "상승", "하락",
    "수익", "손실", "보유", "물렸", "존버", "stock", "invest",
)


def _normalized(text: str) -> str:
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", text).casefold())


def _timestamp(value: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def collect_sentiment_evidence(mandate: dict) -> dict:
    """선정한 종목 관련 YouTube 영상의 댓글 표본을 수집한다.

    Args:
        mandate: 검증된 corp_name·ticker·as_of_date·period_days와 선택적 조회 기간.

    Returns:
        공통 status/evidence/limitations/error와 표본 수·영상·선정 기준을 가진
        dict. 영상 검색 1회, 최대 3개 영상마다 최신순 25개씩 2페이지 한도.
        댓글 작성일로 기간을 적용하고 기준일 이후 수정·중복·무관 댓글 제외.
        영상별 균등 순회로 40개, 댓글당 600자까지 모델에 전달. 댓글 내용을
        감정 점수나 전체 투자자 심리로 변환하지 않는다.

    Side effects:
        YOUTUBE_API_KEY를 사용하는 공개 API 조회. Tool 반복·자동 재시도 없음.
        인증·통신 실패는 error, 정상 조회의 자료 부족은 unavailable/partial로
        반환하며 중립 감정으로 대체하지 않는다.
    """
    result = {
        "status": "unavailable", "evidence": [], "limitations": [
            "선정한 YouTube 영상 댓글 표본의 반응. 전체 투자자·실제 주주 대표성 없음",
            "현재 검색 순위와 현재 공개된 댓글의 표본. 삭제·숨김 댓글과 답글 제외",
            "회사·금융 키워드 규칙은 무관 댓글 혼입과 관련 댓글 누락 가능",
        ], "error": None, "sample_count": 0, "scanned_comment_count": 0,
        "selected_videos": [], "excluded_counts": {},
        "selection_criteria": {
            "video_search": "회사명 + 주가, 관련성순 후보 10개",
            "video_relevance": "제목에 회사명 또는 종목코드, 제목·설명에 금융 키워드",
            "max_videos": 3, "max_comments_per_video": 50, "max_pages_per_video": 2,
            "page_size": 25, "max_model_comments": 40, "max_comment_characters": 600,
            "sampling": "영상별 최신 댓글을 한 개씩 번갈아 선택",
            "comment_relevance": "댓글의 회사명·종목코드 또는 금융 키워드",
            "date_basis": "댓글 publishedAt, 기준일 이후 updatedAt 댓글 제외",
        },
    }
    try:
        company = mandate["corp_name"].strip()
        ticker = mandate["ticker"]
        as_of = date.fromisoformat(mandate["as_of_date"])
        end = date.fromisoformat(mandate.get("query_end_date") or as_of.isoformat())
        days = int(mandate["period_days"])
        start = date.fromisoformat(mandate.get("query_start_date") or (
            end - timedelta(days=days - 1)).isoformat())
        if not company or not re.fullmatch(r"\d{6}", ticker):
            raise ValueError("invalid company")
        if not 1 <= days <= 3650 or start > end or end > as_of or as_of > datetime.now(_KST).date():
            raise ValueError("invalid period")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        result.update(status="error", error={"code": "invalid_input", "message": "검증된 회사·종목·조회 날짜 확인 필요", "retryable": False})
        return result
    lower = datetime.combine(start, time.min, _KST)
    upper = datetime.combine(end + timedelta(days=1), time.min, _KST)
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min, _KST)
    result.update(query_start_date=start.isoformat(), query_end_date=end.isoformat())
    try:
        candidates = youtube_client.search_videos(
            f"{company} 주가", published_before=upper.astimezone(timezone.utc).isoformat(), max_results=10,
        )
    except youtube_client.ProviderError as exc:
        result.update(status="error", error={"code": exc.code, "message": exc.message, "retryable": exc.retryable})
        return result
    aliases = [_normalized(company.replace("주식회사", "").replace("(주)", "")), ticker]
    aliases = [alias for alias in aliases if alias]
    selected, video_ids = [], set()
    for video in candidates[:10]:
        title = _normalized(video["title"])
        topic = _normalized(video["title"] + " " + video["description"])
        stamp = _timestamp(video["published_at"])
        if (stamp is None or stamp >= upper or video["video_id"] in video_ids
                or not any(alias in title for alias in aliases)
                or not any(term in topic for term in _FINANCE_TERMS)):
            continue
        selected.append(video)
        video_ids.add(video["video_id"])
        if len(selected) == 3:
            break
    result["selected_videos"] = [{"video_id": v["video_id"], "title": v["title"],
                                  "url": v["url"], "published_at": v["published_at"]} for v in selected]
    excluded = Counter()
    by_video, seen_ids, seen_texts, failures = [], set(), set(), []
    page_limited = False
    for video in selected:
        accepted, token = [], None
        scanned_for_video = 0
        for _page in range(2):
            try:
                page = youtube_client.list_comments(video["video_id"], page_token=token, max_results=25)
            except youtube_client.ProviderError as exc:
                failures.append({"video_id": video["video_id"], "code": exc.code,
                                 "message": exc.message, "retryable": exc.retryable})
                break
            for comment in page["items"][:min(25, 50 - scanned_for_video)]:
                scanned_for_video += 1
                result["scanned_comment_count"] += 1
                published, updated = _timestamp(comment["published_at"]), _timestamp(comment["updated_at"])
                body = comment["text"].strip()
                normalized = _normalized(body)
                if published is None or updated is None:
                    excluded["unknown_timestamp"] += 1
                elif not lower <= published < upper:
                    excluded["outside_period"] += 1
                elif updated >= cutoff:
                    excluded["updated_after_as_of"] += 1
                elif comment["comment_id"] in seen_ids or normalized in seen_texts:
                    excluded["duplicate"] += 1
                elif len(normalized) < 3:
                    excluded["empty_or_short"] += 1
                else:
                    company_match = any(alias in normalized for alias in aliases)
                    finance_match = any(term in normalized for term in _FINANCE_TERMS)
                    if not company_match and not finance_match:
                        excluded["unrelated"] += 1
                        continue
                    seen_ids.add(comment["comment_id"])
                    seen_texts.add(normalized)
                    accepted.append({**comment, "text": body, "video": video,
                                     "relevance_basis": "company_mention" if company_match else "video_context_and_finance_keyword"})
            token = page["next_page_token"]
            if not token:
                break
        if token:
            page_limited = True
        by_video.append(accepted)
    # ponytail: 키워드 관련성 판정의 한계는 표본 메타데이터에 유지. 평가 후 필요 시 교체.
    balanced = [comment for row in zip_longest(*by_video) for comment in row if comment is not None]
    call_id, retrieved_at = uuid4().hex, datetime.now(timezone.utc).isoformat()
    for index, comment in enumerate(balanced[:40]):
        truncated = len(comment["text"]) > 600
        limits = ["작성자의 실제 투자 여부 미확인", "삭제·수정 이전 원문 복원 불가"]
        if truncated:
            limits.append("댓글 본문 600자 이후 생략")
        if comment["relevance_basis"] != "company_mention":
            limits.append("회사 직접 언급 없음. 영상 맥락과 금융 키워드로 관련성 추정")
        result["evidence"].append({
            "evidence_id": f"youtube:{call_id}:{index}", "kind": "comment", "content": comment["text"][:600],
            "source": {"provider": "YouTube", "url": "https://www.youtube.com/watch?" + urlencode({
                "v": comment["video_id"], "lc": comment["comment_id"]}),
                "video_id": comment["video_id"], "comment_id": comment["comment_id"],
                "video_title": comment["video"]["title"], "updated_at": comment["updated_at"],
                "relevance_basis": comment["relevance_basis"], "truncated": truncated},
            "published_at": comment["published_at"], "observation_start": comment["published_at"],
            "observation_end": comment["published_at"], "retrieved_at": retrieved_at, "limitations": limits,
        })
    result["sample_count"] = len(result["evidence"])
    result["excluded_counts"] = dict(excluded)
    if failures:
        result["collection_errors"] = failures
        result["limitations"].extend(f"{item['video_id']}: {item['message']}" for item in failures)
    if page_limited:
        result["limitations"].append("영상당 최신 댓글 50개 조회 한도. 기간 내 댓글 전체 수집 미보장")
    if len(balanced) > 40:
        result["limitations"].append("관련 댓글 중 영상별 균등 순회 40개만 모델 입력에 포함")
    if result["sample_count"]:
        small_sample = result["sample_count"] < 10
        result["status"] = "partial" if small_sample or failures or page_limited else "complete"
        if small_sample:
            result["limitations"].append("10개 미만의 적은 댓글 표본. 반응 비중 일반화 금지")
    elif failures:
        first = failures[0]
        result.update(status="error", error={key: first[key] for key in ("code", "message", "retryable")})
    else:
        result["limitations"].append("조회 범위와 관련성 조건을 만족하는 댓글 없음. 중립 감정의 증거가 아님")
    return result
