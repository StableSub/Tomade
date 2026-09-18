# 아키텍처 — Tomade

> 2026-09-18 v2 조사 경로·Tool·구조화 보고서 반영. 배포 단위가 아닌 요청 처리 흐름과 책임을 설명한다.

## 현재 구현 범위

### v2 종목 조사 경로

현재 v2 작업은 `feature/agent-v2`, `/Users/anjeongseob/.codex/worktrees/agent-v2/stock_agent`에서 진행한다. 이전 `feature/disclosure-rag` 파일럿을 이어 받은 개발 브랜치이며 main 병합 여부·검증 결과와 아래 구현 구조는 구분한다.

```mermaid
flowchart TD
    Q["사용자 질문"] --> U["upper_agent<br/>직접 답변 또는 ResearchPlan"]
    U -->|직접 답변| A["final_answer"]
    U -->|조사| P["request_parser<br/>후보 추출 + DART·Python 검증"]
    P --> G["ResearchMandate + 자기 ResearchTask<br/>선택된 최대 5개 Worker 병렬 실행"]
    G --> T["일반 Worker<br/>한도 내 Tool 호출"]
    G --> F["Technical·Sentiment<br/>코드가 먼저 고정 자료 수집"]
    T --> E["EvidenceLedger<br/>원본 근거·날짜·크기 확인"]
    F --> E
    E --> D["WorkerDraft<br/>모델의 주장 + 근거 ID"]
    D --> R["finish_report<br/>질문 누락·근거 ID 검사"]
    R --> W["WorkerReport 또는 WorkerError"]
    W --> S["같은 upper_agent<br/>참조된 근거와 한계를 종합"]
    S --> A
```

`agents/worker.py`의 `run_worker()`가 일반 Worker의 조사 루프를 직접 제어한다. Tool 목록은 각 역할 모듈이 고정하고 Tool factory는 검증된 종목·회사·기간을 묶어 모델이 다른 대상으로 바꾸지 못하게 한다. 모델은 허용된 검색어·목차 힌트 등만 선택한다. Technical은 지표 Tool을 한 번 선조회하고 Sentiment는 일반 Python 수집 함수를 실행한 뒤 구조화 보고서 모델을 한 번 호출한다. 사용 가능한 근거가 없으면 보고서 모델 호출을 생략한다.

| Worker | 자료와 허용 기능 | 호출 예산 | 전체 기한 |
| --- | --- | --- | --- |
| Business | `search_disclosure_evidence`, `get_financial_evidence` | 총 5회, 공시 3회·재무 2회 이내 | 600초 |
| Macro / Sector | `search_web` | 3회 | 180초 |
| Event / Catalyst | `get_market_evidence`, `search_web`, `search_disclosure_evidence` | 총 5회, 시세 1회·웹 3회·공시 3회 이내 | 600초 |
| Technical | `get_technical_evidence` 선조회 | 1회 | 180초 |
| Sentiment | `collect_sentiment_evidence`, 모델 Tool 없음 | 표본 준비 1회 | 180초 |

조사 판단 모델은 최대 6회, 별도 `WorkerDraft` 생성은 최대 1회다. 전체 기한의 1/3(최대 120초)을 보고서 생성에 예약하여 Business·Event는 조사 480초·보고 최대 120초, 다른 역할은 조사 120초·보고 최대 60초로 나눈다. 조사 모델이 시간 초과해도 확보한 근거가 있으면 보고 단계로 전환한다. 모델 호출 한 번은 120초, 일반 Tool은 90초, 공시 Tool은 480초 상한이며 해당 단계의 남은 시간이 더 짧으면 그 시간을 적용한다. 같은 Tool·같은 인자의 반복은 실행 전에 차단한다. 자료를 확보했으면 한도 안에서 보고하고, 보고서 형식·근거 참조가 잘못되면 자동 재시도 없이 `WorkerError`로 분리한다. 취소는 추가 호출·응답 전달을 중단하지만 이미 시작된 동기 외부 HTTP의 즉시 종료까지 보장하지 않는다.

#### 근거와 보고서의 책임

- `EvidenceLedger`가 공개일·관측 종료일을 기준일과 대조하고, 실제 Tool이 만든 Evidence만 보관한다. Business는 24개, 다른 일반 Worker는 12개, Sentiment는 40개 상한이다. 본문은 4,000자, 댓글은 600자로 제한한다.
- 모델 출력 `WorkerDraft`에는 주장·질문 번호·근거 ID·미확인 이유만 둔다. `finish_report()`가 모든 질문의 답변 또는 미확인 분류, 존재하는 근거 ID 참조를 검사한 뒤 **참조한 원본 Evidence만** `WorkerReport`에 붙인다.
- 근거 일부 확보는 `partial`, 정상적인 근거 미확보는 `unavailable`, 통신·기한·출력 계약 실패는 `WorkerError`다. 일부 역할 실패로 다른 역할의 결과를 버리지 않고 종합 단계에 함께 전달한다.
- Worker 입력은 자기 `ResearchTask`와 공통 `ResearchMandate`다. 사용자 기억·최근 대화·다른 Worker 보고서는 제공하지 않는다. 상위 Agent는 선택된 결과만 JSON으로 받아 사실·해석·충돌·한계를 설명한다.
- ID의 존재·질문 누락 검사는 인용 문장의 의미나 투자 판단의 정확성을 검증하는 기능과 별개다. 최종 답변은 Markdown 문자열이며 상위 Agent의 최종 주장 전체를 독립 검증하는 노드는 없다.

#### Tool 내부 데이터 경로

| 기능 | 코드의 처리 | 주요 한계 |
| --- | --- | --- |
| 공시 RAG | DART 발견 → 준비 상태 확인·원문 다운로드 → 문단·표 청킹 → SQLite FTS5 + NumPy 벡터 → RRF·부모 문맥 → 최대 5개 근거 | Business는 550달력일 정기보고서 최신·이전 기간 최대 2건, Event는 요청 기간 최신 2건. 정정 관계 불명은 제외 |
| 재무 | DART 정기보고서 선택 → CFS 우선·자료 없음만 OFS → 접수번호·기간·통화 대조 → Decimal 계산 | 초기 12월 결산 회사·최신 회계기간. 정정된 수치의 완전한 과거 재현은 미지원 |
| 웹 | Tavily Search 최대 5개 → 날짜 필터 → 상위 3개 Extract → 원문별 최대 1,600자 | 공개일은 제공처 추정. `search_snippet`과 원문 발췌 구분, 과거 버전 복원 미지원 |
| 시세 | 확정된 종목·기간의 일봉과 급등락일, 1일 요청은 1분봉을 30분 구간으로 집계 | 일봉이 1개뿐이면 기간 수익률은 `null`. 최근 전일 대비 등락률은 `latest_daily_change_pct`로 별도 반환 |
| 기술 | 완료된 일봉 120달력일, 부족 시 365일까지 한 번 확장 → XKRX 세션 대조 → SMA20/60·이격률·거래량 비율·변동성 | 당일 봉 제외. 조정 정책·과거 당시 가격 재현 미검증, 예상 거래일 누락은 관련 지표 계산 불가 |
| 댓글 | 회사·금융 주제 영상 최대 3개 → 영상당 댓글 최대 50개 → 작성·수정일·관련성·중복 필터 → 최대 40개 | 최상위 댓글만 사용. 10개 미만 등은 부분 확보, 전체 투자자 대표성 없음 |

RAG 원문·청크·벡터·목록은 `data/disclosures/`에 저장한다. 새 요청도 공시를 먼저 발견해 대상 목록을 정하고, 단일 프로세스 잠금 후 준비 상태를 재확인한다. 이미 완료한 원문·파싱·색인 단계는 재사용한다. **검색 결과 없음은 원문 부재와 다르며 자동 재색인의 사유가 아니다.** 임베딩은 `text-embedding-3-small`과 `OPENAI_API_KEY`를 사용하므로 모델을 Codex 구독으로 호출해도 별도 API 사용량이 발생한다.

공시 공개일·YouTube 댓글 작성일·웹 추정 공개일·가격 관측일은 서로 다른 시간 정보다. 현재 시점에 조회한 수정 본문·수정주가를 과거 당시 데이터로 완전히 복원한다고 보장하지 않는다. 외부 본문·댓글은 명령이 아닌 조사 자료로 취급한다. 상세 필드는 [스키마](schema.md#종목-조사--v2)를 따른다.

### 도트 사무실 UI

- `office-camera.ts`가 사무실의 100~300% 배율·이동 위치와 버튼·휠·포인터 입력을 관리한다. 실제 지도 CSS 크기를 바꿔 기존 Canvas 크기 관찰자가 원본에서 다시 그리게 하며, 이동은 지도 외곽으로 제한한다. 5px 이상 드래그한 뒤의 클릭만 차단해 캐릭터 선택과 구분한다. 대화 진입 시 초기화·비활성화하며 계정이나 서버에는 저장하지 않는다.
- 마당은 잔디색 바탕, `office-landscape-v1/garden-horizon.webp` 원경과 `office-courtyard-v2/garden-atlas.png`의 9종 소품으로 구성하며 흰 테라스는 없다. 하늘·먼 숲은 약 97 KiB의 정적 WebP 한 장으로 표시하고, 창문 유리 영역에도 같은 이미지를 합성한다. 창틀·커튼은 보존하며 세 창문은 같은 합성 결과를 재사용한다. 정규화한 아틀라스 영역을 잘라 독립 오브젝트로 표시한다. 실내 43개와 마당 151개, 총 194개다. 마당은 기존 9종과 정원 생활 소품 8종을 사용한다. `office-garden-details-v1/garden-details.webp`의 피크닉 테이블·울타리·우편함·장작 보관대·빗물통·수확 바구니·꽃밭·새 목욕대를 기존 렌더러로 배치한다. 실내 좌표 800×500과 동선은 유지하고, 뒤쪽 공간 210단위와 좌우 여백 각 100단위를 포함한 전체 맞춤 영역은 1000×910이다. 집의 800×500 좌표계와 캐릭터 비율은 유지하고, 대화 미니맵에서는 좌우 여백을 제거한다. 뒤쪽 성목은 높이 176단위, 밑동 y=-22로 처마 y=9와 분리하며 앞쪽 나무는 높이 168단위로 표시한다. 대화 집중 시 마당 소품을 숨기고 복귀 시 같은 DOM을 표시한다. 세 직원 책상은 승인된 `office-objects-v3/worker-desk-trial.png`를 공유한다. 실내 가구·소품은 `office-objects-v4` 아틀라스와 `frames.json`의 개별 영역을 사용한다. 외곽 목재·칸막이·계단은 승인된 집 형태에 맞춘 `office-shell-v1`의 6종 아틀라스로 교체했다. 기둥의 사각 캡을 제거하고 낮은 석재 기단·문턱·얇은 처마를 독립 배치한다. 전면 계단은 문턱에, 방 사이 통로의 낮은 목재 마감은 칸막이 끝에 맞춰 빈 틈 없이 이어진다. 세 기둥 아래에는 개별 돌 받침을 두고, `office-architecture.ts`가 직원 바닥을 9×6개의 완전한 나무 짜임 블록, 부장실을 6×6개 체크 타일로 방 내부 치수에 맞춰 그린다. 벽·테두리에서 잘린 타일 조각이 남지 않도록 정수 경계를 사용한다. 같은 모듈이 기둥의 안쪽 테두리·하단 턱과 통로의 두 장 목재 이음을 표현한다.

- 접지 그림자는 `office-room.ts`의 별도 장식 요소로 관리한다. 가구 그림자는 바닥·러그 위와 가구 아래에, 소품 그림자는 받침 가구 위와 소품 아래에 표시한다. `office-architecture.ts`가 가구와 같은 0.54게임단위 격자에 타원형 그림자를 한 번 래스터화하고 크기별 PNG data URL을 재사용한다. 큰 그림자도 같은 픽셀 크기를 유지하며 나무에는 수관의 옅은 그림자와 밑동의 짙은 접촉 그림자를 분리한다. 캐릭터의 기존 그림자 스타일은 유지한다. 장식 요소는 `pointer-events: none`과 `aria-hidden`으로 상호작용에서 제외한다. 같은 사무실 DOM 안에서 미니맵과 함께 축소되고 `OfficeRoom.dispose()`에서 제거된다.

- `frontend/index.html`·`styles.css`가 사무실과 대화·조사 노트·포트폴리오 창을 구성한다. `office-room.ts`의 `OfficeRoom`은 배경·구조 11종과 실내 소품 21개 ID, 마당 17종을 사용한다. 직원 책상은 같은 원본을 가리키는 기존 두 ID를 유지한다. 왼쪽 나무 짜임 바닥은 직원 사무실, 오른쪽 체크 타일 바닥은 부장실이며 가운데 문으로 연결된다. 이전 `assets/research-office.png`는 디자인 참고용으로 보존하며 앱에서 로딩하지 않는다.
- `OfficeRoom`은 에셋을 종류별로 한 번 읽어 자홍색 배경을 제거한다. `pixel-style.ts`에서 기본 직원 캐릭터와 같은 0.54 게임단위/픽셀로 샘플링하되, 앱과 뷰어 모두 `preserveColors: true`로 원본 RGB를 보존한다. 마당·프레임·체크 바닥도 색상 제한을 적용하지 않는다. 최근접 샘플링 후 투명 영역에 인접한 실루엣 안쪽 2픽셀을 짙은 검정으로 채워 바깥 모서리와 내부 구멍의 경계를 닫는다. 알파 영역은 늘리지 않으며 바닥·평평한 벽면·작은 풀과 들꽃은 추가 윤곽 처리를 제외한다. 소품 크기별 Canvas를 캐시하고 `sprite-renderer.ts`가 기기 픽셀 크기에 맞춰 최근접 보간으로 표시한다. 창 크기·미니맵 전환에도 소품의 고유 도트 수는 바뀌지 않는다. 목재 테두리·칸막이는 가장자리를 보존하며 가운데만 늘린다. 바닥은 기존 1게임단위 격자를 유지하고, 나무 바닥의 정수 격자 SVG를 같은 원점으로 반복한다. `OFFICE_SEATS`의 좌석 좌표를 가구와 캐릭터 경로가 공유하며, 의자·책상과 캐릭터의 Y 좌표에 따른 표시 순서로 착석을 표현한다. 책상 명패는 표시하지 않는다. 이름·담당 분야는 각 캐릭터 머리 위에 항상 표시하고, 캐릭터와 같은 위치를 따라가되 가구보다 위에서 렌더링한다. 부장 모니터는 책상 가로 중앙에 놓고 받침대를 상판 앞선 안쪽에 배치한다.
- `app.ts`의 `setOfficeMode`는 동일한 사무실 DOM을 전체 화면과 오른쪽 미니맵 사이에서 350ms 동안 이동·축소한다. 데스크톱은 대화 64%·사무실 36%, 모바일은 전체 폭 대화와 상단 작은 미니맵이다. 미니맵에서 커비를 포함한 다섯 캐릭터는 inert 상태가 되고 사무실 전체가 복귀 버튼이 된다. 작성 중인 질문·캐릭터 상태는 전환 시 유지하며 모션 감소 설정은 전환 애니메이션을 생략한다.
- `renderTranscript`는 저장된 질문·답변과 현재 사용자 질문을 순서대로 표시한다. 사용자 말풍선은 대화 내용 영역의 오른쪽 끝, 부장 답변은 왼쪽에 배치한다. SSE는 마지막 부장 답변만 갱신한다. 질문 전송 후에도 대화창을 유지하며 사용자가 이전 내용을 읽는 중에는 새 답변이 스크롤을 끌어내리지 않는다.
- `office-scene.ts`의 `OfficeScene`이 4개 도트 캐릭터, 통로 경로, 이동·착석·보고 애니메이션을 관리한다. `assets/office-characters.png`는 승인된 캐릭터 디자인으로 만든 4×4 스프라이트 시트다. 행은 페더스 맥그로(부장)·패트(비즈니스)·매트(매크로/섹터)·게왹이(이벤트/카탈리스트), 열은 정면·후면·오른쪽·착석이다. 로딩 때 한 번 배경색을 투명 처리하고 각 자세를 128×160 Canvas에 비율을 유지해 표시한다. 부장 초상화는 같은 이미지에서 빨간 장갑 모자와 얼굴을 함께 사용한다. `app.ts`는 API·대화 저장·SSE 상태를 관리하며 캐릭터에 상태만 전달한다. 이동은 시각적 표현으로 모델·도구의 실행 시점을 제어하지 않는다.
- 대기 중에 부장은 부장실 안에서, 직원은 왼쪽 사무실 안에서 산책한다. `assets/office-walk-{front,back,right}.png`의 새 캐릭터별 4프레임 전신 그림을 기존 이동 거리 기반 로직으로 재생하고 왼쪽은 오른쪽 그림을 반전한다. 프레임 사이를 보간하지 않으며, 방 비율을 반영한 거리 계산으로 상하·좌우 걸음 속도를 맞춘다. 출발·도착 시 가감속하며 정지하면 기본 자세로 돌아간다. 계획의 `tasks[].agent`로 조사 인원을 정하고 Worker의 `node.started`에 자리 이동·착석, `node.completed`에 가운데 문을 통과하는 보고 이동을 연결한다. 선택되지 않은 Worker는 계속 산책한다. 진행률은 선택된 Worker의 완료 수/선택 수다.
- 상위 Agent의 첫 계획 완료와 최종 종합을 구분한다. `run.completed`에서 부장을 앞으로 이동시키고 답변 대화창을 연다. `run.error`나 완료 전 연결 종료에서는 실행 중인 조사 모션을 정리하고 오류 안내를 표시한다.
- 사무실 전체 화면에서 Worker 캐릭터 클릭 시 이번 실행의 보고서·스트리밍 문장을 노트 창에 표시한다. 부장 캐릭터는 대화창을 연다. 완료 출력이 중간 Buffer를 대체한다. 대화 복원 시 Worker 보고서는 비우고 저장된 사용자 질문·최종 답변을 복원한다. pending 대화는 입력을 막고 부장 대화를 다시 열거나 `답변 확인`을 누를 때 서버 상태를 재조회한다.
- 긴 답변·노트는 창 안에서 스크롤한다. 사무실은 16:10 비율을 유지하며 가로·세로 가용 공간 안에 두 방 전체를 맞추므로 수평·수직 이동이 필요 없다. 키보드 입력·캐릭터 선택과 모션 감소 설정을 지원하고 숨겨진 탭에서는 애니메이션을 멈춘다.
- `frontend/tests/office-environment.html`은 실제 Canvas의 희미한 알파 여백 제거, 창틀·알파 보존, 그림자 격자·캐시와 1440×1000·844×390·390×844 격리 화면의 194개 오브젝트 맞춤·마당 숨김·집 외부 배치·클릭 비간섭을 검사한다. API를 호출하지 않는다. `frontend/tests/office-ui.mjs`는 모든 API를 Mock으로 가로채 소품 로딩·캐릭터 클릭·바닥 픽셀 정렬·이동·착석·완료·실패·대화 복원·모바일을 검증한다. 실제 모델·외부 금융 API 성능 검증과는 별개다.

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

### 계층형 프롬프트와 입력 조립

- `src/stock_agent/prompts/`의 `orchestrator.md`, `request_parser.md`, `business.md`, `macro_sector.md`, `event_catalyst.md`, `technical.md`, `sentiment.md`가 IDENTITY·CONSTRAINTS·CAPABILITIES·CONTEXT·BEHAVIOR·KNOWLEDGE 순서의 고정 지침을 관리한다. `common.md`는 전체 공통 제약과 Worker 공통 제약·보고 방식을 제공한다.
- `prompts/builder.py`의 `build_system_prompt()`는 코드가 지정한 역할의 파일과 공통 구역을 호출마다 읽는다. 고정 문구를 조립한 다음 전달받은 동적 값을 한 번만 삽입하며, 사용자 텍스트 안의 중괄호를 다시 해석하지 않는다. 필수 파일·구역·변수 누락이나 불필요한 입력 변수는 오류로 처리한다.
- 상위 Agent는 같은 템플릿에 현재 날짜와 `initial`/`synthesis` 단계, 준비된 사용자 기억·세션 요약을 넣는다. 기억이 없으면 빈 문자열을 사용한다. 메모리 조회·저장·DB·모델 호출은 Builder의 책임이 아니다.
- Parser는 오늘 날짜만 시스템 프롬프트에 넣고 현재 질문은 별도 user 메시지로 유지한다. Worker는 조사 조건·자신의 목표·질문·완료 기준을 기존 user 메시지로 받으며, 시스템 프롬프트에는 이 필드의 의미와 역할 지침을 넣는다.
- Tool 권한과 출력 스키마는 기존 코드에 둔다. Worker는 사용자 기억·최근 대화·다른 Worker 보고서를 모델 입력에 넣지 않는다. 실행 중 수집한 근거는 Tool 호출·결과 메시지로 유지한다.
- Event/Catalyst는 가격 변동 원인 질문에서 시세를 먼저 확인하고 예정 일정 질문에서는 공시·발표부터 조사하도록 안내한다. 이 선택의 적절성·근거 충실성·완료 기준의 의미는 프롬프트에 의존하며, 코드가 Tool 권한·조건·예산·보고서 참조를 별도로 검사한다.
- Markdown 파일은 Python 패키지 데이터로 포함한다. 단기 요약 모델과 포트폴리오 분류·해설 모델은 이번 분리 대상이 아니다.

### 상위 Agent와 LangGraph

- `POST /api/chat/stream`은 `src/stock_agent/graph.py`를 실행한다. 별도 Chat Router·일반 답변·Plan·Synthesis 노드는 없다.
- `upper_agent`는 같은 `PLANNER_MODEL`과 역할별 프롬프트 템플릿으로 직접 답변·조사 계획·조사 후 종합을 담당한다. 첫 호출에서 `UpperDecision`으로 일반 답변 또는 `ResearchPlan`을 반환한다.
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

### 모델 공급자와 Codex 구독 인증

- 우측 상단 설정 창(`frontend/settings.ts`)은 `backend/model_settings.py`에서 서버의 실제 선택 공급자·역할별 모델·키 유무·저장된 인증 상태를 조회한다. 토큰·계정 식별자는 응답에 포함하지 않으며 조회만으로 모델 연결 성공을 판정하지 않는다. Chat/Research의 `run.started.connection`은 해당 요청이 선택한 방식도 전달한다.
- 웹 기기 로그인은 CLI와 같은 `CodexAuth.start_login()`·`poll_login()`을 사용한다. 서버 단일 프로세스에 대기 세션 하나만 보관하고 창이 열렸을 때만 간격을 지켜 승인 조회한다. 로그인 성공은 인증 저장까지만 수행하며 공급자 변경은 별도 적용 버튼으로 요청한다.
- 명시적 전환은 `.env`의 `LLM_PROVIDER` 저장 → 프로세스 환경 갱신 → 모델 캐시 비우기 순서다. `model_session()`이 Chat·Research·포트폴리오 진단 전체 실행을 감싸 진행 중 전환을 거부한다. 모델 ID·API 키·LangGraph 노드·Tool·Memory 계약은 바꾸지 않는다. 여러 서버 프로세스 사이의 설정 동기화는 지원하지 않는다.
- 구독 역할 편집은 `PUT /api/settings/codex/models`로 네 역할의 모델·추론을 검증하고 기존 `.env`를 복사한 임시 파일을 완성한 뒤 원자적으로 교체한다. 성공 후 프로세스 환경과 캐시를 갱신한다. 실행 중 또는 API Key 방식에서는 거부한다. 모델은 기존 역할별 변수, 추론은 `CODEX_<역할>_REASONING_EFFORT`에 저장하며 구독에서만 Responses `reasoning.effort`로 전달한다. 빈 값은 공급자 기본 추론이다. Reviewer 호출 경로는 없고 다섯 Worker는 공통 설정을 유지한다.
- `gateways/llm.py:get_chat_model()`이 `openai`, `openrouter`, `openai_codex`를 선택한다. 구독은 `LLM_PROVIDER=openai_codex`로 명시적으로 선택하며 API 키 유무에 따른 기존 자동 선택은 API 공급자에만 적용한다. 역할별 모델 선택과 Agent·Tool·프롬프트·Memory 흐름은 유지한다.
- `gateways/codex_auth.py`의 CLI가 기기 코드 OAuth 로그인을 제공한다. `CODEX_AUTH_PATH` 또는 `~/.config/stock-agent/codex-auth.json`에 프로젝트 전용 세션을 저장하며 다른 앱의 Codex 인증 파일은 읽거나 수정하지 않는다. 파일은 현재 사용자 소유의 일반 파일·권한 600을 요구한다. 임시 파일과 원자적 교체로 갱신하며 로그아웃은 로컬 파일만 삭제한다.
- 호출 시 최신 토큰을 읽고 만료 60초 전부터 갱신한다. 파일 잠금으로 스레드·프로세스의 동시 갱신을 직렬화하며 잠금 대기는 60초로 제한한다. 401이면 거절된 토큰과 현재 저장 토큰을 비교해 이미 갱신된 값은 재사용하고 한 번만 재요청한다. 인증 누락·취소·갱신 실패·429에 API Key fallback은 없다.
- `gateways/codex.py`의 `ChatCodex`는 `ChatOpenAI`를 확장해 기존 SDK의 Tool Call·Pydantic 구조화 출력·메시지 변환을 재사용한다. `store=false`, `stream=true`, `instructions`와 암호화된 reasoning 재전송을 설정하고 인증 헤더는 고정 Codex Responses 주소에만 보낸다. 도구 호출 ID는 유지하며 서버 저장 item ID에는 의존하지 않는다.
- `invoke`·`ainvoke`도 내부 스트림을 모아 반환한다. 완료 이벤트가 없거나 incomplete이면 실패한다. 401의 한 번 갱신 외 모델 요청 자동 재시도는 없으며 연결 제한은 10초, 네트워크 읽기 제한은 120초다. 중간 Token은 기존 스트리밍 경로로 전달하지만 완료 전 실패는 기존 오류 처리 경로로 전달한다.
- Codex 기본 모델은 `gpt-5.6-luna`이며 역할별 환경변수가 우선한다. 구독에서 실제 허용된 ID를 설정해야 한다. 출력 Token 상한·temperature·top_p·previous_response_id 설정은 지원하지 않고 오류를 반환한다. API 공급자의 기존 설정은 유지한다.
- 인증·도구 재호출·스키마·동기/비동기 스트리밍은 Mock HTTP와 실제 LangChain으로 검증한다. 실제 구독 로그인·모델 접근·응답 품질·한도와 금융 API 통합은 별도 검증 대상이다. 평가 기록은 구독 공급자를 `openai_codex`로 구분한다.

## 노드 책임

### 독립 포트폴리오 진단

- 자동 연결은 `/configuration`(키 유무만 확인) → `/diagnose` 순서다. 계좌 목록 조회·선택을 진단 함수에서 한 번 수행해 자동 진단의 중복 목록 조회를 제거했다. 별도 새로고침·동시 요청에 의한 429 가능성은 남으며 이를 명시적으로 반환한다.
- Toss GET은 401일 때 거절된 캐시 토큰을 갱신해 한 번만 재시도한다. 다른 요청이 이미 갱신했다면 최신 토큰을 재사용한다. 429는 토큰 재발급 대상으로 취급하지 않는다.

- 포트폴리오 창을 처음 열 때 `app.ts`가 `portfolio.ts`를 동적으로 불러온다. 서버에서 Toss 키 유무를 확인하고, 설정된 경우 첫 번째 BROKERAGE 계좌를 자동 선택해 한 번 진단한다. 창을 다시 열어도 재진단하지 않으며 실패해도 Research 입력을 막지 않는다. 새로고침 후 포트폴리오 창을 다시 열면 새 유료 진단이 발생한다.

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
- 회사 후보·조사 질문·기준일·자료 조회 기간·투자 기간 추출
- 상대 날짜 계산용 기준 날짜는 시스템 메시지에, 사용자 원문은 user 메시지에 분리한다. 원문에 날짜·기간이 없으면 null을 추출하고 Python에서 오늘·30일을 적용한다.
- Pydantic `ParsedRequest` 반환
- Tool과 금융 분석 없음

### Deterministic Input Validation

- DART 회사명 확인과 종목코드·회사 식별자 확정
- 복수 종목 거부
- 날짜 형식과 미래 날짜 검사
- 기간 미지정만 30일 기본값, 1~3650일 범위 검사. KST 기준일과 포함형 조회 시작·종료일 생성
- 잘못된 입력은 `input_error`로 조기 종료
- 검증된 입력과 공통 제약을 `ResearchMandate`로 생성

### 상위 Agent — 직접 답변·계획

- `PLANNER_MODEL` 사용
- 필요한 Agent 선택
- 핵심 조사 질문과 완료 기준 생성
- 일반 질문에는 `UpperDecision.final_answer`, 조사 요청에는 `UpperDecision.research_plan` 반환

### Worker Agent

- ResearchPlan에 포함된 Worker만 조건부 edge로 선택해 병렬 실행
- Business: `search_disclosure_evidence`, `get_financial_evidence`
- Macro/Sector: `search_web`
- Event/Catalyst: `get_market_evidence`, `search_web`, `search_disclosure_evidence`
- Technical: 코드가 `get_technical_evidence`를 한 번 호출한 뒤 모델 해석
- Sentiment: 코드가 `collect_sentiment_evidence`를 실행한 뒤 모델 해석, 모델 Tool 없음
- 공통 실행기의 구조화 보고서는 역할별 `*_report`에 저장하며 원문 Evidence는 코드가 첨부

### 같은 상위 Agent — 조사 후 종합

- ResearchPlan과 Worker 결과 종합. Chat에서는 메모리 갱신 Tool만 사용 가능
- 새로운 사실·수치·출처를 생성하지 않도록 프롬프트로 안내한다. 코드에 독립 사실 검증 단계는 없다.
- `final_answer` 마크다운 반환

### Execution Trajectory

- 직접 지정한 종목 조사와 기존 Research API 실행에만 `traces/YYYY-MM-DD/<run_id>.json` 생성
- Chat은 검증·Worker 하위 그래프를 기록하며 상위 Agent 호출·일반 답변은 제외한다. 조사 전용 API는 상위 Agent 호출까지 기록한다. 포트폴리오 진단은 제외한다.
- Trace의 `evidence_tool_call_ids`는 완료된 Tool 호출 ID. v2 `Evidence.evidence_id`는 본문·계산·댓글 항목의 별도 ID이며 둘을 같은 식별자로 취급하지 않음
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
- **DART:** 회사 확인·공시 원문·구조화 재무를 조회한다. 공시 선택 수·기간과 정정 관계 미확인 항목의 보수적 제외로 검색 범위가 제한되며, 재무 API의 현재 수정값을 과거 값으로 사용할 수 없으면 자료 미확보로 보고한다.
- **Tavily:** 날짜를 확인할 수 없는 후보를 제외하고 원문 추출을 시도한다. 제공처의 추정 공개일·검색 발췌·현재 웹 본문은 과거 원본 확인과 구분한다.
- **Toss:** 시세·보유 현황·상품 정보를 제공한다. Technical은 정밀도 보존 일봉과 XKRX 캘린더로 계산하며 누락·조정 정책 한계를 유지한다. 계좌 진단은 국내 원화 일반 주식으로 제한한다.
- **YouTube:** 회사 관련 영상의 댓글 표본만 제공한다. 실제 투자자 여부·시장 전체 대표성은 확인하지 않는다.
- 모든 외부 근거의 기준일 준수·금융적 정확성은 보장되지 않는다. 자동 평가는 [평가 안내](../evals/README.md)의 제한된 계약 범위다.

## 코드 구조

```text
backend/
├── main.py                 # Chat·Research SSE
├── conversations.py        # 대화 저장·복원·요약 경계
├── short_term_memory.py    # 10턴 유지·Luna 요약
└── portfolio.py            # 계좌 진단 API

frontend/
├── app.ts                  # 대화·SSE와 사무실 상태 연결
├── office-room.ts          # 독립 배경·가구 배치, 공유 좌석 좌표
├── sprite-renderer.ts      # 색상 키 제거·기기 픽셀 크기에 맞춘 표시
├── pixel-style.ts          # 캐릭터 기준 배율·검정 실루엣 윤곽·테두리 유지
├── office-scene.ts         # 도트 캐릭터·통로 이동·착석·보고
├── portfolio.ts            # 창을 처음 열 때 진단
├── index.html / styles.css # 사무실·대화 집중 화면·노트
├── assets/office-{environment,objects}-v{1,2}/
└── tests/office-ui.mjs      # 모의 API 기반 브라우저 회귀 검증

src/stock_agent/
├── graph.py
├── state.py
├── trajectory.py
├── control/
│   └── request_parser.py
├── agents/                 # upper + 5 Workers, worker.py 실행·근거·보고서 검증
├── gateways/
├── portfolio/              # schemas·analysis·service
├── tools/                  # 회사·기간이 고정된 LLM 인터페이스와 댓글 수집
├── rag/                    # 공시 발견·원문·청킹·결합 검색
└── vendors/                # DART·Tavily·Toss·YouTube 실제 호출
```

전면 입구는 `office-shell-v1/entrance-v2.png`의 연결된 ㄱ자 목재·문턱·두 단 계단으로 구성한다. `createFrontSection`이 같은 소스로 직원실 438×44, 부장실 282×32 하단부를 독립 조립하며, 작은 별도 끝단 조각을 덧붙이던 배치를 대체한다.

대화 기록 선택·새 대화·삭제는 부장 대화창의 상단에 통합되어 있다. 별도 기록 모달과 우측 상단 기록·포트폴리오 버튼은 없다. 기존 질문·답변을 같은 대화 본문에 복원하며 사용자 질문은 오른쪽에 표시한다. 포트폴리오는 직원 사무실 오른쪽 아래 빈 칸을 산책하는 서류를 든 커비를 누르면 흰색 패널로 열린다. `portfolio-character.ts`가 `office-kirby-v2/walking-atlas.png`의 청록색 키 배경을 메모리에서 제거한다. 정면·후면·오른쪽 각 4프레임을 표시 크기×DPR의 Canvas로 한 번만 최근접 샘플링하고 왼쪽은 반전한다. 기준 격자는 96×96, CSS 크기는 약 6.48cqw로 직원과 같은 0.54 게임단위/픽셀 비율을 유지한다. 원본의 좁은 외곽 영역을 매트의 기본 외곽선과 같은 2도트 기준의 안쪽 윤곽으로 대체한다. 곡선은 원형 거리로 계산해 수평 상단과 대각선 구간의 두께 차이를 줄인다. 소품용 두꺼운 외곽선을 덧붙이지 않는다. 완성 프레임을 해상도별로 캐시하고 Canvas·CSS 크기와 이동 위치를 기기 픽셀에 정렬해 이중 축소·위치 변화에 따른 테두리 깜빡임을 줄인다. (356,405)·(418,405)·(418,338)·(356,338)의 빈 공간을 순환하고 걸음 프레임은 이동 거리에 연동한다. 도착·포커스·마우스 올림·포트폴리오 열기·모션 감소에서 멈추고, 숨겨진 페이지는 RAF를 중단한다. 커비는 화면 진입점이며 Backend Agent/Worker가 아니다. 기존 네 캐릭터의 산책·착석은 유지한다. 포트폴리오의 최초 열기 시 지연 로딩과 API 실행 규칙은 유지한다.


## 공시 RAG 파일럿 기록 · 2026-09-17

다음은 Worker 통합 이전 파일럿 당시의 기록이다. 현재 구현은 위 v2 경로를 따르며, 아래 검색 검사 결과는 통합 이후의 품질 점수로 재해석하지 않는다.

`rag/parser.py`가 DART ZIP의 문단·표를 부모/자식 청크로 추출하고, `rag/service.py`가 `data/disclosures/`에 원문·SQLite FTS5·NumPy 벡터를 저장한다. 검색은 회사·기준일·선택 공시 필터 → BM25/벡터 → RRF → 주변 문맥 반환 순서다. `tools/disclosure_rag.py`는 조건을 고정하고 호출을 최대 3회로 제한하는 Tool factory다. 당시 Worker 그래프에는 등록하지 않았다.

삼성전자 공시 1개에서 실제 검색을 수행했으며 지정 원문 위치 검사 1/3 통과, 2/3 실패다. 당시 실패 후 개선은 수행하지 않았으며, 정정 관계 자동 처리·기간 비교 계산·동시 수집은 미구현이었다. [구현 범위와 검증 결과](disclosure-rag-pilot.md)를 참고한다.
