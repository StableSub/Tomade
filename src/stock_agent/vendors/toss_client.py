"""토스증권 Open API 국내 시세 클라이언트."""

import datetime
import os
import threading
import time
from decimal import Decimal
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://openapi.tossinvest.com"
_KST = ZoneInfo("Asia/Seoul")
_PAGE_SIZE = 200
_MAX_CANDLE_PAGES = 20
_token: str | None = None
_token_expires_at = 0.0
_token_lock = threading.Lock()


def _get_access_token(rejected_token: str | None = None) -> str:
    """캐시된 OAuth Token을 반환하고 만료가 가까우면 새로 발급한다."""
    global _token, _token_expires_at

    with _token_lock:
        if rejected_token is not None and _token == rejected_token:
            _token = None
            _token_expires_at = 0.0
        if _token is not None and time.monotonic() < _token_expires_at:
            return _token

        response = requests.post(
            f"{_BASE_URL}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ["TOSS_CLIENT_ID"],
                "client_secret": os.environ["TOSS_CLIENT_SECRET"],
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        _token = payload["access_token"]
        expires_in = int(payload["expires_in"])
        _token_expires_at = time.monotonic() + max(expires_in - 60, 0)
        return _token


def _get(path: str, params: dict, *, account_seq: int | None = None) -> dict | list:
    """인증 Header를 포함해 토스증권 REST API의 result를 반환한다."""
    headers = {"Authorization": f"Bearer {_get_access_token()}"}
    if account_seq is not None:
        headers["X-Tossinvest-Account"] = str(account_seq)
    response = requests.get(
        f"{_BASE_URL}{path}",
        params=params,
        headers=headers,
        timeout=30,
    )
    if response.status_code == 401:
        # 동시 요청이 이미 갱신한 토큰은 재발급하지 않고 재사용한다. 재시도는 한 번뿐이다.
        rejected_token = headers["Authorization"].removeprefix("Bearer ")
        headers["Authorization"] = f"Bearer {_get_access_token(rejected_token)}"
        response = requests.get(
            f"{_BASE_URL}{path}", params=params, headers=headers, timeout=30,
        )
    response.raise_for_status()
    return response.json()["result"]


def get_accounts() -> list[dict]:
    """본인 계좌 목록을 조회한다.

    인자 없음. 계좌 식별 정보가 포함된 목록을 반환하며 외부 API를 호출한다.
    인증·통신 오류는 호출자에게 전달한다. 반환 원문을 로그나 LLM에 보내지 않는다.
    """
    return _get("/api/v1/accounts", {})


def get_holdings(account_seq: int) -> dict:
    """account_seq 계좌의 보유 자산을 조회해 원본 result를 반환한다.

    조회 전용 외부 API를 호출하며 인증·통신 오류를 전달한다. 현금 잔고는 포함하지
    않는다. 계좌 식별자와 원본 자산 응답은 로그나 LLM에 전달하지 않는다.
    """
    return _get("/api/v1/holdings", {}, account_seq=account_seq)


def get_stock_info(symbols: list[str]) -> list[dict]:
    """symbols의 상품 유형·통화 등 종목 정보를 200개씩 조회해 합쳐 반환한다.

    외부 조회만 수행하며 빈 목록은 API를 호출하지 않는다. 인증·통신 오류는 전달한다.
    """
    result = []
    for offset in range(0, len(symbols), 200):
        result.extend(_get("/api/v1/stocks", {"symbols": ",".join(symbols[offset:offset + 200])}))
    return result


def _parse_timestamp(value: str) -> datetime.datetime:
    """ISO Timestamp를 KST 기준 datetime으로 정규화한다."""
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KST)
    return parsed.astimezone(_KST)


def _get_candles(
    ticker: str,
    interval: str,
    start_at: datetime.datetime,
    end_at: datetime.datetime,
) -> list[dict]:
    """지정 구간의 Candle을 Pagination해 Timestamp 오름차순으로 반환한다."""
    candles_by_timestamp: dict[str, dict] = {}
    before = end_at.isoformat()

    for _ in range(_MAX_CANDLE_PAGES):
        page = _get(
            "/api/v1/candles",
            {
                "symbol": ticker,
                "interval": interval,
                "count": _PAGE_SIZE,
                "before": before,
                "adjusted": "true",
            },
        )
        candles = page.get("candles", [])
        if not candles:
            break

        for candle in candles:
            candles_by_timestamp[candle["timestamp"]] = candle

        oldest = min(_parse_timestamp(candle["timestamp"]) for candle in candles)
        next_before = page.get("nextBefore")
        if oldest < start_at or not next_before:
            break
        before = next_before
    else:
        raise RuntimeError("토스증권 Candle 조회가 최대 페이지 수를 초과했습니다.")

    return sorted(
        (
            candle
            for candle in candles_by_timestamp.values()
            if start_at <= _parse_timestamp(candle["timestamp"]) <= end_at
        ),
        key=lambda candle: _parse_timestamp(candle["timestamp"]),
    )


def get_ohlcv(
    ticker: str,
    days: int = 30,
    end_date: str | None = None,
) -> list[dict]:
    """기준일까지 최근 N일간 토스증권 일봉 OHLCV를 조회한다.

    Args:
        ticker: DART에서 확인한 국내 주식 6자리 종목코드.
        days: 기준일에서 과거로 조회할 달력 일수.
        end_date: ISO 형식의 분석 기준일. 미입력 시 오늘.

    Returns:
        날짜·OHLCV·전 거래일 대비 등락률을 가진 딕셔너리 목록. 요청 기간보다
        이전 일봉 하나를 함께 조회해 첫 거래일의 등락률도 Python으로 계산한다.
        반환 목록은 요청 날짜 범위 안의 데이터만 날짜 오름차순으로 포함한다.

    Raises:
        KeyError: 토스증권 Client 환경변수가 설정되지 않은 경우.
        requests.RequestException: 인증 또는 Candle API 요청이 실패한 경우.
        RuntimeError: 요청 기간이 최대 Pagination 범위를 초과한 경우.
    """
    end = datetime.date.fromisoformat(end_date) if end_date else datetime.date.today()
    start = end - datetime.timedelta(days=days)
    start_at = datetime.datetime.combine(
        start - datetime.timedelta(days=7),
        datetime.time.min,
        tzinfo=_KST,
    )
    end_at = datetime.datetime.combine(end, datetime.time.max, tzinfo=_KST)
    candles = _get_candles(ticker, "1d", start_at, end_at)

    records = []
    previous_close: int | None = None
    for candle in candles:
        candle_date = _parse_timestamp(candle["timestamp"]).date()
        close = int(Decimal(candle["closePrice"]))
        change_pct = 0.0
        if previous_close:
            change_pct = round((close / previous_close - 1) * 100, 2)
        previous_close = close

        if candle_date < start:
            continue
        records.append(
            {
                "date": candle_date.isoformat(),
                "open": int(Decimal(candle["openPrice"])),
                "high": int(Decimal(candle["highPrice"])),
                "low": int(Decimal(candle["lowPrice"])),
                "close": close,
                "volume": int(Decimal(candle["volume"])),
                "change_pct": change_pct,
            }
        )
    return records


def get_intraday_ohlcv(ticker: str, date: str) -> list[dict]:
    """지정 날짜의 토스증권 1분봉 OHLCV를 조회한다.

    Args:
        ticker: DART에서 확인한 국내 주식 6자리 종목코드.
        date: 조회할 KST 기준 ISO 날짜.

    Returns:
        시각·OHLCV를 가진 1분봉 딕셔너리 목록. 장 전체가 200개를 넘으면 Vendor가
        `nextBefore`를 이용해 필요한 페이지를 자동으로 이어서 조회한다.

    Raises:
        KeyError: 토스증권 Client 환경변수가 설정되지 않은 경우.
        requests.RequestException: 인증 또는 Candle API 요청이 실패한 경우.
        RuntimeError: 단일 날짜 조회가 최대 Pagination 범위를 초과한 경우.
    """
    target = datetime.date.fromisoformat(date)
    start_at = datetime.datetime.combine(target, datetime.time.min, tzinfo=_KST)
    end_at = datetime.datetime.combine(target, datetime.time.max, tzinfo=_KST)
    candles = _get_candles(ticker, "1m", start_at, end_at)

    return [
        {
            "timestamp": _parse_timestamp(candle["timestamp"]).isoformat(),
            "open": int(Decimal(candle["openPrice"])),
            "high": int(Decimal(candle["highPrice"])),
            "low": int(Decimal(candle["lowPrice"])),
            "close": int(Decimal(candle["closePrice"])),
            "volume": int(Decimal(candle["volume"])),
        }
        for candle in candles
    ]


def get_current_price(ticker: str) -> dict | None:
    """토스증권에서 국내 종목의 현재가와 데이터 시각을 조회한다.

    Args:
        ticker: DART에서 확인한 국내 주식 6자리 종목코드.

    Returns:
        현재가와 ISO Timestamp를 가진 딕셔너리. 체결 데이터가 없으면 `None`.

    Raises:
        KeyError: 토스증권 Client 환경변수가 설정되지 않은 경우.
        requests.RequestException: 인증 또는 현재가 API 요청이 실패한 경우.
    """
    prices = _get("/api/v1/prices", {"symbols": ticker})
    if not prices or prices[0].get("timestamp") is None:
        return None
    return {
        "timestamp": _parse_timestamp(prices[0]["timestamp"]).isoformat(),
        "price": int(Decimal(prices[0]["lastPrice"])),
    }
