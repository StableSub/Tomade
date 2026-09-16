# Tomade 배경 v2 보완

난로 기준의 공통 도트 스타일에 맞춰 `wall-panel.png`와 `entrance-steps.png`를 built-in `image_gen`으로 재생성했습니다. 벽은 크림·세이지·목재의 세 가로 색면, 계단은 단순한 회색 단으로 정리했습니다. 잔무늬가 팔레트 변환 후 얼룩처럼 강조되는 문제를 제거하기 위한 변경입니다.

[prompts.json](prompts.json)에 원본 경로와 최종 프롬프트를 기록했습니다. CLI fallback은 사용하지 않았습니다. 실제 앱과 [배경 뷰어](../office-environment-v1/index.html)는 `pixel-style.ts`의 캐릭터 기준 배율·공통 팔레트를 사용합니다. 계단에는 실루엣 안쪽 2픽셀 검정 윤곽을 적용하며 벽면에는 윤곽을 넣지 않습니다. 다른 배경 에셋과 정확한 나무 바닥 SVG는 v1에서 계속 사용합니다.
