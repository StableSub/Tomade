"""한 실제 질문의 v2 실행·역할별 근거·최종 답변을 기록한다. 품질 평가 점수는 산출하지 않는다."""

import argparse
import asyncio
import contextlib
import json
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel

from stock_agent.graph import graph
from stock_agent.trajectory import trajectory_run


def serializable(value):
    """Pydantic 결과를 JSON 값으로 변환하고 미지원 타입은 거부한다."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(type(value).__name__)


async def run(question: str, destination: Path) -> dict:
    """질문을 전체 그래프에 넣고 공개 조사 결과·실행 기록을 로컬에 저장한다.

    실제 설정된 모델과 외부 API를 사용하며 사용량이 발생한다. 사용자 기억은 끈다.
    실패는 거짓 성공 대신 예외로 전달한다. 저장 결과는 지표·출처 확인용이며 투자 수익 검증이 아니다.
    """
    destination.mkdir(parents=True, exist_ok=True)
    run_id = 'v2-smoke-' + uuid4().hex[:12]
    with (destination / 'nodes.log').open('w') as logfile, contextlib.redirect_stdout(logfile):
        with trajectory_run(run_id, trace_root=destination) as trace:
            state = await graph.ainvoke({'raw_user_input': question, 'run_id': run_id,
                                        'research_only': True, 'memory_enabled': False})
            trace.mark_status('input_error' if state.get('input_error') else 'completed')
    (destination / 'result.json').write_text(json.dumps(state, default=serializable, ensure_ascii=False, indent=2))
    (destination / 'answer.md').write_text(state.get('final_answer', state.get('input_error', '최종 답변 없음')))
    results = {key: {'status': value.status, 'findings': len(getattr(value, 'findings', [])),
                     'evidence': len(getattr(value, 'evidence', []))}
               for key, value in state.items() if key.endswith('_report')}
    summary = {'run_id': run_id, 'selected_workers': [t.agent for t in state['research_plan'].tasks],
               'workers': results, 'input_error': state.get('input_error'),
               'answer_chars': len(state.get('final_answer', '')), 'destination': str(destination)}
    (destination / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv()
    print(json.dumps(asyncio.run(run(args.question, args.output)), ensure_ascii=False, indent=2))
