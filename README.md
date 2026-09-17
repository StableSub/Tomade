<p align="center">
  <img src="docs/assets/tomade-logo.png" alt="Tomade — 토마토 세 개가 함께하는 로고" width="442">
</p>

<p align="center">
  질문에서 근거까지, 나의 주식 리서치 에이전트.
</p>

<p align="center">
  <strong>Python · LangGraph · FastAPI · TypeScript</strong><br>
  Local-first · Multi-Agent Research · Portfolio Insights
</p>

<p align="center">
  <a href="#시작하기">시작하기</a> ·
  <a href="#주요-기능">주요 기능</a> ·
  <a href="#평가">평가</a> ·
  <a href="docs/architecture.md">아키텍처</a> ·
  <a href="docs/api.md">API</a>
</p>

---

## Tomade

**Tomade**는 자연어 질문에 따라 기업·산업·사건을 조사하고, 보유 주식의 구성과 평가손익을 보여주는 개인용 AI 리서치 프로젝트입니다.

AI Engineering 학습을 목적으로 **질문 라우팅, 역할별 Tool 권한, 구조화된 입력·계획, Python 계산, 평가와 실행 추적**을 직접 연결합니다. 완성된 투자 판단 시스템이 아니라, 근거와 한계를 확인하며 개선하는 로컬 프로토타입입니다.

## 주요 기능

| 기능 | 현재 동작 |
| --- | --- |
| 질문 라우팅 | 상위 Agent가 직접 답변하거나 조사 계획을 작성 |
| 단일 종목 리서치 | 상위 Agent의 계획에 따라 입력 검증·선택 Worker 조사 후 같은 Agent가 종합 |
| 포트폴리오 진단 | 국내 원화 일반 주식의 매입금액·평가금액·손익·종목 및 추정 업종 집중도 표시 |
| 대화 기록 | 대화 생성·선택·삭제, SQLite 저장과 새로고침 후 복원 |
| 실행 추적 | 직접 지정한 종목 조사의 Tool 호출·모델 호출 횟수·노드 시간·실패 기록 |
| 도트 사무실 | Agent 산책·조사 착석·보고 이동, 캐릭터 클릭으로 조사 노트와 부장 대화 열기 |

**세션별 단기 메모리:** 최근 완료된 질문·답변 10턴을 상위 Agent에 전달합니다. 초과한 오래된 턴은 `gpt-5.6-luna`로 기존 요약과 통합하며 원문은 DB에 보존합니다. 장기 기억은 `memory/local/USER.md`에서 자동으로 읽고, 상위 Agent가 필요할 때 갱신합니다.

### 이렇게 질문하세요

- “PER가 뭐야?” — 일반 개념 답변. 저장할 사용자 사실이 있을 때만 메모리 Tool 사용.
- “삼성전자 최근 30일 주가 하락 이유를 분석해줘.” — 종목 조사.

예시는 의도한 경로이며 실제 분류는 LLM 판단에 따라 달라질 수 있습니다.

## 어떻게 작동하나요?

상위 Agent가 직접 답변하거나 조사 계획을 작성합니다. LangGraph가 입력 검증·선택 Worker 조사를 실행한 뒤 같은 상위 Agent로 결과를 돌려줍니다.

**종목 조사**

1. **상위 Agent** — 직접 답변 또는 필요한 Worker·조사 질문·완료 기준 작성.
2. **Parser·Python 검증** — 조사 요청의 회사·날짜·기간 추출 및 검증.
3. **Workers** — 선택된 전문 영역을 병렬 조사.
4. **같은 상위 Agent** — 최초 계획과 보고서를 받아 종합하며 Chat에서는 메모리 갱신 Tool만 사용 가능.

| Worker | 조사 영역 | 허용 Tool |
| --- | --- | --- |
| Business | 기업 공시와 확인 가능한 변화 | DART 공시 목록 |
| Macro / Sector | 산업·거시환경 | Tavily 웹 검색 |
| Event / Catalyst | 가격·거래량과 관련 사건 | Toss 시세·웹 검색·공시 목록 |

**포트폴리오 진단**은 직원 사무실 오른쪽 아래를 걷는 커비를 눌러 포트폴리오 창을 처음 열 때 실행하며, 종목 조사 Graph에서 분리되어 있습니다. 같은 페이지에서 창을 다시 열면 기존 결과를 보여줍니다. Toss 보유 현황 조회 후 AI가 업종을 추정하고, Python이 금액·비중·손익을 계산하며, 설명 모델이 결과를 해설합니다.

### 리서치 오피스 사용법

- 부장 캐릭터 또는 **부장에게 말 걸기**를 누르면 왼쪽 대화 영역과 오른쪽 사무실 미니맵으로 전환합니다. 사무실은 약 0.35초 동안 축소되며 미니맵을 누르면 원래 크기로 돌아옵니다. 모바일에서는 대화창 상단에 작은 미니맵을 표시합니다.
- 사용자 질문은 대화 영역 오른쪽, 부장 답변은 왼쪽에 표시합니다. 저장된 대화와 새 답변을 이어서 읽으며, 질문을 보내도 대화창은 유지됩니다. Enter는 전달, Shift + Enter는 줄바꿈입니다. 미니맵으로 오갈 때 작성 중인 입력도 유지합니다.
- 평소에는 캐릭터가 통로를 걷습니다. 실제 조사 시작 이벤트를 받은 Agent만 자리로 이동해 조사하며, 완료하면 부장에게 보고하러 이동합니다. 일반 질문에서는 Worker가 조사하지 않습니다.
- 사무실 전체 화면에서 Worker를 누르면 이번 실행의 조사 노트를 봅니다. 최종 답변이 도착하면 닫혀 있던 부장 대화창이 열립니다. 대화창에서 이전 내용을 읽는 중에는 스크롤 위치를 유지합니다.
- 부장 대화창 상단에서 대화를 생성·선택·삭제합니다. 과거 대화는 질문·최종 답변을 복원하며 Worker 보고서와 이동 상태는 복원하지 않습니다.
- 토마토 테마의 두 방 사무실과 정원이 화면 크기에 맞춰 표시됩니다. 모바일과 세로 창에서도 드래그 없이 부장·세 연구원·커비를 찾을 수 있습니다. 이름은 캐릭터 위를 따라다니며, 시스템의 동작 줄이기 설정에서는 산책을 멈추고 조사 상태를 즉시 표시합니다.

세부 흐름과 책임은 [아키텍처](docs/architecture.md), 실제 입출력은 [스키마](docs/schema.md)에 정리했습니다.

## 시작하기

### 1. 설치

Python 3.11+, Node.js 22.12+와 npm이 필요합니다. 아래 명령은 프로젝트 루트의 macOS/Linux 셸 기준입니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
npm --prefix frontend install
```

### 2. 환경 설정

`.env.example`을 참고해 프로젝트 루트에 `.env`를 만들고 사용할 기능의 키를 입력합니다. 기존 `.env`가 있다면 필요한 항목만 수정하세요.

| 설정 | 사용처 |
| --- | --- |
| `LLM_PROVIDER` | `openai` / `openrouter`는 API Key, `openai_codex`는 ChatGPT 구독 OAuth |
| `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | API 공급자의 인증. `openai_codex`에서는 사용하지 않음 |
| `CODEX_AUTH_PATH` | 구독 인증 파일. 기본 `~/.config/stock-agent/codex-auth.json` |
| `SUMMARY_MODEL` | 단기 요약 전용. 기본 `gpt-5.6-luna`, OpenRouter는 `openai/gpt-5.6-luna`. `LLM_MODEL`과 별도 |
| `PARSER_MODEL` · `PLANNER_MODEL` · `WORKER_MODEL` | 역할별 모델. 공통 기본값은 `LLM_MODEL` |
| `DART_OPENAPI_KEY` | 회사 확인·공시 조회 |
| `TAVILY_API_KEY` | 웹 검색 |
| `TOSS_CLIENT_ID` · `TOSS_CLIENT_SECRET` | 시세·계좌 조회. Toss 허용 IP 설정 필요 |

Parser 모델을 생략하면 Worker 모델 설정을 먼저 사용합니다. 상위 Agent의 일반 답변·조사 계획·결과 종합은 Planner, 포트폴리오 업종 분류는 Worker, 해설은 Planner 모델을 사용합니다. `.env`를 직접 수정했다면 서버를 재시작하세요.

#### ChatGPT 구독으로 모델 호출

웹에서는 **우측 상단 톱니바퀴 → ChatGPT 계정으로 로그인 → 로그인 페이지 열기**에서 표시된 기기 코드를 입력합니다. 완료 후 **Codex · 구독 인증 → 이 방식 사용**을 누르면 다음 요청부터 적용됩니다. 로그인만 완료해도 기존 호출 방식이 자동으로 바뀌지는 않습니다.

톱니바퀴 옆에는 실행 중 서버가 선택한 `OpenAI · API Key`, `OpenRouter · API Key`, `Codex · 구독 인증`이 표시됩니다. 설정 창에서 저장된 로그인 상태와 역할별 모델, 현재 페이지의 최근 대화 요청 방식을 확인할 수 있습니다. 상태 조회는 실제 모델을 호출하지 않으므로 인증 성공·모델 접근 권한을 검증한 결과는 아닙니다.

설정 창에서 방식을 변경하면 `.env`의 `LLM_PROVIDER`에 저장하고 서버 재시작 없이 모델 캐시를 비워 적용합니다. 답변·조사·포트폴리오 진단 중에는 전환할 수 없습니다. API 키는 `.env`에서 수정합니다. 실행 환경에서 별도로 지정한 환경변수는 재시작 시 `.env`보다 우선합니다. 로그인 창을 닫으면 승인 조회가 멈추며 다시 열어 이어갈 수 있지만 서버 재시작 후에는 새 코드를 발급해야 합니다.

구독 방식을 적용하면 **구독 모델 · 추론 깊이 변경**에서 부장·질문 해석·조사·대화 요약의 모델과 추론 깊이를 고르고 **모델 설정 저장**을 누릅니다. 세 조사 Worker는 같은 설정을 사용하며 포트폴리오 분류는 조사, 해설은 부장 설정을 따릅니다. 네 역할을 한 번에 `.env`에 저장하고 다음 요청부터 적용합니다. 저장 오류 시 기존 파일·실행 설정을 유지합니다. 창을 다시 열면 저장한 값으로 돌아가며, 수정 중 상태 새로고침은 작성 중 선택을 보존합니다.

모델 선택지는 `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`입니다. 추론은 기본값(요청에서 생략)·low·medium·high·xhigh·max이며 GPT-5.6 계열은 none도 지원합니다. 목록은 앱이 허용하는 설정 조합이고 계정별 접근 권한 조회 결과는 아닙니다. 실제 구독 접근·응답 품질은 별도 검증 대상입니다. [모델 선택 안내](https://learn.chatgpt.com/docs/models)

UI는 `PLANNER_MODEL`, `PARSER_MODEL`, `WORKER_MODEL`, `SUMMARY_MODEL`과 `CODEX_<역할>_REASONING_EFFORT`를 저장합니다. 모델 변수는 API Key 방식에서도 공유하고 추론 변수는 구독 호출에만 적용합니다. **PLANNER_MODEL·WORKER_MODEL을 지우면 기존 fallback으로 달라질 수 있으므로 선택을 유지하려면 남겨두세요.** `REVIEWER_MODEL`은 현재 호출하는 Agent가 없어 삭제해도 현재 동작에 영향이 없고, `REVIEWRMODEL`이라는 변수는 코드에서 읽지 않습니다.

macOS/Linux에서 다음 명령을 실행하고 출력된 OpenAI URL에 기기 코드를 입력합니다. ChatGPT 보안 설정이나 워크스페이스에서 **기기 코드 로그인**이 활성화되어 있어야 합니다.

```bash
.venv/bin/python -m stock_agent.gateways.codex_auth login
.venv/bin/python -m stock_agent.gateways.codex_auth status
```

로그인 후 `.env`의 `LLM_PROVIDER=openai_codex`, `LLM_MODEL=gpt-5.6-luna`를 설정하고 서버를 재시작합니다. 기존 `PARSER_MODEL`·`PLANNER_MODEL`·`WORKER_MODEL`·`SUMMARY_MODEL`에 별도 모델을 지정했다면 해당 ID도 구독 계정에서 사용할 수 있는 모델로 맞추세요. Codex 공급자의 모델 미지정 기본값은 `gpt-5.6-luna`이며 실제 계정의 모델 접근 권한을 보장하지 않습니다. API 전용 기본값인 `gpt-4o-mini`를 그대로 두지 마세요.

인증은 프로젝트 전용 파일에 권한 `600`으로 저장하며 `~/.codex/auth.json`이나 다른 하네스의 세션을 읽거나 변경하지 않습니다. CLI도 `.env`의 `CODEX_AUTH_PATH`를 읽습니다. 토큰 파일은 저장소 밖에 두고 공유하지 마세요. 로컬 로그아웃은 `.venv/bin/python -m stock_agent.gateways.codex_auth logout`이며 서버 측 세션 폐기는 아닙니다.

LangGraph·Tool·Memory 흐름은 동일하고 모델 통신만 Codex Responses로 전환합니다. 만료 전 갱신과 401의 한 번 재인증을 지원하며, 429·한도 소진·다른 오류에는 유료 API로 자동 전환하지 않습니다. API Key 모드도 계속 사용할 수 있습니다. 호출은 API 비용 또는 선택한 계정의 구독 사용량을 소비합니다.

구독 경로는 외부 하네스의 공개 구현을 참고한 연동으로 전용 엔드포인트 변경 시 유지보수가 필요합니다. 현재 자동 검증은 Mock HTTP 기반 인증·도구 호출·구조화 출력·스트리밍이며 실제 계정 로그인·모델 호출은 별도 확인 대상입니다. [OpenAI 인증 안내](https://learn.chatgpt.com/docs/auth), [참고한 PI 구현](https://github.com/earendil-works/pi/tree/e4c75a73222ae2c72abb5f5314fa35ee8effc508/packages/ai/src)

> [!WARNING]
> Toss 키가 설정되어 있으면 **포트폴리오 창을 처음 열 때 첫 BROKERAGE 계좌를 조회하고 LLM 진단을 실행**합니다. 새로고침 후 창을 다시 열면 새 API 비용 또는 구독 사용량이 발생합니다. 키가 없거나 진단에 실패해도 부장 대화는 유지되지만, 시세 등 각 경로에 필요한 연동은 별도로 설정해야 합니다.

### 3. 실행

```bash
bash scripts/dev.sh
```

[http://127.0.0.1:5173](http://127.0.0.1:5173)에서 접속합니다. FastAPI는 8000, Vite는 5173 포트로 실행하며 종료는 `Ctrl+C`입니다.

## 평가

현재 자동 LLM 평가는 **입력 파싱과 Planner의 Worker 선택 계약**을 확인합니다. 상위 Agent의 일반/조사 선택 정확도나 최종 투자 의견의 정확성을 뜻하지 않습니다.

| 평가 데이터 | 사례 수 | 상태 |
| --- | ---: | --- |
| Input Parsing | 12 | 실행·자동 채점 구현 |
| Planner Routing | 12 | 실행·자동 채점 구현 |
| End-to-end | 3 | 질문·평가 기준 초안, 자동 실행 미구현 |
| Grounding | 1 | 공식 자료·기대 사실 준비, 자동 채점 미구현 |

24개 계약 사례는 개발용 데이터이며 독립 Holdout이나 금융 정확도 벤치마크가 아닙니다.

```bash
# 외부 API 없이 데이터셋 계약 검사
.venv/bin/python evals/scripts/validate_datasets.py

# 외부 API 없이 주요 회귀 테스트
.venv/bin/python -m unittest tests.test_eval_contract tests.test_portfolio tests.test_conversations tests.test_short_term_memory tests.test_chat_router

# 실제 LLM 평가: 실행 시 API 비용 또는 구독 사용량 발생
.venv/bin/python evals/scripts/run_eval.py --suite parsing,routing --label baseline --runs 3
```

실행 설정·버전 해시·사례별 결과를 저장하고 같은 평가 계약의 이전 실행과 비교합니다. 상세 계약과 결과 해석은 [평가 안내](evals/README.md), 사례 목록은 [Dataset View](evals/DATASET_VIEW.md)를 참고하세요.

## 현재 한계와 데이터 관리

- **리서치 범위:** 단일 종목만 지원합니다. 공시 Tool은 목록·제목·URL만 제공하며, 본문·구조화된 재무 수치는 제공하지 않습니다.
- **근거 검증:** Worker 보고서는 문자열입니다. 인용의 정확성·주장과 근거의 일치·모든 자료의 과거 기준일 준수를 코드로 보장하지 않습니다.
- **진단 범위:** 현금·해외 주식·ETF·목표 비중·부채·실현손익·배당은 포함하지 않습니다. 업종은 AI 추정이며 공식 분류가 아닙니다. 하락 시나리오는 API에 남아 있지만 화면에는 표시하지 않습니다.
- **대화 저장:** 질문·최종 답변은 `data/chat.sqlite3`에 저장합니다. 개인정보나 보유 종목이 메시지에 포함되면 함께 저장될 수 있습니다. 대화 삭제 시 해당 메시지도 삭제합니다.
- **Trace:** Chat 조사의 입력 검증·Worker 실행과 조사 전용 API 실행을 `traces/YYYY-MM-DD/<run_id>.json`에 기록합니다. Chat의 상위 Agent 호출과 일반 답변·포트폴리오 진단은 제외합니다. 대화 DB 저장과 별개입니다.
- **중단 처리:** 끊긴 대화 응답은 중단 상태로 남기며 자동 재실행하지 않습니다. 포트폴리오 상세 표·Worker 조사 노트·캐릭터 상태는 대화 기록에 저장하지 않습니다.

> [!IMPORTANT]
> 로그인 없는 **로컬 단일 사용자·서버 단일 프로세스** 용도입니다. 공개 서버에 배포하지 마세요. `.env`, 대화 DB, Trace에는 민감 정보가 있을 수 있으므로 공유하지 마세요.

## 기술 스택과 문서

**Backend** · Python, LangGraph, LangChain, FastAPI, Uvicorn, SSE, SQLite  
**Frontend** · Vanilla TypeScript, Vite  
**Integrations** · OpenAI API / Codex 구독 / OpenRouter, DART, Tavily, Toss Securities Open API

| 문서 | 내용 |
| --- | --- |
| [아키텍처](docs/architecture.md) | 현재 구성·Agent 책임·실행 경로 |
| [스키마](docs/schema.md) | 입력·계획·공유 상태·포트폴리오 계약 |
| [API](docs/api.md) | HTTP 요청·응답·스트리밍 |
| [평가](evals/README.md) | 데이터·채점·실행·비교 방법 |

프로젝트 표시명은 **Tomade**이며, 내부 Python 패키지명은 `stock_agent`를 사용합니다.

---

Tomade의 분석과 투자 의견은 참고용이며 수익을 보장하지 않습니다. 자동 주문 기능은 제공하지 않습니다.
