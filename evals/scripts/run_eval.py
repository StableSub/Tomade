"""Parsing과 Routing 평가를 반복 실행하고 비교 가능한 결과를 저장한다."""

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from stock_agent.agents.orchestrator import (
    SYSTEM_PROMPT,
    upper_agent_node,
)
from stock_agent.control.request_parser import (
    SYSTEM_PROMPT as PARSER_SYSTEM_PROMPT,
)
from stock_agent.control.request_parser import request_parsing_node
from stock_agent.gateways.llm import get_chat_model

from dataset_io import EVAL_ROOT, load_dataset, write_json
from validate_datasets import validate_datasets

AVAILABLE_SUITES = ("parsing", "routing")
DATASET_FILES = {
    "parsing": "input_parsing.json",
    "routing": "planner_routing.json",
}


def parse_args() -> argparse.Namespace:
    """명령행에서 평가 suite, 반복 횟수와 결과 label을 읽는다."""
    parser = argparse.ArgumentParser(
        description="StockAgent의 Parsing과 Routing 평가를 실행합니다.",
    )
    parser.add_argument(
        "--suite",
        default="all",
        help="실행할 suite를 쉼표로 구분합니다: parsing,routing 또는 all",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="LLM 기반 사례의 반복 실행 횟수입니다.",
    )
    parser.add_argument(
        "--label",
        default="baseline",
        help="결과 디렉터리를 구분할 실험 이름입니다.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="특정 case만 실행합니다. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        help="같은 평가 계약으로 저장한 runs.json과 사례별 성공 횟수를 비교합니다.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="제품 노드의 디버그 출력을 터미널에 함께 표시합니다.",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs는 1 이상이어야 합니다.")
    return args


def resolve_suites(raw_value: str) -> list[str]:
    """쉼표로 구분된 suite 입력을 중복 없는 실행 순서로 정규화한다.

    Args:
        raw_value: `all` 또는 parsing, routing의 쉼표 구분 문자열.

    Returns:
        `AVAILABLE_SUITES` 순서로 정렬된 suite 이름 목록.

    Raises:
        ValueError: 지원하지 않는 suite 이름이 포함된 경우.
    """
    requested = {value.strip() for value in raw_value.split(",") if value.strip()}
    if requested == {"all"}:
        return list(AVAILABLE_SUITES)
    invalid = requested - set(AVAILABLE_SUITES)
    if not requested or invalid:
        names = ", ".join(sorted(invalid)) or "(비어 있음)"
        raise ValueError(f"지원하지 않는 suite입니다: {names}")
    return [suite for suite in AVAILABLE_SUITES if suite in requested]


def to_json_value(value: Any) -> Any:
    """Pydantic 객체를 포함한 실행 결과를 JSON 직렬화 가능한 값으로 바꾼다."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    return value


def invoke_node(
    node: Callable[[dict[str, Any]], dict[str, Any]],
    state: dict[str, Any],
    *,
    verbose: bool,
) -> dict[str, Any]:
    """제품 노드를 호출하고 기본 모드에서는 개발용 stdout 출력을 숨긴다."""
    if verbose:
        return node(state)
    with contextlib.redirect_stdout(io.StringIO()):
        return node(state)


def base_result(
    *,
    suite: str,
    case_id: str,
    run_index: int,
    started_at: float,
) -> dict[str, Any]:
    """모든 suite가 공유하는 사례 식별자와 실행 시간을 만든다."""
    return {
        "suite": suite,
        "case_id": case_id,
        "run_index": run_index,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }


def error_result(
    *,
    suite: str,
    case_id: str,
    run_index: int,
    started_at: float,
    error: Exception,
) -> dict[str, Any]:
    """평가 실행 자체가 실패한 사례를 나머지 결과와 같은 형태로 반환한다."""
    return {
        **base_result(
            suite=suite,
            case_id=case_id,
            run_index=run_index,
            started_at=started_at,
        ),
        "status": "error",
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }


def run_parsing_case(
    case: dict[str, Any],
    run_index: int,
    *,
    verbose: bool,
) -> dict[str, Any]:
    """고정 날짜·회사 매핑으로 Parser를 실행하고 필드와 오류 사유 패턴을 채점한다.

    의미 보존과 자유문장 오류 사유의 완전한 의미 판정은 미평가로 남긴다.
    모듈 patch를 사용하므로 이 평가 함수는 한 프로세스에서 순차 실행한다.
    """
    started_at = time.perf_counter()
    fixed_today = datetime.date.fromisoformat(case["today"])
    companies = json.loads(
        (EVAL_ROOT / "fixtures/companies.json").read_text(encoding="utf-8")
    )["companies"]

    class EvalDate(datetime.date):
        @classmethod
        def today(cls):
            return fixed_today

    try:
        # Parser 모듈만 고정한다. 실행 시간·Trace의 실제 시계는 변경하지 않는다.
        with (
            patch("stock_agent.control.request_parser.datetime", SimpleNamespace(date=EvalDate)),
            patch(
                "stock_agent.control.request_parser.dart_client.find_ticker_by_name",
                side_effect=lambda name: companies.get(name.strip()),
            ),
        ):
            output = invoke_node(
                request_parsing_node,
                {"raw_user_input": case["raw_user_input"]},
                verbose=verbose,
            )
    except Exception as error:
        return error_result(
            suite="parsing",
            case_id=case["case_id"],
            run_index=run_index,
            started_at=started_at,
            error=error,
        )

    expected = case.get("expected")
    input_error = output.get("input_error")
    if expected is None:
        checks = {
            "expected_error_detected": bool(input_error),
            "no_research_mandate": not output.get("research_mandate"),
            "error_reason_pattern": bool(
                re.search(case["expected_error_pattern"], input_error or "")
            ),
        }
        actual = {
            "input_error": input_error,
            "parsed_request": to_json_value(output.get("parsed_request")),
        }
    else:
        mandate = output.get("research_mandate") or {}
        expected_date = expected["as_of_date"]
        checks = {
            "no_input_error": input_error is None,
            "corp_name": mandate.get("corp_name") == expected["corp_name"],
            "ticker": mandate.get("ticker") == expected["ticker"],
            "period_days": mandate.get("period_days") == expected["period_days"],
            "as_of_date": mandate.get("as_of_date") == expected_date,
        }
        actual = {
            "research_mandate": mandate,
            "parsed_request": to_json_value(output.get("parsed_request")),
        }

    passed = all(checks.values())
    return {
        **base_result(
            suite="parsing",
            case_id=case["case_id"],
            run_index=run_index,
            started_at=started_at,
        ),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "unscored": ["question_intent", "error_reason_semantics"],
        "expected": {
            "normalized_fields": expected,
            "error_rubric": case.get("expected_error"),
            "question_intent": case["expected_question_intent"],
        },
        "actual": actual,
    }


def build_routing_mandate(case: dict[str, Any]) -> dict[str, Any]:
    """Routing 사례의 질문을 Planner가 소비하는 ResearchMandate로 만든다."""
    return {
        "original_question": case["question"],
        "research_question": case["question"],
        "ticker": case["ticker"],
        "corp_name": case["corp_name"],
        "as_of_date": case["as_of_date"],
        "period_days": case["period_days"],
        "purpose": "근거 기반 종목 리서치와 투자 판단 지원",
        "constraints": [
            "투자 의견에는 근거, 판단 조건, 반대 요인과 불확실성을 함께 제시한다.",
            "수익을 보장하거나 자동 주문을 실행하지 않는다.",
            "확인된 사실과 해석을 구분한다.",
            "분석 기준일 이후의 정보를 사용하지 않는다.",
        ],
    }


def run_routing_case(
    case: dict[str, Any],
    run_index: int,
    *,
    verbose: bool,
) -> dict[str, Any]:
    """Planner를 실행하고 기대 Agent 집합의 정확도와 재현용 Plan을 저장한다."""
    started_at = time.perf_counter()
    try:
        output = invoke_node(
            upper_agent_node,
            {"raw_user_input": (f"{case['corp_name']} ({case['ticker']}) "
                                f"기준일 {case['as_of_date']}, 최근 {case['period_days']}일. {case['question']}"),
             "research_only": True},
            verbose=verbose,
        )
    except Exception as error:
        return error_result(
            suite="routing",
            case_id=case["case_id"],
            run_index=run_index,
            started_at=started_at,
            error=error,
        )

    plan = output["research_plan"]
    expected_agents = set(case["expected_agents"])
    actual_agents = {task.agent for task in plan.tasks}
    checks = {
        "exact_agent_match": actual_agents == expected_agents,
        "all_required_agents_selected": expected_agents <= actual_agents,
        "no_unexpected_agents": actual_agents <= expected_agents,
    }
    passed = checks["exact_agent_match"]
    return {
        **base_result(
            suite="routing",
            case_id=case["case_id"],
            run_index=run_index,
            started_at=started_at,
        ),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "expected_agents": sorted(expected_agents),
        "actual_agents": sorted(actual_agents),
        "required_agent_recall": round(
            len(expected_agents & actual_agents) / len(expected_agents),
            4,
        ),
        "routing_precision": round(
            len(expected_agents & actual_agents) / len(actual_agents),
            4,
        ) if actual_agents else 0.0,
        "research_plan": to_json_value(plan),
        "unscored": ["question_coverage", "role_fit", "question_duplication"],
    }


RUNNERS = {
    "parsing": run_parsing_case,
    "routing": run_routing_case,
}


def filter_cases(
    cases: list[dict[str, Any]],
    requested_case_ids: set[str],
) -> list[dict[str, Any]]:
    """case ID 필터가 있으면 해당 사례만 입력 순서대로 반환한다."""
    if not requested_case_ids:
        return cases
    return [case for case in cases if case["case_id"] in requested_case_ids]


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """전체 실행 결과를 suite별 성공률, 지연 시간과 Routing 지표로 집계한다."""
    summary: dict[str, Any] = {
        "total_runs": len(results),
        "passed": sum(result["status"] == "pass" for result in results),
        "failed": sum(result["status"] == "fail" for result in results),
        "errors": sum(result["status"] == "error" for result in results),
        "suites": {},
    }
    summary["pass_rate"] = round(
        summary["passed"] / summary["total_runs"],
        4,
    ) if summary["total_runs"] else 0.0
    summary["cases"] = {}
    for result in results:
        counts = summary["cases"].setdefault(
            result["case_id"], {"runs": 0, "passed": 0, "failed": 0, "errors": 0}
        )
        counts["runs"] += 1
        counts[{"pass": "passed", "fail": "failed", "error": "errors"}[result["status"]]] += 1

    by_suite: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_suite[result["suite"]].append(result)

    for suite in AVAILABLE_SUITES:
        suite_results = by_suite.get(suite)
        if not suite_results:
            continue
        passed = sum(result["status"] == "pass" for result in suite_results)
        suite_summary: dict[str, Any] = {
            "runs": len(suite_results),
            "passed": passed,
            "failed": sum(result["status"] == "fail" for result in suite_results),
            "errors": sum(result["status"] == "error" for result in suite_results),
            "pass_rate": round(passed / len(suite_results), 4),
            "average_latency_ms": round(
                sum(result["latency_ms"] for result in suite_results)
                / len(suite_results),
                2,
            ),
        }
        if suite == "routing":
            scored = [
                result for result in suite_results if result["status"] != "error"
            ]
            suite_summary["required_agent_recall"] = _average_metric(
                scored,
                "required_agent_recall",
            )
            suite_summary["routing_precision"] = _average_metric(
                scored,
                "routing_precision",
            )
            suite_summary["routing_consistency"] = routing_consistency(scored)
        summary["suites"][suite] = suite_summary
    return summary


def _average_metric(results: list[dict[str, Any]], key: str) -> float:
    """키가 존재하는 결과들의 산술 평균을 네 자리로 반환한다."""
    values = [result[key] for result in results if key in result]
    return round(sum(values) / len(values), 4) if values else 0.0


def routing_consistency(results: list[dict[str, Any]]) -> float:
    """같은 사례 반복 실행 중 가장 자주 선택된 Agent 조합의 평균 비율을 계산한다."""
    by_case: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for result in results:
        by_case[result["case_id"]].append(tuple(result["actual_agents"]))
    consistency = [
        Counter(routes).most_common(1)[0][1] / len(routes)
        for routes in by_case.values()
        if routes
    ]
    return round(sum(consistency) / len(consistency), 4) if consistency else 0.0


def current_model_config(suites: list[str]) -> dict[str, Any]:
    """실행할 모델의 적용 설정만 기록하며 API 키·헤더 등은 읽어 내보내지 않는다.

    Args:
        suites: 실행할 parsing/routing 목록.
    Returns:
        역할별 모델 이름, API 경로 종류와 추론·샘플링 설정.
    """
    result = {}
    for suite in suites:
        role = "parser" if suite == "parsing" else "planner"
        model = get_chat_model(role)
        result[role] = {
            "model": model.model_name,
            "provider": "openrouter" if model.openai_api_base == "https://openrouter.ai/api/v1" else "openai",
            "use_responses_api": model.use_responses_api,
            "temperature": model.temperature,
            "reasoning_effort": model.reasoning_effort,
            "reasoning": model.reasoning,
        }
    return result


def contract_hashes() -> dict[str, str]:
    """채점 코드·데이터·회사 Fixture의 SHA-256을 비교 계약으로 반환한다."""
    paths = [
        EVAL_ROOT / "scripts/run_eval.py",
        EVAL_ROOT / "scripts/validate_datasets.py",
        EVAL_ROOT / "scripts/dataset_io.py",
        EVAL_ROOT / "fixtures/companies.json",
        *(EVAL_ROOT / "datasets" / name for name in DATASET_FILES.values()),
    ]
    return {
        str(path.relative_to(EVAL_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def compare_runs(baseline: dict, metadata: dict, results: list[dict]) -> list[dict]:
    """같은 계약·사례·반복 수의 전후 성공 횟수를 비교한다.

    오류가 있는 사례는 판정 불가로 표시한다. 계약이 다르거나 예전 기록에
    계약 해시가 없으면 ValueError로 비교를 거부한다. 통계적 유의성은 주장하지 않는다.
    """
    for key in ("contract_hashes", "suites", "case_ids", "requested_runs"):
        if key not in baseline["metadata"] or baseline["metadata"][key] != metadata[key]:
            raise ValueError(f"비교 조건 불일치: {key}")
    before = summarize_results(baseline["runs"])["cases"]
    after = summarize_results(results)["cases"]
    if before.keys() != after.keys():
        raise ValueError("비교할 실제 사례 집합이 다릅니다.")
    comparisons = []
    for case_id, current in after.items():
        previous = before[case_id]
        if previous["runs"] != current["runs"]:
            raise ValueError(f"실제 반복 수 불일치: {case_id}")
        delta = current["passed"] - previous["passed"]
        verdict = (
            "unknown" if previous["errors"] or current["errors"]
            else "improved" if delta > 0
            else "regressed" if delta < 0
            else "unchanged"
        )
        comparisons.append({"case_id": case_id, "before": previous, "after": current, "verdict": verdict})
    return comparisons


def prompt_hashes() -> dict[str, str]:
    """Baseline과 변경 버전에서 Prompt 동일성을 확인할 SHA-256 앞 12자를 반환한다."""
    return {
        "parser": hashlib.sha256(PARSER_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
        "planner": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
    }


def render_report(metadata: dict[str, Any], summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    """JSON 요약과 실패 사례를 사람이 빠르게 읽을 수 있는 Markdown으로 렌더링한다."""
    lines = [
        f"# Evaluation Report — {metadata['label']}",
        "",
        f"- 시작: {metadata['started_at']}",
        f"- 종료: {metadata['finished_at']}",
        f"- Suite: {', '.join(metadata['suites'])}",
        f"- LLM 반복 횟수: {metadata['requested_runs']}",
        f"- 전체 실행: {summary['total_runs']}",
        f"- 통과: {summary['passed']}",
        f"- 실패: {summary['failed']}",
        f"- 실행 오류: {summary['errors']}",
        f"- 전체 통과율: {summary['pass_rate']:.2%}",
        "- 범위: 제품 계약 채점. 질문 의미·Plan 품질·금융 정확도는 미평가.",
        "",
        "## Suite 요약",
        "",
        "| Suite | 실행 | 통과율 | 평균 지연(ms) |",
        "|---|---:|---:|---:|",
    ]
    for suite, values in summary["suites"].items():
        lines.append(
            f"| {suite} | {values['runs']} | {values['pass_rate']:.2%} | "
            f"{values['average_latency_ms']:.2f} |"
        )

    routing = summary["suites"].get("routing")
    if routing:
        lines.extend(
            [
                "",
                "## Routing 지표",
                "",
                f"- Required Agent Recall: {routing['required_agent_recall']:.2%}",
                f"- Routing Precision: {routing['routing_precision']:.2%}",
                f"- 반복 일관성: {routing['routing_consistency']:.2%}",
            ]
        )

    lines.extend(["", "## 사례별 반복 결과", "", "| 사례 | 통과/실행 | 오류 |", "|---|---:|---:|"])
    for case_id, counts in summary["cases"].items():
        lines.append(f"| {case_id} | {counts['passed']}/{counts['runs']} | {counts['errors']} |")
    if "comparison" in summary:
        lines.extend(["", "## 이전 실행과 비교", "", "| 사례 | 이전 통과 | 현재 통과 | 판정 |", "|---|---:|---:|---|"])
        for item in summary["comparison"]:
            lines.append(f"| {item['case_id']} | {item['before']['passed']} | {item['after']['passed']} | {item['verdict']} |")
    unsuccessful = [result for result in results if result["status"] != "pass"]
    lines.extend(["", "## 실패 및 오류", ""])
    if not unsuccessful:
        lines.append("- 없음")
    else:
        for result in unsuccessful:
            label = (
                result["error"]["message"]
                if result["status"] == "error"
                else ", ".join(
                    name
                    for name, passed in result.get("checks", {}).items()
                    if not passed
                )
            )
            lines.append(
                f"- `{result['case_id']}` run {result['run_index']} "
                f"[{result['status']}]: {label}"
            )
    return "\n".join(lines) + "\n"


def result_directory(label: str, started_at: datetime.datetime) -> Path:
    """실험 label과 로컬 시각으로 충돌하지 않는 결과 디렉터리를 만든다."""
    safe_label = re.sub(r"[^\w.-]+", "-", label, flags=re.UNICODE).strip("-.")
    if not safe_label:
        raise ValueError("--label에 파일명으로 사용할 문자가 필요합니다.")
    timestamp = started_at.strftime("%Y%m%d-%H%M%S")
    return EVAL_ROOT / "results" / safe_label / timestamp


def main() -> None:
    """선택한 데이터셋을 실행하고 pretty JSON 및 Markdown 평가 결과를 저장한다."""
    args = parse_args()
    validate_datasets()
    suites = resolve_suites(args.suite)
    requested_case_ids = set(args.case_id)
    started_at = datetime.datetime.now().astimezone()
    results: list[dict[str, Any]] = []
    matched_case_ids: set[str] = set()
    selected = {
        suite: filter_cases(load_dataset(DATASET_FILES[suite]), requested_case_ids)
        for suite in suites
    }
    matched_case_ids = {case["case_id"] for cases in selected.values() for case in cases}
    if requested_case_ids - matched_case_ids:
        raise ValueError(f"선택한 suite에 없는 case: {sorted(requested_case_ids - matched_case_ids)}")
    if not matched_case_ids:
        raise ValueError("실행할 평가 사례가 없습니다.")
    baseline = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    metadata = {
        "suites": suites,
        "case_ids": sorted(matched_case_ids),
        "requested_runs": args.runs,
        "contract_hashes": contract_hashes(),
    }
    if baseline is not None:
        for key in metadata:
            if baseline["metadata"].get(key) != metadata[key]:
                raise ValueError(f"비교 조건 불일치: {key}. LLM 실행 전에 중단합니다.")
    models = current_model_config(suites)

    for suite in suites:
        cases = selected[suite]
        matched_case_ids.update(case["case_id"] for case in cases)
        repetitions = args.runs
        runner = RUNNERS[suite]
        for case in cases:
            for run_index in range(1, repetitions + 1):
                print(f"[{suite}] {case['case_id']} run {run_index}/{repetitions}")
                results.append(
                    runner(case, run_index, verbose=args.verbose)
                )

    finished_at = datetime.datetime.now().astimezone()
    metadata = {
        **metadata,
        "label": args.label,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "suites": suites,
        "requested_runs": args.runs,
        "case_ids": sorted(matched_case_ids),
        "models": models,
        "prompt_hashes": prompt_hashes(),
        "implementation_hashes": {
            str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SRC_DIR.rglob("*.py"))
        },
    }
    summary = summarize_results(results)
    if baseline is not None:
        summary["comparison"] = compare_runs(baseline, metadata, results)
    output_dir = result_directory(args.label, started_at)
    write_json(output_dir / "runs.json", {"metadata": metadata, "runs": results})
    write_json(output_dir / "summary.json", {"metadata": metadata, "summary": summary})
    (output_dir / "report.md").write_text(
        render_report(metadata, summary, results),
        encoding="utf-8",
    )

    print(f"results: {output_dir}")
    print(
        f"pass={summary['passed']} fail={summary['failed']} "
        f"error={summary['errors']} pass_rate={summary['pass_rate']:.2%}"
    )


if __name__ == "__main__":
    main()
