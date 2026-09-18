"""완료된 국내 일봉에서 고정 기술 지표와 계산 근거를 생성하는 Tool."""

import datetime
import math
import re
import statistics
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars
import requests
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from stock_agent.vendors import toss_client

_KST = ZoneInfo("Asia/Seoul")
_METRICS = (
    ("sma_20", "KRW", 20, 20, "mean(last 20 closes)"),
    ("sma_60", "KRW", 60, 60, "mean(last 60 closes)"),
    ("distance_sma_20_pct", "percent", 20, 20, "(latest_close / sma_20 - 1) * 100"),
    ("distance_sma_60_pct", "percent", 60, 60, "(latest_close / sma_60 - 1) * 100"),
    ("volume_ratio_20", "ratio", 20, 21, "latest_volume / mean(previous 20 volumes)"),
    ("daily_volatility_20_pct", "percent", 20, 21, "stdev(20 simple daily returns, ddof=1) * 100"),
)


class TechnicalMetric(BaseModel):
    """한 지표의 값과 계산 창, 계산 불가 사유를 검증하는 반환 계약."""

    model_config = ConfigDict(allow_inf_nan=False)
    name: str
    value: float | None
    unit: str
    window: int
    window_start: str | None
    window_end: str | None
    observation_count: int
    reason: str | None
    evidence_id: str | None


class TechnicalEvidence(BaseModel):
    """ToolMessage로 직렬화하기 전 기술 분석 결과를 검증하는 계약."""

    model_config = ConfigDict(allow_inf_nan=False)
    status: Literal["complete", "partial", "unavailable", "error"]
    ticker: str
    as_of_date: str
    effective_date: str | None = None
    latest_close: float | None = None
    latest_volume: float | None = None
    metrics: list[TechnicalMetric] = Field(default_factory=list)
    source: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: dict | None = None


def _number(value: object, *, allow_zero: bool) -> float | None:
    """유한한 가격·거래량만 계산용 수로 변환한다."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        return None
    return number


def _normalize(records: list[dict], start: str, end: str) -> list[dict]:
    """날짜별 중복을 합치되 잘못된 값과 충돌한 항목의 위치를 보존한다."""
    by_date: dict[str, dict] = {}
    for record in records:
        day = datetime.date.fromisoformat(record["date"]).isoformat()
        if day < start or day > end:
            continue
        row = by_date.setdefault(day, {"date": day})
        for field in ("close", "volume"):
            value = _number(record.get(field), allow_zero=field == "volume")
            reason = f"invalid_{field}" if value is None else None
            if field in row and (row[field] != value or row[f"{field}_reason"] != reason):
                value, reason = None, f"conflicting_{field}"
            # Once conflicting, a later duplicate must never restore one selected value.
            if row.get(f"{field}_reason") == f"conflicting_{field}":
                value, reason = None, f"conflicting_{field}"
            row[field], row[f"{field}_reason"] = value, reason
    return sorted(by_date.values(), key=lambda row: row["date"])


def _sessions(start: str, end: str) -> set[str] | None:
    """XKRX의 예정 거래일을 반환하고 지원 범위 밖은 미검증으로 남긴다."""
    try:
        calendar = exchange_calendars.get_calendar("XKRX", start=start, end=end)
        return {day.date().isoformat() for day in calendar.sessions}
    except ValueError:
        return None


def _metric_value(name: str, values: list[float]) -> tuple[float | None, str | None]:
    """검증된 입력 창으로 한 지표를 계산한다."""
    try:
        if name.startswith("sma_"):
            result = statistics.fmean(values)
        elif name.startswith("distance_"):
            result = (values[-1] / statistics.fmean(values) - 1) * 100
        elif name == "volume_ratio_20":
            average = statistics.fmean(values[:-1])
            if average == 0:
                return None, "zero_average_volume"
            result = values[-1] / average
        else:
            returns = [current / previous - 1 for previous, current in zip(values, values[1:])]
            if not all(math.isfinite(value) for value in returns):
                return None, "numeric_range_exceeded"
            result = statistics.stdev(returns) * 100
    except (OverflowError, ValueError):
        return None, "numeric_range_exceeded"
    return (result, None) if math.isfinite(result) else (None, "numeric_range_exceeded")


def collect_technical_evidence(
    mandate: dict, *, now: datetime.datetime | None = None,
) -> TechnicalEvidence:
    """확정된 조사 조건의 시세를 조회하고 고정 기술 지표를 계산한다.

    Args:
        mandate: 검증된 ticker와 필수 as_of_date가 포함된 조사 조건.
        now: 날짜 경계 검증에 사용하는 timezone-aware 시각. 미입력 시 현재 KST.

    Returns:
        숫자·출처·계산 창·근거 ID를 포함하는 결과. 120일 조회 후 60봉 미만이면
        365일까지 한 번 확장한다. 오늘 봉은 항상 제외한다. 입력·외부 경계 오류는
        error, 자료 부족은 null 지표로 구분하며 오류 메시지에 인증 원문은 포함하지 않는다.

    Side effects:
        Toss 조회 API 호출. 기존 인증 갱신 이외 별도 자동 재시도 없음.
    """
    now = now or datetime.datetime.now(_KST)
    if now.tzinfo is None:
        raise ValueError("now는 시간대가 있는 datetime이어야 합니다.")
    now = now.astimezone(_KST)
    ticker = mandate.get("ticker", "")
    raw_date = mandate.get("as_of_date", "")
    result = TechnicalEvidence(status="error", ticker=str(ticker), as_of_date=str(raw_date))

    def fail(code: str, message: str, retryable: bool = False) -> TechnicalEvidence:
        result.status = "error"
        result.error = {"code": code, "message": message, "retryable": retryable}
        return result

    if not isinstance(ticker, str) or not re.fullmatch(r"[0-9]{6}", ticker):
        return fail("invalid_input", "ticker는 검증된 국내 주식 6자리 코드여야 합니다.")
    try:
        requested = datetime.date.fromisoformat(raw_date)
        if requested.isoformat() != raw_date or requested > now.date():
            raise ValueError
    except (TypeError, ValueError):
        return fail("invalid_input", "as_of_date는 미래가 아닌 YYYY-MM-DD 날짜여야 합니다.")
    end = requested - datetime.timedelta(days=1) if requested == now.date() else requested
    try:
        for days in (120, 365):
            start = end - datetime.timedelta(days=days - 1)
            records = toss_client.get_daily_series(ticker, days, end.isoformat())
            rows = _normalize(records, start.isoformat(), end.isoformat())
            if sum(row["close"] is not None for row in rows) >= 60:
                break
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        retryable = code is None or code == 429 or code >= 500
        return fail("provider_error", "Toss 시세 조회 실패. 인증·허용 IP·연결 상태 확인 후 재시도 가능.", retryable)
    except KeyError as exc:
        if exc.args and exc.args[0] in ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"):
            return fail("missing_credentials", "TOSS_CLIENT_ID와 TOSS_CLIENT_SECRET 설정 필요.")
        return fail("invalid_response", "Toss 일봉 응답에 필수 항목 누락.")
    except (TypeError, ValueError, RuntimeError, OverflowError):
        return fail("invalid_response", "Toss 일봉 형식 또는 조회 범위 확인 필요.")

    sessions = _sessions(start.isoformat(), end.isoformat())
    if sessions is not None and any(row["date"] not in sessions for row in rows):
        return fail("invalid_response", "XKRX 비거래일에 일봉이 존재하여 날짜 조건 검증 실패.")
    result.source = {
        "provider": "Toss Securities Open API",
        "url": "https://openapi.tossinvest.com/api/v1/candles",
        "interval": "1d", "retrieved_at": now.isoformat(), "calendar": "XKRX",
        "calendar_version": exchange_calendars.__version__,
        "query_start": start.isoformat(), "query_end": end.isoformat(),
        "adjustment_requested": True, "adjustment_verified": False,
        "point_in_time_verified": False,
    }
    result.limitations = [
        "제공처 가격·거래량 조정 정책과 과거 당시의 수정주가 이용 가능성 미검증.",
        "XKRX 캘린더는 예정 거래일 기준이며 종목별 거래정지·제공처 누락의 원인 구분 불가.",
    ]
    if requested == now.date():
        result.limitations.append("KST 오늘의 봉은 장 마감 여부와 무관하게 제외.")
    if sessions is None:
        result.limitations.append("XKRX 캘린더 지원 범위 밖으로 거래일 연속성 미검증.")
    if rows:
        latest = rows[-1]
        result.effective_date = latest["date"]
        result.latest_close, result.latest_volume = latest["close"], latest["volume"]
        for field in ("close", "volume"):
            if latest[field] is None:
                result.limitations.append(f"마지막 일봉의 {field} 사용 불가: {latest[f'{field}_reason']}.")
        if result.effective_date != raw_date:
            result.limitations.append(f"요청 기준일 {raw_date}와 실제 마지막 관측일 {result.effective_date} 차이 존재.")
        if sessions and max(sessions) > result.effective_date:
            result.limitations.append("최근 예정 거래일 봉 미확보. 지연·거래정지 여부 확인 필요.")
    prefix = f"technical:{uuid.uuid4().hex}"

    def evidence(name: str, value: float, unit: str, first: str, last: str, formula: str, window: int) -> str:
        evidence_id = f"{prefix}:{name}"
        result.evidence.append({
            "evidence_id": evidence_id, "kind": "metric",
            "content": {"name": name, "value": value, "unit": unit, "formula": formula,
                        "window": window, "input_conditions": {"ticker": ticker, "as_of_date": raw_date,
                        "effective_date": result.effective_date, "completed_daily_bars_only": True,
                        "calendar": "XKRX", "annualized": False}},
            "source": dict(result.source), "published_at": None,
            "observation_start": first, "observation_end": last,
            "retrieved_at": now.isoformat(), "limitations": list(result.limitations),
        })
        return evidence_id

    for field, unit in (("latest_close", "KRW"), ("latest_volume", "shares")):
        value = getattr(result, field)
        if value is not None:
            evidence(field, value, unit, result.effective_date, result.effective_date, "observed daily bar", 1)

    for name, unit, window, needed, formula in _METRICS:
        subset = rows[-needed:]
        field = "volume" if name == "volume_ratio_20" else "close"
        values = [row[field] for row in subset]
        reason = None
        if len(subset) < needed:
            reason = "insufficient_history"
        elif any(value is None for value in values):
            reason = next(row[f"{field}_reason"] for row in subset if row[field] is None)
        elif sessions is None or {row["date"] for row in subset} != {
            day for day in sessions if subset[0]["date"] <= day <= subset[-1]["date"]
        }:
            reason = "unverified_gap"
        value = None
        if reason is None:
            value, reason = _metric_value(name, values)
        first = subset[0]["date"] if subset else None
        last = subset[-1]["date"] if subset else None
        evidence_id = evidence(name, value, unit, first, last, formula, window) if value is not None else None
        result.metrics.append(TechnicalMetric(
            name=name, value=value, unit=unit, window=window,
            window_start=first, window_end=last,
            observation_count=sum(value is not None for value in values),
            reason=reason, evidence_id=evidence_id,
        ))
        if reason:
            result.limitations.append(f"{name} 계산 불가: {reason}, 유효 입력 {sum(value is not None for value in values)}/{needed}개.")
    available = sum(metric.value is not None for metric in result.metrics)
    result.status = "complete" if available == len(_METRICS) else "partial" if available else "unavailable"
    return TechnicalEvidence.model_validate(result.model_dump())


def make_technical_tool(mandate: dict):
    """조사 조건을 고정한 무인자 Technical Tool을 생성한다.

    Args:
        mandate: Graph가 검증한 ticker·as_of_date. 사본을 보관하여 모델 인자 변경 차단.
    Returns:
        get_technical_evidence 이름의 LangChain Tool. 호출 시 외부 조회를 수행하고
        검증된 JSON 문자열을 반환한다. 실행 오류도 동일 계약의 error로 반환한다.
    """
    fixed_mandate = dict(mandate)

    @tool
    def get_technical_evidence() -> str:
        """배정 종목·기준일의 완료된 일봉 지표를 한 번 조회한다.

        인자 없음. 종가·거래량, SMA20/60, 이격률, 직전 20봉 거래량 비율,
        20일 수익률 표본 표준편차를 JSON으로 반환한다. 오늘 봉 제외, 계산 불가 값은
        null과 이유 반환. 외부 시세 조회를 수행하며 오류·자료 부족을 구분한다.
        같은 질문에서 반복 호출하지 않으며 골든크로스·매매 주체·미래 방향은 제공하지 않는다.
        """
        return collect_technical_evidence(fixed_mandate).model_dump_json()

    return get_technical_evidence
