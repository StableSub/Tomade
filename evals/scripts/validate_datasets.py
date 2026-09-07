"""평가 계약·Fixture 참조를 검사한다. 외부 API와 LLM은 호출하지 않는다."""

import datetime
import json
import math
import re
from pathlib import Path

from dataset_io import EVAL_ROOT

VALID_AGENTS = {"business", "macro_sector", "event_catalyst"}


def validate_datasets(root: Path = EVAL_ROOT) -> dict[str, int]:
    """모든 데이터셋의 타입·정답 계약·근거 참조를 검증한다.

    Args:
        root: datasets/와 fixtures/를 가진 평가 디렉터리.
    Returns:
        suite별 사례 수. pending/reference_ready는 실행 가능한 평가 수가 아니다.
    Raises:
        ValueError: 필수 값, 날짜, Agent, Fixture 또는 정답 계약이 잘못된 경우.
    """
    datasets = {}
    ids = set()
    for name in ("input_parsing", "planner_routing", "end_to_end", "grounding"):
        rows = json.loads((root / "datasets" / f"{name}.json").read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"{name}: JSON 배열이 필요합니다.")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{name}: 사례는 객체여야 합니다.")
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
                raise ValueError(f"잘못되거나 중복된 case_id: {case_id}")
            ids.add(case_id)
            for key in ("origin", "label_rationale"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f"{case_id}: {key} 누락")
            if row["origin"] not in {"product_contract", "official_source", "synthetic", "observed_failure"}:
                raise ValueError(f"{case_id}: 잘못된 origin")
            question = row.get("raw_user_input" if name == "input_parsing" else "question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError(f"{case_id}: 질문 누락")
            if name == "input_parsing":
                today = _date(row.get("today"))
                expected = row.get("expected")
                has_error = isinstance(row.get("expected_error"), str) and bool(row["expected_error"].strip())
                if (expected is not None) == has_error:
                    raise ValueError(f"{case_id}: 정상 정답 또는 오류 정답 중 하나만 필요")
                if expected is not None:
                    if not isinstance(expected, dict):
                        raise ValueError(f"{case_id}: 정상 정답은 객체여야 합니다.")
                    _company(expected)
                    _period(expected.get("period_days"))
                    if _date(expected.get("as_of_date")) > today:
                        raise ValueError(f"{case_id}: 정상 정답이 미래 기준일")
                    if row.get("expected_error_pattern") is not None:
                        raise ValueError(f"{case_id}: 정상 사례에 오류 패턴 지정")
                else:
                    pattern = row.get("expected_error_pattern")
                    if not isinstance(pattern, str) or not pattern.strip():
                        raise ValueError(f"{case_id}: 오류 사유 패턴 누락")
                    re.compile(pattern)
                if not row.get("expected_question_intent"):
                    raise ValueError(f"{case_id}: 질문 의도 기준 누락")
            elif name in {"planner_routing", "end_to_end"}:
                _company(row)
                _date(row.get("as_of_date"))
                _period(row.get("period_days"))
                agents = row.get("expected_agents")
                if (
                    not isinstance(agents, list) or not agents
                    or any(not isinstance(a, str) for a in agents)
                    or len(agents) != len(set(agents))
                    or not set(agents) <= VALID_AGENTS
                ):
                    raise ValueError(f"{case_id}: 잘못된 expected_agents")
                if name == "end_to_end":
                    if row.get("evaluation_status") != "pending":
                        raise ValueError(f"{case_id}: E2E Runner 미구현, pending만 허용")
                    for key in ("must_cover", "must_not_claim", "required_source_types"):
                        if not row.get(key):
                            raise ValueError(f"{case_id}: {key} 누락")
            else:
                if row.get("evaluation_status") != "reference_ready":
                    raise ValueError(f"{case_id}: 자동 채점 미구현, reference_ready만 허용")
                fixture_name = row.get("fixture")
                if not isinstance(fixture_name, str) or Path(fixture_name).name != fixture_name:
                    raise ValueError(f"{case_id}: 잘못된 Fixture 파일명")
                fixture_path = root / "fixtures" / fixture_name
                if not fixture_path.is_file():
                    raise ValueError(f"{case_id}: Fixture 없음")
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                for key in ("fixture_id", "source_url", "source_locator", "content", "limitations"):
                    if not isinstance(fixture.get(key), str) or not fixture[key].strip():
                        raise ValueError(f"{case_id}: Fixture {key} 누락")
                if not fixture["source_url"].startswith("https://"):
                    raise ValueError(f"{case_id}: 출처 URL 형식 오류")
                if _date(fixture["published_at"]) > _date(fixture["retrieved_at"]):
                    raise ValueError(f"{case_id}: 수집일이 공개일 이전")
                _date(fixture["period_end"])
                facts = row.get("expected_facts")
                if not isinstance(facts, list) or not facts:
                    raise ValueError(f"{case_id}: 기대 사실 누락")
                names = set()
                for fact in facts:
                    if not fact.get("name") or fact["name"] in names or not fact.get("unit"):
                        raise ValueError(f"{case_id}: 사실 이름·단위 누락 또는 중복")
                    names.add(fact["name"])
                    for key in ("value", "absolute_tolerance"):
                        value = fact.get(key)
                        if type(value) not in (int, float) or not math.isfinite(value):
                            raise ValueError(f"{case_id}: 잘못된 {key}")
                    if fact["absolute_tolerance"] < 0:
                        raise ValueError(f"{case_id}: 음수 허용 오차")
        datasets[name] = len(rows)
    mapping = json.loads((root / "fixtures/companies.json").read_text(encoding="utf-8"))["companies"]
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("회사 Fixture는 비어 있지 않은 매핑이어야 합니다.")
    for name, ticker in mapping.items():
        _company({"corp_name": name, "ticker": ticker})
    return datasets


def _date(value):
    """ISO 날짜만 허용한다."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"잘못된 날짜: {value}")
    return datetime.date.fromisoformat(value)


def _period(value):
    """달력 일수 범위를 검사한다."""
    if type(value) is not int or not 1 <= value <= 3650:
        raise ValueError(f"잘못된 기간: {value}")


def _company(row):
    """회사 표시명과 6자리 종목코드를 검사한다."""
    if not isinstance(row.get("corp_name"), str) or not row["corp_name"].strip():
        raise ValueError("회사명 누락")
    if not isinstance(row.get("ticker"), str) or not re.fullmatch(r"\d{6}", row["ticker"]):
        raise ValueError("종목코드는 6자리 문자열이어야 합니다.")


def main() -> None:
    """데이터 계약 검증 결과를 출력하며 금융 내용의 정확성은 채점하지 않는다."""
    counts = validate_datasets()
    for name, count in counts.items():
        print(f"{name}: {count}")
    print("dataset validation: OK (LLM/E2E 품질 평가는 실행하지 않음)")


if __name__ == "__main__":
    main()
