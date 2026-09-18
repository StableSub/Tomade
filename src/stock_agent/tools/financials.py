"""검증된 회사·기준일에 묶인 재무 원값과 Decimal 계산 근거 Tool."""

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from stock_agent.vendors.financials_client import FinancialAPIError, get_financial_snapshot

# 표준 계정 우선. 표준 계정이 없을 때만 정확한 한글 계정명을 사용한다.
_ACCOUNTS = {
    "revenue": ({"IS", "CIS"}, {"Revenue"}, {"매출액", "수익(매출액)"}),
    "operating_income": ({"IS", "CIS"}, {"OperatingIncomeLoss"}, {"영업이익", "영업이익(손실)"}),
    "net_income": ({"IS", "CIS"}, {"ProfitLoss"}, {"당기순이익", "당기순이익(손실)", "반기순이익", "반기순이익(손실)", "분기순이익", "분기순이익(손실)"}),
    "total_assets": ({"BS"}, {"Assets"}, {"자산총계"}),
    "total_liabilities": ({"BS"}, {"Liabilities"}, {"부채총계"}),
    "total_equity": ({"BS"}, {"Equity"}, {"자본총계"}),
    "operating_cash_flow": ({"CF"}, {"CashFlowsFromUsedInOperatingActivities"}, {"영업활동현금흐름", "영업활동으로인한현금흐름"}),
}
_FLOW_METRICS = {"revenue", "operating_income", "net_income", "operating_cash_flow"}


def _number(value) -> Decimal | None:
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _same_cash_flow_period(row: dict, month: int) -> bool:
    """현금흐름 전기명을 확인해 연간과 분·반기 비교 혼합을 거부한다."""
    names = [re.sub(r"\s+", "", str(row.get(key, ""))) for key in ("thstrm_nm", "frmtrm_nm")]
    periods = [re.fullmatch(r"제(\d+)기(.*)", name) for name in names]
    if not all(periods) or int(periods[0][1]) != int(periods[1][1]) + 1:
        return False
    suffixes = {3: {"1분기", "1/4분기"}, 6: {"반기", "2분기", "2/4분기"},
                9: {"3분기", "3/4분기"}, 12: {"", "말"}}
    return all(period[2] in suffixes[month] for period in periods)


def _account(rows: list[dict], metric: str, month: int) -> tuple[dict | None, str | None]:
    divisions, account_ids, names = _ACCOUNTS[metric]
    rows = [row for row in rows if row.get("sj_div") in divisions]
    standard = [row for row in rows
                if re.sub(r"^(ifrs-full|ifrs|dart)_", "", str(row.get("account_id", ""))) in account_ids]
    candidates = standard or [row for row in rows if re.sub(r"\s+", "", str(row.get("account_nm", ""))) in names]
    if not candidates:
        return None, "지원하는 계정명·표준계정 없음"
    current_key = "thstrm_add_amount" if month != 12 and metric in _FLOW_METRICS - {"operating_cash_flow"} else "thstrm_amount"
    previous_key = "frmtrm_add_amount" if current_key == "thstrm_add_amount" else "frmtrm_amount"
    normalized = []
    for row in candidates:
        currency = str(row.get("currency", "")).strip().upper()
        value = _number(row.get(current_key))
        if value is None or not re.fullmatch(r"[A-Z]{3}", currency):
            return None, "금액 또는 통화 확인 불가"
        previous = _number(row.get(previous_key)) if metric in _FLOW_METRICS else None
        if metric == "operating_cash_flow" and not _same_cash_flow_period(row, month):
            previous = None
        normalized.append({"value": value, "currency": currency, "previous": previous,
                           "current_field": current_key, "previous_field": previous_key,
                           "account_id": row.get("account_id"), "account_nm": row.get("account_nm"),
                           "current_label": row.get("thstrm_nm"), "previous_label": row.get("frmtrm_q_nm") if current_key == "thstrm_add_amount" else row.get("frmtrm_nm")})
    if len({(item["value"], item["currency"], item["previous"]) for item in normalized}) > 1:
        return None, "동일 계정의 중복 금액·통화 충돌"
    return normalized[0], None


def make_financial_tool(mandate: dict):
    """검증된 회사와 기준일을 고정한 get_financial_evidence Tool을 만든다.

    Args:
        mandate: corp_code와 as_of_date가 있는 공통 조사 조건.
    Returns:
        인자 없는 LangChain Tool. 모델이 회사·기준일·산식을 바꿀 수 없다.
        호출 시 한 최신 보고서의 원값·비율·전년 동기 성장률 JSON을 반환한다.
        API·자료 오류는 JSON 상태와 안전한 설명으로 반환하며 자동 재시도는 없다.
    """
    corp_code = str(mandate.get("corp_code", ""))
    as_of_date = str(mandate.get("as_of_date", ""))

    @tool
    def get_financial_evidence() -> str:
        """조사 회사의 기준일까지 공개된 최신 재무 수치와 계산 근거를 조회한다.

        인자 없음. 공통 조사 조건의 회사·기준일을 고정하여 DART 연결 재무제표를
        우선 조회하고 자료가 없을 때만 별도로 전환한다. 매출·영업이익·순이익·
        자산·부채·자본·영업현금흐름과 계산 가능한 이익률·부채비율·동기 성장률을
        출처·기간·원값·산식과 함께 JSON 문자열로 반환한다. 분·반기 손익은 누적.
        오류와 자료 부족은 구분하며 원인 해석·가치평가·재조회는 수행하지 않는다.
        """
        result = {"status": "unavailable", "evidence": [], "limitations": [], "error": None}
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
                raise ValueError("ISO 날짜 형식 필요")
            cutoff = date.fromisoformat(as_of_date)
            if cutoff > datetime.now(ZoneInfo("Asia/Seoul")).date() or not re.fullmatch(r"\d{8}", corp_code):
                raise ValueError("회사 식별자 또는 기준일 형식·범위 확인 필요")
            snapshot = get_financial_snapshot(corp_code, as_of_date)
        except ValueError:
            result.update(status="error", error={"code": "invalid_input", "message": "검증된 8자리 회사 코드와 미래가 아닌 ISO 기준일 필요", "retryable": False})
            return json.dumps(result, ensure_ascii=False)
        except FinancialAPIError as exc:
            result.update(status="error", error={"code": exc.code, "message": str(exc), "retryable": exc.retryable})
            return json.dumps(result, ensure_ascii=False)
        result["limitations"] = list(snapshot["limitations"])
        if not snapshot["rows"]:
            return json.dumps(result, ensure_ascii=False)
        report, basis = snapshot["report"], snapshot["basis"]
        year, month = report["year"], report["month"]
        period_start = f"{year}-01-01"
        retrieved_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        prefix = f"financial:{uuid4().hex[:12]}"
        accounts = {}
        missing = []

        def append_evidence(metric: str, value: Decimal, unit: str, formula: str,
                            inputs: dict, account: dict | None = None, previous: bool = False):
            content = {"metric": metric, "value": str(value), "unit": unit, "formula": formula,
                       "inputs": inputs, "basis": basis, "business_year": year,
                       "report_code": report["report_code"], "period_semantics": "annual" if month == 12 else "year_to_date",
                       "requested_as_of_date": as_of_date}
            if metric.startswith("total_") or metric == "liabilities_to_equity_pct":
                content["period_semantics"] = "period_end"
            if account:
                content.update(account_id=account["account_id"], account_name=account["account_nm"],
                               source_field=account["current_field"], source_period_label=account["current_label"])
            if previous:
                content.update(comparison_period_start=f"{year - 1}-01-01",
                               comparison_period_end=f"{year - 1}{report['period_end'][4:]}")
            result["evidence"].append({
                "evidence_id": f"{prefix}:{metric}", "kind": "metric", "content": content,
                "source": {"provider": "OpenDART", "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={report['rcept_no']}",
                           "receipt_id": report["rcept_no"], "title": report["report_nm"],
                           "endpoint": "fnlttSinglAcntAll", "corp_code": corp_code},
                "published_at": report["published_at"],
                "observation_start": report["period_end"] if content["period_semantics"] == "period_end" else period_start,
                "observation_end": report["period_end"], "retrieved_at": retrieved_at,
                "limitations": list(snapshot["limitations"]),
            })

        for metric in _ACCOUNTS:
            account, reason = _account(snapshot["rows"], metric, month)
            if reason:
                missing.append(f"{metric}: {reason}")
                continue
            accounts[metric] = account
            append_evidence(metric, account["value"], account["currency"], "reported_amount",
                            {account["current_field"]: str(account["value"])}, account)
        for metric, numerator, denominator in (("operating_margin_pct", "operating_income", "revenue"),
                                                ("liabilities_to_equity_pct", "total_liabilities", "total_equity")):
            top, bottom = accounts.get(numerator), accounts.get(denominator)
            if not top or not bottom or top["currency"] != bottom["currency"] or bottom["value"] <= 0:
                missing.append(f"{metric}: 원값 부족·통화 불일치 또는 분모가 0 이하")
                continue
            append_evidence(metric, top["value"] / bottom["value"] * 100, "%",
                            f"{numerator} / {denominator} * 100",
                            {numerator: str(top["value"]), denominator: str(bottom["value"]), "currency": top["currency"]})
        for metric in sorted(_FLOW_METRICS):
            account = accounts.get(metric)
            if not account or account["previous"] is None or account["previous"] <= 0:
                missing.append(f"{metric}_yoy_pct: 비교 가능한 동기값 부족 또는 전기값이 0 이하")
                continue
            append_evidence(f"{metric}_yoy_pct", (account["value"] / account["previous"] - 1) * 100, "%",
                            "(current / previous_comparable_period - 1) * 100",
                            {"current": str(account["value"]), "previous_comparable_period": str(account["previous"]),
                             "currency": account["currency"], "current_field": account["current_field"],
                             "previous_field": account["previous_field"], "previous_period_label": account["previous_label"]},
                            previous=True)
        result["limitations"].extend(missing)
        result["status"] = "complete" if not missing else "partial" if result["evidence"] else "unavailable"
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    return get_financial_evidence
