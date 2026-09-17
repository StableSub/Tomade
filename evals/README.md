# StockAgent-Eval v0.2

제품 계약 준수와 근거 기반 답변을 구분해 평가한다. 현재 자동 실행은 Parsing·Routing뿐이다.

## 현재 범위

| 데이터 | 수 | 상태 |
|---|---:|---|
| Input Parsing | 12 | 제품 계약 평가: 필드·오류 사유 패턴 |
| Planner Routing | 12 | 제품 계약 평가: Agent 집합 |
| End-to-end | 3 | `pending`: 실제 근거·Runner 미구현 |
| Grounding | 1 | `reference_ready`: 공식 자료·기대 사실 준비, 자동 채점 미구현 |

24개는 개발 중 공개된 계약 사례이며 Holdout이나 금융 정확도 Benchmark가 아니다.
`origin`과 `label_rationale`에 출처 유형과 정답 이유를 기록한다. AI가 작성한 정책 설명을 전문가 검증으로 표시하지 않는다.

## 데이터와 채점

- `input_parsing.json`: `today`와 기대 기준일을 고정한다. `fixtures/companies.json`으로 회사 조회를 대체한다.
- 제품 Parser 모듈의 날짜와 회사 조회만 평가 실행 중 교체한다. 모델 호출은 실제 LLM을 사용하므로 API 비용 또는 구독 사용량을 소비한다. 평가 함수는 순차 실행한다.
- 회사명 표기는 현재 계약대로 Exact Match한다. 현대차·현대자동차는 매핑에서 같은 코드지만, 표시명 정확성은 별도 계약 검사다.
- 오류는 존재 여부와 `expected_error_pattern`을 모두 검사한다. 패턴은 문구 기반 휴리스틱이며 오류 의미를 완전히 검증하지 않는다. 안정적인 유형 채점에는 제품 오류 코드 도입이 후속으로 필요하다.
- `expected_question_intent`의 의미, Plan 질문 누락·역할 적합성은 `unscored`로 표시한다. 현재 통과율에 의미 품질을 포함하지 않는다.
- Routing은 현재 최소 Agent 정책을 검사한다. 특히 routing-006/008/009의 다른 실행 경로가 금융적으로 틀렸다는 의미는 아니다.
- 실제 DART 목록·Vendor 연동은 고정 매핑 평가와 별개다.

## 실제 자료 기반 사례

`datasets/grounding.json`은 삼성전자 2025년 2분기 연결 매출·영업이익·전분기 매출 변화를 묻는다.
`fixtures/samsung_2025_q2.json`에 공식 발표 URL·공개일·수집일·짧은 원문 인용·근거 위치·요약을 보관한다.

- 출처: [삼성전자 공식 실적 발표](https://news.samsung.com/global/samsung-electronics-announces-second-quarter-2025-results).
- 제목이나 검색 요약만으로 정답을 만들지 않고 공식 페이지 본문을 확인했다.
- 기대 수치는 발표 요약의 반올림 정밀도이며 단위·비교 기간과 함께 검사해야 한다.
- 실제 DART Tool 응답이나 과거 불변 스냅샷이 아니다. 현 Business Tool의 실적 원문 수집 능력을 증명하지 않는다.
- 이 사례는 근거 준비까지만 완료됐다. 자동 자연어 채점·Judge·전체 그래프 Fixture 실행은 아직 없다.
- 원본 자료 기반 사례와 향후 수치를 바꾼 합성 오류 사례의 점수는 분리한다.

## 실행

프로젝트 루트에서 실행한다.

```bash
# 외부 API 없이 데이터 계약 검증
.venv/bin/python evals/scripts/validate_datasets.py

# 사람이 읽는 View 재생성
.venv/bin/python evals/scripts/render_dataset_view.py

# 외부 API 없이 평가기 회귀 테스트
.venv/bin/python -m unittest tests.test_eval_contract

# 실제 LLM 평가: API 비용 또는 구독 사용량을 소비하므로 승인된 실행에만 사용
.venv/bin/python evals/scripts/run_eval.py --suite parsing,routing --label contract-v2 --runs 3

# 같은 사례·반복 수·채점 계약의 이전 결과와 비교
.venv/bin/python evals/scripts/run_eval.py --suite parsing,routing --label candidate --runs 3 --compare evals/results/contract-v2/<실행시각>/runs.json
```

`--case-id`로 특정 사례를 선택할 수 있다. 알 수 없는 사례·잘못된 데이터·비교 계약 불일치는 LLM 실행 전에 중단한다.
`--suite all`도 현재 구현된 parsing/routing만 실행하며, pending/reference_ready 사례를 통과로 집계하지 않는다.

## 결과와 비교

기존처럼 `results/<label>/<시각>/runs.json`, `summary.json`, `report.md`를 저장한다.

- 실제 모델 객체의 모델 이름·공급자·Responses 설정·추론/temperature 설정을 허용 목록으로 기록한다. Codex 구독 공급자는 `openai_codex`로 구분한다. API 키·OAuth 토큰·헤더는 모델 메타데이터에 포함하지 않는다.
- 공통 지침을 조립한 Parser·Planner 프롬프트 해시, 제품 Python 코드 해시, 데이터·회사 Fixture·채점 코드 해시를 기록한다. 프롬프트 해시는 날짜를 `<runtime-date>`로 고정하고 Planner는 initial·빈 기억을 사용하므로 실행일이나 개인 기억에 따라 바뀌지 않는다.
- 사례별 통과/실행·오류 횟수, 지연과 Routing 지표를 제공한다. 모델 토큰·비용 수집은 후속 작업이다.
- 비교는 동일 사례·반복 수·계약 해시가 필요하다. 해시 없는 과거 baseline은 그대로 보존하고 비교 입력으로는 거부한다.
- 비교 판정은 성공 횟수의 개선·퇴보·동일이며, 어느 쪽이든 실행 오류가 있으면 판정 불가다. 통계적 유의성이나 실제 사용자 성공률을 주장하지 않는다.
- 예전 결과를 새 기준에 맞춰 덮어쓰지 않는다. 이 계약으로 새 baseline을 실행해야 한다.

## 다음 단계

1. 실제 자료 기반 고정 답변 평가를 연결하고 숫자·출처 비교부터 구현한다.
2. 원본 근거를 제공하는 LLM Judge와 정상/오류 대조 사례를 추가한다. 전수 사람 채점을 선행 조건으로 두지 않되 Judge 점수를 금융 정답으로 취급하지 않는다.
3. 외부 응답을 고정한 전체 그래프 평가를 구현한다. Fixture 누락 시 실서비스 API로 넘어가지 않고, 타당한 검색어·순서 차이를 허용한다.
4. 실제 사용 실패를 회귀 사례에 추가한다.

### 상위 Agent 통합 이후 평가 범위

현재 routing suite는 별도 Planner가 아닌 상위 Agent의 첫 호출에 research_only를 적용해 Worker 선택을 평가한다. 일반 답변/조사 선택과 최종 종합 품질은 이 점수에 포함되지 않는다. 시스템 프롬프트가 변경됐으므로 이전 기준선과 비교할 때 프롬프트 해시와 입력 조건을 함께 확인한다.
