"""Agent들이 공유하는 결정적 국내 시장 Evidence Tool."""

import datetime
from functools import lru_cache
from threading import Lock
from typing import Annotated

from langchain_core.tools import tool

from stock_agent.vendors import dart_client, toss_client

_SIGNIFICANT_MOVE_PCT = 3.0
_MARKET_CACHE_LOCK = Lock()


def _resolve_ticker(raw: str) -> str | None:
    """종목코드 또는 회사명을 6자리 종목코드로 정규화한다."""
    raw = raw.strip()
    if len(raw) == 6 and raw.isdigit():
        return raw
    return dart_client.find_ticker_by_name(raw)


@lru_cache(maxsize=128)
def _get_daily_market_evidence_cached(
    ticker: str,
    days: int,
    as_of_date: str,
) -> str:
    """동일 종목·기간·기준일의 일봉 Evidence를 프로세스에서 재사용한다."""
    records = toss_client.get_ohlcv(ticker, days=days, end_date=as_of_date)
    if not records:
        return f"'{ticker}' 종목은 {as_of_date} 기준 최근 {days}일 시세 데이터가 없습니다."
    return _format_daily_market_evidence(ticker, days, as_of_date, records)


def _format_daily_market_evidence(
    ticker: str,
    days: int,
    as_of_date: str,
    records: list[dict],
) -> str:
    """일봉 OHLCV에서 기간 요약과 주요 급등락 날짜를 계산한다."""
    first = records[0]
    latest = records[-1]
    period_return = 0.0
    if first["close"]:
        period_return = round((latest["close"] / first["close"] - 1) * 100, 2)

    highest = max(records, key=lambda record: record["high"])
    lowest = min(records, key=lambda record: record["low"])
    average_volume = round(
        sum(record["volume"] for record in records) / len(records)
    )
    significant_moves = [
        record
        for record in records
        if abs(record["change_pct"]) >= _SIGNIFICANT_MOVE_PCT
    ]

    lines = [
        "## Market Evidence",
        f"- 종목코드: {ticker}",
        f"- 분석 기준일: {as_of_date}",
        f"- 요청 기간: 최근 {days}일",
        f"- 실제 거래일: {len(records)}일 ({first['date']} ~ {latest['date']})",
        f"- 시작 종가: {first['close']:,}원",
        f"- 마지막 종가: {latest['close']:,}원",
        f"- 기간 수익률: {period_return}%",
        f"- 기간 최고가: {highest['high']:,}원 ({highest['date']})",
        f"- 기간 최저가: {lowest['low']:,}원 ({lowest['date']})",
        f"- 일평균 거래량: {average_volume:,}주",
        "- 출처: 토스증권 Open API 일봉",
        "",
        f"### 주요 급등락일 (절대 등락률 {_SIGNIFICANT_MOVE_PCT}% 이상)",
    ]

    if significant_moves:
        lines.extend(
            f"- {record['date']}: {record['change_pct']}%, "
            f"종가 {record['close']:,}원, 거래량 {record['volume']:,}주"
            for record in significant_moves
        )
    else:
        lines.append("- 해당 기준을 충족하는 거래일 없음")

    lines.extend(
        [
            "",
            "### 일별 근거",
            "| 날짜 | 종가 | 등락률(%) | 거래량 |",
            "|---|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {record['date']} | {record['close']:,} | "
        f"{record['change_pct']} | {record['volume']:,} |"
        for record in records
    )
    return "\n".join(lines)


def _bucket_intraday_records(records: list[dict]) -> list[dict]:
    """1분봉을 LLM이 읽기 적당한 30분 OHLCV 구간으로 집계한다."""
    buckets: dict[datetime.datetime, dict] = {}
    for record in records:
        timestamp = datetime.datetime.fromisoformat(record["timestamp"])
        bucket_at = timestamp.replace(
            minute=(timestamp.minute // 30) * 30,
            second=0,
            microsecond=0,
        )
        bucket = buckets.get(bucket_at)
        if bucket is None:
            buckets[bucket_at] = {
                "timestamp": bucket_at,
                "open": record["open"],
                "high": record["high"],
                "low": record["low"],
                "close": record["close"],
                "volume": record["volume"],
            }
            continue
        bucket["high"] = max(bucket["high"], record["high"])
        bucket["low"] = min(bucket["low"], record["low"])
        bucket["close"] = record["close"]
        bucket["volume"] += record["volume"]
    return list(buckets.values())


def _format_intraday_market_evidence(
    ticker: str,
    as_of_date: str,
    records: list[dict],
    previous_close: int | None,
    quote: dict | None,
) -> str:
    """1분봉에서 단일 거래일의 장중 추세와 30분 구간 Evidence를 계산한다."""
    first = records[0]
    latest = records[-1]
    latest_price = quote["price"] if quote else latest["close"]
    latest_timestamp = quote["timestamp"] if quote else latest["timestamp"]
    highest = max(records, key=lambda record: record["high"])
    lowest = min(records, key=lambda record: record["low"])
    volume = sum(record["volume"] for record in records)
    open_change_pct = round((latest_price / first["open"] - 1) * 100, 2)
    previous_change_pct = None
    if previous_close:
        previous_change_pct = round((latest_price / previous_close - 1) * 100, 2)

    lines = [
        "## Intraday Market Evidence",
        f"- 종목코드: {ticker}",
        f"- 분석 날짜: {as_of_date}",
        f"- 데이터 기준 시각: {latest_timestamp}",
        f"- 시가: {first['open']:,}원",
        f"- 최신가: {latest_price:,}원",
        f"- 시가 대비 등락률: {open_change_pct}%",
    ]
    if previous_close is not None and previous_change_pct is not None:
        lines.extend(
            [
                f"- 전 거래일 종가: {previous_close:,}원",
                f"- 전 거래일 종가 대비 등락률: {previous_change_pct}%",
            ]
        )
    else:
        lines.append("- 전 거래일 종가 대비 등락률: 확인 불가")

    lines.extend(
        [
            f"- 장중 최고가: {highest['high']:,}원 ({highest['timestamp']})",
            f"- 장중 최저가: {lowest['low']:,}원 ({lowest['timestamp']})",
            f"- 조회된 1분봉: {len(records)}개",
            f"- 누적 거래량: {volume:,}주",
            "- 출처: 토스증권 Open API 현재가·1분봉·일봉",
            "",
            "### 30분 단위 장중 근거",
            "| 시각 | 시가 | 고가 | 저가 | 종가 | 거래량 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {bucket['timestamp'].strftime('%H:%M')} | {bucket['open']:,} | "
        f"{bucket['high']:,} | {bucket['low']:,} | {bucket['close']:,} | "
        f"{bucket['volume']:,} |"
        for bucket in _bucket_intraday_records(records)
    )
    return "\n".join(lines)


def _get_intraday_market_evidence(ticker: str, as_of_date: str) -> str:
    """단일 날짜의 1분봉과 전 거래일 종가를 결합한다."""
    records = toss_client.get_intraday_ohlcv(ticker, as_of_date)
    if not records:
        return f"'{ticker}' 종목은 {as_of_date} 기준 1분봉 시세 데이터가 없습니다."

    daily_records = toss_client.get_ohlcv(ticker, days=7, end_date=as_of_date)
    previous_records = [
        record for record in daily_records if record["date"] < as_of_date
    ]
    previous_close = previous_records[-1]["close"] if previous_records else None
    quote = None
    if as_of_date == datetime.date.today().isoformat():
        quote = toss_client.get_current_price(ticker)
    return _format_intraday_market_evidence(
        ticker,
        as_of_date,
        records,
        previous_close,
        quote,
    )


@tool
def get_market_evidence(
    ticker: Annotated[
        str,
        "한국 종목코드 6자리 또는 정확한 상장 회사명",
    ],
    days: Annotated[int, "조회할 기간의 달력 일수"] = 30,
    as_of_date: Annotated[
        str,
        "분석 기준일 ISO 형식(YYYY-MM-DD). 미입력 시 오늘",
    ] = "",
) -> str:
    """토스증권 시세와 Python 계산을 결합한 Market Evidence를 반환한다.

    단일 날짜 요청은 Pagination한 1분봉으로 장중 추세를 계산하고, 여러 날짜
    요청은 일봉으로 기간 수익률·평균 거래량·주요 급등락 날짜를 계산한다.
    과거 일봉 Evidence는 종목·기간·기준일별로 프로세스 캐시에서 재사용하며,
    오늘의 단일 날짜 Evidence는 최신성을 위해 캐시하지 않는다.

    Args:
        ticker: 내부 종목코드 또는 DART로 코드 변환 가능한 정확한 회사명.
        days: 기준일부터 과거로 조회할 달력 일수. `1`이면 1분봉을 사용한다.
        as_of_date: 미래 정보 차단과 조회 종료 시점에 사용할 ISO 기준일.

    Returns:
        단일 날짜의 장중 추세 또는 여러 날짜의 기간 요약을 담은 마크다운 문자열.
        입력·인증·API 호출이 실패하면 예외 대신 원인과 재시도 안내를 반환한다.
    """
    normalized_ticker = _resolve_ticker(ticker)
    if normalized_ticker is None:
        return "종목을 찾을 수 없습니다. 정확한 상장 회사명으로 다시 시도하세요."
    if days <= 0:
        return "조회 기간은 1일 이상의 정수여야 합니다."

    normalized_date = as_of_date.strip() or datetime.date.today().isoformat()
    try:
        parsed_date = datetime.date.fromisoformat(normalized_date)
    except ValueError:
        return "분석 기준일은 YYYY-MM-DD 형식이어야 합니다."
    if parsed_date > datetime.date.today():
        return "분석 기준일은 오늘보다 미래일 수 없습니다."

    try:
        if days == 1:
            return _get_intraday_market_evidence(normalized_ticker, normalized_date)
        with _MARKET_CACHE_LOCK:
            return _get_daily_market_evidence_cached(
                normalized_ticker,
                days,
                normalized_date,
            )
    except KeyError:
        return (
            "토스증권 API 인증 정보가 없습니다. TOSS_CLIENT_ID와 "
            "TOSS_CLIENT_SECRET을 설정한 뒤 재시도하세요."
        )
    except Exception as error:
        return (
            f"토스증권 시세 조회 중 오류가 발생했습니다 ({type(error).__name__}). "
            f"종목코드 '{normalized_ticker}'와 허용 IP를 확인하고 재시도하세요."
        )
