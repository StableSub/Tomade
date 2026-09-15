# 사무실 UI 브라우저 회귀 검사

Vite를 실행한 상태에서 Node와 설치된 Playwright로 실행합니다. 모든 `/api/**` 요청은 테스트의 메모리 데이터와 제어 가능한 SSE 스트림으로 가로채므로 실제 대화 DB·Toss·LLM을 호출하지 않습니다.

```sh
# 프로젝트에서 playwright를 해석할 수 있는 환경
node frontend/tests/office-ui.mjs

# 다른 위치에 설치된 Playwright와 기존 Chrome 사용
PLAYWRIGHT_MODULE_PATH=/absolute/path/to/node_modules/playwright \
OFFICE_BROWSER_CHANNEL=chrome \
node frontend/tests/office-ui.mjs
```

`OFFICE_BASE_URL` 기본값은 `http://127.0.0.1:5173`입니다. `OFFICE_SCREENSHOTS_DIR` 기본값은 `/tmp/stock-office-ui-test`입니다. 브라우저가 없으면 Playwright 브라우저를 준비하거나 설치된 Chrome 채널을 지정해야 합니다.

걷기 검사는 실제 RAF에서 네 방향·4프레임 전신 그림, 가로로 긴 방의 이동 거리와 걸음의 일치, 출발 가속, 정지 자세, 모션 설정 전환을 확인합니다. 화면 크기별 캐릭터 비율·클릭 영역과 착석도 확인합니다. `walking-frames.html`에는 실제 Canvas에서 캡처한 걷기 프레임을 모아 육안 검토할 수 있게 저장합니다.

두 방 검사는 부장과 직원의 산책 영역 분리, 네 작업 자리의 착석, 모든 직원이 가운데 문으로만 이동해 부장실에 보고하는지, 완료 후 부장 대화 진입을 확인합니다. `two-room-working.png`, `two-room-reporting.png`, `two-room-manager-arrived.png`에서 실제 배치를 확인할 수 있습니다.

대화 집중 모드에서는 같은 사무실 DOM의 중간 축소 프레임, 미니맵 복귀·키보드 접근, 작성 중 입력 유지, 모든 사용자 말풍선의 오른쪽 정렬, 여러 턴의 스트리밍·복원·중복 없음, 읽던 스크롤 위치 유지, 모바일·가로 화면과 모션 감소를 확인합니다. `focus-chat-<폭>x<높이>.png`에 각 화면의 결과를 저장합니다.

확인 범위: 데스크톱·세로 창·모바일·가로 화면에서 사무실 전체 맞춤과 스크롤 없음, 실제 RAF 산책, 새 책상 좌표의 선택 Worker 착석, 진행률·스트리밍 보고서, 최종 답변 시 부장 대화창, 오류·연결 종료 시 모션 정리, 대화 생성·전환·삭제·복원·pending 재조회, 포트폴리오 지연 로딩, 모바일 긴 답변·노트, 모션 감소, 완료 시 열린 보조 창 처리. bfcache 관련 검증은 합성한 persisted pagehide/pageshow 이벤트 수준이며 실제 브라우저 뒤로 가기 캐시 복원은 별도 확인 대상입니다.
