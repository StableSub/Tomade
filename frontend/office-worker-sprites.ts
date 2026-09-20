import { createPixelSprite, OBJECT_PIXEL_SIZE } from './pixel-style';

export type StandingWorkerId = 'technical' | 'sentiment';
export type WorkerPose = 'idle' | 'research' | 'seated';

const SOURCES: Partial<Record<StandingWorkerId, string>> = {
  technical: new URL('./assets/office-workers-v1/patrick-atlas.png', import.meta.url).href,
  sentiment: new URL('./assets/office-workers-v1/spongebob-atlas.png', import.meta.url).href,
};
const atlases = new Map<StandingWorkerId, Promise<HTMLCanvasElement[]>>();
const shiftedFrames = new WeakMap<HTMLCanvasElement, HTMLCanvasElement>();

/** Paint worker frames at device resolution and retain a closed ink boundary.
 * The source already has the staff's two-native-pixel contour. The final pass
 * only repairs exposed physical edge pixels after fractional nearest sampling;
 * it does not thicken the existing interior contour or alter shared prop rendering.
 */
export class WorkerSpriteRenderer {
  private readonly sources = new Map<HTMLCanvasElement, HTMLCanvasElement>();
  private readonly observer = new ResizeObserver(entries => {
    for (const entry of entries) this.paint(entry.target as HTMLCanvasElement);
  });
  private readonly resize = () => {
    for (const canvas of this.sources.keys()) this.paint(canvas);
  };

  constructor() { window.addEventListener('resize', this.resize); }

  /** Observe an explicitly CSS-sized worker canvas and paint its cached native pose. */
  attach(canvas: HTMLCanvasElement, source: HTMLCanvasElement): void {
    this.sources.set(canvas, source);
    canvas.dataset.pixelWidth = String(source.width);
    canvas.dataset.pixelHeight = String(source.height);
    canvas.dataset.pixelGrid = source.dataset.pixelGrid;
    canvas.dataset.outlinePixels = source.dataset.outlinePixels;
    this.observer.observe(canvas);
    this.paint(canvas);
  }

  private paint(canvas: HTMLCanvasElement): void {
    const source = this.sources.get(canvas);
    if (!source) return;
    const style = getComputedStyle(canvas);
    const width = Math.round(parseFloat(style.width) * devicePixelRatio);
    const height = Math.round(parseFloat(style.height) * devicePixelRatio);
    if (!(width > 0 && height > 0)) return;
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(source, 0, 0, width, height);
    const pixels = ctx.getImageData(0, 0, width, height);
    const filled = (x: number, y: number) => x >= 0 && y >= 0 && x < width && y < height
      && pixels.data[(y * width + x) * 4 + 3] >= 128;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      if (!filled(x, y)) { pixels.data[offset + 3] = 0; continue; }
      pixels.data[offset + 3] = 255;
      if (!filled(x - 1, y) || !filled(x + 1, y) || !filled(x, y - 1) || !filled(x, y + 1)) {
        pixels.data.set([25, 23, 22, 255], offset);
      }
    }
    ctx.putImageData(pixels, 0, 0);
  }

  /** Stop resize observation and release owned frame references. */
  dispose(): void {
    this.observer.disconnect(); this.sources.clear();
    window.removeEventListener('resize', this.resize);
  }
}

/** Identify the two workers that have no assigned desk or walking route. */
export function isStandingWorker(id: string): id is StandingWorkerId {
  return id === 'technical' || id === 'sentiment';
}

/** Decode a worker's idle/research/seated-A/seated-B atlas without removing pink.
 * Generated alpha is thresholded during pixel normalization; a cyan fallback key
 * is accepted only for cyan pixels, preserving Patrick's pink and purple shorts.
 * Missing or invalid local images reject without substituting another character.
 */
export function loadWorkerSprites(id: StandingWorkerId): Promise<HTMLCanvasElement[]> {
  let result = atlases.get(id);
  if (result) return result;
  result = (async () => {
    const url = SOURCES[id];
    if (!url) throw new Error(`${id} 캐릭터 이미지가 아직 준비되지 않았습니다.`);
    const image = new Image();
    image.src = url;
    await image.decode();
    const crops: HTMLCanvasElement[] = [];
    for (let index = 0; index < 4; index++) {
      const cell = document.createElement('canvas');
      cell.width = Math.floor(image.naturalWidth / 2);
      cell.height = Math.floor(image.naturalHeight / 2);
      const ctx = cell.getContext('2d', { willReadFrequently: true })!;
      ctx.drawImage(image, (index % 2) * cell.width, Math.floor(index / 2) * cell.height,
        cell.width, cell.height, 0, 0, cell.width, cell.height);
      const pixels = ctx.getImageData(0, 0, cell.width, cell.height);
      let left = cell.width, top = cell.height, right = -1, bottom = -1;
      for (let y = 0; y < cell.height; y++) for (let x = 0; x < cell.width; x++) {
        const offset = (y * cell.width + x) * 4;
        const [r, g, b, a] = pixels.data.subarray(offset, offset + 4);
        if (a < 96 || (g > 220 && b > 220 && r < 40)) pixels.data[offset + 3] = 0;
        else {
          pixels.data[offset + 3] = 255;
          left = Math.min(left, x); top = Math.min(top, y);
          right = Math.max(right, x); bottom = Math.max(bottom, y);
        }
      }
      if (right < left) throw new Error(`${id} 캐릭터 자세가 비어 있습니다.`);
      const crop = document.createElement('canvas');
      crop.width = right - left + 1; crop.height = bottom - top + 1;
      crop.getContext('2d')!.putImageData(pixels, -left, -top);
      crops.push(crop);
    }
    // Same 128×160 native canvas and 152-pixel standing height as Pat and Mat.
    // One shared scale retains relative pose sizes and a two-pixel closed contour.
    const scale = Math.min(152 / crops[0].height, 120 / Math.max(...crops.map(crop => crop.width)));
    return crops.map(crop => {
      const normalized = createPixelSprite(crop, crop.width * scale * OBJECT_PIXEL_SIZE,
        crop.height * scale * OBJECT_PIXEL_SIZE, { preserveColors: true });
      const frame = document.createElement('canvas');
      frame.width = 128; frame.height = 160;
      frame.dataset.pixelGrid = String(OBJECT_PIXEL_SIZE);
      frame.dataset.outlinePixels = normalized.dataset.outlinePixels;
      frame.getContext('2d')!.drawImage(normalized, Math.round((128 - normalized.width) / 2),
        156 - normalized.height);
      return frame;
    });
  })();
  atlases.set(id, result);
  return result;
}

/** Select a generated pose; seated frames alternate hands, standing research gently bobs one native pixel. */
export function workerFrame(frames: HTMLCanvasElement[], pose: WorkerPose, frame: number): HTMLCanvasElement {
  if (pose !== 'research' || frame % 2 === 0) return frames[pose === 'idle' ? 0 : pose === 'research' ? 1 : 2 + frame % 2];
  const cached = shiftedFrames.get(frames[1]);
  if (cached) return cached;
  const shifted = document.createElement('canvas');
  shifted.width = 128; shifted.height = 160;
  shifted.dataset.pixelGrid = frames[1].dataset.pixelGrid;
  shifted.dataset.outlinePixels = frames[1].dataset.outlinePixels;
  shifted.getContext('2d')!.drawImage(frames[1], 0, -1);
  shiftedFrames.set(frames[1], shifted);
  return shifted;
}
