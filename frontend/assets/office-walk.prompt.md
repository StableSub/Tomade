# 현재 캐릭터 걷기 에셋

기존 이동 거리 기반 4프레임 재생 로직에 페더스 맥그로·패트·매트·게왹이의 새 그림을 연결했습니다. 정면·뒷모습·오른쪽 각각 4×4 시트이며 왼쪽은 오른쪽을 런타임에 반전합니다. 모든 방향은 열 순서대로 재생합니다. 짧은 반복 걸음으로 표현하며 프레임 사이를 보간하지 않습니다.

도구: built-in `image_gen`. 참조는 현재 기본 캐릭터 시트입니다.
최종 생성 원본 폴더: `/Users/anjeongseob/.codex/generated_images/01a09e8f-b7c6-7990-aeaf-b83cc9294f84/`.
- 정면: `exec-32970f61-cda5-489f-a6e6-0b41df31208b.png` (초기 `exec-a78b867b-b452-45c3-b44b-ecbffbda5547.png`에서 다리 보정).
- 후면: `exec-df1ce766-fd92-4aa4-b214-a6489ae4eb02.png`.
- 오른쪽: `exec-c6c0618f-a697-47d2-bccf-4ed25069b445.png`.

## 현재 front 생성 프롬프트

Generate a production WALK CYCLE sprite atlas for the supplied approved four-character base atlas. Exact identities, hats, faces, body proportions and fine pixel style MUST match. Output exactly FOUR equal COLUMNS by FOUR equal ROWS on uniform pure MAGENTA #ff00ff. One full-body sprite centered inside each cell, baseline matched across row, ample padding. No text, grid, arrows, ground, cast shadows, floor, chair, desk, paper or props. Fixed body/head scale across all four frames, no squashing/stretched faces.
ROWS: 1 Feathers McGraw black penguin/white front belly/orange feet and beak, the RED RUBBER GLOVE HAT with all fingers visible in EVERY frame. 2 PAT yellow sweater, blue flat beret, blue trousers and black shoes. 3 MAT red sweater, BLUE-WHITE STRIPED POM-POM HAT, blue trousers/black shoes. 4 mint-green ARTBOX ALIEN, broad head, TWO round-tip antennae, black almond eyes on FRONT ONLY, tiny smiling mouth, stubby green arms and legs, no clothing.
COLUMNS are FOUR CONSECUTIVE WALK PHASES in temporal order: 1 left-leg contact/right-arm forward, 2 passing with feet close and one heel lifted, 3 right-leg contact/left-arm forward, 4 opposite passing phase with feet close and other heel lifted. Real alternating feet and opposite arm swing, small readable changes. Each column is visually distinct and the fourth loops into first. No interpolation blur; limited-frame classic pixel walking is desired. Penguin waddles with alternating orange feet and subtle flipper counter-swing; alien bobs with alternating short legs, two antennae stay stable. Keep hats/red glove fully inside cells, no detached bits and no duplicating an extra eye on the back.
DIRECTION LOCK: ALL SIXTEEN FIGURES FACE STRICTLY FRONT, toward the viewer/downward as in base atlas column 1. Faces and both eyes visible in every frame, faces straight forward, never turn sideways. Show the approved front appearance during walking.

## 현재 back 생성 프롬프트

Generate a production WALK CYCLE sprite atlas for the supplied approved four-character base atlas. Exact identities, hats, faces, body proportions and fine pixel style MUST match. Output exactly FOUR equal COLUMNS by FOUR equal ROWS on uniform pure MAGENTA #ff00ff. One full-body sprite centered inside each cell, baseline matched across row, ample padding. No text, grid, arrows, ground, cast shadows, floor, chair, desk, paper or props. Fixed body/head scale across all four frames, no squashing/stretched faces.
ROWS: 1 Feathers McGraw black penguin/white front belly/orange feet and beak, the RED RUBBER GLOVE HAT with all fingers visible in EVERY frame. 2 PAT yellow sweater, blue flat beret, blue trousers and black shoes. 3 MAT red sweater, BLUE-WHITE STRIPED POM-POM HAT, blue trousers/black shoes. 4 mint-green ARTBOX ALIEN, broad head, TWO round-tip antennae, black almond eyes on FRONT ONLY, tiny smiling mouth, stubby green arms and legs, no clothing.
COLUMNS are FOUR CONSECUTIVE WALK PHASES in temporal order: 1 left-leg contact/right-arm forward, 2 passing with feet close and one heel lifted, 3 right-leg contact/left-arm forward, 4 opposite passing phase with feet close and other heel lifted. Real alternating feet and opposite arm swing, small readable changes. Each column is visually distinct and the fourth loops into first. No interpolation blur; limited-frame classic pixel walking is desired. Penguin waddles with alternating orange feet and subtle flipper counter-swing; alien bobs with alternating short legs, two antennae stay stable. Keep hats/red glove fully inside cells, no detached bits and no duplicating an extra eye on the back.
DIRECTION LOCK: ALL SIXTEEN FIGURES FACE STRICTLY BACK, away from viewer/upward as in base atlas column 2. No eyes, nose, beak, smile or facial markings visible anywhere on ANY back of a head. Penguin back and flippers are black with no white belly visible. Alien back head is plain green. Heads NEVER rotate; movement is only limbs and small weight shift.

## 현재 right 생성 프롬프트

Generate a production WALK CYCLE sprite atlas for the supplied approved four-character base atlas. Exact identities, hats, faces, body proportions and fine pixel style MUST match. Output exactly FOUR equal COLUMNS by FOUR equal ROWS on uniform pure MAGENTA #ff00ff. One full-body sprite centered inside each cell, baseline matched across row, ample padding. No text, grid, arrows, ground, cast shadows, floor, chair, desk, paper or props. Fixed body/head scale across all four frames, no squashing/stretched faces.
ROWS: 1 Feathers McGraw black penguin/white front belly/orange feet and beak, the RED RUBBER GLOVE HAT with all fingers visible in EVERY frame. 2 PAT yellow sweater, blue flat beret, blue trousers and black shoes. 3 MAT red sweater, BLUE-WHITE STRIPED POM-POM HAT, blue trousers/black shoes. 4 mint-green ARTBOX ALIEN, broad head, TWO round-tip antennae, black almond eyes on FRONT ONLY, tiny smiling mouth, stubby green arms and legs, no clothing.
COLUMNS are FOUR CONSECUTIVE WALK PHASES in temporal order: 1 left-leg contact/right-arm forward, 2 passing with feet close and one heel lifted, 3 right-leg contact/left-arm forward, 4 opposite passing phase with feet close and other heel lifted. Real alternating feet and opposite arm swing, small readable changes. Each column is visually distinct and the fourth loops into first. No interpolation blur; limited-frame classic pixel walking is desired. Penguin waddles with alternating orange feet and subtle flipper counter-swing; alien bobs with alternating short legs, two antennae stay stable. Keep hats/red glove fully inside cells, no detached bits and no duplicating an extra eye on the back.
DIRECTION LOCK: ALL SIXTEEN FIGURES FACE STRICTLY RIGHT in clean side profile as in base atlas column 3. Nose/beak and face at image-right, backs at left, all walking to the RIGHT in every column. Profile head and hat retain same silhouette as the approved right-facing base. Legs alternate front/back and arms counter-swing. No front or back view.

## 현재 정면 걸음 보정 프롬프트

Surgical walk-cycle correction of this EXACT 4x4 front-facing sprite atlas. Preserve the pure magenta background, equal grid cells, all sprite positions, all faces, hats, heads, torso sizes, pixel style, row1 penguin and row4 alien completely unchanged.
ONLY correct the legs and arms of PAT (yellow shirt, ROW2) and MAT (red shirt, ROW3). They currently repeat the SAME forward leg in all four columns. This must become an alternating walk sequence:
COLUMN1: keep current contact step, shoe on viewer RIGHT lower/forward, shoe on viewer LEFT higher/back.
COLUMN2: passing pose, both feet nearly aligned below hips, viewer-LEFT heel lifted. Arms closer to body.
COLUMN3: REVERSE the legs from column1: shoe on viewer LEFT lower/forward, shoe on viewer RIGHT higher/back. Arm swing also reverses from column1.
COLUMN4: passing pose, feet nearly aligned, viewer-RIGHT heel lifted. Arms closer to body.
The third column must CLEARLY use the opposite forward leg from the first. The four frames form LEFT step / passing / RIGHT step / passing. No head turning, no resizing, no facial changes, no swapping clothes, no torso wobble. Keep all faces looking directly toward viewer, same hat silhouette. Modify LOWER LIMBS and arm swing only in rows2 and3. All other pixels should remain unchanged. No text or props.

# 이전 사람 캐릭터 걷기 제작 기록

## 정면 이벤트 캐릭터 연속성 보정

Edit ONLY the bottom-row THIRD sprite in this exact 4 by 4 front-walking sprite sheet. Leave all other 15 sprites pixel-identical and leave magenta #FF00FF background identical.
The woman in bottom row third column still has two animation continuity errors. Correct BOTH:
A) Her head/hair must match bottom row FIRST column exactly: keep bangs and face, move the long ponytail to SCREEN RIGHT of her body. Remove the erroneous SCREEN LEFT ponytail. Her ponytail MUST remain on screen right for all four columns, not switch sides.
B) Her SCREEN LEFT leg and shoe must be extended downward and planted at the bottom baseline. Her SCREEN RIGHT leg and shoe should be slightly behind and 18 pixels HIGHER than the left shoe. Currently the right shoe is lower like column one, which is wrong: column three must have the OPPOSITE foot forward.
Keep her papers held in the SCREEN LEFT hand against the left side of her torso, and the free hand on SCREEN RIGHT. No other changes. Maintain the exact fine pixel style, body proportions, uniform 4x4 grid and solid magenta backdrop.


Built-in `image_gen`으로 기존 `office-characters.png`의 네 인물을 참조해 생성했습니다. 파일은 프로젝트의 `frontend/assets/office-walk-front.png`, `office-walk-back.png`, `office-walk-right.png`입니다. 각각 4개 인물 행과 4개 연속 자세 열을 포함합니다. 왼쪽은 오른쪽 시트를 런타임에 반전합니다. 원본 생성 파일은 별도로 보존합니다.

후면 시트의 실제 자세를 확인해 재생 순서를 열 1 → 3 → 2 → 4로 지정했습니다. 다른 방향은 열 순서대로 재생합니다. 자홍색 배경은 공통 로더에서 한 번 제거하고, 프레임마다 원본의 비율을 유지합니다.

## front 생성 프롬프트

Use case: identity-preserve.
Asset type: production fine-pixel 2D RPG walking-animation sprite atlas for the Tomade office UI.
Input image is the identity and art-style reference, NOT the requested layout of poses. Preserve those exact four people, fine pixel detail, face shapes, proportions, hairstyles and clothes.
Make ONE square atlas of EXACTLY 4 rows x 4 columns, 16 full-body sprites total. Rows top to bottom: 1 brown-haired male manager in dark suit vest/jacket, white shirt, red tie; 2 brown-haired male business researcher in ivory white shirt and dark trousers; 3 black-haired male analyst with glasses in charcoal jacket over white shirt, dark trousers; 4 brown ponytail female researcher in ivory blouse and dark trousers, carrying a small bundle of papers in one hand consistently.
Columns left to right are 4 distinct sequential phases of a relaxed realistic walking loop: (1) left foot forward/right foot back contact, opposite arm forward, (2) weight on left leg, right knee bends and passes under body, arms pass near torso, (3) right foot forward/left foot back contact, opposite arm forward, (4) weight on right leg, left knee bends and passes under body, arms near torso. Clearly alternate BOTH the legs and counter-swinging arms; natural modest stride, not running. Arms and legs must actually change pose between columns, including the third frame having OPPOSITE leg forward from first frame.
Composition: sixteen equal invisible square cells, each figure centered at EXACTLY the same scale within its row, consistent head size in every frame, consistent baseline in each row. Leave at least 25% horizontal padding and 10% vertical padding in every cell. Keep all hair, hands, and shoes entirely within each cell. Same slightly elevated RPG camera as reference. Crisp small manually placed pixel clusters and clean recognizable faces; no blur or melted faces.
Backdrop: perfectly uniform solid vivid magenta RGB 255,0,255 (#FF00FF) across the entire sheet, touching every character silhouette cleanly. No checkerboard, no texture, no gradient, no shadows or glow on backdrop, no floor, no other scene elements.
No text, labels, borders, divider lines, hats, chairs, desks, or extra people.
Direction: All 16 sprites face DIRECTLY TOWARD the viewer (front view), walking down-screen. Keep face and chest facing viewer throughout all four frames, show knees bending and alternating forward shoes with clear footwork.

### 자세 보정 프롬프트

Surgical correction of THIS exact 4x4 pixel sprite atlas. Preserve faces, hair, art, row positions, sizes, background #FF00FF and every sprite except the following two pose errors.
1. Column FOUR currently incorrectly repeats column TWO. In column FOUR of ALL four rows, draw the OPPOSITE passing step: the leg on SCREEN LEFT is now straight and the SCREEN LEFT shoe is planted lowest at the shared baseline; the leg on SCREEN RIGHT is bent at the knee and the SCREEN RIGHT shoe is lifted higher beside the left calf. Column TWO has screen-right foot planted and screen-left foot raised; column FOUR must visibly reverse that. Arms in column FOUR pass close beside the torso. Do not mirror or alter their heads or hairstyles.
2. Woman, bottom row, column THREE: keep her original head and ponytail orientation identical to bottom-row column ONE and TWO (ponytail visible toward SCREEN RIGHT). She must carry the papers in the hand on SCREEN LEFT, exactly as in her other three frames. Her SCREEN RIGHT hand is free and swings. Preserve the column THREE opposing leg stance with SCREEN LEFT foot forward. Papers must not teleport hands during a loop.
This is an identity-preserving precise pixel art edit, not a new design. Keep exactly 16 whole-body sprites in 4 rows and 4 columns, uniform magenta background. No other changes.

## back 생성 프롬프트

Use case: identity-preserve.
Asset type: production fine-pixel 2D RPG walking-animation sprite atlas for the Tomade office UI.
Input image is the identity and art-style reference, NOT the requested layout of poses. Preserve those exact four people, fine pixel detail, face shapes, proportions, hairstyles and clothes.
Make ONE square atlas of EXACTLY 4 rows x 4 columns, 16 full-body sprites total. Rows top to bottom: 1 brown-haired male manager in dark suit vest/jacket, white shirt, red tie; 2 brown-haired male business researcher in ivory white shirt and dark trousers; 3 black-haired male analyst with glasses in charcoal jacket over white shirt, dark trousers; 4 brown ponytail female researcher in ivory blouse and dark trousers, carrying a small bundle of papers in one hand consistently.
Columns left to right are 4 distinct sequential phases of a relaxed realistic walking loop: (1) left foot forward/right foot back contact, opposite arm forward, (2) weight on left leg, right knee bends and passes under body, arms pass near torso, (3) right foot forward/left foot back contact, opposite arm forward, (4) weight on right leg, left knee bends and passes under body, arms near torso. Clearly alternate BOTH the legs and counter-swinging arms; natural modest stride, not running. Arms and legs must actually change pose between columns, including the third frame having OPPOSITE leg forward from first frame.
Composition: sixteen equal invisible square cells, each figure centered at EXACTLY the same scale within its row, consistent head size in every frame, consistent baseline in each row. Leave at least 25% horizontal padding and 10% vertical padding in every cell. Keep all hair, hands, and shoes entirely within each cell. Same slightly elevated RPG camera as reference. Crisp small manually placed pixel clusters and clean recognizable faces; no blur or melted faces.
Backdrop: perfectly uniform solid vivid magenta RGB 255,0,255 (#FF00FF) across the entire sheet, touching every character silhouette cleanly. No checkerboard, no texture, no gradient, no shadows or glow on backdrop, no floor, no other scene elements.
No text, labels, borders, divider lines, hats, chairs, desks, or extra people.
Direction: All 16 sprites face DIRECTLY AWAY from the viewer (back view), walking up-screen. Show back of head and shoulders only throughout all four frames. No faces seen. Show believable alternating rear-view heel lifts and arm counter-swing.

## right 생성 프롬프트

Use case: identity-preserve.
Asset type: production fine-pixel 2D RPG walking-animation sprite atlas for the Tomade office UI.
Input image is the identity and art-style reference, NOT the requested layout of poses. Preserve those exact four people, fine pixel detail, face shapes, proportions, hairstyles and clothes.
Make ONE square atlas of EXACTLY 4 rows x 4 columns, 16 full-body sprites total. Rows top to bottom: 1 brown-haired male manager in dark suit vest/jacket, white shirt, red tie; 2 brown-haired male business researcher in ivory white shirt and dark trousers; 3 black-haired male analyst with glasses in charcoal jacket over white shirt, dark trousers; 4 brown ponytail female researcher in ivory blouse and dark trousers, carrying a small bundle of papers in one hand consistently.
Columns left to right are 4 distinct sequential phases of a relaxed realistic walking loop: (1) left foot forward/right foot back contact, opposite arm forward, (2) weight on left leg, right knee bends and passes under body, arms pass near torso, (3) right foot forward/left foot back contact, opposite arm forward, (4) weight on right leg, left knee bends and passes under body, arms near torso. Clearly alternate BOTH the legs and counter-swinging arms; natural modest stride, not running. Arms and legs must actually change pose between columns, including the third frame having OPPOSITE leg forward from first frame.
Composition: sixteen equal invisible square cells, each figure centered at EXACTLY the same scale within its row, consistent head size in every frame, consistent baseline in each row. Leave at least 25% horizontal padding and 10% vertical padding in every cell. Keep all hair, hands, and shoes entirely within each cell. Same slightly elevated RPG camera as reference. Crisp small manually placed pixel clusters and clean recognizable faces; no blur or melted faces.
Backdrop: perfectly uniform solid vivid magenta RGB 255,0,255 (#FF00FF) across the entire sheet, touching every character silhouette cleanly. No checkerboard, no texture, no gradient, no shadows or glow on backdrop, no floor, no other scene elements.
No text, labels, borders, divider lines, hats, chairs, desks, or extra people.
Direction: All 16 sprites face SCREEN RIGHT in a clean consistent side / slight three-quarter profile, walking right. Do not turn toward camera between frames. Front and rear legs visibly exchange places and knees bend in the passing phases; counter-swinging arms. The ponytail trails toward screen left.

### 자세 보정 프롬프트

Precise corrective edit of THIS exact 4x4 pixel sprite atlas, for an actual four-frame walking animation. Everyone still faces SCREEN RIGHT in profile. Keep all faces, hairstyles, outfit identity, head sizes, cell layout and pure #FF00FF background unchanged.
Currently columns ONE and THREE repeat the same stride, and columns TWO and FOUR repeat the same bent leg. Fix the gait while retaining all 16 sprites:
COLUMN ONE is first contact: visible NEAR arm swings BACK to screen left, near leg swings FORWARD to screen right; keep it.
COLUMN TWO is passing: near leg planted under body, far leg swinging past; keep it.
COLUMN THREE is opposite contact: swap the arm and leg layering and actions from column ONE. Now the visible NEAR arm swings FORWARD to screen right and the near leg extends BACKWARD toward screen left. The FAR leg reaches forward toward screen right. Show the near thigh and back shoe clearly crossing in FRONT of the far leg. Do not simply duplicate column ONE. The shoulders and hair face same direction.
COLUMN FOUR is opposite passing: visible NEAR leg bends at the knee and lifts the knee FORWARD toward screen right; its lifted shoe below the knee is in front of the standing far leg, with toes facing right. Far leg is straight and planted under body. Near arm passes center, far arm counter-swings. Do not repeat the foot lifted BEHIND body from column TWO.
Woman keeps papers tucked against her chest in the same arm in all four cells; only free arm swings. Preserve each person's head and upper torso structure. Full-body modest relaxed walking, NO running, NO jumping, no extra legs, no shadows, no props added. All four phases visibly alternate the near leg and far leg. Do not change scale or cell positions.
