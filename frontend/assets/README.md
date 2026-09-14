# Tomade 도트 사무실 배경

`research-office.png`는 사용자가 승인한 토마토 테마 정사각형 시안에서 네 사람만 제거한 배경입니다. built-in `image_gen` 편집 결과를 프로젝트에 적용했고 생성 원본은 별도로 보존했습니다. 로고·명패·가구·도트 질감은 유지하며 실제 대화와 조사 내용은 HTML로 표시합니다.

`office-characters.png`는 같은 시안의 네 인물을 기준으로 built-in `image_gen`으로 만든 캐릭터 시트입니다. 4개 행은 부장·비즈니스·매크로·이벤트이며, 각 행의 4개 자세는 정면·뒷모습·오른쪽 걷기·착석입니다. 시트의 자홍색 배경은 파일의 투명 채널이 아니므로 `office-scene.ts`에서 로딩 시 한 번 투명 처리합니다. 원본 그림의 비율을 유지해 128×160 Canvas에 표시하며 부장 초상화도 같은 시트에서 가져옵니다. 얼굴을 도형으로 다시 그리지 않습니다.

캐릭터 생성·편집 프롬프트는 [office-characters.prompt.md](office-characters.prompt.md)에 보존했습니다.

`office-walk-front.png`·`office-walk-back.png`·`office-walk-right.png`는 같은 네 인물의 방향별 4단계 걷기 시트입니다. 전신 그림을 교체해 팔·다리를 번갈아 움직이고, 실제 이동 거리에 따라 프레임을 진행합니다. 정지 시 기본 시트로 돌아갑니다. 화면상의 캐릭터와 클릭 영역은 종전보다 20% 확대했습니다. 생성 및 보정에 사용한 built-in `image_gen` 프롬프트는 [office-walk.prompt.md](office-walk.prompt.md)에 보존했습니다.

최종 배경 편집 프롬프트:

> Use case: precise-object-edit. Convert the supplied APPROVED square Tomade pixel-art office into its interactive game background. REMOVE ONLY ALL FOUR HUMAN CHARACTERS: the manager at upper center, the seated business researcher at middle-left, the seated macro researcher at middle-right, and the walking ponytailed person over the central tomato rug. Reconstruct the chairs, desk surfaces and rug/floor behind those four people. All FOUR desk chairs remain, EMPTY. Preserve EVERYTHING ELSE EXACTLY: full square framing, entire room, tomato rug, red chairs, green lamps, fine crisp hand-placed 2D pixel art, wood floor pattern, furniture positions, tomato plants, sofa, entrance, and readable signs 'Tomade', '부장 Agent', '비즈니스', '매크로 / 섹터', '이벤트 / 카탈리스트'. Do not change layout or move furniture; animated characters will be overlaid on the preserved coordinates. Do not add people, UI, new signs, new furniture or art. No face remnants, no body shadows or papers floating where people were removed. No smoothing, no re-illustration, no 3D, no cropping. This is a surgical removal edit, not a redesign.
