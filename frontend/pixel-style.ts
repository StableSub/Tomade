// Match the staff sprites: 160 canvas rows displayed at 10.8% of an 800-unit room.
export const OBJECT_PIXEL_SIZE = 800 * .108 / 160;
export const OBJECT_OUTLINE_PIXELS = 2;
// The silhouette ink matches the characters; material colors remain separate.
export const OFFICE_PALETTE = [
  '#191716', '#26312c', '#3d362b', '#614932', '#805c38', '#a27440', '#c4934e', '#dfb36e', '#f0cf91',
  '#1e2d34', '#34454f', '#4f606a', '#718189', '#a9b6b5',
  '#215442', '#30725a', '#458b6c', '#66a17f', '#8db689', '#b4cc98',
  '#baa480', '#d7c5a1', '#ebdfbd', '#f7efda', '#bec5a9',
  '#315372', '#42799a', '#69a3bb', '#aad0d6',
  '#793e31', '#a84b35', '#d46841', '#ec9a53', '#9b3430', '#cd4735', '#e57254', '#e9a330', '#fad56d',
  '#244951', '#316c77', '#4c91a0', '#8ab6b6', '#b7bcba', '#d4d7c9', '#eef0e4',
  '#efdbb0', '#e4cca0', '#bda57d',
] as const;
// Parquet's three exact seam/fill colors stay reserved for that existing SVG.
// Competing near-identical cream shades otherwise turn source grain into speckles.
const colors = OFFICE_PALETTE.slice(0, -3).map(hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)));

type PixelStyle = { outline?: boolean; pixelSize?: number; preserveColors?: boolean };

// Outline inside the binary silhouette, including holes. Do not grow the object or
// cover openings between legs/rails. Diagonal neighbors close staircase corners too.
function inkContour(sprite: HTMLCanvasElement): void {
  const ctx = sprite.getContext('2d')!;
  const pixels = ctx.getImageData(0, 0, sprite.width, sprite.height);
  const alpha = new Uint8Array(sprite.width * sprite.height);
  for (let i = 0; i < alpha.length; i++) alpha[i] = pixels.data[i * 4 + 3];
  for (let y = 0; y < sprite.height; y++) for (let x = 0; x < sprite.width; x++) {
    if (!alpha[y * sprite.width + x]) continue;
    let edge = false;
    for (let dy = -OBJECT_OUTLINE_PIXELS; dy <= OBJECT_OUTLINE_PIXELS && !edge; dy++) {
      for (let dx = -OBJECT_OUTLINE_PIXELS; dx <= OBJECT_OUTLINE_PIXELS; dx++) {
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || yy < 0 || xx >= sprite.width || yy >= sprite.height || !alpha[yy * sprite.width + xx]) {
          edge = true; break;
        }
      }
    }
    if (edge) pixels.data.set([25, 23, 22, 255], (y * sprite.width + x) * 4);
  }
  ctx.putImageData(pixels, 0, 0);
  sprite.dataset.outlinePixels = String(OBJECT_OUTLINE_PIXELS);
}

/** Build a sprite on the staff character's pixel scale, with a closed dark silhouette.
 * Width/height are room units, independent of display DPI/zoom. Nearest-neighbor
 * sampling matches the character renderer. The two-cell ink contour stays inside
 * the binary alpha mask so holes and footprint are preserved. Flat backgrounds can
 * opt out of contours; exact tiles can retain their original one-unit grid.
 * preserveColors retains source RGB instead of quantizing it to the office palette.
 */
export function createPixelSprite(source: HTMLCanvasElement, width: number, height: number, style: PixelStyle = {}): HTMLCanvasElement {
  const pixelSize = style.pixelSize ?? OBJECT_PIXEL_SIZE;
  const sprite = document.createElement('canvas');
  sprite.width = Math.round(width / pixelSize); sprite.height = Math.round(height / pixelSize);
  const ctx = sprite.getContext('2d')!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(source, 0, 0, sprite.width, sprite.height);
  const pixels = ctx.getImageData(0, 0, sprite.width, sprite.height);
  for (let i = 0; i < pixels.data.length; i += 4) {
    if (pixels.data[i + 3] < 96) { pixels.data[i + 3] = 0; continue; }
    pixels.data[i + 3] = 255;
    if (style.preserveColors) continue;
    let best = colors[0], distance = Infinity;
    for (const color of colors) {
      const score = (pixels.data[i] - color[0]) ** 2 + (pixels.data[i + 1] - color[1]) ** 2 + (pixels.data[i + 2] - color[2]) ** 2;
      if (score < distance) { distance = score; best = color; }
    }
    pixels.data.set([...best, 255], i);
  }
  ctx.putImageData(pixels, 0, 0);
  sprite.dataset.pixelGrid = String(pixelSize);
  if (style.outline !== false) inkContour(sprite);
  return sprite;
}

/** Resize a frame by stretching its center, retaining the native border thickness. */
export function fitPixelFrame(source: HTMLCanvasElement, width: number, height: number, border = 3): HTMLCanvasElement {
  const pixelSize = Number(source.dataset.pixelGrid);
  const result = document.createElement('canvas'); result.width = Math.round(width / pixelSize); result.height = Math.round(height / pixelSize);
  border = Math.round(border / pixelSize);
  const ctx = result.getContext('2d')!; ctx.imageSmoothingEnabled = false;
  const sx = [0, border, source.width - border, source.width], sy = [0, border, source.height - border, source.height];
  const dx = [0, border, result.width - border, result.width], dy = [0, border, result.height - border, result.height];
  for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
    ctx.drawImage(source, sx[col], sy[row], sx[col + 1] - sx[col], sy[row + 1] - sy[row],
      dx[col], dy[row], dx[col + 1] - dx[col], dy[row + 1] - dy[row]);
  }
  result.dataset.pixelGrid = String(pixelSize);
  if (source.dataset.outlinePixels) inkContour(result);
  return result;
}
