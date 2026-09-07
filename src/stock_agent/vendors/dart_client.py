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
