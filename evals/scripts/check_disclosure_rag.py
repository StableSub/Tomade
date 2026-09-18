"""고정된 삼성전자 원문 정답을 검색하고 실패 시 결과만 저장한다."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from stock_agent.rag.service import MODEL, DEFAULT_ROOT, search_evidence
from stock_agent.rag.parser import VERSION


def main():
    """원문 정답 3개와 회사·기준일 필터를 검사해 JSON 결과를 남긴다.

    임베딩 API만 호출한다. 자동 개선·재검색 없음. 실패 결과도 모두 보존하며
    검색 실패가 하나라도 있으면 종료 코드 1을 반환한다.
    """
    p = argparse.ArgumentParser()
    p.add_argument('--env-file', type=Path, required=True)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--dataset', type=Path, default=Path('evals/datasets/disclosure_rag_samsung.json'))
    p.add_argument('--output', type=Path, default=Path('evals/results/disclosure-rag-samsung.json'))
    args = p.parse_args()
    load_dotenv(args.env_file)
    raw = args.dataset.read_bytes(); spec = json.loads(raw)
    parsed = args.root / 'parsed' / spec['receipt_id'] / VERSION / 'blocks.jsonl'
    blocks = {b['block_id']: b for b in map(json.loads, parsed.read_text().splitlines())}
    for case in spec['cases']:
        assert case['expected_phrase'] in blocks[case['expected_block_id']]['text']
    result = {'dataset_sha256': hashlib.sha256(raw).hexdigest(), 'model': MODEL,
              'parser_version': VERSION, 'receipt_id': spec['receipt_id'], 'cases': []}
    for case in spec['cases']:
        start = time.monotonic()
        hits = search_evidence(case['query'], spec['corp_code'], spec['as_of_date'], args.root,
                               receipt_ids=[spec['receipt_id']])
        matching = [i for i, hit in enumerate(hits, 1)
                    if hit['block_id'] == case['expected_block_id'] and case['expected_phrase'] in hit['text']]
        check = dict(case, passed=bool(matching), rank=matching[0] if matching else None,
                     elapsed_seconds=round(time.monotonic()-start, 3), results=hits)
        result['cases'].append(check)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(case['id'], 'PASS' if matching else 'FAIL', 'rank', check['rank'], flush=True)
    result['company_filter'] = not search_evidence('차입금', '00000000', spec['as_of_date'], args.root)
    result['date_filter'] = not search_evidence('차입금', spec['corp_code'], '2026-03-09', args.root)
    result['passed'] = all(c['passed'] for c in result['cases']) and result['company_filter'] and result['date_filter']
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
