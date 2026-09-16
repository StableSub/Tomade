# 현재 캐릭터 시트

`office-characters.png`의 행은 페더스 맥그로·패트·매트·게왹이, 열은 정면·뒷모습·오른쪽·착석입니다. 부장만 정면으로 앉고 직원 셋은 뒷모습으로 앉습니다. 자홍색 배경은 런타임에 제거합니다.

도구: built-in `image_gen`.
참조 시안: `exec-58db9b99-c5a5-46da-b912-dad29d9179c1.png`.
최종 원본: `/Users/anjeongseob/.codex/generated_images/01a09e8f-b7c6-7990-aeaf-b83cc9294f84/exec-e100ade4-6323-418a-95ee-14369c18da80.png`.

## 현재 시트 생성 프롬프트

Production sprite atlas for Tomade. Use the supplied CHARACTER DESIGN SHEET only as identity/style reference. Output a PERFECTLY REGULAR 4 COLUMN by 4 ROW sprite atlas on uniform solid saturated MAGENTA #ff00ff background. Exactly sixteen isolated full-body character sprites, one per equal square cell. No labels, words, borders, chairs, desk, shadows, props, icons, ground, scene or decorative elements. No spill across cell boundaries. Generous magenta padding on every side including head and feet. Keep every sprite of a character the same body size across its row, baseline aligned. Crisp deliberate fine square pixel art, no smooth vector rendering, intact small eyes and faces.

ROWS top to bottom:
1 Feathers McGraw from reference: black penguin, white belly, tiny black deadpan eyes, orange beak and feet, tall RED RUBBER GLOVE HAT on his head in EVERY pose. Preserve visible finger silhouette, white belly only on front, solid black back. No suit/human hands.
2 PAT: yellow sweater, solid blue FLAT BERET, peach round bald face/bulb nose, blue trousers, black shoes.
3 MAT: red sweater, blue-and-white horizontal striped BEANIE with white pom-pom, peach round bald face/bulb nose, blue trousers, black shoes.
4 The exact mint green ARTBOX ALIEN from the reference: large wide round head, TWO round-tipped antennae, TWO large slanted black almond eyes with white dots, small black smile, compact green star-like body with two short legs. Same shape across directions. No clothes/chain/ears.

COLUMNS left to right:
1 FRONT: standing neutral, face directed down toward viewer, both feet fully visible.
2 BACK: standing neutral facing away/upward, absolutely NO face, NO eyes or nose on back of head. Back of penguin fully black, hat remains; Pat and Mat show their cap backs; alien's back has NO face.
3 RIGHT PROFILE: neutral standing facing image RIGHT, nose/beak and eye(s) on right side, back on left. Full body, legs distinguishable.
4 SEATED WORKING: ROW1 penguin faces FRONT toward viewer with flippers extending slightly forward, lower body sitting. ROWS2/3/4 face strictly BACK/upward toward a desk that is NOT DRAWN: backs of heads and bodies visible, arms extended forward, slightly bent seated legs. Do not draw any chair, table, keyboard, desk or detached object. The atlas will be layered over real furniture.

Characters are coherent simplified pixel sprites based faithfully on supplied designs. Keep the source clothing, hats, alien face, red glove hat. No redesign or larger anime eyes. All four rows use the same pixel density. Return only the atlas.

## 이전 사람 캐릭터 시트 생성 프롬프트

Use case: identity-preserve / game sprite asset extraction. The provided image is the APPROVED character identity and pixel-art style reference. Create a production SPRITE ATLAS of the SAME FOUR people, faithfully preserving their faces, hairstyles, proportions, outfits and rich fine-pixel RPG art. The atlas will replace crude programmatically drawn avatars in this office. The reference faces are the target, not a suggestion. Exactly FOUR CHARACTER IDENTITIES repeated across poses.

OUTPUT: square PNG sprite sheet, preferably 2048x2048, TRUE TRANSPARENT ALPHA BACKGROUND. No white/colored background, no checkerboard drawn into pixels, no ground shadows, no floor, no office, no props other than the woman's papers in walking pose, no labels, no text, no border or grid lines. Arrange EXACTLY FOUR ROWS and FOUR COLUMNS, 16 isolated sprites total, in equal invisible square cells. Each sprite is fully within its own cell with abundant transparent padding. Uniform scale, equal cell centers, head and foot baseline aligned. Character height approximately 75% of each cell. Every full body wholly visible including hair, hands and feet, with zero cell overlap.

ROW 1: MANAGER from top-center of reference: softly tousled medium brown hair with side-swept fringe, friendly clean refined face and clear dark eyes, dark charcoal business suit, white shirt and narrow red tie, black trousers and shoes. No glasses.
ROW 2: BUSINESS ANALYST from middle-left: short warm brown textured hair, youthful clear face, white/ivory long-sleeve collared shirt, dark trousers and black shoes. No jacket, no glasses, no blue shirt, no tie.
ROW 3: MACRO ANALYST from middle-right: tousled black hair, neat small round black glasses, dark charcoal/black office jacket, white shirt, dark trousers and black shoes. Do NOT use green clothing.
ROW 4: EVENT ANALYST from center walking figure: brown ponytail and side bangs, clear gentle feminine face, ivory/white long-sleeve blouse, dark charcoal trousers and black shoes. Do NOT use blue clothing or a skirt.

The SAME column poses apply to all rows:
COLUMN 1: full body facing FRONT, calm standing idle pose, both eyes and face clearly readable.
COLUMN 2: full body facing directly AWAY (back view), same outfit and hair identity.
COLUMN 3: full body walking toward SCREEN RIGHT in a right-facing three-quarter side profile, clear natural walking stride with separate feet; woman carries a small white research report as in the reference.
COLUMN 4: SITTING / WORKING pose with bent knees, arms slightly extended for typing, NO chair and NO desk. Manager faces FRONT with a visible friendly face; other three face mostly AWAY with a small natural side glance as in reference. Keep seated full body and bent legs within cell.

Art style: match exactly the source's lovingly crafted high-detail 2D pixel characters, delicate coherent face features, rich but controlled stepped hair highlights, crisp dark outlines, clean pixel clusters, warm skin, readable hands. Fine small pixel units; do not reduce to a crude 16x16 or 32x32 face, do not smooth into a painted anime illustration. Coherent anatomy, no melted eyes, no deformed heads. Charming adults in a cozy 2D RPG office, faithful to reference characters. 16 sprites in exactly 4x4 uniform cells on actual alpha transparency.

## 시트 배경 정리 프롬프트

Edit ONLY the BACKGROUND of this exact 4x4 pixel-character sprite atlas. Replace the entire gray-and-white checkerboard with ONE PERFECTLY FLAT SOLID PURE MAGENTA COLOR #FF00FF (RGB 255,0,255). This is a chroma-key backdrop for a game sprite renderer. Absolutely no checkerboard, no texture, no gradients, no shadow, no off-white padding. Every pixel not belonging to one of the sixteen sprites must be magenta. Preserve all sixteen character sprites, their faces, detailed pixel art, poses, clothes, positions, sizes, row/column order and overall square dimensions exactly. Do not move, resize, blur or alter any sprite. Crisp hard opaque sprite edges, no pink halo or added outline. Keep all four rows and all four columns. No new content, no text. Only replace checkerboard with uniformly solid vivid magenta.
