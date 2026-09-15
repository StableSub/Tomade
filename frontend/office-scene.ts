/** The four clickable characters shown in the research office. */
export type AgentId = 'upper_agent' | 'business' | 'macro_sector' | 'event_catalyst';

/** Research activity supplied by the app's existing run events. */
export type AgentActivity = 'idle' | 'working' | 'done' | 'error';

type Point = { x: number; y: number };
type Direction = 'front' | 'back' | 'left' | 'right';
type Motion = 'walking' | 'seated' | 'idle';
type Waypoint = Point & { edges: string[] };
type Character = {
  id: AgentId;
  button: HTMLButtonElement;
  canvas: HTMLCanvasElement;
  status: HTMLSpanElement;
  activity: AgentActivity;
  position: Point;
  node: string;
  edgeStart: string;
  path: string[];
  purpose: 'wander' | 'desk' | 'report';
  motion: Motion;
  direction: Direction;
  pause: number;
  cycle: number;
  speed: number;
  walkDistance: number;
};

const NAMES: Record<AgentId, string> = {
  upper_agent: '부장 Agent',
  business: '비즈니스',
  macro_sector: '매크로 / 섹터',
  event_catalyst: '이벤트 / 카탈리스트',
};

// Feet coordinates follow the 16:10 house. The only connection between rooms is the doorway.
const ROOM_ASPECT = 8 / 5;
const WAYPOINTS: Record<string, Waypoint> = {
  employeeTop: { x: 32, y: 34, edges: ['employeeCenter'] },
  employeeCenter: { x: 32, y: 55, edges: ['employeeTop', 'businessAisle', 'macroAisle', 'employeeLower'] },
  businessAisle: { x: 15.3, y: 55, edges: ['employeeCenter', 'businessDesk'] },
  businessDesk: { x: 15.3, y: 49, edges: ['businessAisle'] },
  macroAisle: { x: 42, y: 55, edges: ['employeeCenter', 'macroDesk', 'employeeRight'] },
  macroDesk: { x: 42, y: 49, edges: ['macroAisle'] },
  employeeRight: { x: 54.5, y: 55, edges: ['macroAisle', 'doorLeft'] },
  employeeLower: { x: 32, y: 80, edges: ['employeeCenter', 'employeeBottom'] },
  employeeBottom: { x: 32, y: 84, edges: ['employeeLower', 'eventAisle', 'entry'] },
  eventAisle: { x: 17.1, y: 84, edges: ['employeeBottom', 'eventDesk'] },
  eventDesk: { x: 17.1, y: 81, edges: ['eventAisle'] },
  entry: { x: 35.5, y: 84, edges: ['employeeBottom'] },
  doorLeft: { x: 54.5, y: 53, edges: ['employeeRight', 'doorway'] },
  doorway: { x: 60, y: 53, edges: ['doorLeft', 'managerEntry'] },
  managerEntry: { x: 65, y: 53, edges: ['doorway', 'managerSide', 'reportAisle'] },
  managerSide: { x: 65, y: 28, edges: ['managerEntry', 'managerBack'] },
  managerBack: { x: 78, y: 28, edges: ['managerSide', 'managerDesk'] },
  managerDesk: { x: 78, y: 34, edges: ['managerBack'] },
  reportAisle: { x: 65, y: 58, edges: ['managerEntry', 'reportLeft', 'managerLowerLeft'] },
  reportLeft: { x: 69, y: 58, edges: ['reportAisle', 'reportCenter'] },
  reportCenter: { x: 77, y: 58, edges: ['reportLeft', 'reportMacro', 'reportRight'] },
  reportMacro: { x: 77, y: 53, edges: ['reportCenter'] },
  reportRight: { x: 85, y: 58, edges: ['reportCenter'] },
  managerLowerLeft: { x: 65, y: 68, edges: ['reportAisle', 'managerLeft'] },
  managerLeft: { x: 68, y: 68, edges: ['managerLowerLeft', 'managerFront'] },
  managerFront: { x: 78, y: 68, edges: ['managerLeft'] },
};

const DESKS: Record<AgentId, string> = {
  upper_agent: 'managerDesk',
  business: 'businessDesk',
  macro_sector: 'macroDesk',
  event_catalyst: 'eventDesk',
};
const STARTS: Record<AgentId, string> = {
  upper_agent: 'managerFront',
  business: 'employeeCenter',
  macro_sector: 'employeeRight',
  event_catalyst: 'employeeLower',
};
const WANDER: Record<AgentId, string[]> = {
  upper_agent: ['managerLeft', 'managerEntry', 'managerFront'],
  business: ['businessAisle', 'employeeTop', 'employeeCenter', 'employeeLower'],
  macro_sector: ['employeeTop', 'employeeRight', 'employeeCenter'],
  event_catalyst: ['employeeCenter', 'employeeLower', 'entry', 'employeeLower'],
};

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, (a.y - b.y) / ROOM_ASPECT);
}

function route(from: string, to: string): string[] {
  if (from === to) return [];
  const pending = [from];
  const previous = new Map<string, string | null>([[from, null]]);
  for (let index = 0; index < pending.length; index += 1) {
    const current = pending[index];
    for (const next of WAYPOINTS[current].edges) {
      if (previous.has(next)) continue;
      previous.set(next, current);
      if (next === to) {
        const result = [to];
        let cursor = current;
        while (cursor !== from) {
          result.unshift(cursor);
          cursor = previous.get(cursor)!;
        }
        return result;
      }
      pending.push(next);
    }
  }
  return [];
}

type SpriteRect = { x: number; y: number; width: number; height: number };
type SpriteAtlas = { image: HTMLCanvasElement; frames: Record<AgentId, SpriteRect[]> };
type WalkDirection = Exclude<Direction, 'left'>;
const WALK_IMAGES: Record<WalkDirection, string> = {
  front: new URL('./assets/office-walk-front.png', import.meta.url).href,
  back: new URL('./assets/office-walk-back.png', import.meta.url).href,
  right: new URL('./assets/office-walk-right.png', import.meta.url).href,
};
const WALK_SPEED = 8.5;
const WALK_ACCELERATION = 22;
// One complete step cycle covers 5% of the room width, regardless of frame rate or direction.
const WALK_CYCLE_DISTANCE = 5;
let spriteAtlas: SpriteAtlas | null = null;
let spriteAtlasPromise: Promise<SpriteAtlas> | null = null;
const walkingAtlases: Partial<Record<WalkDirection, SpriteAtlas>> = {};
let walkingAtlasesPromise: Promise<void> | null = null;

// Each generated sheet has four character rows and four poses on a magenta backdrop.
async function decodeSpriteAtlas(url: string): Promise<SpriteAtlas> {
  const image = new Image();
  image.src = url;
  await image.decode();
  const layer = document.createElement('canvas');
  layer.width = image.naturalWidth;
  layer.height = image.naturalHeight;
  const ctx = layer.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('캐릭터 이미지를 표시할 수 없습니다.');
  ctx.drawImage(image, 0, 0);
  const pixels = ctx.getImageData(0, 0, layer.width, layer.height);
  for (let i = 0; i < pixels.data.length; i += 4) {
    const r = pixels.data[i], g = pixels.data[i + 1], b = pixels.data[i + 2];
    if (r - g > 32 && b - g > 32) pixels.data[i + 3] = 0;
  }
  ctx.putImageData(pixels, 0, 0);
  const frames = {} as SpriteAtlas['frames'];
  (Object.keys(NAMES) as AgentId[]).forEach((id, row) => {
    frames[id] = [];
    for (let column = 0; column < 4; column++) {
      const left = Math.round(column * layer.width / 4);
      const top = Math.round(row * layer.height / 4);
      const right = Math.round((column + 1) * layer.width / 4);
      const bottom = Math.round((row + 1) * layer.height / 4);
      let x0 = right, y0 = bottom, x1 = left, y1 = top;
      for (let y = top; y < bottom; y++) {
        for (let x = left; x < right; x++) {
          if (pixels.data[(y * layer.width + x) * 4 + 3] === 0) continue;
          x0 = Math.min(x0, x); y0 = Math.min(y0, y);
          x1 = Math.max(x1, x); y1 = Math.max(y1, y);
        }
      }
      if (x0 > x1 || y0 > y1) throw new Error('캐릭터 자세 이미지를 찾지 못했습니다.');
      frames[id].push({ x: x0, y: y0, width: x1 - x0 + 1, height: y1 - y0 + 1 });
    }
  });
  return { image: layer, frames };
}

function loadSpriteAtlas(): Promise<SpriteAtlas> {
  spriteAtlasPromise ??= decodeSpriteAtlas(new URL('./assets/office-characters.png', import.meta.url).href)
    .then(atlas => (spriteAtlas = atlas));
  return spriteAtlasPromise;
}

function loadWalkingAtlases(): Promise<void> {
  walkingAtlasesPromise ??= Promise.all((Object.keys(WALK_IMAGES) as WalkDirection[]).map(async direction => {
    walkingAtlases[direction] = await decodeSpriteAtlas(WALK_IMAGES[direction]);
  })).then(() => undefined);
  return walkingAtlasesPromise;
}

function drawCharacter(
  canvas: HTMLCanvasElement,
  id: AgentId,
  direction: Direction,
  frame: number,
  motion: Motion,
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx || !spriteAtlas) return;
  const seated = motion === 'seated';
  const walking = motion === 'walking';
  const walkDirection = direction === 'left' ? 'right' : direction;
  const atlas = walking ? walkingAtlases[walkDirection] : spriteAtlas;
  if (!atlas) return;
  const { image, frames } = atlas;
  const column = seated ? 3 : direction === 'back' ? 1 : direction === 'front' ? 0 : 2;
  const source = frames[id][walking ? frame : column];
  // A shared scale per walking row preserves the original drawing's weight shift and head size.
  const referenceHeight = walking ? Math.max(...frames[id].map(pose => pose.height)) : frames[id][0].height;
  const scale = (canvas.height - 8) / referenceHeight;
  const width = source.width * scale;
  const height = source.height * scale;
  const x = (canvas.width - width) / 2;
  const y = canvas.height - 4 - height;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.imageSmoothingEnabled = false;
  ctx.save();
  if (!seated && direction === 'left') { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
  if (seated) ctx.translate(0, -(frame % 2));
  ctx.drawImage(image, source.x, source.y, source.width, source.height, x, y, width, height);
  ctx.restore();
  canvas.dataset.spriteState = 'ready';
  canvas.dataset.spritePose = walking ? `walk-${direction}` : ['front', 'back', 'right', 'seated'][column];
  canvas.dataset.spriteFrame = String(frame);
}

/** Paint the selected reference character's portrait; a missing local asset is labeled on the canvas. */
export function paintPortrait(canvas: HTMLCanvasElement, id: AgentId): void {
  canvas.width = 192;
  canvas.height = 192;
  canvas.dataset.spriteState = 'loading';
  void loadSpriteAtlas().then(({ image, frames }) => {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const face = frames[id][0];
    const crop = Math.max(face.width, face.height * (id === 'upper_agent' ? 0.76 : 0.49));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(image, face.x + (face.width - crop) / 2, face.y, crop, crop,
      0, 0, canvas.width, canvas.height);
    canvas.dataset.spriteState = 'ready';
  }).catch(() => {
    canvas.dataset.spriteState = 'error';
    canvas.setAttribute('aria-label', `${NAMES[id]} 초상화를 불러오지 못했습니다.`);
  });
}

/** Animate accessible office characters; only supplied activities describe real work. */
export class OfficeScene {
  private readonly characters = new Map<AgentId, Character>();
  private readonly clicks = new AbortController();
  private frameId = 0;
  private lastTime = 0;
  private elapsed = 0;
  private disposed = false;
  // Keep animation frames on the last preference event instead of polling the media query.
  private motionReduced: boolean;

  /** Add clickable characters and share the app's motion preference for both room and sprite transitions. */
  constructor(
    container: HTMLElement,
    onSelect: (id: AgentId, trigger: HTMLButtonElement) => void,
    private readonly reducedMotion: MediaQueryList,
  ) {
    this.motionReduced = reducedMotion.matches;
    (Object.keys(NAMES) as AgentId[]).forEach((id, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'office-agent';
      button.dataset.agent = id;
      button.setAttribute('aria-pressed', 'false');
      const canvas = document.createElement('canvas');
      canvas.className = 'agent-sprite';
      canvas.width = 128;
      canvas.height = 160;
      canvas.dataset.spriteState = 'loading';
      canvas.setAttribute('aria-hidden', 'true');
      const name = document.createElement('span');
      name.className = 'agent-name';
      name.textContent = NAMES[id];
      const status = document.createElement('span');
      status.className = 'agent-status';
      status.setAttribute('aria-hidden', 'true');
      button.append(canvas, name, status);
      if (id === 'upper_agent') {
        const talk = document.createElement('span');
        talk.className = 'agent-talk';
        talk.textContent = '대화하기';
        talk.setAttribute('aria-hidden', 'true');
        button.append(talk);
      }
      button.addEventListener('click', () => onSelect(id, button), { signal: this.clicks.signal });
      container.append(button);
      const start = STARTS[id];
      const character: Character = {
        id, button, canvas, status, activity: 'idle',
        position: { x: WAYPOINTS[start].x, y: WAYPOINTS[start].y },
        node: start, edgeStart: start, path: [], purpose: 'wander',
        motion: 'idle', direction: 'front', pause: 0.8 + index * 0.65,
        cycle: 0, speed: 0, walkDistance: 0,
      };
      this.characters.set(id, character);
      this.render(character, true);
    });
    void Promise.all([loadSpriteAtlas(), loadWalkingAtlases()]).then(() => {
      if (this.disposed) return;
      for (const character of this.characters.values()) this.render(character, true);
    }).catch(() => {
      if (this.disposed) return;
      for (const character of this.characters.values()) {
        character.canvas.dataset.spriteState = 'error';
        character.button.classList.add('sprite-unavailable');
        character.button.title = '캐릭터 이미지를 불러오지 못했습니다. 눌러서 대화와 조사 내용을 확인할 수 있습니다.';
      }
    });
    this.reducedMotion.addEventListener('change', this.onMotionPreference);
    document.addEventListener('visibilitychange', this.onVisibility);
    this.start();
  }

  /** Route a character to work or report; repeated identical events preserve its current path. */
  setActivity(id: AgentId, activity: AgentActivity): void {
    const character = this.characters.get(id);
    if (!character || character.activity === activity || this.disposed) return;
    character.activity = activity;
    character.pause = 0;
    if (activity === 'working') {
      this.go(character, DESKS[id], 'desk');
    } else if (activity === 'done') {
      const destination = id === 'upper_agent' ? 'managerFront'
        : id === 'event_catalyst' ? 'reportRight'
          : id === 'macro_sector' ? 'reportMacro' : 'reportLeft';
      this.go(character, destination, 'report');
    } else {
      character.purpose = 'wander';
      this.go(character, WANDER[id][character.cycle++ % WANDER[id].length], 'wander');
    }
    this.render(character, true);
    this.start();
  }

  /** Clear the prior run's activity while allowing characters to return through the aisles. */
  reset(): void {
    for (const id of this.characters.keys()) this.setActivity(id, 'idle');
    this.setSelected(null);
  }

  /** Expose selection for the visual focus ring and assistive technology. */
  setSelected(id: AgentId | null): void {
    for (const character of this.characters.values()) {
      const selected = character.id === id;
      character.button.dataset.selected = String(selected);
      character.button.setAttribute('aria-pressed', String(selected));
    }
  }

  /** Remove owned elements and stop animation and preference/visibility listeners. */
  dispose(): void {
    this.disposed = true;
    this.clicks.abort();
    cancelAnimationFrame(this.frameId);
    this.frameId = 0;
    this.reducedMotion.removeEventListener('change', this.onMotionPreference);
    document.removeEventListener('visibilitychange', this.onVisibility);
    for (const character of this.characters.values()) character.button.remove();
    this.characters.clear();
  }

  private go(character: Character, destination: string, purpose: Character['purpose']): void {
    character.purpose = purpose;
    if (character.motion !== 'walking') {
      character.speed = 0;
      character.walkDistance = 0;
    }
    character.motion = 'idle';
    if (this.motionReduced) {
      character.node = destination;
      character.edgeStart = destination;
      character.position = { x: WAYPOINTS[destination].x, y: WAYPOINTS[destination].y };
      character.path = [];
      this.arrive(character);
      return;
    }
    // A new event midway down an aisle starts from an endpoint of that same edge.
    const next = character.path[0];
    let anchor = character.node;
    if (next) {
      anchor = distance(character.position, WAYPOINTS[character.edgeStart]) <= distance(character.position, WAYPOINTS[next])
        ? character.edgeStart : next;
    }
    character.path = distance(character.position, WAYPOINTS[anchor]) > 0.02 ? [anchor] : [];
    character.path.push(...route(anchor, destination));
    if (character.path.length) character.motion = 'walking';
    else this.arrive(character);
  }

  private arrive(character: Character): void {
    character.edgeStart = character.node;
    character.speed = 0;
    character.walkDistance = 0;
    if (character.purpose === 'desk') {
      character.motion = 'seated';
      character.direction = character.id === 'upper_agent' ? 'front' : 'back';
      character.pause = Infinity;
    } else if (character.purpose === 'report') {
      character.motion = 'idle';
      character.direction = character.id === 'upper_agent' ? 'front' : 'back';
      character.pause = character.id === 'upper_agent' ? Infinity : 4.5;
    } else {
      character.motion = 'idle';
      character.direction = 'front';
      character.pause = 1.2 + (character.cycle % 4) * 0.55;
    }
  }

  private advance(character: Character, seconds: number): void {
    if (!character.path.length) {
      character.pause -= seconds;
      if (character.pause <= 0 && character.purpose !== 'desk') {
        const destinations = WANDER[character.id];
        this.go(character, destinations[character.cycle++ % destinations.length], 'wander');
      }
      return;
    }
    let previous = character.position;
    let remainingPath = 0;
    for (const node of character.path) {
      remainingPath += distance(previous, WAYPOINTS[node]);
      previous = WAYPOINTS[node];
    }
    const targetSpeed = Math.min(WALK_SPEED, Math.sqrt(2 * WALK_ACCELERATION * remainingPath));
    const speedChange = WALK_ACCELERATION * seconds;
    character.speed += Math.max(-speedChange, Math.min(speedChange, targetSpeed - character.speed));
    let stride = character.speed * seconds;
    while (character.path.length && stride > 0) {
      const target = WAYPOINTS[character.path[0]];
      const dx = target.x - character.position.x;
      const dy = target.y - character.position.y;
      const remaining = distance(character.position, target);
      if (remaining > 0) {
        character.direction = Math.abs(dx) > Math.abs(dy) / ROOM_ASPECT
          ? dx > 0 ? 'right' : 'left'
          : dy > 0 ? 'front' : 'back';
      }
      const traveled = Math.min(stride, remaining);
      character.walkDistance += traveled;
      stride -= traveled;
      if (remaining <= traveled) {
        character.position = { x: target.x, y: target.y };
        character.node = character.path.shift()!;
        character.edgeStart = character.node;
        if (!character.path.length) this.arrive(character);
      } else {
        character.position.x += dx * traveled / remaining;
        character.position.y += dy * traveled / remaining;
      }
    }
  }

  private render(character: Character, force = false): void {
    const { button, activity, motion, id } = character;
    button.style.left = `${character.position.x.toFixed(3)}%`;
    button.style.top = `${character.position.y.toFixed(3)}%`;
    button.style.zIndex = String(Math.round(character.position.y * 10));
    button.dataset.x = character.position.x.toFixed(3);
    button.dataset.y = character.position.y.toFixed(3);
    button.dataset.activity = activity;
    button.dataset.motion = motion;
    button.dataset.purpose = character.purpose;
    button.dataset.walkDistance = character.walkDistance.toFixed(4);
    const label = activity === 'working'
      ? motion === 'seated' ? id === 'upper_agent' ? '생각 중' : '조사 중' : '자리로 이동'
      : activity === 'done'
        ? id === 'upper_agent' ? '답변 도착' : character.purpose === 'report' && motion === 'walking' ? '보고하러 이동' : '보고 완료'
        : activity === 'error' ? '조사 중단' : motion === 'walking' ? '산책 중' : '대기 중';
    if (character.status.textContent !== label) {
      character.status.textContent = label;
      button.setAttribute('aria-label', `${NAMES[id]} · ${label} · 클릭하여 대화 또는 조사 내용 보기`);
    }
    const frame = this.motionReduced || motion === 'idle' ? 0
      : motion === 'walking' ? Math.floor(character.walkDistance / WALK_CYCLE_DISTANCE * 4) % 4
        : Math.floor(this.elapsed / 340) % 4;
    const signature = `${character.direction}-${motion}-${frame}`;
    if (force || button.dataset.frame !== signature) {
      button.dataset.frame = signature;
      drawCharacter(character.canvas, id, character.direction, frame, motion);
    }
  }

  private start(): void {
    if (this.disposed || this.frameId || document.hidden || this.motionReduced) return;
    this.lastTime = 0;
    this.frameId = requestAnimationFrame(this.tick);
  }

  private readonly tick = (now: number): void => {
    this.frameId = 0;
    if (this.disposed || document.hidden || this.motionReduced) return;
    const delta = this.lastTime ? Math.min(now - this.lastTime, 50) : 0;
    this.lastTime = now;
    this.elapsed += delta;
    for (const character of this.characters.values()) {
      this.advance(character, delta / 1000);
      this.render(character);
    }
    this.frameId = requestAnimationFrame(this.tick);
  };

  private readonly onVisibility = (): void => {
    cancelAnimationFrame(this.frameId);
    this.frameId = 0;
    this.lastTime = 0;
    if (!document.hidden) this.start();
  };

  private readonly onMotionPreference = (event: MediaQueryListEvent): void => {
    this.motionReduced = event.matches;
    cancelAnimationFrame(this.frameId);
    this.frameId = 0;
    if (this.motionReduced) {
      for (const character of this.characters.values()) {
        if (character.path.length) {
          if (character.purpose !== 'wander') {
            this.go(character, character.path[character.path.length - 1], character.purpose);
          } else {
            character.path = [];
            character.motion = 'idle';
            character.speed = 0;
            character.walkDistance = 0;
          }
        }
        this.render(character, true);
      }
    } else {
      for (const character of this.characters.values()) {
        if (character.purpose === 'wander') character.pause = 0.6;
      }
      this.start();
    }
  };
}
