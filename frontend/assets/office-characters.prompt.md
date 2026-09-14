## 캐릭터 시트 생성 프롬프트

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
