# 걷기 애니메이션 에셋

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

