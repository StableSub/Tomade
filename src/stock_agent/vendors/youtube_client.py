"""YouTube 공개 영상과 최상위 댓글을 한 페이지씩 조회하는 클라이언트."""

import os
from urllib.parse import urlencode

import requests

from stock_agent.control.external_budget import check_external_budget
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://www.googleapis.com/youtube/v3"
_TIMEOUT_SECONDS = 15


class ProviderError(RuntimeError):
    """원문 응답·요청 URL·인증정보를 포함하지 않는 외부 연동 오류.

    Args:
        code: 프로그램에서 분기할 안전한 오류 코드.
        message: 사용자에게 전달할 고정 오류 설명.
        retryable: 이후 실행에서 다시 시도할 수 있는 일시적 오류 여부.

    이 예외 자체는 재시도를 수행하지 않으며 수집기가 호출 예산을 관리한다.
    """

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


def _invalid_response() -> ProviderError:
    """외부 응답 내용을 노출하지 않는 형식 오류를 만든다."""
    return ProviderError("invalid_response", "YouTube 응답 형식을 확인할 수 없습니다.")


def _http_error(status: int, body: object) -> ProviderError:
    """상태 코드와 알려진 사유만 읽어 안전한 오류로 변환한다."""
    reasons: set[str] = set()
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        errors = body["error"].get("errors", [])
        if isinstance(errors, list):
            reasons = {
                item["reason"]
                for item in errors
                if isinstance(item, dict) and isinstance(item.get("reason"), str)
            }
    if "commentsDisabled" in reasons:
        return ProviderError("comments_disabled", "이 영상은 댓글 조회가 비활성화되어 있습니다.")
    if reasons & {"quotaExceeded", "dailyLimitExceeded"}:
        return ProviderError("quota_exceeded", "YouTube API 할당량을 소진했습니다. 할당량 갱신 후 다시 시도하세요.")
    if status == 429 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return ProviderError("rate_limited", "YouTube 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.", True)
    if status in (401, 403):
        return ProviderError("auth_error", "YouTube API 키와 API 사용 권한을 확인하세요.")
    if status == 404:
        return ProviderError("not_found", "YouTube 영상 또는 댓글을 찾을 수 없습니다.")
    return ProviderError(
        "provider_error", "YouTube 요청을 처리하지 못했습니다.", status >= 500
    )


def _get(endpoint: str, params: dict) -> dict:
    """고정 API 경로를 한 번 호출하고 비밀정보를 제거한 오류만 반환한다."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("missing_credentials", "YOUTUBE_API_KEY 설정이 필요합니다.")
    try:
        check_external_budget()
        response = requests.get(
            f"{_BASE_URL}/{endpoint}",
            params={**params, "key": api_key},
            timeout=_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ProviderError(
            "network_error", "YouTube 연결에 실패했습니다. 잠시 후 다시 시도하세요.", True
        ) from None
    try:
        body = response.json()
    except ValueError:
        if response.status_code != 200:
            raise _http_error(response.status_code, None) from None
        raise _invalid_response() from None
    if response.status_code != 200:
        raise _http_error(response.status_code, body)
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise _invalid_response()
    return body


def _object(value: object) -> dict:
    """필수 객체가 누락되거나 다른 자료형이면 응답 오류로 처리한다."""
    if not isinstance(value, dict):
        raise _invalid_response()
    return value


def _string(value: object, *, allow_empty: bool = False) -> str:
    """필수 문자열을 검증하고 원문 값을 그대로 반환한다."""
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _invalid_response()
    return value


def search_videos(
    query: str, published_before: str, max_results: int = 10
) -> list[dict[str, str]]:
    """기준 시각 이전 영상을 관련성순으로 최대 10개 조회한다.

    Args:
        query: 회사명과 주식 관련 표현을 포함한 검색어.
        published_before: 영상 공개 시각 상한인 RFC 3339 문자열.
        max_results: 한 번에 조회할 수, 1~10 범위로 제한.

    Returns:
        video_id, title, description, published_at, url 문자열을 가진 목록.
        공개일 하한은 지정하지 않아 오래된 영상의 최근 댓글도 조사 가능하다.

    Raises:
        ValueError: 검색어나 공개 시각 상한이 비어 있는 경우.
        ProviderError: 인증·네트워크·API·응답 형식 오류. API 호출은 한 번이며
            검색 페이지를 추가 조회하거나 자동 재시도하지 않는다.
    """
    if not query.strip() or not published_before.strip():
        raise ValueError("검색어와 영상 공개 시각 상한이 필요합니다.")
    body = _get("search", {
        "part": "snippet",
        "type": "video",
        "order": "relevance",
        "q": query,
        "publishedBefore": published_before,
        "maxResults": max(1, min(max_results, 10)),
    })
    videos = []
    for item in body["items"]:
        item = _object(item)
        identity = _object(item.get("id"))
        snippet = _object(item.get("snippet"))
        video_id = _string(identity.get("videoId"))
        videos.append({
            "video_id": video_id,
            "title": _string(snippet.get("title")),
            "description": _string(snippet.get("description"), allow_empty=True),
            "published_at": _string(snippet.get("publishedAt")),
            "url": "https://www.youtube.com/watch?" + urlencode({"v": video_id}),
        })
    return videos


def list_comments(
    video_id: str, page_token: str | None = None, max_results: int = 50
) -> dict:
    """공개된 최상위 댓글 한 페이지를 시간순으로 조회한다.

    Args:
        video_id: 댓글을 수집할 영상 식별자.
        page_token: 이전 응답의 next_page_token, 첫 페이지는 None.
        max_results: 한 페이지의 요청 수, 1~50 범위로 제한.

    Returns:
        items에는 comment_id, video_id, text, published_at, updated_at을
        가진 댓글 목록, next_page_token에는 후속 페이지 식별자 또는 None.
        text는 공개 API의 textDisplay를 plainText로 요청한 값이며 작성자만
        조회 가능한 textOriginal과는 구분한다. 답글은 수집하지 않는다.

    Raises:
        ValueError: 영상 식별자가 비어 있는 경우.
        ProviderError: 댓글 비활성화·인증·네트워크·API·응답 형식 오류.
            자동 페이지 탐색·재시도·날짜 필터는 수행하지 않는다.
    """
    if not video_id.strip():
        raise ValueError("영상 식별자가 필요합니다.")
    params = {
        "part": "snippet",
        "videoId": video_id,
        "order": "time",
        "textFormat": "plainText",
        "maxResults": max(1, min(max_results, 50)),
    }
    if page_token:
        params["pageToken"] = page_token
    body = _get("commentThreads", params)
    next_page_token = body.get("nextPageToken")
    if next_page_token is not None:
        next_page_token = _string(next_page_token)
    comments = []
    for thread in body["items"]:
        snippet = _object(_object(thread).get("snippet"))
        comment = _object(snippet.get("topLevelComment"))
        content = _object(comment.get("snippet"))
        comments.append({
            "comment_id": _string(comment.get("id")),
            "video_id": video_id,
            "text": _string(content.get("textDisplay"), allow_empty=True),
            "published_at": _string(content.get("publishedAt")),
            "updated_at": _string(content.get("updatedAt")),
        })
    return {"items": comments, "next_page_token": next_page_token}
