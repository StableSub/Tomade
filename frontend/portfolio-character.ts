import { OBJECT_PIXEL_SIZE, OBJECT_OUTLINE_PIXELS } from './pixel-style';

type Direction = 'front' | 'back' | 'left' | 'right';
type Frame = { x: number; y: number; width: number; height: number };
// This loop stays in the empty lower-right staff area, below desks and left of the partition.
const STOPS = [{ x: 356, y: 405 }, { x: 418, y: 405 }, { x: 418, y: 338 }, { x: 356, y: 338 }];
const SPEED = 38;
const ACCELERATION = 120;
const STRIDE = 28;

// Normalize the existing outer ink after the single atlas-to-display sample. Only
// the narrow silhouette band is touched; eyes, mouth, papers and interior colors stay intact.
function finishOutline(canvas: HTMLCanvasElement, thickness: number): void {
  const ctx = canvas.getContext('2d')!;
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const original = new Uint8ClampedArray(image.data);
  const { width, height } = canvas;
  const depth = new Int16Array(width * height).fill(-1);
  const queue: number[] = [];
  const opaque = (x: number, y: number) => x >= 0 && y >= 0 && x < width && y < height && original[(y * width + x) * 4 + 3] >= 128;
  const ink = (i: number) => Math.max(original[i], original[i + 1], original[i + 2]) < 140 && original[i] + original[i + 1] + original[i + 2] < 270;
  // Distance to transparent space, using the same square cells as the sprite.
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (!opaque(x, y)) { image.data[(y * width + x) * 4 + 3] = 0; continue; }
    image.data[(y * width + x) * 4 + 3] = 255;
    let boundary = false;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!opaque(x + dx, y + dy)) boundary = true;
    }
    if (boundary) { depth[y * width + x] = 0; queue.push(y * width + x); }
  }
  const band = thickness + Math.max(2, Math.ceil(width / 96 * 2));
  for (let head = 0; head < queue.length; head++) {
    const index = queue[head], x = index % width, y = Math.floor(index / width);
    if (depth[index] >= band) continue;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const next = (y + dy) * width + x + dx;
      if (!opaque(x + dx, y + dy) || depth[next] !== -1) continue;
      depth[next] = depth[index] + 1; queue.push(next);
    }
  }
  // Use circular distance for the stroke: a square erosion makes diagonal arcs
  // heavier than the flat crown. The half-cell allowance keeps pixel corners joined.
  const stroke = new Uint8Array(width * height);
  const radius = thickness + 1, limit = (thickness + .5) ** 2;
  for (const index of queue) {
    if (depth[index] > thickness) continue;
    const x = index % width, y = Math.floor(index / width);
    for (let dy = -radius; dy <= radius && !stroke[index]; dy++) {
      for (let dx = -radius; dx <= radius; dx++) {
        if (dx * dx + dy * dy <= limit && !opaque(x + dx, y + dy)) { stroke[index] = 1; break; }
      }
    }
  }
  for (const index of queue) {
    const i = index * 4, layer = depth[index];
    if (stroke[index]) { image.data.set([25, 23, 22, 255], i); continue; }
    if (!ink(i) || layer >= band) continue;
    // Replace a surplus original outline cell with the closest interior material,
    // instead of stacking another black stroke over an already uneven border.
    const x = index % width, y = Math.floor(index / width);
    let nearest = Infinity, donor = -1;
    for (let dy = -band; dy <= band; dy++) for (let dx = -band; dx <= band; dx++) {
      const candidate = (y + dy) * width + x + dx;
      if (!opaque(x + dx, y + dy) || stroke[candidate] || ink(candidate * 4)) continue;
      const distance = dx * dx + dy * dy;
      if (distance < nearest) { nearest = distance; donor = candidate * 4; }
    }
    if (donor >= 0) image.data.set(original.subarray(donor, donor + 3), i);
  }
  ctx.putImageData(image, 0, 0);
}

/** Animate the portfolio character independently of backend research workers.
 * Decode a local cyan-key atlas once and paint four walking frames with the same
 * staff pixel scale. Frames are sampled once at device resolution with a uniform
 * staff-weight outer contour; cached frames retain their artwork during walking. Missing artwork leaves the
 * labeled portfolio button usable. Hidden pages, reduced motion and selection pause movement.
 */
export class PortfolioCharacter {
  private readonly button: HTMLButtonElement;
  private readonly listeners = new AbortController();
  private readonly sizeObserver = new ResizeObserver(entries => this.resize(entries[0].contentRect.width));
  private readonly renderedFrames = new Map<string, HTMLCanvasElement>();
  private roomScale = 1;
  private dpr = window.devicePixelRatio;
  private atlas?: HTMLCanvasElement;
  private frames: Frame[][] = [];
  private referenceHeight = 1;
  private x = STOPS[0].x;
  private y = STOPS[0].y;
  private next = 1;
  private pause = 1.2;
  private distance = 0;
  private speed = 0;
  private direction: Direction = 'front';
  private walking = false;
  private selected = false;
  private hovered = false;
  private focused = false;
  private disposed = false;
  private reduced: boolean;
  private frameId = 0;
  private lastTime = 0;
  private signature = '';

  constructor(private readonly canvas: HTMLCanvasElement, private readonly motionPreference: MediaQueryList) {
    this.button = canvas.parentElement as HTMLButtonElement;
    this.reduced = motionPreference.matches;
    canvas.dataset.pixelWidth = "96"; canvas.dataset.pixelHeight = "96";
    canvas.dataset.spriteState = 'loading';
    canvas.dataset.pixelGrid = String(OBJECT_PIXEL_SIZE);
    const options = { signal: this.listeners.signal };
    this.button.addEventListener('pointerenter', () => { this.hovered = true; this.render(); }, options);
    this.button.addEventListener('pointerleave', () => { this.hovered = false; this.render(); }, options);
    this.button.addEventListener('focus', () => { this.focused = this.button.matches(':focus-visible'); this.render(); }, options);
    this.button.addEventListener('blur', () => { this.focused = false; this.render(); }, options);
    document.addEventListener('visibilitychange', this.onVisibility, options);
    motionPreference.addEventListener('change', this.onPreference, options);
    window.addEventListener('resize', this.onResize, options);
    this.sizeObserver.observe(this.button.parentElement!);
    this.onResize();
    this.render();
    void this.load().then(() => {
      if (this.disposed) return;
      this.render(); this.start();
    }).catch(() => {
      if (!this.disposed) {
        canvas.dataset.spriteState = 'error';
        this.button.title = '커비 이미지를 불러오지 못했습니다. 눌러서 포트폴리오를 확인할 수 있습니다.';
      }
    });
  }

  /** Pause while the portfolio panel is open; never initiate analysis from animation. */
  setPaused(paused: boolean): void { this.selected = paused; this.render(); }

  private get stopped(): boolean { return this.reduced || this.selected || this.hovered || this.focused; }

  private async load(): Promise<void> {
    const image = new Image();
    image.src = new URL('./assets/office-kirby-v2/walking-atlas.png', import.meta.url).href;
    await image.decode();
    if (this.disposed) return;
    const source = document.createElement('canvas');
    source.width = image.naturalWidth; source.height = image.naturalHeight;
    const ctx = source.getContext('2d', { willReadFrequently: true })!;
    ctx.drawImage(image, 0, 0);
    const pixels = ctx.getImageData(0, 0, source.width, source.height);
    for (let i = 0; i < pixels.data.length; i += 4) {
      const r = pixels.data[i], g = pixels.data[i + 1], b = pixels.data[i + 2];
      if (g - r > 50 && b - r > 50 && g > 90 && b > 90) pixels.data[i + 3] = 0;
    }
    ctx.putImageData(pixels, 0, 0);
    for (let row = 0; row < 3; row++) {
      const frames: Frame[] = [];
      for (let column = 0; column < 4; column++) {
        const x0 = Math.round(column * source.width / 4), x1 = Math.round((column + 1) * source.width / 4);
        const y0 = Math.round(row * source.height / 3), y1 = Math.round((row + 1) * source.height / 3);
        let left = x1, top = y1, right = -1, bottom = -1;
        for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
          if (!pixels.data[(y * source.width + x) * 4 + 3]) continue;
          left = Math.min(left, x); top = Math.min(top, y);
          right = Math.max(right, x); bottom = Math.max(bottom, y);
        }
        if (right < left) throw new Error('커비 걷기 자세를 찾지 못했습니다.');
        frames.push({ x: left, y: top, width: right - left + 1, height: bottom - top + 1 });
      }
      this.frames.push(frames);
    }
    // One scale across directions prevents a turn from stretching Kirby's round body.
    this.referenceHeight = Math.max(...this.frames.flat().map(frame => frame.height));
    this.atlas = source;
  }

  private advance(seconds: number): void {
    if (this.stopped) { this.speed = 0; return; }
    if (this.pause > 0) { this.pause -= seconds; return; }
    const target = STOPS[this.next], dx = target.x - this.x, dy = target.y - this.y;
    const remaining = Math.hypot(dx, dy);
    this.walking = true;
    this.direction = Math.abs(dx) > Math.abs(dy) ? dx > 0 ? 'right' : 'left' : dy > 0 ? 'front' : 'back';
    const speed = Math.min(SPEED, Math.sqrt(2 * ACCELERATION * remaining));
    this.speed += Math.max(-ACCELERATION * seconds, Math.min(ACCELERATION * seconds, speed - this.speed));
    const traveled = Math.min(remaining, this.speed * seconds);
    if (remaining <= traveled || remaining < .05) {
      this.x = target.x; this.y = target.y;
      this.next = (this.next + 1) % STOPS.length;
      this.walking = false; this.direction = 'front';
      this.distance = 0; this.speed = 0; this.pause = .85;
    } else {
      this.x += dx / remaining * traveled; this.y += dy / remaining * traveled;
      this.distance += traveled;
    }
  }

  private render(): void {
    const moving = this.walking && !this.stopped;
    const frame = moving ? Math.floor(this.distance / STRIDE * 4) % 4 : 0;
    // The walking position advances freely, while the painted feet land on device pixels.
    const unit = this.roomScale * this.dpr;
    this.button.style.left = `${Math.round(this.x * unit) / unit / 8}%`;
    this.button.style.top = `${Math.round(this.y * unit) / unit / 5}%`;
    this.button.style.zIndex = String(Math.round(this.y * 2));
    this.button.dataset.x = (this.x / 8).toFixed(3); this.button.dataset.y = (this.y / 5).toFixed(3);
    this.button.dataset.motion = moving ? 'walking' : 'idle';
    this.button.dataset.walkDistance = this.distance.toFixed(3);
    const direction = moving ? this.direction : 'front';
    const signature = `${direction}-${frame}`;
    this.canvas.dataset.spritePose = moving ? `walk-${direction}` : 'front';
    this.canvas.dataset.spriteFrame = String(frame);
    if (!this.atlas || signature === this.signature) return;
    this.signature = signature;
    if (!this.renderedFrames.has(signature)) {
      const source = this.frames[direction === 'back' ? 1 : direction === 'front' ? 0 : 2][frame];
      const display = document.createElement('canvas');
      display.width = this.canvas.width; display.height = this.canvas.height;
      const scale = (display.height * 88 / 96) / this.referenceHeight;
      const width = Math.round(source.width * scale), height = Math.round(source.height * scale);
      const ctx = display.getContext('2d')!;
      ctx.imageSmoothingEnabled = false;
      if (direction === 'left') { ctx.translate(display.width, 0); ctx.scale(-1, 1); }
      ctx.drawImage(this.atlas, source.x, source.y, source.width, source.height,
        Math.round((display.width - width) / 2), display.height - Math.round(display.height * 4 / 96) - height, width, height);
      finishOutline(display, Math.max(1, Math.round(OBJECT_OUTLINE_PIXELS * display.width / 96)));
      this.renderedFrames.set(signature, display);
    }
    const ctx = this.canvas.getContext('2d')!;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.drawImage(this.renderedFrames.get(signature)!, 0, 0);
    this.canvas.dataset.outlinePixels = String(Math.max(1, Math.round(OBJECT_OUTLINE_PIXELS * this.canvas.width / 96)));
    this.canvas.dataset.spriteState = 'ready';
  }

  private resize(roomWidth: number): void {
    if (this.disposed || roomWidth <= 0) return;
    this.roomScale = roomWidth / 800;
    this.dpr = window.devicePixelRatio;
    const pixels = Math.max(1, Math.round(roomWidth * .0648 * this.dpr));
    // CSS and backing store use the same physical pixels: the browser no longer
    // shrinks a 96px bitmap a second time at a fractional scale.
    this.canvas.style.width = `${pixels / this.dpr}px`;
    this.canvas.style.height = `${pixels / this.dpr}px`;
    if (this.canvas.width !== pixels || this.canvas.height !== pixels) {
      this.canvas.width = pixels; this.canvas.height = pixels;
      this.renderedFrames.clear(); this.signature = '';
    }
    this.render();
  }

  private readonly onResize = (): void => this.resize(parseFloat(getComputedStyle(this.button.parentElement!).width));

  private start(): void {
    if (this.disposed || !this.atlas || this.frameId || this.reduced || document.hidden) return;
    this.lastTime = 0; this.frameId = requestAnimationFrame(this.tick);
  }

  private readonly tick = (now: number): void => {
    this.frameId = 0;
    if (this.disposed || this.reduced || document.hidden) return;
    const seconds = this.lastTime ? Math.min(now - this.lastTime, 50) / 1000 : 0;
    this.lastTime = now;
    this.advance(seconds); this.render();
    this.frameId = requestAnimationFrame(this.tick);
  };

  private readonly onVisibility = (): void => {
    cancelAnimationFrame(this.frameId); this.frameId = 0; this.lastTime = 0;
    if (!document.hidden) this.start();
  };

  private readonly onPreference = (event: MediaQueryListEvent): void => {
    this.reduced = event.matches;
    cancelAnimationFrame(this.frameId); this.frameId = 0; this.speed = 0;
    this.render(); this.start();
  };

  /** Stop frame updates and listeners when leaving outside the back/forward cache. */
  dispose(): void {
    this.disposed = true; this.listeners.abort(); this.sizeObserver.disconnect();
    this.renderedFrames.clear();
    cancelAnimationFrame(this.frameId); this.frameId = 0;
  }
}
