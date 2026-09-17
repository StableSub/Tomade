# 정원 생활 소품

승인된 정원 시안을 기준으로 built-in imagegen으로 제작한 4열×2행, 8종 아틀라스입니다. 오른쪽 빈 공간에는 작은 석재 새 목욕대를 추가했습니다. 새나 물 분사 애니메이션은 없습니다.

`garden-details.webp`는 생성 PNG를 무손실 WebP로 인코딩한 1774×887 알파 이미지입니다. 행 우선 순서는 피크닉 테이블·울타리·우편함·장작 보관대 / 빗물통·수확 바구니·꽃밭·새 목욕대입니다. `office-room.ts`와 소품 뷰어에서 개별 프레임을 읽어 기존 픽셀 격자·캐시·접지 그림자를 재사용합니다. 꽃밭은 가는 식물 경계를 유지하기 위해 추가 검은 윤곽을 넣지 않습니다.

생성 이미지의 아주 약한 알파 여백이 소품 크기와 바닥점을 바꾸지 않도록 `loadSpriteSource`가 픽셀 변환과 동일한 96/255 미만 알파를 제외하고 자릅니다.

## 생성 프롬프트

Use case: stylized-concept. Asset type: production reusable pixel-art SPRITE ATLAS for the approved Tomade office garden.
Input reference image: approved garden enrichment concept, STYLE AND OBJECT REFERENCE ONLY.
Generate ONE atlas, exact 4 COLUMNS × 2 ROWS, eight equal square cells, preferably 2048×1024. Every sprite centered in its own cell with generous 12% margin. All eight complete isolated sprites, no item crosses a cell. No visible grid, labels, text or numbers.
Background is PERFECTLY FLAT SOLID MAGENTA #FF00FF throughout, also in every hole and between legs. No checkerboard, no white, no cast shadows, no grass ground outside the flower patch.

Exact row-major content:
TOP LEFT: small honey-oak picnic table with attached front and rear benches, front horizontal, slightly elevated orthogonal RPG view, clearly drawn wooden legs. One small ivory mug and one closed slate-blue book on tabletop. Match the picnic table in the reference. Logical size about 142×70 pixels.
TOP SECOND: ONE short warm wood rail fence segment, two slender vertical posts and two horizontal rails, straight front view, no diagonal recession. Entire posts visible, plain fine wood texture. Logical size about 90×34 pixels.
TOP THIRD: ONE small terracotta-red rounded mailbox on one brown wooden post with a small flat footing. Tiny red/green tomato emblem only, absolutely no letters. Front/side readable at the reference's elevated camera. Logical size about 32×58 pixels.
TOP RIGHT: ONE low neat firewood storage rack, two wooden side posts and neatly stacked split logs with visible circular end grain, long horizontal silhouette. Match reference wood pile. Logical size about 70×55 pixels.
BOTTOM LEFT: ONE medium wooden rain barrel, muted blue-grey metal hoops, subtly visible elliptical open top with still blue-grey water, no faucet extending outside, no floor. Logical size about 44×52 pixels.
BOTTOM SECOND: ONE small low wicker harvest basket, a few ripe red tomatoes with green calyx, low basket with a single thin handle, finely drawn weave. Logical size about 34×29 pixels.
BOTTOM THIRD: ONE low wide irregular flowering garden clump, white daisies, small yellow centers and a few muted warm-yellow flowers, soft olive/sage leaves. Width about twice height. No pot, no stone edging, no giant black perimeter, no grass rectangle, leave natural transparent gaps between stalks. Logical size about 62×30 pixels.
BOTTOM RIGHT: ONE SMALL grey-beige stone birdbath, a shallow broad circular basin viewed as an ellipse, slim pedestal and stable round foot. Tiny still pale blue water surface and one short edge highlight, no fountain jets, no bird or other animal, no ivy. Same slightly elevated orthogonal view. Logical size about 50×62 pixels. This will stand in the right-side garden of the reference.

Style and production constraints:
All assets must look drawn by the same artist as the reference's wooden garden bench, tomato bed and trees. Fine crisp small-pixel clusters, restrained warm oak/terracotta/sage colors, dark THIN outlines, gentle upper-left light, 2-4 tones per material with modest texture. Bigger objects have MORE pixels, not bigger pixel blocks. Do not render blurry painted illustration, glossy 3D, vector art, thick sticker borders or hard cast shadows. Dark pixels are part of object contours only. Consistent camera and light across all cells. These images will be shown at small game size. No extra objects, characters, UI, house, scenery, watermark, text, duplicate cells or merged sprites. Eight isolated sprites on pure magenta, 4×2 grid.
