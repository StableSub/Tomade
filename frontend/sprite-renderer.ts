/** Normalized atlas bounds [left, top, right, bottom] before color-key cropping. */
export type SpriteFrame = readonly [number, number, number, number];

/** Decode a local sprite (or atlas frame) and remove its color-key padding.
 * The returned canvas is an in-memory source; the asset file is never modified.
 * Image loading failures and empty keyed sprites reject the promise.
 */
export async function loadSpriteSource(url: string, opaque = false, frame: SpriteFrame = [0, 0, 1, 1]): Promise<HTMLCanvasElement> {
  const image = new Image();
  image.src = url;
  await image.decode();
  const source = document.createElement('canvas');
  const leftPixel = Math.round(frame[0] * image.naturalWidth), topPixel = Math.round(frame[1] * image.naturalHeight);
  source.width = Math.round(frame[2] * image.naturalWidth) - leftPixel;
  source.height = Math.round(frame[3] * image.naturalHeight) - topPixel;
  const ctx = source.getContext('2d', { willReadFrequently: true })!;
  ctx.drawImage(image, leftPixel, topPixel, source.width, source.height, 0, 0, source.width, source.height);
  if (opaque) return source;

  const pixels = ctx.getImageData(0, 0, source.width, source.height);
  let left = source.width, top = source.height, right = -1, bottom = -1;
  for (let y = 0; y < source.height; y++) for (let x = 0; x < source.width; x++) {
    const i = (y * source.width + x) * 4;
    const r = pixels.data[i], g = pixels.data[i + 1], b = pixels.data[i + 2];
    if (r - g > 12 && b - g > 12 && b > r * .6) pixels.data[i + 3] = 0;
    else if (pixels.data[i + 3]) {
      left = Math.min(left, x); top = Math.min(top, y);
      right = Math.max(right, x); bottom = Math.max(bottom, y);
    }
  }
  if (right < left) throw new Error(`오브젝트가 비어 있습니다: ${url}`);
  const crop = document.createElement('canvas');
  crop.width = right - left + 1; crop.height = bottom - top + 1;
  crop.getContext('2d')!.putImageData(pixels, -left, -top);
  return crop;
}

/** Paint source sprites into the display's device pixels, preserving a fixed pixel-art grid.
 * Observe CSS size/DPR changes without sampling a previous display bitmap again.
 * Call release() for replaced previews and dispose() when the owning page unloads.
 */
export class SpriteRenderer {
  private readonly sources = new Map<HTMLCanvasElement, HTMLCanvasElement>();
  private readonly observer = new ResizeObserver(entries => {
    for (const entry of entries) {
      const canvas = entry.target as HTMLCanvasElement;
      this.paint(canvas, entry.contentRect.width, entry.contentRect.height);
    }
  });
  private readonly resize = () => {
    for (const canvas of this.sources.keys()) this.refresh(canvas);
  };

  constructor() { window.addEventListener('resize', this.resize); }

  /** Attach a canvas with an explicit CSS size to a decoded full-resolution source. */
  attach(canvas: HTMLCanvasElement, source: HTMLCanvasElement): void {
    this.sources.set(canvas, source);
    delete canvas.dataset.sampled;
    if (source.dataset.pixelGrid) {
      canvas.dataset.pixelWidth = String(source.width); canvas.dataset.pixelHeight = String(source.height);
      canvas.dataset.pixelGrid = source.dataset.pixelGrid;
      canvas.dataset.outlinePixels = source.dataset.outlinePixels ?? '0';
    }
    this.observer.observe(canvas);
    this.refresh(canvas);
  }

  private refresh(canvas: HTMLCanvasElement): void {
    // Computed dimensions exclude the office's animated transform to the minimap.
    const style = getComputedStyle(canvas);
    this.paint(canvas, parseFloat(style.width), parseFloat(style.height));
  }

  private paint(canvas: HTMLCanvasElement, cssWidth: number, cssHeight: number): void {
    const source = this.sources.get(canvas);
    if (!source || !(cssWidth > 0 && cssHeight > 0)) return;
    const width = Math.max(1, Math.round(cssWidth * window.devicePixelRatio));
    const height = Math.max(1, Math.round(cssHeight * window.devicePixelRatio));
    if (canvas.width === width && canvas.height === height && canvas.dataset.sampled === 'true') return;
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d')!;
    // Fixed game sprites retain their palette/grid; unnormalized image sources use
    // coverage-aware downsampling. Neither branch samples a previous display bitmap.
    ctx.imageSmoothingEnabled = !source.dataset.pixelGrid && (width < source.width || height < source.height);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(source, 0, 0, width, height);
    canvas.dataset.sampled = 'true';
  }

  /** Stop observing a preview before it is replaced or removed. */
  release(canvas: HTMLCanvasElement): void {
    this.observer.unobserve(canvas);
    this.sources.delete(canvas);
  }

  /** Release all size observers and the DPR/viewport listener. */
  dispose(): void {
    this.observer.disconnect(); this.sources.clear();
    window.removeEventListener('resize', this.resize);
  }
}
