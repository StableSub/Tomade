import { OBJECT_PIXEL_SIZE } from './pixel-style';

const shadowImages = new Map<string, string>();

/** Rasterize a contact patch on the furniture pixel grid and reuse it by size.
 * Returns a local PNG data URL; no network access or scene mutations. A larger
 * patch has more pixels, rather than enlarging a fixed CSS polygon's steps.
 */
export function contactShadowImage(width: number, height: number): string {
  const w = Math.max(1, Math.round(width / OBJECT_PIXEL_SIZE));
  const h = Math.max(1, Math.round(height / OBJECT_PIXEL_SIZE));
  const key = `${w}:${h}`;
  if (!shadowImages.has(key)) {
    const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#382817';
    for (let y = 0; y < h; y++) {
      const radius = Math.sqrt(1 - ((y + .5 - h / 2) / (h / 2)) ** 2) * w / 2;
      const left = Math.round(w / 2 - radius), right = Math.round(w / 2 + radius);
      ctx.fillRect(left, y, right - left, 1);
    }
    shadowImages.set(key, canvas.toDataURL());
  }
  return shadowImages.get(key)!;
}

/** Paint the shared outdoor panorama only into the four exposed window panes.
 * Mutates an already normalized window sprite; curtains, mullions, sill and
 * silhouette remain intact. Inputs are decoded local canvases; no I/O occurs.
 */
export function paintWindowView(window: HTMLCanvasElement, landscape: HTMLCanvasElement): void {
  const ctx = window.getContext('2d')!, w = window.width, h = window.height;
  // Pane masks follow the existing curtain silhouette in furniture-atlas.png.
  const panes = [
    [[.307,.162],[.465,.162],[.465,.468],[.254,.468],[.294,.33]],
    [[.541,.162],[.698,.162],[.72,.33],[.767,.468],[.541,.468]],
    [[.236,.558],[.465,.558],[.465,.829],[.251,.829]],
    [[.541,.558],[.776,.558],[.751,.829],[.541,.829]],
  ];
  ctx.save(); ctx.beginPath();
  for (const points of panes) {
    points.forEach(([x,y], index) => {
      const px = Math.round(x * w), py = Math.round(y * h);
      if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.closePath();
  }
  ctx.clip(); ctx.imageSmoothingEnabled = false;
  const width = Math.round(w * .55), height = Math.round(h * .68);
  // A window looks toward the treeline, rather than down at the nearby lawn.
  const cropHeight = landscape.height * .70, cropWidth = cropHeight * width / height;
  ctx.drawImage(landscape, (landscape.width - cropWidth) / 2, landscape.height * .12, cropWidth, cropHeight,
    Math.round(w * .23), Math.round(h * .155), width, height);
  ctx.restore();
}

/** Fit complete floor blocks to the room's inner faces, without cropped edge tiles.
 * Returns an opaque integer-pixel canvas; no network requests or scene mutations.
 */
export function createRoomFloor(width: number, height: number, parquet: boolean): HTMLCanvasElement {
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d')!;
  const columns = parquet ? 9 : 6, rows = 6;
  for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
    const x = Math.round(col * width / columns), right = Math.round((col + 1) * width / columns);
    const y = Math.round(row * height / rows), bottom = Math.round((row + 1) * height / rows);
    const horizontal = (row + col) % 2 === 0;
    ctx.fillStyle = parquet ? '#efe0bd' : horizontal ? '#f2edda' : '#c5cdb5';
    ctx.fillRect(x, y, right - x, bottom - y);
    if (!parquet) continue;
    for (let plank = 0; plank < 3; plank++) {
      const px = horizontal ? x : x + Math.round(plank * (right - x) / 3);
      const py = horizontal ? y + Math.round(plank * (bottom - y) / 3) : y;
      const pw = horizontal ? right - x : Math.round((plank + 1) * (right - x) / 3) - Math.round(plank * (right - x) / 3);
      const ph = horizontal ? Math.round((plank + 1) * (bottom - y) / 3) - Math.round(plank * (bottom - y) / 3) : bottom - y;
      ctx.fillStyle = plank === 1 ? '#ead7b2' : '#efe0bd'; ctx.fillRect(px, py, pw, ph);
      ctx.fillStyle = '#c8b48f'; ctx.fillRect(px, py, pw, 1); ctx.fillRect(px, py, 1, ph);
    }
  }
  return canvas;
}

/** Add the reference's inset timber rim/end lip or the two-plank passage finish.
 * Mutates only the supplied native-grid sprite, retaining its outer ink and alpha.
 */
export function finishTimber(sprite: HTMLCanvasElement, passage = false, grounded = false): HTMLCanvasElement {
  const ctx = sprite.getContext('2d')!, w = sprite.width, h = sprite.height;
  const pixel = Number(sprite.dataset.pixelGrid);
  const unit = (value: number) => Math.max(1, Math.round(value / pixel));
  const line = (color: string, x: number, y: number, width: number, height: number) => {
    ctx.fillStyle = color; ctx.fillRect(x, y, width, height);
  };
  if (passage) {
    ctx.fillStyle = '#d8b475'; ctx.fillRect(0, 0, w, h);
    for (const x of [0, Math.round(w / 2)]) {
      line('#a67b44', x, 0, unit(.54), h);
      line('#efd09a', x + unit(.54), 0, unit(.54), h);
    }
    line('#a67b44', w - unit(.54), 0, unit(.54), h);
    return sprite;
  }
  const original = ctx.getImageData(0, 0, w, h);
  const inset = unit(2), lip = unit(grounded ? 1.6 : 5), thin = unit(1.08);
  // A continuous recessed panel, with a darker short end lip like the concept.
  line('#77502c', inset, inset, w - inset * 2, thin);
  line('#81572e', inset, inset, thin, h - inset * 2 - lip);
  line('#f0ca83', inset + thin, inset + thin, thin, h - inset * 2 - lip - thin);
  line('#81572e', w - inset - thin, inset, thin, h - inset * 2 - lip + thin);
  line('#f0ca83', inset + thin, inset + thin, w - inset * 2 - thin * 2, thin);
  line('#79502b', inset, h - inset - lip, w - inset * 2, thin);
  line('#d3a460', inset, h - inset - lip + thin, w - inset * 2, thin);
  line('#986b37', unit(1.1), h - lip, w - unit(2.2), lip - unit(1.1));
  line('#d3a460', unit(1.1), h - lip, w - unit(2.2), thin);
  line('#81572e', unit(1.1), h - unit(2), w - unit(2.2), thin);
  // The source's stepped corners can extend inside the rectangular end lip.
  // Keep every original ink/transparent cell when adding the interior bevel.
  const finished = ctx.getImageData(0, 0, w, h);
  for (let i = 0; i < original.data.length; i += 4) {
    if (!original.data[i + 3] || (original.data[i] === 25 && original.data[i + 1] === 23 && original.data[i + 2] === 22)) {
      finished.data.set(original.data.subarray(i, i + 4), i);
    }
  }
  ctx.putImageData(finished, 0, 0);
  return sprite;
}

/** Build a self-contained worker or manager front rail between its own columns.
 * The worker section contains the entrance; the manager section is a straight rail.
 * Ends sit one world unit behind column edges, hiding cut outlines at the joint.
 */
export function createFrontSection(source: HTMLCanvasElement, workerRoom: boolean): HTMLCanvasElement {
  const pixel = Number(source.dataset.pixelGrid);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round((workerRoom ? 438 : 282) / pixel);
  canvas.height = workerRoom ? source.height : Math.round(32 / pixel);
  const ctx = canvas.getContext('2d')!; ctx.imageSmoothingEnabled = false;
  const left = Math.round(123 / pixel), right = left + source.width;
  if (workerRoom) ctx.drawImage(source, left, 0);
  const sourceWidth = Math.floor(source.width * .285) - 2;
  const joins: number[] = workerRoom ? [left + 2, right - 2] : [];
  const wing = (start: number, end: number, count: number) => {
    for (let i = 0; i < count; i++) {
      const x = Math.round(start + (end - start) * i / count);
      const next = Math.round(start + (end - start) * (i + 1) / count);
      ctx.drawImage(source, 2, 0, sourceWidth, source.height, x, 0, next - x, source.height);
      if (i) joins.push(x);
    }
  };
  // Overlap the source's vertical cut edges so the top timber remains continuous.
  if (workerRoom) {
    wing(0, left + 2, 1);
    wing(right - 2, canvas.width, 1);
  } else {
    wing(0, canvas.width, 2);
  }
  bridgeCuts(canvas, joins, Math.round(4 / pixel));
  return canvas;
}

/** Match only structural wood to the entrance's material, preserving texture,
 * alpha and silhouette ink. Flat wall paint is excluded by the wood color mask.
 */
export function matchFrameTimber(sprite: HTMLCanvasElement, entrance: HTMLCanvasElement): void {
  const ctx = sprite.getContext('2d')!, pixels = ctx.getImageData(0, 0, sprite.width, sprite.height);
  const ref = entrance.getContext('2d')!.getImageData(0, 0, entrance.width, entrance.height);
  const wood = (r: number, g: number, b: number, a: number) => a === 255 && r > g * 1.08 && g > b * 1.15 && r > 80;
  const average = (data: ImageData, reference: boolean) => {
    const sum = [0, 0, 0]; let count = 0;
    for (let y = 0; y < data.height; y++) for (let x = 0; x < data.width; x++) {
      // Sample the continuous rail face, below its highlight and above stone.
      if (reference && (x < data.width * .06 || x > data.width * .28 || y < data.height * .10 || y > data.height * .24)) continue;
      const i = (y * data.width + x) * 4;
      if (!wood(data.data[i], data.data[i+1], data.data[i+2], data.data[i+3])) continue;
      for (let c = 0; c < 3; c++) sum[c] += data.data[i+c];
      count++;
    }
    return count ? sum.map(value => value / count) : null;
  };
  const current = average(pixels, false), target = average(ref, true);
  if (!current || !target) return;
  for (let i = 0; i < pixels.data.length; i += 4) {
    if (!wood(pixels.data[i], pixels.data[i+1], pixels.data[i+2], pixels.data[i+3])) continue;
    for (let c = 0; c < 3; c++) pixels.data[i+c] = Math.round(Math.min(255, pixels.data[i+c] * target[c] / current[c]));
  }
  ctx.putImageData(pixels, 0, 0);
}

// Remove artificial material/alpha breaks at atlas cuts, retaining real tile seams.
function bridgeCuts(canvas: HTMLCanvasElement, joins: number[], radius: number): void {
  // The crop boundary is not a construction joint. Bridge its color reset and
  // stepped alpha corners using intact material on either side of that cut.
  const ctx = canvas.getContext('2d')!;
  const material = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const original = new Uint8ClampedArray(material.data);
  for (const join of joins) for (let y = 0; y < canvas.height; y++) {
    const start = join - radius, end = join + radius;
    const a = (y * canvas.width + start) * 4, b = (y * canvas.width + end) * 4;
    if (!original[a + 3] || !original[b + 3]) continue;
    for (let x = start; x <= end; x++) {
      const mix = (x - start) / (end - start), i = (y * canvas.width + x) * 4;
      for (let c = 0; c < 3; c++) material.data[i + c] = Math.round(original[a + c] * (1 - mix) + original[b + c] * mix);
      material.data[i + 3] = 255;
    }
  }
  ctx.putImageData(material, 0, 0);
}

/** Repeat the narrow roof tiles without a doubled outline at each atlas boundary. */
export function extendRoof(source: HTMLCanvasElement): HTMLCanvasElement {
  const canvas = document.createElement('canvas'), pixel = Number(source.dataset.pixelGrid);
  canvas.width = Math.round(768 / pixel); canvas.height = source.height;
  const ctx = canvas.getContext('2d')!; ctx.imageSmoothingEnabled = false;
  const joins: number[] = [];
  for (let x = 0; x < canvas.width; x += source.width) {
    ctx.drawImage(source, x, 0);
    if (x) joins.push(x);
  }
  bridgeCuts(canvas, joins, 4);
  return canvas;
}
