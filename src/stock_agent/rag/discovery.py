"""회사·기준일·역할에 따라 검색 가능한 실제 공시 접수번호 선택."""

import datetime as dt
import re
from zoneinfo import ZoneInfo

from stock_agent.vendors.dart_client import list_disclosure_reports


def report_period(report: dict) -> str | None:
    """DART 제목에 명시된 보고기간 YYYY.MM을 반환하며 추측하지 않는다."""
    match = re.search(r"\((\d{4})\.(\d{2})\)", report["report_nm"])
    if match and 1 <= int(match[2]) <= 12:
        return f"{match[1]}.{match[2]}"
    return None


def _correction_reason(report: dict) -> str | None:
    if "철" in report.get("rm", "") or "철회" in report["report_nm"]:
        return "withdrawal_unresolved"
    if "정" in report.get("rm", "") or "정정" in report["report_nm"]:
        return "correction_unresolved"
    return None


def _canonical_title(report: dict) -> str:
    return re.sub(r"\[[^\]]*\]", "", report["report_nm"]).strip()


def validate_disclosure_scope(corp_code: str, as_of_date: str,
                              query_start_date: str, query_end_date: str,
                              scope: str) -> None:
    """코드가 고정한 회사·날짜·역할 범위를 검증하며 잘못된 값은 ValueError."""
    cutoff = dt.date.fromisoformat(as_of_date)
    start, end = dt.date.fromisoformat(query_start_date), dt.date.fromisoformat(query_end_date)
    if (not re.fullmatch(r"\d{8}", corp_code) or scope not in {"business", "event"}
            or start > end or end > cutoff or cutoff > dt.datetime.now(ZoneInfo("Asia/Seoul")).date()):
        raise ValueError("공시의 회사·기준일·조회 기간·역할이 잘못됐습니다.")


def discover_disclosures(corp_code: str, as_of_date: str, query_start_date: str,
                         query_end_date: str, scope: str) -> dict:
    """역할별 발견 후 회사·접수일·정정 상태를 재검사해 최대 두 공시를 선택한다.

    Business는 기준일 전 550달력일의 정기보고서에서 최신 두 보고기간을 선택한다.
    Event는 요청한 접수 기간의 모든 유형을 최신 접수순으로 선택한다.
    Returns: reports, limitations, reason. reason은 정상 부재와 정정 미확인 구분.
    Raises: 입력 ValueError 및 DART API 오류 전파. 원문 저장·검색은 수행하지 않는다.
    목록의 정정·철회 표시는 발생 시각이 없어 과거 당시의 상태로 단정하지 않는다.
    """
    validate_disclosure_scope(corp_code, as_of_date, query_start_date, query_end_date, scope)
    cutoff = dt.date.fromisoformat(as_of_date)
    start = ((cutoff - dt.timedelta(days=549)).isoformat()
             if scope == "business" else query_start_date)
    end = as_of_date if scope == "business" else query_end_date
    reports = list_disclosure_reports(corp_code, start, end, report_type=None,
                                      disclosure_type="A" if scope == "business" else None)
    valid = []
    limitations = []
    for report in reports:
        required = {"corp_code", "rcept_no", "rcept_dt", "report_nm"}
        if (not isinstance(report, dict) or not required <= report.keys()
                or any(not isinstance(report[key], str) for key in required)
                or not isinstance(report.get("rm", ""), str)):
            raise ValueError("DART 목록의 필수 필드 누락 또는 형식 오류")
        published = dt.datetime.strptime(report["rcept_dt"], "%Y%m%d").date().isoformat()
        if report["corp_code"] != corp_code or not start <= published <= end:
            continue
        if not re.fullmatch(r"\d{14}", report["rcept_no"]):
            raise ValueError("DART 목록의 접수번호 오류")
        valid.append(report)
    if not valid:
        return {"reports": [], "limitations": ["공시 조회 범위에 대상 문서 없음"], "reason": "no_documents"}
    # 동일 제목의 정정이 발견되면 원본의 rm 누락도 우회 경로로 사용하지 않는다.
    blocked_titles = {_canonical_title(r) for r in valid if _correction_reason(r)}
    excluded = [r for r in valid if _canonical_title(r) in blocked_titles]
    if excluded:
        limitations.append("정정·철회 관계 또는 발생 시점 미확인으로 해당 제목의 공시 제외. 기준일 당시 무효라는 판정은 아님")
    if scope == "business":
        periodic = [r for r in valid if report_period(r) is not None]
        if len(periodic) < len(valid):
            limitations.append("제목에서 보고기간을 확인하지 못한 정기공시 제외")
        available_periods = sorted({report_period(r) for r in periodic}, reverse=True)
        periods = available_periods[:2]
        if len(available_periods) > 2:
            limitations.append("기준일 전 550달력일에서 최신 두 보고기간만 원문 조사. 더 오래된 기간 비교는 미확인")
        selected = []
        for index, period in enumerate(periods):
            group = [r for r in periodic if report_period(r) == period]
            if any(_canonical_title(r) in blocked_titles for r in group):
                if index == 0:
                    return {"reports": [], "limitations": limitations + ["최신 보고기간의 확정본 미확인. 이전 보고서를 최신 기준 자료로 대체하지 않음"],
                            "reason": "unresolved_correction"}
                continue
            selected.append(max(group, key=lambda r: (r["rcept_dt"], r["rcept_no"])))
        if not selected:
            return {"reports": [], "limitations": limitations or ["보고기간을 확인할 수 있는 정기보고서 없음"],
                    "reason": "no_eligible_documents"}
        if any(not query_start_date <= dt.datetime.strptime(r["rcept_dt"], "%Y%m%d").date().isoformat()
               <= query_end_date for r in selected):
            limitations.append("사업 기준 자료 확보를 위해 사건 조회 기간 밖의 기준일 이전 정기보고서 포함. 각 출처의 보고기간·접수일 확인 필요")
    else:
        eligible = [r for r in valid if _canonical_title(r) not in blocked_titles]
        eligible.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]), reverse=True)
        selected = eligible[:2]
        if len(eligible) > 2:
            limitations.append(f"조회 범위의 적격 공시 {len(eligible)}건 중 최신 2건만 원문 조사. 전체 사건을 조사한 결과가 아님")
        if not selected:
            return {"reports": [], "limitations": limitations, "reason": "unresolved_correction"}
    return {"reports": selected, "limitations": limitations, "reason": None}
