# 현재 스키마 — stock_agent

> 2026-09-17 모델 연결 설정 추가. 목표 설계와 현재 계약을 구분한다.

## 모델 연결 설정

`backend/model_settings.py`의 `ProviderSelection`은 `provider` 한 필드이며 `openai`, `openrouter`, `openai_codex`를 허용한다. API 키·모델 ID 변경은 받지 않는다.

설정 조회/전환 응답:

| 필드 | 계약 |
| --- | --- |
| provider | 위 세 공급자 또는 미설정·잘못된 설정이면 null |
| auth_mode | api_key / subscription / null |
| models | planner, parser, worker, summary별 최종 모델 ID. 공급자 미설정이면 빈 객체 |
| reasoning_efforts | 같은 네 역할의 추론 깊이 또는 null(기본값). API Key 방식은 null |
| codex_model_options | 앱이 허용하는 모델 ID → 추론 깊이 배열. 계정 접근 권한 목록은 아님 |
| busy | Chat·Research·포트폴리오 진단 실행 중 여부 |
| api_keys | openai, openrouter 키 존재 여부 boolean. 키 값 제외 |
| codex | state(signed_out/signed_in/expired/error), message. 저장된 인증의 로컬 상태 |
| login | 아래 로그인 상태 또는 null |

로그인 상태는 `id`(UUID), `state`(pending/completed/expired/error), `message`, `user_code`(pending일 때만 문자열, 그 외 null), `verification_url`(고정 OpenAI 기기 로그인 주소), `interval`(조회 간격 초), `expires_in`(남은 초)다. 서버의 `LoginSession`에 있는 인증 객체·기기 인증 ID·토큰은 직렬화하지 않는다. 대기 세션은 메모리, 완료한 인증은 프로젝트 전용 파일에 저장한다.

`PUT /api/settings/codex/models`의 `CodexRoleSettings`는 planner, parser, worker, summary 네 필드를 모두 요구한다. 각 값은 `{model, reasoning_effort}`다. model은 gpt-6-astra 또는 gpt-5.6-sol/terra/luna이며 reasoning_effort는 null·none·low·medium·high·xhigh·max다. Astra의 none, 모르는 모델/단계, 추가 필드, 누락 역할은 422다. 추론 기본값은 null이며 누락해도 null로 처리한다.

SSE `run.started`는 `run_id` 외에 `connection: {provider, auth_mode, models, reasoning_efforts, busy}`를 포함한다. 요청의 선택 설정이며 실제 인증 성공 기록은 아니다. 대화 DB에는 저장하지 않는다.

## Chat

### 대화 저장 — 구현

로컬 SQLite `data/chat.sqlite3`에 다음 테이블을 사용한다. 시각은 UTC ISO 문자열이며
대화는 `user_id=local`로 분리한다. 로그인/다중 사용자 인증은 미구현이다.

| 테이블 | 필드 |
| --- | --- |
| conversations | id(UUID), user_id, title, created_at, updated_at, summary, last_summarized_message_id |
| messages | id(정수), conversation_id(FK), role(user/assistant), content, status, created_at |

status는 pending/completed/error/interrupted다. 질문은 completed로, 답변은 pending으로
같은 트랜잭션에 삽입한다. 메시지 ID 순서로 복원하며 최종 응답 시 답변 행을 갱신한다.
대화의 updated_at은 마지막 질문 시각이다. 첫 질문의 공백을 정리한 최대 40자로 제목을 정한다.
대화 삭제는 메시지에 CASCADE된다. 실행 그래프·포트폴리오 상세 표·장기 선호는 저장하지 않는다.

`ChatRequest`는 message(1~300자)와 선택적 conversation_id(UUID)를 받는다.
ID를 생략하면 대화 저장·단기 맥락 없이 실행하며 로컬 장기 기억은 공유한다. ID가 있으면 요약과 최근 완료된 10턴을 상위 Agent 입력에 포함한다.

`summary`는 기본 빈 문자열인 TEXT, `last_summarized_message_id`는 기본 null인 INTEGER다.
서버 시작 시 기존 DB에 누락된 두 컬럼만 추가한다. 경계는 마지막으로 요약한 완료 턴의 assistant 메시지 ID다.
요약과 경계는 함께 갱신하며 원문은 남긴다. API 대화 객체에도 두 필드가 포함된다.

`backend/short_term_memory.py`의 `SessionSummary`는 goal, constraints, active_state,
resolved_questions의 네 문자열을 요구한다. 공백만 있는 값은 거부하고 검증 후 Markdown으로 변환한다.

### 상위 Agent 결정

`agents/orchestrator.py`의 `UpperDecision`은 `intent`, `final_answer`, `research_plan`을 가진다.

- general: 비어 있지 않은 final_answer, research_plan은 null.
- research: ResearchPlan 필수, final_answer는 null.
- 조사 이후 같은 상위 Agent가 final_answer를 반환하면 종료한다. Router의 intent-only 계약과 별도 ChatState는 제거했다.
- `short_term_summary`는 요약 문자열, `recent_messages`는 역할·내용 튜플 목록(최대 20개 메시지)이다. 현재 질문은 포함하지 않는다.

### 장기 메모리 Tool

`memory_enabled`는 서버가 로컬 Chat에서만 true로 설정한다. 클라이언트 요청 필드가 아니다.
`update_memory` 입력: action(add/replace/remove), content(추가·교체 시 필수), old_text(교체·삭제 시 필수).
성공은 success=true, action, changed, message를 반환한다. 실패는 success=false와 message,
호출 한도 도달 시 done=true를 추가한다. 파일은 `memory/local/USER.md`이며 항목 구분자는 `\n§\n`이다.
새 API·DB 컬럼은 추가하지 않는다.

## 종목 조사

`src/stock_agent/state.py`가 현재 정의다.

| 타입 | 실제 필드 |
| --- | --- |
| ParsedRequest | company_candidates, research_question, as_of_date, period_days, needs_clarification, clarification_reason |
| ResearchMandate | original_question, research_question, ticker, corp_name, as_of_date, period_days, purpose, constraints |
| ResearchTask | agent, objective, questions, completion_criteria |
| ResearchPlan | planning_summary, tasks |
| StockAgentState | memory_enabled, short_term_summary, recent_messages, raw_user_input, intent, research_only, run_id, parsed_request, input_error, research_mandate, research_plan, business_report, macro_sector_report, event_catalyst_report, final_answer |

ParsedRequest·ResearchTask·ResearchPlan은 Pydantic 모델이다. 날짜·기간 후보는 null이 가능하며 이후 Python이 검증·기본값 처리를 한다. ResearchMandate와 StockAgentState는 TypedDict이므로 그 자체가 런타임 검증을 실행하지 않는다.

AgentName은 business / macro_sector / event_catalyst다. Plan tasks와 Task questions·completion_criteria는 최소 1개다. 같은 Agent 작업의 병합과 질문·완료 기준 최대 4개 처리는 스키마가 아니라 `_normalize_plan()`에서 수행한다.

### 입력 검증 순서와 계획 정규화

상위 Agent가 조사 계획을 만든 뒤 Parser가 현재 질문에서 후보를 추출한다. 검증 코드는 다음 순서로 처리한다.

| 순서 | 코드 검증·정규화 |
| --- | --- |
| 1 | needs_clarification이면 사유와 함께 조기 종료 |
| 2 | 회사 후보를 DART에서 확인; 미확인·0개·복수 회사 거부 |
| 3 | 기준일 미지정은 오늘; 잘못된 ISO 날짜·미래 날짜 거부 |
| 4 | 기간 기본값 30일, 허용 범위 1~3650일 |
| 5 | 공백을 제거한 조사 질문이 비면 거부; 성공 시 Mandate 생성 |

현재 기간 기본값은 `parsed.period_days or 30`으로 처리하므로 0도 30으로 바뀐다. 0을 오류로 거부하는 구현은 아니다. 상대 날짜·별칭·질문 의미의 정확한 추출은 프롬프트에 의존한다.

`ResearchMandate.original_question`은 Parser에 전달한 현재 원문이다. `_normalize_plan()`은 같은 Worker 작업을 병합하고 첫 objective를 유지하며 questions·completion_criteria를 중복 제거해 각각 최대 4개로 제한한다. 완료 기준의 실제 충족 여부를 독립 검증하는 코드는 없다.

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


## 공시 근거 검색 · 내부 파일럿 계약

공개 API/StockAgentState 변경은 없다. `search_evidence`는 질문, 고정 회사 코드·기준일, 선택 접수번호·목차 힌트를 받으며 `chunk_id`, `block_id`, `parent_id`, `member`, `source_line`, `section`, `kind`, `range`, `text`, `search_text`, `receipt_id`, `published_date`, `source_url`, `context`, `context_truncated`, BM25/벡터 순위와 RRF 점수를 반환한다. `range`는 본문은 문자 오프셋(끝 제외), 표는 원문 표의 행 범위(1부터, 끝 포함)다.

Tool factory는 `retrieved`, `no_indexed_evidence`, `budget_exhausted`, `error` 상태를 JSON 문자열로 반환한다. `retrieved`는 관련 후보가 있다는 뜻이며 사실 정확성·조사 완료 판정이 아니다. [상세 검증](disclosure-rag-pilot.md).
