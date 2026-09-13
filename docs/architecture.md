# 아키텍처 — Tomade

> 2026-09-13 코드 대조. 배포 단위가 아닌 요청 처리 흐름과 책임을 설명한다.

## 현재 구현 범위

### 대화 기록

- `backend/conversations.py`가 로컬 단일 사용자(`local`)의 대화방·메시지를 SQLite `data/chat.sqlite3`에 저장한다. 외부 DB/ORM 의존성·로그인은 없다. 모든 대화 API에 기존 로컬 접근 제한과 no-store를 적용한다.
- 프론트는 대화 생성·선택·삭제와 URL 대화 ID 기반 복원을 제공한다. 첫 메시지로 제목을 정하며 LLM을 호출하지 않는다.
- Chat 요청에 `conversation_id`가 있으면 질문과 pending 답변을 트랜잭션으로 저장하고, 최종 SSE 전달 전에 completed/error 답변을 저장한다. 연결 중단은 interrupted로 남기며 서버 시작 시 남은 pending을 복구한다. 단일 서버 프로세스만 지원한다.
- 같은 대화의 동시 실행·실행 중 삭제는 409로 거부한다. 대화 삭제 시 메시지도 삭제한다. 재연결·모델 자동 재실행은 없다.
- 저장 범위는 사용자 메시지와 최종 답변·정제된 오류다. 포트폴리오 상세 응답, Tool 결과, 노드 출력은 저장하지 않는다. 최종 답변에 포함된 보유정보 등은 대화 DB에 남을 수 있다.
- 저장된 완료 질문·답변 쌍은 상위 Agent의 단기 컨텍스트에도 사용한다. error/interrupted 응답과 현재 질문은 이전 턴 집계에서 제외한다. 장기 메모리는 사용자별 파일로 분리한다.

### 단기 메모리

- `backend/short_term_memory.py`가 새 질문의 첫 Graph 실행 전에 해당 세션의 요약과 완료된 대화를 준비한다. 현재 pending 답변으로 같은 세션의 동시 요청·삭제를 막은 상태에서 수행한다.
- 최근 10턴은 user/assistant 원문으로 유지한다. 11턴이면 오래된 1턴, 밀린 대화가 더 많으면 최근 10턴을 제외한 구간을 기존 요약과 함께 압축한다. 현재 질문은 마지막 user 메시지로 한 번만 전달한다.
- `SUMMARY_MODEL` 기본값은 `gpt-5.6-luna`이며 OpenRouter는 `openai/gpt-5.6-luna`를 사용한다. 공통 `LLM_MODEL`을 따르지 않는다. 실제 공급자의 모델 접근 권한과 호출 성공은 별도 검증이 필요하다.
- 출력은 `SessionSummary`의 목표·제약과 선호·현재 작업 상태·이미 해결한 질문 네 항목을 검증한 뒤 Markdown으로 저장한다. `conversations.summary`와 마지막 요약 턴의 답변 ID를 한 트랜잭션으로 갱신하고 원문은 보존한다.
- 요약 모델 호출은 DB 트랜잭션 밖에서 수행한다. 호출·출력 검증 실패 시 기존 요약과 경계를 유지하고 이번 요청은 run.error/error로 종료한다. 자동 재요약 루프는 없다.
- 요약은 시스템 프롬프트의 `[SHORT_TERM_MEMORY]`에, 최근 원문은 역할별 메시지에 넣는다. 첫 답변·계획과 조사 후 종합에 같은 맥락을 사용하며 종합 전에 다시 압축하지 않는다.
- Parser·Worker 하위 그래프에는 세션 요약과 최근 메시지 필드를 제외한다. Parser는 현재 질문만 해석하므로 종목을 생략한 후속 조사 요청은 제한된다.
- 토큰 기반 압축과 초기 메시지 별도 보존은 사용하지 않는다. 10턴이 입력 토큰 한도를 보장하지 않으며, 임계값 이후에는 통상 요청마다 요약 비용과 지연이 추가된다.

### 장기 메모리

- `tools/user_memory.py`가 `memory/local/USER.md`를 관리한다. 로컬 단일 사용자이며 사용자·경로를 Tool 인자로 받지 않는다. 파일은 Git에서 제외한다.
- 세션 ID 유무와 관계없이 로컬 Chat의 상위 Agent 호출마다 파일을 읽어 `[MEMORY]`에 넣는다. 조사 후 종합에서도 다시 읽는다. 공개 Research API와 Parser·Worker에는 주입하거나 Tool을 제공하지 않는다.
- 파일은 `\n§\n`으로 구분한 자유 텍스트 항목 목록이다. add는 동일 항목을 중복 추가하지 않고, replace/remove는 old_text가 포함된 항목이 정확히 하나일 때만 변경한다. 항목 구분자를 content에 넣는 요청은 거부한다.
- 현재 발언에서 사용자가 직접 밝힌 지속적인 사용자·환경·투자 성향·주식 배경지식은 별도의 기억 요청이 없어도 추가·갱신하도록 시스템 지침과 Tool 설명으로 유도한다. 질문만으로 성향·지식 수준을 추측하지 않으며, 저장 거부 정보·포트폴리오 수치·세션 임시 요청·이미 저장된 동일 정보는 추가하지 않도록 안내한다. 저장 적절성은 모델 판단이며 코드가 사실 여부나 저장 판단을 보장하지 않는다.
- 단일 서버 프로세스의 잠금 안에서 최신 파일을 읽고 변경한다. 임시 파일 작성 후 원자적으로 교체하여 동시 대화의 저장 유실과 부분 파일 노출을 방지한다. 다중 서버 프로세스는 지원하지 않는다.
- 입력/대상 오류와 쓰기 오류는 success=false로 반환하여 답변을 이어가도록 한다. 처음 파일을 읽지 못하면 빈 기억으로 대체하지 않고 해당 요청을 실패시킨다.
- 상위 Agent 호출별 최대 3회 변경을 시도한다. 한도 이후 Tool은 종료 안내만 반환하고 파일을 변경하지 않는다. 모델이 계속 호출을 반복하면 내부 Graph의 recursion_limit=16에서 요청을 오류 종료한다. 연구 계획과 종합은 별도 호출 예산이다.
- 파일 길이 제한은 보류했다. 대화방 삭제는 장기 기억을 지우지 않으며, 명시적인 기억 삭제는 remove로 처리한다. 원본 대화와 요약에 남은 과거 언급까지 삭제하는 기능은 아니다.
- 실제 LangChain loop + 가짜 모델로 도구 호출 후 답변을 검증했다. 실제 LLM 저장 판단·삭제 판단·반복 방지 효과는 별도 평가 대상이다.

### 상위 Agent와 LangGraph

- `POST /api/chat/stream`은 `src/stock_agent/graph.py`를 실행한다. 별도 Chat Router·일반 답변·Plan·Synthesis 노드는 없다.
- `upper_agent`는 같은 `PLANNER_MODEL`과 시스템 프롬프트로 직접 답변·조사 계획·조사 후 종합을 담당한다. 첫 호출에서 `UpperDecision`으로 일반 답변 또는 `ResearchPlan`을 반환한다.
- 일반 답변은 첫 상위 Agent 호출로 종료한다. 조사 요청은 계획을 만든 뒤 기존 Parser·Python으로 입력을 검증하고 선택된 Worker를 병렬 실행한다.
- `research` 하위 그래프에는 입력 검증과 Worker만 있다. 선택된 Worker가 모두 끝나면 같은 `upper_agent` 노드로 돌아와 최초 질문·계획·조사 조건·보고서를 입력받아 종합한다. 잘못된 입력은 Worker 실행 전에 종료한다.
- FastAPI는 단기 맥락 준비·이벤트 변환·대화 저장을 담당한다. 그래프 조건부 엣지가 실행을 제어하며 최종 완료 이벤트는 요청당 한 번 보낸다.
- `/api/research/stream`도 같은 그래프에 `research_only=true`를 전달해 조사 계획을 요구한다. 이 경로는 대화 DB에 저장하지 않는다.
- Chat 상위 Agent는 USER.md를 자동으로 읽고 메모리 갱신 Tool을 사용한다. 포트폴리오 자동 진단은 별도 API로 유지한다.

```text
사용자 질문 → 상위 Agent
                ├─ 일반 답변 → 종료
                └─ 조사 계획 → 입력 검증 → 선택 Worker 병렬 조사
                                  실패 → 오류 종료       ↓
                                                같은 상위 Agent → 종합 답변
```

## 노드 책임

### 독립 포트폴리오 진단

- 자동 연결은 `/configuration`(키 유무만 확인) → `/diagnose` 순서다. 계좌 목록 조회·선택을 진단 함수에서 한 번 수행해 자동 진단의 중복 목록 조회를 제거했다. 별도 새로고침·동시 요청에 의한 429 가능성은 남으며 이를 명시적으로 반환한다.
- Toss GET은 401일 때 거절된 캐시 토큰을 갱신해 한 번만 재시도한다. 다른 요청이 이미 갱신했다면 최신 토큰을 재사용한다. 429는 토큰 재발급 대상으로 취급하지 않는다.

- 페이지 진입 시 서버가 Toss 키 유무를 확인한다. 설정된 경우 API 목록의 첫 번째 BROKERAGE 계좌를 자동 선택해 한 번 진단한다. 별도 탭·계좌 선택 UI는 없으며 실패해도 Research 입력을 막지 않는다. 새로고침은 새 유료 진단을 발생시킨다.

- `backend/portfolio.py` → `src/stock_agent/portfolio/service.py`. 기존 Research Graph·State·Trajectory를 호출하지 않는다.
- `portfolio/schemas.py`는 입력·업종·AI 출력 스키마, `analysis.py`는 외부 호출 없는 정규화·계산, `service.py`는 프롬프트·Toss/LLM 호출·실행 순서·외부 오류 처리를 담당한다. 패키지 초기화는 서비스 모듈을 자동 import하지 않는다.
- 본인 계좌 선택 → Toss Holdings·Stock Info 조회 → 원화 국내 `STOCK` 필터·중복 합산 → AI 업종 분류 → Decimal 계산 → AI 해설.
- 업종은 `WORKER_MODEL`의 단일 Structured Output 호출, 해설은 `PLANNER_MODEL`의 단일 Structured Output 호출이다. Tool loop는 없으며 분류 누락·중복·추가를 검사한다.
- 지원 평가금액이 0이거나 업종 분류가 누락·중복되면 중단한다. 분류·해설 실패 시 부분 성공 보고서를 반환하지 않으며 자동 재분류·진단 재시도는 없다.
- 종목·상위 3종목·업종 비중과 최대 종목 -20% 시나리오를 계산한다. 금액·비율은 JSON 문자열로 전달하고 화면에서 반올림한다.
- 종목별·전체 매입금액, 현재 평가금액, 평가손익과 평가손익률을 Decimal로 계산해 표로 출력한다. 현재 보유분 기준이며 추가 금액 필드는 LLM에 전달하지 않는다. 매입금액 0의 손익률은 산정 불가로 표시한다.
- 분모는 지원 대상 주식 평가금액만이다. 현금·목표 비중·외화·ETF 등 제외 자산은 포함하지 않는다. 신용 매수 여부는 현재 Holdings 필드로 판별하지 못하며 부채·레버리지 위험은 평가하지 않는다.
- 계좌번호는 브라우저·LLM에 보내지 않는다. 분류에는 회사 식별 정보만, 해설에는 질문·비중·분류·시나리오 비율만 보낸다. 로컬 Trace와 브라우저 영속 저장은 사용하지 않는다. 선택용 accountSeq는 로컬 클라이언트와 서버 사이에서만 사용한다.
- 인증 없는 개인 실행이므로 새 API는 loopback 접속·로컬 Host/Origin만 허용한다. 공개 배포는 지원하지 않으며 조회·주문 권한이 분리된 토큰을 보장하는 것은 아니다. 코드에서 주문 API를 호출하지 않는다.
- 실제 계좌·LLM 통합 실행은 아직 검증하지 않았다. Mock 테스트와 프론트 빌드로 확인한다.

### Request Parsing

- `PARSER_MODEL` 사용
- 회사 후보·조사 질문·기준일·기간 추출
- 상대 날짜 계산용 기준 날짜는 시스템 메시지에, 사용자 원문은 user 메시지에 분리한다. 원문에 날짜·기간이 없으면 null을 추출하고 Python에서 오늘·30일을 적용한다.
- Pydantic `ParsedRequest` 반환
- Tool과 금융 분석 없음

### Deterministic Input Validation

- DART 회사명 확인과 내부 종목코드 자동 변환
- 복수 종목 거부
- 날짜 형식과 미래 날짜 검사
- 기간 기본값·범위 검사
- 잘못된 입력은 `input_error`로 조기 종료
- 검증된 입력과 공통 제약을 `ResearchMandate`로 생성

### 상위 Agent — 직접 답변·계획

- `PLANNER_MODEL` 사용
- 필요한 Agent 선택
- 핵심 조사 질문과 완료 기준 생성
- 일반 질문에는 `UpperDecision.final_answer`, 조사 요청에는 `UpperDecision.research_plan` 반환

### Worker Agent

- ResearchPlan에 포함된 Worker만 조건부 edge로 선택해 병렬 실행
- Business: `get_disclosure`
- Macro/Sector: `search_web`
- Event/Catalyst: `get_market_evidence`, `search_web`, `get_disclosure`

### 같은 상위 Agent — 조사 후 종합

- ResearchPlan과 Worker 결과 종합. Chat에서는 메모리 갱신 Tool만 사용 가능
- 새로운 사실·수치·출처를 생성하지 않도록 프롬프트로 안내한다. 코드에 독립 사실 검증 단계는 없다.
- `final_answer` 마크다운 반환

### Execution Trajectory

- 직접 지정한 종목 조사와 기존 Research API 실행에만 `traces/YYYY-MM-DD/<run_id>.json` 생성
- Chat은 검증·Worker 하위 그래프를 기록하며 상위 Agent 호출·일반 답변은 제외한다. 조사 전용 API는 상위 Agent 호출까지 기록한다. 포트폴리오 진단은 제외한다.
- Evidence ID는 완료된 Tool 호출 ID이며 주장·인용의 타당성을 검증한 결과가 아님
- Worker 내부 Tool 이름·인자·결과와 Evidence Tool 호출 ID 기록
- 기록 범위 안의 Parser·상위 Agent·Worker 모델 호출 횟수 기록
- 상위 LangGraph 노드별 실행 시간 기록
- 예외 발생 시 노드 이름·오류·직전 공유 상태 기록
- Token delta와 모델 내부 추론은 기록하지 않음

## 데이터 흐름

### 평가 실행 경계

- `evals/scripts/run_eval.py`는 실제 Parser와 상위 Agent의 조사 계획 동작을 평가 사례별로 호출한다.
- Parsing 평가에서만 Parser 모듈의 오늘 날짜와 회사 조회를 고정 Fixture로 교체한다. 제품 실행 경로는 변경하지 않는다.
- 계약·입력 검증은 LLM 실행 전에 수행하고, 모델·프롬프트·코드·데이터 버전과 사례별 반복 결과를 저장한다.
- 자동 평가는 Parsing·Routing만 지원한다. 공식 실적 자료 기반 Grounding 사례는 근거 준비 상태이며 Worker·Synthesis·E2E 자동 채점은 미구현이다.
- 상세 평가 계약과 명령은 `evals/README.md`에서 관리한다.

```text
raw_user_input
→ 상위 Agent: 직접 답변 또는 ResearchPlan
→ 조사일 때 ParsedRequest·검증된 ResearchMandate
→ Worker Reports
→ 같은 상위 Agent: Final Answer
```

## 설계 이유와 데이터 한계

- **의도 분류와 종목 검증 분리:** 일반 질문에 회사 입력을 강제하지 않고, 조사에 필요한 회사·날짜는 Python으로 확정한다.
- **계획과 실행 분리:** LLM이 Structured Plan을 작성하고 LangGraph가 Worker 경로를 제어한다. Worker별 Tool 권한은 코드로 제한한다.
- **계좌 진단 분리:** 숫자는 Python으로 계산하고 AI는 업종 추정·해설을 담당한다. 계좌 구성 진단 때문에 종목 리서치 전체를 실행하지 않는다.
- **대화 원문과 모델 맥락 분리:** DB 원문은 유지하고 모델에는 누적 요약과 최근 완료된 10턴을 전달한다. 요약 손실과 장문 입력 한도는 별도 평가가 필요하다.
- **DART:** 회사 확인·공시 목록을 제공한다. 공시 본문·재무 수치를 가져오지 않으며 목록 조회는 오늘 기준이다. 비정상 응답 코드가 빈 목록으로 처리되는 한계가 있다.
- **Tavily:** 검색 결과의 제목·URL·본문 일부를 제공한다. 원문 전체를 읽거나 자료 공개일을 강제 검증하지 않는다.
- **Toss:** 시세·보유 현황·상품 정보를 제공한다. 계좌 진단은 국내 원화 일반 주식으로 제한한다.
- 모든 외부 근거의 기준일 준수·금융적 정확성은 보장되지 않는다. 자동 평가는 [평가 안내](../evals/README.md)의 제한된 계약 범위다.

## 코드 구조

```text
backend/
├── main.py                 # Chat·Research SSE
├── conversations.py        # 대화 저장·복원·요약 경계
├── short_term_memory.py    # 10턴 유지·Luna 요약
└── portfolio.py            # 계좌 진단 API

frontend/

src/stock_agent/
├── graph.py
├── state.py
├── trajectory.py
├── control/
│   └── request_parser.py
├── agents/
├── gateways/
├── portfolio/              # schemas·analysis·service
├── tools/
└── vendors/
```
