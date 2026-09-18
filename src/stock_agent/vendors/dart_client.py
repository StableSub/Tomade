"""DART OpenAPI 클라이언트 (공시 조회 + 종목코드 해석)."""

import io
import os
import zipfile
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://opendart.fss.or.kr/api"
# 캐시: XML 전체(약 8MB)를 한 번만 다운로드하기 위한 모듈 수준 저장
_corp_codes: dict[str, str] | None = None      # {"삼성전자": "00126380", ...} 고유번호
_name_to_ticker: dict[str, str] | None = None  # {"삼성전자": "005930", ...} 종목코드


def _get_api_key() -> str:
    """환경변수에서 DART API 키를 읽고, 없으면 KeyError를 발생시킨다."""
    return os.environ["DART_OPENAPI_KEY"]


def _load_company_data() -> None:
    """CORPCODE.xml을 다운로드해 두 캐시(고유번호 맵, 종목코드 맵)를 채운다.

    DART의 회사 목록에는 상장 여부를 나타내는 stock_code가 포함되어 있다.
    stock_code가 있는 회사만 상장사로 간주한다.
    """
    global _corp_codes, _name_to_ticker

    if _corp_codes is not None:
        return  # 이미 로드됨

    response = requests.get(
        f"{_BASE_URL}/corpCode.xml",
        params={"crtfc_key": _get_api_key()},
        timeout=60,
    )
    response.raise_for_status()

    # 응답은 zip으로 압축된 CORPCODE.xml → 풀어서 파싱
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        xml = zf.read("CORPCODE.xml").decode("utf-8")

    _corp_codes = {}
    _name_to_ticker = {}
    for item in ET.fromstring(xml).iter("list"):
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()
        if not (corp_name and stock_code):
            continue  # 비상장사는 건너뜀

        _corp_codes[corp_name] = item.findtext("corp_code")
        _name_to_ticker[corp_name] = stock_code


def find_corp_code(corp_name: str) -> str | None:
    """정확한 회사명을 DART 고유번호로 변환한다.

    Args:
        corp_name: DART 회사 목록에서 찾을 정확한 한국 회사명.

    Returns:
        일치하는 8자리 DART 고유번호. 상장사를 찾지 못하면 `None`.
        최초 호출에서는 DART 회사 목록을 다운로드하고 이후 캐시를 재사용한다.
    """
    _load_company_data()
    return _corp_codes.get(corp_name)


def find_ticker_by_name(corp_name: str) -> str | None:
    """정확한 회사명을 상장 종목코드로 변환한다.

    Args:
        corp_name: DART 회사 목록에서 찾을 정확한 한국 회사명.

    Returns:
        일치하는 6자리 종목코드. 상장사를 찾지 못하면 `None`.
        KRX 목록 API 대신 캐시된 DART 회사 목록을 사용한다.
    """
    _load_company_data()
    return _name_to_ticker.get(corp_name)


def get_disclosures(corp_name: str, days: int = 30, max_count: int = 10) -> list[dict]:
    """최근 N일간 주요 공시 목록을 조회한다.

    Args:
        corp_name: 정확한 한국 회사명
        days: 조회 기간(일)
        max_count: 최대 공시 수

    Returns:
        날짜·제목·원문 URL을 가진 공시 딕셔너리 목록. 공시가 없거나 DART가
        데이터 없음 상태를 반환하면 빈 목록을 반환한다.

    Raises:
        ValueError: 회사명을 DART 상장사 목록에서 찾을 수 없는 경우.
        requests.RequestException: DART HTTP 요청 또는 응답 검증이 실패한 경우.
    """
    corp_code = find_corp_code(corp_name)
    if corp_code is None:
        raise ValueError(f"DART에서 회사를 찾을 수 없습니다: {corp_name}")

    import datetime

    end = datetime.date.today()
    begin = end - datetime.timedelta(days=days)

    response = requests.get(
        f"{_BASE_URL}/list.json",
        params={
            "crtfc_key": _get_api_key(),
            "corp_code": corp_code,
            "bgn_de": begin.strftime("%Y%m%d"),
            "page_count": min(max_count, 100),
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    # status "000"이 정상. "013"은 데이터 없음 등 → 빈 목록 반환
    if data.get("status") != "000":
        return []

    return [
        {
            "date": item.get("rcept_dt", ""),
            "title": item.get("report_nm", ""),
            "url": f"https://dart.fss.or.kr/dsab007/view.do?rcept_no={item.get('rcept_no', '')}",
        }
        for item in data.get("list", [])
    ]


def list_disclosure_reports(corp_code: str, start: str, end: str,
                            report_type: str | None = "A001", *,
                            disclosure_type: str | None = None, max_pages: int = 10) -> list[dict]:
    """명시한 회사·접수 기간의 공시를 모든 페이지에서 조회한다.

    Args: corp_code는 8자리 DART 코드, start/end는 ISO 날짜,
        report_type은 DART 상세 유형 또는 None, disclosure_type은 A~J 대분류다.
        둘 다 None이면 모든 유형. max_pages는 1~10으로 API 조회를 제한한다.
    Returns: 접수번호·접수일·정정 비고를 유지한 목록. 데이터 없음만 빈 목록.
    Raises: 입력 오류는 ValueError, DART 오류는 RuntimeError,
        통신 오류는 requests.RequestException. API 키는 반환하지 않는다.
    """
    import datetime
    import re

    if not re.fullmatch(r"\d{8}", corp_code):
        raise ValueError("회사 코드는 8자리 숫자여야 합니다.")
    begin, finish = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    if (begin > finish or (report_type is not None and not re.fullmatch(r"[A-J]\d{3}", report_type))
            or (disclosure_type is not None and not re.fullmatch(r"[A-J]", disclosure_type))
            or not 1 <= max_pages <= 10):
        raise ValueError("조회 기간 또는 공시 유형·페이지 한도가 잘못됐습니다.")
    reports, page = [], 1
    while True:
        params = {
            "crtfc_key": _get_api_key(), "corp_code": corp_code,
            "bgn_de": begin.strftime("%Y%m%d"), "end_de": finish.strftime("%Y%m%d"),
            "last_reprt_at": "N", "page_count": 100, "page_no": page,
            "sort": "date", "sort_mth": "desc",
        }
        if report_type is not None:
            params["pblntf_detail_ty"] = report_type
        if disclosure_type is not None:
            params["pblntf_ty"] = disclosure_type
        response = requests.get(f"{_BASE_URL}/list.json", params=params, timeout=(5, 30))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("DART 목록 응답 형식 오류")
        if data.get("status") == "013":
            return reports
        if data.get("status") != "000":
            status = str(data.get("status", "unknown"))
            status = status if re.fullmatch(r"\d{3}", status) else "unknown"
            raise RuntimeError(f"DART 목록 오류: {status}")
        entries = data.get("list")
        if not isinstance(entries, list):
            raise ValueError("DART 공시 목록 필드 오류")
        try:
            total_pages = int(data["total_page"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("DART 공시 페이지 필드 오류") from exc
        reports.extend(entries)
        if page >= total_pages:
            return reports
        if page >= max_pages:
            raise RuntimeError("DART 공시 목록 페이지 한도 초과")
        page += 1


def download_disclosure_original(receipt_id: str) -> bytes:
    """14자리 접수번호의 공시 원문 ZIP을 다운로드한다.

    Returns: 원본 ZIP bytes. 저장 부작용은 없으며 API 호출만 수행한다.
    Raises: 잘못된 번호·ZIP은 ValueError, DART 오류는 RuntimeError,
        통신 실패는 requests.RequestException. 오류 메시지에 키를 포함하지 않는다.
    """
    import re

    if not re.fullmatch(r"\d{14}", receipt_id):
        raise ValueError("접수번호는 14자리 숫자여야 합니다.")
    response = requests.get(f"{_BASE_URL}/document.xml", params={
        "crtfc_key": _get_api_key(), "rcept_no": receipt_id,
    }, timeout=(5, 30))
    response.raise_for_status()
    payload = response.content
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
            raise ValueError("지원하지 않는 XML 선언입니다.")
        try:
            error = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError("DART 원문 응답이 ZIP 또는 오류 XML 형식이 아닙니다.") from exc
        status = error.findtext("status", "unknown")
        status = status if re.fullmatch(r"\d{3}", status) else "unknown"
        raise RuntimeError(f"DART 원문 오류: {status}")
    return payload
