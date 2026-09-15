# Tomade 도트 사무실 배경

`research-office.png`는 사용자가 승인한 간소화 배경입니다. 토마토 로고·중앙 러그·네 작업 공간을 유지하고 책더미, 벽 장식, 화분과 복잡한 무늬를 줄였습니다. built-in `image_gen` 편집 원본은 별도로 보존했으며 실제 캐릭터와 대화는 HTML·Canvas로 표시합니다. [최종 배경 프롬프트](research-office.prompt.md)를 함께 보존했습니다.

세 Worker 모니터에는 비즈니스의 실적 막대 차트, 매크로/섹터의 시장 추세선·산업 블록, 이벤트/카탈리스트의 일정·뉴스 목록을 표시합니다. 역할을 구분하는 배경 그래픽이며 실시간 데이터나 실제 조사 결과를 표시하지 않습니다. 부장 모니터는 좌석 방향에 맞춰 뒷면을 유지합니다.

`office-characters.png`는 같은 시안의 네 인물을 기준으로 built-in `image_gen`으로 만든 캐릭터 시트입니다. 4개 행은 부장·비즈니스·매크로·이벤트이며, 각 행의 4개 자세는 정면·뒷모습·오른쪽 걷기·착석입니다. 시트의 자홍색 배경은 파일의 투명 채널이 아니므로 `office-scene.ts`에서 로딩 시 한 번 투명 처리합니다. 원본 그림의 비율을 유지해 128×160 Canvas에 표시하며 부장 초상화도 같은 시트에서 가져옵니다. 얼굴을 도형으로 다시 그리지 않습니다.

캐릭터 생성·편집 프롬프트는 [office-characters.prompt.md](office-characters.prompt.md)에 보존했습니다.

`office-walk-front.png`·`office-walk-back.png`·`office-walk-right.png`는 같은 네 인물의 방향별 4단계 걷기 시트입니다. 전신 그림을 교체해 팔·다리를 번갈아 움직이고, 실제 이동 거리에 따라 프레임을 진행합니다. 정지 시 기본 시트로 돌아갑니다. 화면상의 캐릭터와 클릭 영역은 종전보다 20% 확대했습니다. 생성 및 보정에 사용한 built-in `image_gen` 프롬프트는 [office-walk.prompt.md](office-walk.prompt.md)에 보존했습니다.

이전의 장식이 많은 배경은 Git 이력에 보존되어 있습니다.
