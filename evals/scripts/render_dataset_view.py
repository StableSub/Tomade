"""StockAgent-Eval JSON을 사람이 읽기 쉬운 Markdown 문서로 변환한다."""

from pathlib import Path

from dataset_io import load_dataset

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "DATASET_VIEW.md"

AGENT_LABELS = {
    "business": "Business Agent",
    "macro_sector": "Macro / Sector Agent",
    "event_catalyst": "Event / Catalyst Agent",
}


def bullet_items(items: list[str]) -> list[str]:
    """문자열 목록을 들여쓰기 된 Markdown bullet 목록으로 변환한다.

    Args:
        items: 표시할 문자열 목록.

    Returns:
        각 값 앞에 Markdown bullet을 붙인 문자열 목록.
    """
    return [f"  - {item}" for item in items]


def render_parsing(rows: list[dict]) -> list[str]:
    """단일 자연어 입력 Parser 사례와 예상 정규화 결과를 렌더링한다.

    Args:
        rows: `input_parsing.json`에서 읽은 사례 목록.

    Returns:
        원본 입력, 예상 필드, 오류 기준이 포함된 Markdown 줄 목록.
    """
    lines = ["## 1. Input Parsing Dataset", ""]
    for row in rows:
        lines.extend(
            [
                f"### {row['case_id']}",
                "",
                f"- **사용자 단일 입력:** {row['raw_user_input']}",
                f"- **고정 오늘:** {row['today']}",
                f"- **출처 유형:** {row['origin']}",
                f"- **정답 이유:** {row['label_rationale']}",
            ]
        )
        if expected := row.get("expected"):
            lines.extend(
                [
                    f"- **예상 회사:** {expected['corp_name']} (`{expected['ticker']}`)",
                    f"- **예상 기간:** {expected['period_days']}일",
                    f"- **예상 기준일:** {expected['as_of_date']}",
                ]
            )
        else:
            lines.append(f"- **예상 오류:** {row['expected_error']}")
            lines.append(f"- **오류 사유 패턴:** `{row['expected_error_pattern']}`")
        intents = ", ".join(row["expected_question_intent"])
        tags = ", ".join(f"`{tag}`" for tag in row["tags"])
        lines.extend(
            [
                f"- **질문 의도:** {intents}",
                f"- **분류:** {tags}",
                "",
            ]
        )
    return lines


def render_routing(rows: list[dict]) -> list[str]:
    """Planner Routing 사례를 질문과 예상 Agent 중심으로 렌더링한다.

    Args:
        rows: `planner_routing.json`에서 읽은 사례 목록.

    Returns:
        Markdown 문서에 바로 추가할 줄 단위 문자열 목록.
    """
    lines = ["## 2. Planner Routing Dataset", ""]
    for row in rows:
        agents = ", ".join(AGENT_LABELS[name] for name in row["expected_agents"])
        tags = ", ".join(f"`{tag}`" for tag in row["tags"])
        lines.extend(
            [
                f"### {row['case_id']} — {row['corp_name']}",
                "",
                f"- **종목코드:** `{row['ticker']}`",
                f"- **사용자 질문:** {row['question']}",
                f"- **예상 Agent:** {agents}",
                f"- **고정 기준일:** {row['as_of_date']}",
                f"- **출처 유형:** {row['origin']}",
                f"- **정답 이유:** {row['label_rationale']}",
                f"- **분류:** {tags}",
                "",
            ]
        )
    return lines


def render_end_to_end(rows: list[dict]) -> list[str]:
    """End-to-end 사례의 필수·금지 Rubric을 렌더링한다.

    Args:
        rows: `end_to_end.json`에서 읽은 사례 목록.

    Returns:
        입력과 평가 Rubric이 구분된 Markdown 줄 목록.
    """
    lines = ["## 3. End-to-end Dataset", ""]
    for row in rows:
        agents = ", ".join(AGENT_LABELS[name] for name in row["expected_agents"])
        source_types = ", ".join(row["required_source_types"])
        lines.extend(
            [
                f"### {row['case_id']} — {row['corp_name']}",
                "",
                f"- **종목코드:** `{row['ticker']}`",
                f"- **분석 기준일:** {row['as_of_date']}",
                f"- **분석 기간:** {row['period_days']}일",
                f"- **사용자 질문:** {row['question']}",
                f"- **예상 Agent:** {agents}",
                "- **반드시 포함할 내용:**",
                *bullet_items(row["must_cover"]),
                "- **금지할 주장:**",
                *bullet_items(row["must_not_claim"]),
                f"- **필요한 출처 유형:** {source_types}",
                f"- **실행 방식:** `{row['mode']}`",
                f"- **Evidence Fixture:** `{row['evidence_fixture_status']}`",
                f"- **평가 상태:** `{row['evaluation_status']}` — 자동 실행·채점 대상 아님",
                "",
            ]
        )
    return lines


def main() -> None:
    """세 JSON 데이터셋을 하나의 읽기 전용 Markdown View로 생성한다."""
    parsing = load_dataset("input_parsing.json")
    routing = load_dataset("planner_routing.json")
    end_to_end = load_dataset("end_to_end.json")

    grounding = load_dataset("grounding.json")
    lines = [
        "# StockAgent-Eval v0.2 — 데이터 보기",
        "",
        "> 이 문서는 사람이 검토하기 위한 View다. 자동 평가의 원본은 `datasets/*.json`이다.",
        "",
        "## 요약",
        "",
        f"- Input Parsing: **{len(parsing)}개**",
        f"- Planner Routing: **{len(routing)}개**",
        f"- End-to-end 초안 (pending): **{len(end_to_end)}개**",
        f"- 실제 근거 준비 사례 (reference_ready): **{len(grounding)}개**",
        "- 현재 자동 실행: Parsing·Routing 24개. 위 준비 사례는 통과율에 포함하지 않는다.",
        "",
        "---",
        "",
        *render_parsing(parsing),
        "---",
        "",
        *render_routing(routing),
        "---",
        "",
        *render_end_to_end(end_to_end),
    ]
    lines.extend(["## 4. 고정 근거 준비 사례", ""])
    for row in grounding:
        lines.extend([
            f"### {row['case_id']}",
            "",
            f"- **질문:** {row['question']}",
            f"- **정답 이유:** {row['label_rationale']}",
            f"- **근거 파일:** `fixtures/{row['fixture']}`",
            f"- **평가 범위:** {row['evaluation_scope']}",
            "- **기대 사실:**",
            *[f"  - {fact['name']}: {fact['value']} {fact['unit']} (허용 오차 ±{fact['absolute_tolerance']})"
              for fact in row["expected_facts"]],
            "",
        ])
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"rendered: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
