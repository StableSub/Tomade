"""평가 데이터와 실행 결과를 읽고 쓰는 공통 JSON 유틸리티."""

import json
from pathlib import Path
from typing import Any

EVAL_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = EVAL_ROOT / "datasets"


def load_dataset(filename: str) -> list[dict[str, Any]]:
    """사람이 읽기 좋게 들여쓴 JSON 배열 데이터셋을 읽는다.

    Args:
        filename: `evals/datasets/` 아래의 JSON 파일명.

    Returns:
        입력 순서를 유지한 평가 사례 딕셔너리 목록.

    Raises:
        ValueError: 최상위 값이 배열이 아니거나 사례가 객체가 아닌 경우.
    """
    path = DATASET_DIR / filename
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"Dataset 최상위 값은 배열이어야 합니다: {path}")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Dataset의 각 사례는 객체여야 합니다: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    """값을 UTF-8 pretty JSON으로 기록하고 상위 디렉터리를 생성한다.

    Args:
        path: JSON을 기록할 경로.
        value: JSON 직렬화 가능한 값.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
