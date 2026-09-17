# API 명세 — Tomade

> 2026-09-17 모델 설정·로그인 API 추가. Chat·대화 저장·포트폴리오와 기존 Research SSE 계약.

## 1. 목적

### Chat Routing — 구현

`POST /api/chat/stream`은 `{message: 1~300자, conversation_id?: UUID}`를 받고 SSE로 답한다. 공백·잘못된 UUID는 422, 외부 접근은 403이다. ID가 있으면 질문과 최종 답변을 저장한다. 없는 대화는 404, 같은 대화에서 답변 생성 중이면 409이며 모델 호출 전에 거부한다. ID 생략 시 대화 기록·단기 맥락 없이 실행하되 로컬 사용자의 장기 기억은 공유한다. 프론트 Chat은 선택 대화의 ID를 전달하며 기존 `/api/research/stream`은 직접 종목 조사 전용으로 유지한다.

- `upper_agent`가 첫 호출에서 직접 답변하거나 `intent: research`와 `research_plan`을 반환한다.
- 일반 답변은 구조화 출력 완료 후 전달하며 Parser·Worker를 skipped로 표시한다.
- 조사 요청은 `request_parser` → 선택 Worker → 같은 `upper_agent` 순서다. 상위 Agent는 계획과 종합에서 같은 노드 ID를 사용하므로 node.started/completed가 두 번 발생한다.
- 조사 후 종합은 node.delta로 스트리밍한다. run.completed는 최종 답변이 완성된 뒤 한 번만 전달한다.
- Chat은 계좌 조회·진단을 실행하지 않는다. 세션 ID가 있으면 단기 메모리를 주입한다. 장기 기억은 세션 ID와 관계없이 로컬 Chat에 자동 주입하며 필요 시 상위 Agent가 갱신한다.
- 상위 Agent는 PLANNER_MODEL을 사용한다. Mock 검증은 실행 계약을 확인하며 실제 모델 판단 품질은 별도 평가 대상이다.

### 대화방 API — 구현

모든 경로는 로컬 단일 사용자 전용이며 외부 접근은 403, 성공 응답은 `Cache-Control: no-store`다.

| 메서드·경로 | 응답 |
| --- | --- |
| GET /api/conversations | 최근 updated_at 순 대화 배열 |
| POST /api/conversations | 본문 없이 생성. 201과 빈 대화 객체 |
| GET /api/conversations/{id} | 대화 객체와 messages 배열(ID 오름차순) |
| DELETE /api/conversations/{id} | 대화·메시지 삭제 후 204. 생성 중이면 409 |

대화 객체: `id, user_id, title, created_at, updated_at, summary, last_summarized_message_id`. 메시지 객체:
`id, conversation_id, role, content, status, created_at`. 필드 계약은 [스키마](schema.md)를 따른다.
없는 대화 또는 다른 소유자의 대화는 404, 잘못된 UUID는 422다. 초기 사용자 ID는 서버에서
`local`로 고정하며 클라이언트가 사용자를 지정하지 않는다. 인증/공개 배포는 지원하지 않는다.

Chat은 사용자 질문과 pending 답변을 먼저 저장한다. run.completed/run.error의 최종 내용은
이벤트를 보내기 전에 저장한다. 연결 중단·서버 재시작은 interrupted로 표시한다.
서버는 한 프로세스로 실행한다. 자동 재실행·재연결·다른 탭의 실시간 갱신은 없다.
UI는 URL의 대화 ID로 복원한다. 서버는 최근 완료된 10턴과 세션 요약을 상위 Agent에 전달한다.
10턴 초과 시 SUMMARY_MODEL로 오래된 구간을 통합 요약한다. 요약 실패 시 기존 요약·경계를 보존하고
run.error(code=node_execution_failed)를 전송하며 현재 답변을 error로 저장한다. 원문과 내부 오류는 응답에 노출하지 않는다.
기록은 사용자 메시지·최종 답변·정제된 오류만이며 토큰·노드 출력·포트폴리오 상세 표는 제외한다.

### 모델 연결 설정 API — 구현

로컬 단일 사용자·단일 서버 프로세스 전용이다. `require_local`로 외부 접근을 403으로 거부하고 성공 응답은 `Cache-Control: no-store`다. 앱 사용자 로그인과 별개로 모델 공급자 인증을 다룬다.

| 메서드·경로 | 동작 |
| --- | --- |
| GET /api/settings/models | 현재 공급자·인증 방식·역할별 모델·실행 여부·키 유무·Codex 로그인 상태 조회. 외부 호출 없음 |
| PUT /api/settings/models | `{provider: openai 또는 openrouter 또는 openai_codex}`. `.env` 저장·현재 프로세스 적용 후 조회와 같은 응답 |
| PUT /api/settings/codex/models | `{planner, parser, worker, summary}` 각각 `{model, reasoning_effort}`. 구독 활성 상태에서 네 역할을 함께 저장하고 조회와 같은 응답 |
| POST /api/settings/codex/login | 기기 코드 발급. 진행 중 로그인은 재사용 |
| POST /api/settings/codex/login/{id}/poll | 간격을 지켜 승인 조회. 완료 시 프로젝트 전용 인증 저장. 공급자는 유지 |
| DELETE /api/settings/codex/login/{id} | 로그인 대기 종료. `{cancelled: true}`. 저장된 인증은 삭제하지 않음 |

조회 응답은 `provider`, `auth_mode`, `models`, `reasoning_efforts`, `codex_model_options`, `busy`, `api_keys`, `codex`, `login`이다. 로그인 응답은 `id`, `state`, `message`, `user_code`, 고정 `verification_url`, `interval`, `expires_in`이다. 필드와 상태는 [스키마](schema.md#모델-연결-설정)를 따른다. 토큰·계정 ID·API 키 값·내부 기기 인증 ID는 반환하지 않는다.

PUT은 저장된 구독 인증 또는 API 키가 없거나 실행 중이면 409, 잘못된 공급자는 422, 파일 저장 실패는 500이다. 로그인 발급 실패는 정제된 메시지와 502, 없는 대기 ID는 404다. 승인 조회 실패는 로그인 `state=error`로 전달한다. 로그인 시간은 최대 15분이며 서버 재시작 시 대기 세션은 사라진다. 상태 조회는 실제 모델 인증·권한 검증을 수행하지 않는다.

역할 설정 PUT은 실행 중 또는 구독 방식이 아니면 409, 모델·추론 조합이나 역할 스키마가 잘못되면 422, 저장 실패는 500이다. 네 역할의 설정을 원자적으로 저장하고 캐시를 비운다. 실제 모델 호출은 수행하지 않는다.

### 독립 포트폴리오 API — 구현

- 자동 실행: `GET /api/portfolio/configuration`으로 키 존재 여부만 확인한다(외부 호출 없음). configured=true이면 `POST /api/portfolio/diagnose`에 `{}`를 전송한다. 서버가 계좌 목록을 한 번 조회해 첫 BROKERAGE를 선택한다. 자동 흐름에서 `/accounts`를 먼저 호출하지 않는다.
- `account_seq`는 선택 항목이며 명시하면 본인 계좌 목록과 검증한다. 외부 실행 실패는 `toss.accounts`, `toss.holdings`, `toss.stocks`, `llm.classification`, `llm.explanation` 단계와 upstream HTTP 상태만 알린다. 서버 로그는 단계·예외 유형·상태만 기록하며 원문·계좌·토큰은 기록하지 않는다. upstream 429는 429로 반환한다.

- `GET /api/portfolio/accounts`: `{configured: boolean, accounts: [{account_seq, account_type}]}`. 서버에 Toss 키가 없으면 false·빈 목록을 반환하고 외부 호출하지 않는다. 키 값은 노출하지 않는다. BROKERAGE만 반환하며 계좌번호는 제외한다. 프론트는 첫 번째 계좌를 자동 진단한다.
- `POST /api/portfolio/diagnose`: `{account_seq?: 양의 정수, message?: 1~300자}`. 질문 생략 시 기본 집중도 진단 요청을 사용한다. 공백 질문은 422다.
- JSON 응답: `fetched_at`, `source`, `scope`, `currency`, `total_amount`, `holdings`, `top_one_pct`, `top_three_pct`, `sectors`, `scenario`, `excluded`, `explanation`.
- `holdings`: 종목코드·이름·금액·백분율·AI 업종·분류 이유. `sectors`: 업종·금액·백분율. `scenario`: 최대 종목 코드·이름·충격률·영향 금액·영향률. 모든 수치는 금액/백분율 문자열이다.
- `excluded`: 종목코드·이름·제외 사유. `explanation`: 요약·관찰 목록·한계 목록. 계좌 식별자는 진단 응답에 포함하지 않는다.
- 보유분 손익: 종목별 `purchase_amount`, `profit_loss`, `profit_loss_pct`, 전체 `total_purchase_amount`, `total_profit_loss`, `total_profit_loss_pct` 추가. 금액과 손익률은 문자열, 매입금액 0의 손익률은 null이다. 합산 손익률은 종목별 평균이 아닌 합산 매입금액 기준이다. Toss `marketValue.purchaseAmount`와 `amount`를 사용하며 별도 세금·수수료 공제 전, 매도 실현손익·배당 미포함이다.
- SSE가 아닌 독립 요청/응답이다. 계좌를 본인 목록과 검증하고 Toss 조회와 업종·해설 LLM 호출을 수행한다. 웹에서는 포트폴리오 창을 처음 열 때 한 번 실행하며 폴링·자동 재시도·취소·재개는 없다. 새로고침 후 창을 다시 열면 새 호출 비용이 발생한다.
- `/diagnose` 오류: 403 외부 접근, 422 입력·계좌/분류 검증 실패, 503 API 경계의 설정/응답 필드 누락, 502 공급자 실행 실패, upstream 429는 429. 서비스 단계에서 포장된 오류는 원인에 따라 502/429로 반환하므로 모든 설정 누락이 503인 것은 아니다. 공급자 오류 원문은 반환하거나 로그로 남기지 않는다.
- 로컬 개인 실행만 허용한다. 성공 응답 `Cache-Control: no-store`, 클라이언트 캐시·영속 저장 없음. 공개 배포 전 사용자 인증과 계좌 권한 분리가 필요하다.

기존 `/api/research/stream`에는 Chat·대화·포트폴리오 API의 `require_local` 검사가 붙어 있지 않다. 개발 서버의 loopback 바인딩을 유지해야 하며 공개 배포용 인증은 없다.

아래는 기존 종목 조사 SSE 계약이며 포트폴리오 API와 독립이다.

현재 웹 화면에 다음 정보를 실시간으로 전달한다.

- 사용자가 입력한 종목 질문
- LangGraph 노드 실행 상태
- 완료된 노드의 산출물
- 선택되지 않은 Worker 상태
- Orchestrator의 최종 마크다운 답변

현재 Chat UI는 선택 세션의 요약과 최근 완료된 10턴을 사용하며, 상위 Agent가 계획을 만든 경우에만 검증·Worker 조사를 실행한다. 세션 ID 없는 Chat과 Research API는 독립 실행을 유지한다.

## 2. MVP 범위

### 포함

- 단일 자연어 질문 전송
- 노드 단위 Server-Sent Events Streaming
- 노드 시작·완료·선택 안 됨 상태
- Worker와 상위 Agent 종합의 Token Streaming
- 노드 산출물
- 최종 답변
- 입력 및 실행 오류

### 제외

- 종목명을 생략한 후속 조사 요청의 Parser 해석 확장
- 실행 결과 재조회
- 실행 취소
- 로그인과 사용자별 세션
- 여러 종목 동시 분석

## 3. Research Streaming

```http
POST /api/research/stream
Content-Type: application/json
Accept: text/event-stream
```

### Request

```json
{
  "message": "삼성전자 최근 30일 주가가 오른 이유를 알려줘"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `message` | string | O | 종목과 질문을 포함한 단일 자연어 입력 |

`message`는 1자 이상 300자 이하여야 한다. 길이·필드 형식 검증 실패는 Pydantic 오류 목록을 담은 HTTP `422`를 반환한다. 공백만 있는 입력은 아래처럼 문자열 detail을 반환한다. 둘 다 Graph 실행 전 거부한다.

```json
{
  "detail": "message는 1자 이상 300자 이하여야 합니다."
}
```

### Response

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
```

각 SSE의 `data`는 JSON 객체다.

```text
event: node.completed
data: {"run_id":"run-123","node":"business","output":{"business_report":"..."}}

```

## 4. Node 식별자

API는 실제 LangGraph 노드 이름을 사용한다.

```text
upper_agent
request_parser
business
macro_sector
event_catalyst
```

현재 노드 식별자는 `upper_agent`, `request_parser`, `business`, `macro_sector`, `event_catalyst`다. 프론트에서는 상위 Agent를 부장 캐릭터로, 세 Worker를 조사 캐릭터로 표시하며 입력 검증은 현재 부장 답변 영역과 접근성 상태로 안내한다.

## 5. Event 명세

### 5.1 `run.started`

Chat/Research Run이 시작됐음을 알린다. `connection`에는 해당 요청이 선택한 공급자·인증 방식·역할별 모델·추론 깊이·실행 상태를 담는다. 모델 호출 성공 여부는 아니다.

```text
event: run.started
data: {"run_id":"run-123","connection":{"provider":"openai_codex","auth_mode":"subscription","models":{"planner":"gpt-5.6-luna","parser":"gpt-5.6-luna","worker":"gpt-5.6-luna","summary":"gpt-5.6-luna"},"reasoning_efforts":{"planner":null,"parser":null,"worker":null,"summary":null},"busy":true}}

```

프론트엔드는 이전 노드 상태를 초기화하고 입력창을 비활성화한다.

### 5.2 `node.started`

`{run_id, node}`. 노드 실행 단계를 표시한다. 조사 경로의 upper_agent는 계획과 종합에서 각각 발생한다.

### 5.3 `node.delta`

`{run_id, node, delta}`. Worker 보고서와 상위 Agent 종합의 텍스트 조각이다. 일반 답변은 구조화 출력 완료 후 전달하므로 같은 방식의 토큰 스트림을 보장하지 않는다.

### 5.4 `node.completed`

`{run_id, node, output}`. 노드의 State Update를 전달한다. 상위 Agent의 첫 조사 출력에는 intent와 research_plan, 종합 출력에는 final_answer가 들어간다.

### 5.5 `node.skipped`

`{run_id, node}`. 조사에서는 선택하지 않은 Worker, 일반 답변에서는 request_parser와 세 Worker를 표시한다.

### 5.6 `run.completed`

최종 답변까지 생성된 정상 종료 이벤트다.

```text
event: run.completed
data: {"run_id":"run-123","final_answer":"# 삼성전자 리서치 답변\n\n..."}

```

프론트엔드는 최종 답변을 부장 대화창에 Markdown으로 표시하고 입력창을 다시 활성화한다.

### 5.7 `run.error`

Stream 시작 이후 입력 해석 또는 노드 실행이 실패했음을 알린다.

```text
event: run.error
data: {"run_id":"run-123","node":"request_parser","code":"input_error","message":"현재는 한 번에 한 종목만 지원합니다."}

```

노드 실행 오류 예시:

```text
event: run.error
data: {"run_id":"run-123","node":"business","code":"node_execution_failed","message":"Business Agent 실행에 실패했습니다."}

```

내부 Stack Trace, API Key, 공급자 응답 원문은 클라이언트에 전달하지 않는다.

## 6. 노드별 Output

`output`은 각 LangGraph 노드가 반환한 State Update 구조를 유지한다.

### 6.1 Request Parser

```json
{
  "parsed_request": {
    "company_candidates": ["삼성전자"],
    "research_question": "최근 30일 주가가 오른 이유",
    "as_of_date": null,
    "period_days": 30,
    "needs_clarification": false,
    "clarification_reason": null
  },
  "research_mandate": {
    "original_question": "삼성전자 최근 30일 주가가 오른 이유를 알려줘",
    "research_question": "최근 30일 주가가 오른 이유",
    "ticker": "005930",
    "corp_name": "삼성전자",
    "as_of_date": "2026-08-24",
    "period_days": 30,
    "purpose": "근거 기반 종목 리서치와 투자 판단 지원",
    "constraints": [
      "투자 의견에는 근거, 판단 조건, 반대 요인과 불확실성을 함께 제시한다.",
      "수익을 보장하거나 자동 주문을 실행하지 않는다.",
      "확인된 사실과 해석을 구분한다.",
      "분석 기준일 이후의 정보를 사용하지 않는다."
    ]
  }
}
```

### 6.2 상위 Agent — 조사 계획

```json
{
  "intent": "research",
  "research_plan": {
    "planning_summary": "가격 변동 이유 조사이므로 Event/Catalyst를 선택했다.",
    "tasks": [
      {
        "agent": "event_catalyst",
        "objective": "주요 가격 변동과 관련 사건 확인",
        "questions": [
          "주요 가격 변동일은 언제인가?",
          "해당 시점에 어떤 사건이 있었는가?"
        ],
        "completion_criteria": [
          "가격 수치를 포함한다.",
          "사건의 출처를 포함한다."
        ]
      }
    ]
  }
}
```

Plan의 `tasks`에 포함된 Worker는 `node.started`, 포함되지 않은 Worker는 `node.skipped`로 전달한다.

### 6.3 Worker

Business:

```json
{
  "business_report": "# Business Report\n\n..."
}
```

Macro/Sector:

```json
{
  "macro_sector_report": "# Macro / Sector Report\n\n..."
}
```

Event/Catalyst:

```json
{
  "event_catalyst_report": "# Event / Catalyst Report\n\n..."
}
```

Worker가 둘 이상 선택되면 병렬로 실행되므로 `node.delta`와 완료 이벤트 순서는 고정하지 않는다. 프론트엔드는 `node`별 Buffer를 분리한다.

### 6.4 같은 상위 Agent — 종합

```json
{
  "final_answer": "# 삼성전자 리서치 답변\n\n..."
}
```

상위 Agent 종합의 `node.delta`는 Chat Assistant Bubble에 즉시 추가한다. 같은 `final_answer`를 `node.completed`와 `run.completed`에 포함해 최종 Markdown을 확정한다.

## 7. 정상 Stream 예시

Event/Catalyst만 선택된 경우. Parser 산출물은 흐름 설명을 위해 빈 객체로 생략했다.

```text
event: run.started
data: {"run_id":"run-123"}

event: node.started
data: {"run_id":"run-123","node":"upper_agent"}

event: node.completed
data: {"run_id":"run-123","node":"upper_agent","output":{"intent":"research","research_plan":{"planning_summary":"가격 변동 조사","tasks":[{"agent":"event_catalyst","objective":"변동 원인 확인","questions":["변동 원인은?"],"completion_criteria":["가격과 사건 근거 확인"]}]}}}

event: node.started
data: {"run_id":"run-123","node":"request_parser"}

event: node.completed
data: {"run_id":"run-123","node":"request_parser","output":{"parsed_request":{},"research_mandate":{}}}

event: node.skipped
data: {"run_id":"run-123","node":"business"}

event: node.skipped
data: {"run_id":"run-123","node":"macro_sector"}

event: node.started
data: {"run_id":"run-123","node":"event_catalyst"}

event: node.delta
data: {"run_id":"run-123","node":"event_catalyst","delta":"주요 가격 변동일은 "}

event: node.delta
data: {"run_id":"run-123","node":"event_catalyst","delta":"2026-08-20입니다."}

event: node.completed
data: {"run_id":"run-123","node":"event_catalyst","output":{"event_catalyst_report":"주요 가격 변동일은 2026-08-20입니다."}}

event: node.started
data: {"run_id":"run-123","node":"upper_agent"}

event: node.delta
data: {"run_id":"run-123","node":"upper_agent","delta":"# 삼성전자 리서치 답변\n\n"}

event: node.completed
data: {"run_id":"run-123","node":"upper_agent","output":{"final_answer":"# Final Answer\n..."}}

event: run.completed
data: {"run_id":"run-123","final_answer":"# Final Answer\n..."}

```

## 8. LangGraph 연결

백엔드는 LangGraph의 State Update와 LLM Token Stream을 API 이벤트로 변환한다. 현재 `graph.astream(..., stream_mode=["custom", "updates"], subgraphs=True)`에서 custom 이벤트를 `node.delta`, updates를 `node.completed`로 변환한다.

```text
State Update
→ node.completed

최종 자연어 출력 Token
→ node.delta
```

LangGraph update:

```python
{
    "business": {
        "business_report": "..."
    }
}
```

SSE 변환:

```text
event: node.completed
data: {"run_id":"run-123","node":"business","output":{"business_report":"..."}}

```

## 9. 프론트엔드 처리 규칙

```text
질문 전달 (run.started 수신 전)
→ 이전 조사 상태 초기화, 입력 비활성화, 대화창 유지, 오른쪽에 사용자 질문 추가

node.started
→ 노드 running, 선택된 Worker 자리 이동·착석

node.delta
→ node별 Buffer와 열린 조사 노트·부장 대화에 문장 반영

node.completed
→ 노드 done, 최종 Output으로 Buffer 교체, Worker 보고 이동
  (첫 upper_agent 계획 완료는 최종 답변으로 취급하지 않음)

node.skipped
→ 노드 skipped, 해당 Worker는 산책 유지

run.completed
→ 부장 대화창 자동 열기, 최종 Markdown 표시, 입력 활성화

run.error / 완료 전 연결 종료
→ 조사 모션 정리, 부장 오류 안내, 입력 활성화
```

프론트엔드는 병렬 Worker의 Token과 완료 순서를 가정하지 않고 `node`별 Buffer를 독립적으로 관리한다.

## 10. 구현 기술

```text
Backend
├─ FastAPI
├─ Uvicorn
└─ StreamingResponse

Frontend
├─ Vanilla TypeScript
└─ Vite

Transport
├─ 단일 POST 요청
├─ SSE Response Stream
└─ fetch() Stream Reader
```

프론트엔드는 `EventSource` 대신 `fetch()`로 POST 요청을 보내고 Response Stream에서 SSE를 읽는다. 개발 환경에서는 Vite가 `/api`를 FastAPI로 Proxy하고, 배포 시에는 FastAPI가 빌드된 정적 프론트엔드와 API를 같은 Origin에서 제공한다.
