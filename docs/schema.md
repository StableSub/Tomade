# 현재 스키마 — stock_agent

> 2026-09-07 코드 기준. 목표 설계와 현재 계약을 구분한다.

## Chat

### 대화 저장 — 구현

로컬 SQLite `data/chat.sqlite3`에 다음 테이블을 사용한다. 시각은 UTC ISO 문자열이며
대화는 `user_id=local`로 분리한다. 로그인/다중 사용자 인증은 미구현이다.

| 테이블 | 필드 |
| --- | --- |
| conversations | id(UUID), user_id, title, created_at, updated_at |
| messages | id(정수), conversation_id(FK), role(user/assistant), content, status, created_at |

status는 pending/completed/error/interrupted다. 질문은 completed로, 답변은 pending으로
같은 트랜잭션에 삽입한다. 메시지 ID 순서로 복원하며 최종 응답 시 답변 행을 갱신한다.
대화의 updated_at은 마지막 질문 시각이다. 첫 질문의 공백을 정리한 최대 40자로 제목을 정한다.
대화 삭제는 메시지에 CASCADE된다. 실행 그래프·포트폴리오 상세 표·장기 선호는 저장하지 않는다.

`ChatRequest`는 message(1~300자)와 선택적 conversation_id(UUID)를 받는다.
ID를 생략한 기존 호출은 저장 없는 독립 실행이다. 저장된 기록은 모델 입력에 포함하지 않는다.

### 상위 Agent 결정

`agents/orchestrator.py`의 `UpperDecision`은 `intent`, `final_answer`, `research_plan`을 가진다.

- general: 비어 있지 않은 final_answer, research_plan은 null.
- research: ResearchPlan 필수, final_answer는 null.
- 조사 이후 같은 상위 Agent가 final_answer를 반환하면 종료한다. Router의 intent-only 계약과 별도 ChatState는 제거했다.
- 현재 요청 상태에는 세션 메모리가 없다.

## 종목 조사

`src/stock_agent/state.py`가 현재 정의다.

| 타입 | 실제 필드 |
| --- | --- |
| ParsedRequest | company_candidates, research_question, as_of_date, period_days, needs_clarification, clarification_reason |
| ResearchMandate | original_question, research_question, ticker, corp_name, as_of_date, period_days, purpose, constraints |
| ResearchTask | agent, objective, questions, completion_criteria |
| ResearchPlan | planning_summary, tasks |
| StockAgentState | raw_user_input, intent, research_only, run_id, parsed_request, input_error, research_mandate, research_plan, business_report, macro_sector_report, event_catalyst_report, final_answer |

ParsedRequest·ResearchTask·ResearchPlan은 Pydantic 모델이다. 날짜·기간 후보는 null이 가능하며 이후 Python이 검증·기본값 처리를 한다. ResearchMandate와 StockAgentState는 TypedDict이므로 그 자체가 런타임 검증을 실행하지 않는다.

AgentName은 business / macro_sector / event_catalyst다. Plan tasks와 Task questions·completion_criteria는 최소 1개다. 같은 Agent 작업의 병합과 질문·완료 기준 최대 4개 처리는 스키마가 아니라 `_normalize_plan()`에서 수행한다.

Worker 보고서와 최종 답변은 문자열이다. WorkerReport·Evidence·Confidence 구조화 모델과 심볼릭 검증 노드는 미구현이다.

## 포트폴리오

`src/stock_agent/portfolio/schemas.py`에 독립 정의한다.

| 타입 | 계약 |
| --- | --- |
| Holding | symbol, name, amount, purchase_amount. 두 금액은 필수·유한·0 이상 Decimal |
| SectorAssignments | items: symbol, sector, reason. reason은 1~300자 |
| Sector | 정보기술, 커뮤니케이션, 경기소비재, 필수소비재, 금융, 산업재, 소재, 에너지, 헬스케어, 유틸리티, 부동산, 미분류 |
| PortfolioExplanation | summary 1~2000자, observations 최대 5개, limitations 1~5개 |

입력 종목과 업종 분류 결과의 정확한 집합 일치·중복 검사는 계산 코드가 수행한다. 업종의 금융적 정확성 검사는 아니다.

금액·백분율은 Decimal 계산 후 문자열로 반환한다. 매입금액 0일 때 평가손익률은 null이다. fetched_at은 앱 수집 시각이며 원천 평가 시각을 보장하지 않는다. HTTP 입출력은 [API 문서](api.md)를 따른다.

## 평가 데이터 계약 (v0.2, 구현)

- Parsing 사례는 `today`, 명시적 기대 날짜, `origin`, `label_rationale`을 가진다.
- 정상 정답과 오류 정답 중 하나만 지정한다. 오류 사례의 `expected_error_pattern`은 문구 기반 채점이며 제품 오류 Enum이 아니다.
- Routing 사례는 고정 `as_of_date`·`period_days`와 `expected_agents`·정답 이유를 가진다.
- 기존 E2E 사례의 `evaluation_status=pending`, Grounding 사례의 `evaluation_status=reference_ready`는 자동 실행·채점 대상이 아니다.
- Grounding의 `fixture`는 `evals/fixtures/`의 근거 파일을 참조하고, `expected_facts`는 지표명·값·단위·절대 허용 오차를 가진다.
- 실행 결과는 실제 모델 설정·버전 해시·미평가 항목과 사례별 반복 집계를 저장한다. 제품 API·공유 State 스키마는 이번 평가 변경으로 바뀌지 않았다.
