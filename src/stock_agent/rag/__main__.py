"""공시 한 개 준비와 독립 검색용 CLI. 실패 뒤 자동 개선·재검색 없음."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAIError
from requests import RequestException

from stock_agent.rag.service import DEFAULT_ROOT, prepare_report, search_evidence
from stock_agent.vendors.dart_client import list_disclosure_reports


def main() -> int:
    """명령행 인자를 검증해 원문 하나를 준비하거나 검색 결과를 JSON 출력한다.

    --env-file은 키를 환경에 로드하되 출력하지 않는다. 네트워크/입력 실패는
    오류 종류만 출력하고 1을 반환한다. 결과 없음은 빈 근거 목록으로 반환한다.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--env-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--corp-code", required=True)
    prepare.add_argument("--start", required=True)
    prepare.add_argument("--as-of", required=True)
    prepare.add_argument("--receipt", required=True)
    prepare.add_argument("--report-type", default="A001")
    search = sub.add_parser("search")
    search.add_argument("--corp-code", required=True)
    search.add_argument("--as-of", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--receipt", action="append")
    search.add_argument("--section", default="")
    args = parser.parse_args()
    if args.env_file: load_dotenv(args.env_file)
    try:
        if args.command == "prepare":
            reports = list_disclosure_reports(args.corp_code, args.start, args.as_of, args.report_type)
            args.root.mkdir(parents=True, exist_ok=True)
            (args.root / "discovery.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
            selected = next((r for r in reports if r["rcept_no"] == args.receipt), None)
            if selected is None: raise ValueError("조회 범위에 없는 접수번호")
            result = prepare_report(selected, args.root)
        else:
            result = search_evidence(args.query, args.corp_code, args.as_of, args.root,
                                     receipt_ids=args.receipt, section_hint=args.section)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RequestException, OpenAIError, ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
