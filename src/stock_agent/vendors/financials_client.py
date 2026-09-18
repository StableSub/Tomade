"""DART 정기보고서의 공개 시점과 재무 API 접수번호를 대조하는 연동."""

import calendar
import os
import re
from datetime import date, datetime, timedelta

import requests

from stock_agent.control.external_budget import check_external_budget

_BASE_URL = "https://opendart.fss.or.kr/api"
_REPORT_CODES = {("사업보고서", 12): "11011", ("반기보고서", 6): "11012",
                 ("분기보고서", 3): "11013", ("분기보고서", 9): "11014"}


class FinancialAPIError(RuntimeError):
    """재무 외부 경계 오류. 인증키·응답 URL 없이 코드와 재시도 가능성 보관."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _request(endpoint: str, params: dict) -> dict:
    key = os.getenv("DART_OPENAPI_KEY")
    if not key:
        raise FinancialAPIError("missing_configuration", "DART_OPENAPI_KEY 설정 필요")
    try:
        check_external_budget()
        response = requests.get(f"{_BASE_URL}/{endpoint}.json",
                                params={"crtfc_key": key, **params}, timeout=(5, 20))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status = getattr(exc.response, "status_code", None)
        retryable = status is None or status == 429 or status >= 500
        raise FinancialAPIError("http_error", "DART 통신 실패. 설정과 연결 상태 확인", retryable) from None
    except ValueError:
        raise FinancialAPIError("invalid_response", "DART JSON 응답 확인 불가") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise FinancialAPIError("invalid_response", "DART 상태 코드 확인 불가")
    if payload["status"] not in {"000", "013"}:
        code = payload["status"]
        raise FinancialAPIError(f"dart_{code}", f"DART 오류 {code}. 인증·할당량·서비스 상태 확인",
                                code in {"020", "800", "900"})
    if payload["status"] == "000" and (not isinstance(payload.get("list"), list)
                                       or any(not isinstance(row, dict) for row in payload["list"])):
        raise FinancialAPIError("invalid_response", "DART 목록 형식 확인 불가")
    return payload


def get_financial_snapshot(corp_code: str, as_of_date: str) -> dict:
    """기준일까지 공개된 최신 회계기간 한 개의 재무 원행을 조회한다.

    Args:
        corp_code: 검증된 8자리 DART 회사 코드.
        as_of_date: ISO 조회 기준일. 미래 날짜 검증은 호출 Tool 책임.
    Returns:
        rows, report, basis, limitations를 포함한 dict. 자료 없음·시점 불일치는
        빈 rows와 이유를 반환. 12월 결산 확인 회사만 지원하며 조회 범위는 730일,
        목록 최대 2페이지와 재무 CFS/OFS 최대 2회로 제한한다.
    Raises:
        ValueError: 입력 형식 오류. FinancialAPIError: 통신·인증·응답 오류.
        외부 GET 호출 외 파일 쓰기와 자동 재시도는 없다.
    """
    if not re.fullmatch(r"\d{8}", corp_code):
        raise ValueError("corp_code는 8자리 숫자 필요")
    cutoff = date.fromisoformat(as_of_date)
    result = {"rows": [], "report": None, "basis": None, "limitations": []}
    reports = []
    for page in (1, 2):
        payload = _request("list", {
            "corp_code": corp_code, "bgn_de": (cutoff - timedelta(days=729)).strftime("%Y%m%d"),
            "end_de": cutoff.strftime("%Y%m%d"), "pblntf_ty": "A", "last_reprt_at": "N",
            "sort": "date", "sort_mth": "desc", "page_count": 100, "page_no": page,
        })
        if payload["status"] == "013":
            break
        reports.extend(payload["list"])
        try:
            total_pages = int(payload["total_page"])
        except (KeyError, ValueError, TypeError):
            raise FinancialAPIError("invalid_response", "DART 목록 페이지 수 확인 불가") from None
        if total_pages <= page:
            break
        if page == 2:
            result["limitations"].append("정기공시 목록은 최근 730일·200건까지만 확인")

    candidates = []
    for report in reports:
        if report.get("corp_code") != corp_code or "철" in str(report.get("rm", "")):
            continue
        match = re.search(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)",
                          str(report.get("report_nm", "")))
        try:
            published = datetime.strptime(str(report.get("rcept_dt", "")), "%Y%m%d").date()
        except ValueError:
            continue
        if not match or published > cutoff or not re.fullmatch(r"\d{14}", str(report.get("rcept_no", ""))):
            continue
        kind, year, month = match.group(1), int(match.group(2)), int(match.group(3))
        if not 1 <= month <= 12 or year < 2015:
            continue
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        if period_end > published:
            continue
        candidates.append({**report, "kind": kind, "year": year, "month": month,
                           "published_at": published.isoformat(), "period_end": period_end.isoformat()})
    annual = [report for report in candidates if report["kind"] == "사업보고서"]
    if not annual or max(annual, key=lambda report: report["period_end"])["month"] != 12:
        result["limitations"].append("12월 결산 여부를 확인하지 못했거나 지원하지 않는 결산월")
        return result
    candidates = [report for report in candidates if (report["kind"], report["month"]) in _REPORT_CODES]
    report = max(candidates, key=lambda row: (row["period_end"], row["published_at"], row["rcept_no"]))
    report["report_code"] = _REPORT_CODES[report["kind"], report["month"]]
    result["report"] = report
    for basis in ("CFS", "OFS"):
        payload = _request("fnlttSinglAcntAll", {
            "corp_code": corp_code, "bsns_year": str(report["year"]),
            "reprt_code": report["report_code"], "fs_div": basis,
        })
        if payload["status"] == "013":
            continue
        rows = payload["list"]
        if not rows:
            raise FinancialAPIError("invalid_response", "정상 상태의 재무 응답에 계정 없음")
        # API는 접수번호 선택 인자가 없으므로 기준일 이전 보고서와 완전히 일치해야 사용.
        if any(row.get("rcept_no") != report["rcept_no"] for row in rows):
            result["limitations"].append("재무 API 접수번호와 기준일까지 확인한 최신 보고서 불일치. 정정 전 수치 복원 불가")
            return result
        if any(row.get("corp_code") != corp_code or row.get("bsns_year") != str(report["year"])
               or row.get("reprt_code") != report["report_code"]
               or row.get("fs_div", basis) != basis for row in rows):
            result["limitations"].append("재무 응답의 회사·회계기간·연결/별도 조건 불일치")
            return result
        result.update(rows=rows, basis=basis)
        if basis == "OFS":
            result["limitations"].append("연결 재무자료 없음. 전체 지표를 별도 재무제표 기준으로 계산")
        result["limitations"].append("현재 DART 응답과 접수번호를 대조한 값. 정정 이력 전체와 과거 당시 수치의 완전한 재현은 미검증")
        return result
    result["limitations"].append("선택한 보고서의 연결·별도 재무 API 자료 없음")
    return result
