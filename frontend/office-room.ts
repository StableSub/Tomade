import { createRoomFloor, finishTimber, createFrontSection, extendRoof, matchFrameTimber } from './office-architecture';
import type { AgentId } from './office-scene';
import { loadSpriteSource, SpriteRenderer } from './sprite-renderer';
import { createPixelSprite, fitPixelFrame } from './pixel-style';

/** Percent-based feet positions shared by the furniture and character routes. */
export const OFFICE_SEATS: Record<AgentId, { x: number; y: number }> = {
  upper_agent: { x: 78, y: 34 },
  business: { x: 15.3, y: 49 },
  macro_sector: { x: 42, y: 49 },
  event_catalyst: { x: 17.1, y: 81 },
};

const GARDEN_ATLAS = new URL('./assets/office-courtyard-v2/garden-atlas.png', import.meta.url).href;

const SHELL_ATLAS = new URL('./assets/office-shell-v1/shell-atlas.png', import.meta.url).href;

const ASSETS = {
  parquet: { url: new URL('./assets/office-environment-v1/floor-parquet.svg', import.meta.url).href, width: 96, opaque: true },
  checker: { url: new URL('./assets/office-environment-v1/floor-checker.svg', import.meta.url).href, width: 96, opaque: true },
  wall: { url: new URL('./assets/office-objects-v4/structure-atlas.png', import.meta.url).href, frame: [0.55,0.77,0.95,0.95], width: 160, opaque: true },
  beamH: { url: SHELL_ATLAS, frame: [0, 0, .5, 1/3], width: 192, opaque: false },
  beamV: { url: SHELL_ATLAS, frame: [.5, 0, 1, 1/3], width: 16, opaque: false },
  partition: { url: SHELL_ATLAS, frame: [.5, 0, 1, 1/3], width: 20, opaque: false },
  entrance: { url: new URL('./assets/office-shell-v1/entrance-v2.png', import.meta.url).href, width: 264, opaque: false },
  managerFront: { url: new URL('./assets/office-shell-v1/entrance-v2.png', import.meta.url).href, width: 282, opaque: false },
  foundation: { url: SHELL_ATLAS, frame: [0, 1/3, .5, 2/3], width: 96, opaque: false },
  stoneFoot: { url: SHELL_ATLAS, frame: [.032, .471, .105, .525], width: 24, opaque: false },
  passageWood: { url: SHELL_ATLAS, frame: [.735, .07, .756, .31], width: 20, opaque: true },
  eave: { url: SHELL_ATLAS, frame: [.5, 1/3, 1, 2/3], width: 192, opaque: false },
  workerDesk: { url: new URL('./assets/office-objects-v3/worker-desk-trial.png', import.meta.url).href, width: 200, opaque: false },
  trialDesk: { url: new URL('./assets/office-objects-v3/worker-desk-trial.png', import.meta.url).href, width: 138, opaque: false },
  managerDesk: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0,0,0.36,0.3333333333333333], width: 216, opaque: false },
  blueChair: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.4,0,0.63,0.3333333333333333], width: 76, opaque: false },
  greenChair: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.7,0,1,0.3333333333333333], width: 76, opaque: false },
  managerChair: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0,0.3333333333333333,0.3333333333333333,0.6666666666666666], width: 86, opaque: false },
  businessMonitor: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0,0,0.3333333333333333,0.3333333333333333], width: 86, opaque: false },
  macroMonitor: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0.3333333333333333,0,0.6666666666666666,0.3333333333333333], width: 86, opaque: false },
  eventMonitor: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0.6666666666666666,0,1,0.3333333333333333], width: 86, opaque: false },
  backMonitor: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0,0.3333333333333333,0.3333333333333333,0.6666666666666666], width: 86, opaque: false },
  window: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0,0.6666666666666666,0.3333333333333333,1], width: 150, opaque: false },
  stove: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.3333333333333333,0.63,0.6666666666666666,1], width: 105, opaque: false },
  sofa: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.3333333333333333,0.3333333333333333,0.6666666666666666,0.63], width: 170, opaque: false },
  rug: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.6666666666666666,0.6666666666666666,1,1], width: 180, opaque: false },
  tools: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0,0.6666666666666666,0.3333333333333333,1], width: 110, opaque: false },
  shelf: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0.6666666666666666,0.3333333333333333,1,0.6666666666666666], width: 122, opaque: false },
  cabinet: { url: new URL('./assets/office-objects-v4/furniture-atlas.png', import.meta.url).href, frame: [0.6666666666666666,0.3333333333333333,1,0.6666666666666666], width: 86, opaque: false },
  tomato: { url: new URL('./assets/office-objects-v4/structure-atlas.png', import.meta.url).href, frame: [0,0,0.5,0.25], width: 48, opaque: false },
  plant: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0.6666666666666666,0.6666666666666666,1,1], width: 44, opaque: false },
  picture: { url: new URL('./assets/office-objects-v4/details-atlas.png', import.meta.url).href, frame: [0.3333333333333333,0.6666666666666666,0.6666666666666666,1], width: 82, opaque: false },
  mug: { url: new URL('./assets/office-objects-v4/structure-atlas.png', import.meta.url).href, frame: [0.5,0,1,0.25], width: 38, opaque: false },
  gardenTree: { url: GARDEN_ATLAS, frame: [0, 0, 1/3, 1/3], width: 80, opaque: false },
  shrub: { url: GARDEN_ATLAS, frame: [1/3, 0, 2/3, 1/3], width: 46, opaque: false },
  tomatoPlanter: { url: GARDEN_ATLAS, frame: [2/3, 0, 1, 1/3], width: 38, opaque: false },
  gardenBench: { url: GARDEN_ATLAS, frame: [0, 1/3, 1/3, 2/3], width: 90, opaque: false },
  // The watering can extends past the nominal cell: keep it with the full bed.
  tomatoBed: { url: GARDEN_ATLAS, frame: [1/3, 1/3, .725, 2/3], width: 174, opaque: false },
  steppingStone: { url: GARDEN_ATLAS, frame: [.735, 1/3, 1, 2/3], width: 62, opaque: false },
  gardenRocks: { url: GARDEN_ATLAS, frame: [0, 2/3, 1/3, 1], width: 30, opaque: false },
  grass: { url: GARDEN_ATLAS, frame: [1/3, 2/3, 2/3, 1], width: 14, opaque: false },
  flowers: { url: GARDEN_ATLAS, frame: [2/3, 2/3, 1, 1], width: 14, opaque: false },
} as const;
type AssetId = keyof typeof ASSETS;
type Placement = {
  asset: AssetId;
  x: number; y: number; width: number; height: number; depth: number;
  repeat?: boolean;
  courtyard?: boolean;
};
// All furniture uses an 800x500 room coordinate system. Depth equals feet Y * 2,
// matching office-scene's percent-Y * 10, so independent furniture can occlude actors.
function placements(): Placement[] {
  const parts: Placement[] = [];
  const add = (asset: AssetId, x: number, y: number, width: number, height: number, depth = 1, repeat = false) =>
    parts.push({ asset, x, y, width, height, depth, repeat });
  add('parquet', 32, 136, 436, 302, 0, true);
  // The opening is fully covered; patterns stop exactly at the timber faces.
  add('passageWood', 468, 238, 20, 52, 0);
  add('checker', 488, 170, 280, 268, 0, true);
  add('wall', 32, 30, 436, 106);
  add('wall', 488, 30, 280, 140);
  add('eave', 16, 9, 768, 6, 1);
  add('partition', 468, 14, 20, 224, 475);
  add('partition', 468, 290, 20, 160, 966);
  add('beamH', 16, 14, 768, 16);
  add('beamV', 16, 14, 16, 436, 966);
  add('beamV', 768, 14, 16, 436, 966);
  for (const [x, width] of [[12, 24], [464, 28], [764, 24]]) add('stoneFoot', x, 448, width, 22, 965);
  add('parquet', 252, 438, 68, 8, 0, true);
  // Two independent room fronts terminate behind the three columns.
  add('entrance', 31, 438, 438, 44, 963);
  add('managerFront', 487, 438, 282, 32, 963);

  // The house keeps its 800x500 coordinates; its courtyard extends below the entrance.
  const garden = (asset: AssetId, x: number, y: number, width: number, height: number) =>
    parts.push({ asset, x, y, width, height, depth: 4, courtyard: true });
  for (let i = 0; i < 5; i++) garden('steppingStone', 255, 486 + i * 26, 62, 20);
  garden('tomatoPlanter', 194, 484, 38, 50);
  garden('tomatoPlanter', 340, 484, 38, 50);
  garden('gardenTree', 12, -66, 80, 78);
  garden('gardenTree', 704, -66, 80, 78);
  garden('gardenTree', 688, 512, 82, 92);
  garden('shrub', 92, -28, 55, 36);
  garden('shrub', 656, -20, 40, 28);
  garden('shrub', 515, 572, 45, 36);
  garden('shrub', 658, 574, 45, 36);
  garden('gardenBench', 568, 550, 90, 65);
  garden('tomatoBed', 12, 528, 174, 92);
  for (const [x,y,w,h] of [[752,-12,26,20],[470,606,26,20],[774,509,20,16]]) garden('gardenRocks', x,y,w,h);
  for (const [x,y] of [[82,490],[449,540],[748,610],[15,610],[204,579],[582,-28]]) garden('flowers', x,y,14,18);
  for (const [x,y] of [[174,-36],[254,-53],[360,-20],[449,-45],[540,-16],[618,-51],
    [0,82],[2,203],[0,349],[0,442],[786,112],[786,264],[786,400],
    [50,486],[130,499],[408,490],[497,480],[558,509],[641,493],[768,480],
    [201,536],[394,550],[474,572],[27,512],[714,617],[392,610],[208,618],[96,623],[552,622]]) garden('grass', x,y,14,7);

  add('window', 128, 64, 88, 58, 10);
  add('window', 294, 64, 88, 58, 10);
  add('window', 578, 64, 88, 58, 10);
  add('tools', 230, 80, 62, 48, 10);
  add('shelf', 393, 63, 66, 46, 10);
  add('stove', 34, 72, 56, 115, 374);
  add('picture', 704, 67, 48, 38, 10);
  add('cabinet', 721, 114, 44, 82, 392);
  add('cabinet', 34, 350, 40, 82, 864);
  // The cabinet top begins at y=350; sink the cup base into that top plane.
  add('mug', 45, 335, 18, 20, 865);
  add('rug', 548, 275, 146, 90, 1);
  add('sofa', 653, 366, 106, 68, 868);
  add('plant', 635, 96, 22, 26, 11);
  add('tomato', 48, 40, 22, 24, 11);

  for (const agent of ['business', 'macro_sector', 'event_catalyst'] as AgentId[]) {
    const feet = OFFICE_SEATS[agent], x = feet.x * 8, y = feet.y * 5;
    add(agent === 'business' ? 'trialDesk' : 'workerDesk', x - 46, y - 95, 138, 72, (y - 23) * 2);
    add(agent === 'macro_sector' ? 'greenChair' : 'blueChair', x - 20, y - 52, 40, 52, y * 2 + 1);
    add(agent === 'business' ? 'businessMonitor' : agent === 'macro_sector' ? 'macroMonitor' : 'eventMonitor',
      x - 24, y - 117, 48, 40, (y - 23) * 2 + 1);

  }
  const boss = OFFICE_SEATS.upper_agent, x = boss.x * 8, y = boss.y * 5;
  add('managerChair', x - 22, y - 57, 44, 62, y * 2 - 10);
  add('managerDesk', x - 78, y - 26, 148, 76, (y + 50) * 2);
  add('backMonitor', x - 28, y - 32, 48, 38, (y + 50) * 2 + 1);
  return parts.map(part => ({ ...part, x: Math.round(part.x), y: Math.round(part.y) }));
}

// Contact patches belong to their receiving surface, not the object's outline.
// Furniture casts onto the floor; small props cast above their supporting furniture.
function contactShadows(part: Placement): HTMLElement[] {
  const shadows: HTMLElement[] = [];
  const patch = (x: number, y: number, width: number, height: number, opacity: number, surface = false) => {
    const shadow = document.createElement('div');
    shadow.className = 'office-contact-shadow';
    shadow.dataset.shadowFor = part.asset;
    shadow.dataset.shadowSurface = surface ? 'furniture' : 'floor';
    if (part.courtyard) shadow.dataset.courtyard = 'true';
    shadow.setAttribute('aria-hidden', 'true');
    shadow.style.left = `${(part.x + x) / 8}%`;
    shadow.style.top = `${(part.y + y) / 5}%`;
    shadow.style.width = `${width / 8}%`; shadow.style.height = `${height / 5}%`;
    shadow.style.opacity = String(opacity);
    // Same depth as the prop, inserted before it: above the support, below the prop.
    shadow.style.zIndex = String(surface ? part.depth : 2);
    shadows.push(shadow);
  };
  const { asset, width: w, height: h } = part;
  if (asset === 'workerDesk' || asset === 'trialDesk' || asset === 'managerDesk') {
    patch(8, h - 19, w - 7, 24, .12);
    patch(2, h - 3, 14, 7, .24);
    patch(w - 15, h - 3, 14, 7, .24);
    if (asset !== 'managerDesk') patch(w * .68, h - 5, 11, 6, .20);
  } else if (asset === 'blueChair' || asset === 'greenChair' || asset === 'managerChair') {
    patch(3, h - 7, w - 1, 12, .14);
    patch(3, h - 3, 9, 6, .24);
    patch(w - 10, h - 3, 9, 6, .24);
  } else if (asset === 'steppingStone') {
    patch(2, h - 3, w, 5, .14);
  } else if (asset === 'tomatoBed') {
    // The watering can shares the atlas sprite, but has its own raised footprint.
    patch(w * .78, h * .89, w * .23, 9, .12);
    patch(w * .81, h * .91, w * .16, 5, .23);
  } else if (asset === 'tomatoPlanter' || asset === 'shrub' || asset === 'gardenTree' || asset === 'gardenBench' || asset === 'gardenRocks') {
    patch(3, h - 4, w - 1, 7, .18);
  } else if (asset === 'foundation' || asset === 'stoneFoot') {
    patch(0, h - 1, w, 5, .16);
  } else if (asset === 'entrance') {
    patch(0, 28, 203, 4, .16);
    patch(307, 28, w - 307, 4, .16);
    patch(203, h - 2, 104, 5, .18);
  } else if (asset === 'managerFront') {
    patch(0, 28, w, 4, .16);
  } else if (asset === 'cabinet' || asset === 'stove' || asset === 'sofa') {
    patch(3, h - 7, w, 12, .20);
    patch(3, h - 3, 10, 6, .22);
    patch(w - 10, h - 3, 10, 6, .22);
  } else if (asset === 'businessMonitor' || asset === 'macroMonitor' || asset === 'eventMonitor' || asset === 'backMonitor') {
    patch(w * .26 + 2, h - 3, w * .52, 5, .22, true);
  } else if (asset === 'mug' || asset === 'plant') {
    patch(w * .12 + 1, h - 3, w * .78, 5, .24, true);
  }
  return shadows;
}

async function loadAsset(id: AssetId): Promise<HTMLCanvasElement> {
  const asset = ASSETS[id];
  const source = await loadSpriteSource(asset.url, asset.opaque, 'frame' in asset ? asset.frame : undefined);
  // Both floors use exact integer-grid SVG colors without baked texture or filtering.
  if (id === 'checker') return createPixelSprite(source, 96, 96, { pixelSize: 1, outline: false, preserveColors: true });
  if (id !== 'parquet') return source;
  const sprite = document.createElement('canvas');
  sprite.width = asset.width;
  sprite.height = Math.round(asset.width * source.height / source.width);
  const target = sprite.getContext('2d')!;
  target.imageSmoothingEnabled = false;
  target.drawImage(source, 0, 0, sprite.width, sprite.height);
  return sprite;
}

/** Mount independently placed background and furniture.
 * Local assets load once; failures are visibly reported without blocking the chat controls.
 * The same nodes survive full-room/minimap transitions and are removed by dispose().
 */
export class OfficeRoom {
  private readonly nodes: HTMLElement[] = [];
  private readonly renderer = new SpriteRenderer();
  private disposed = false;

  constructor(private readonly container: HTMLElement) {
    container.dataset.roomState = 'loading';
    const houseShadow = document.createElement('div');
    houseShadow.className = 'office-house-shadow';
    houseShadow.dataset.shadowFor = 'house';
    houseShadow.dataset.courtyard = 'true';
    houseShadow.setAttribute('aria-hidden', 'true');
    this.nodes.push(houseShadow); container.append(houseShadow);
    const parts = placements();
    const pending = new Map<AssetId, Promise<HTMLCanvasElement>>();
    const styled = new Map<string, HTMLCanvasElement>();
    const canvasFor = (id: AssetId) => {
      if (!pending.has(id)) pending.set(id, loadAsset(id));
      return pending.get(id)!;
    };
    const draws = parts.map(part => {
      for (const shadow of contactShadows(part)) {
        this.nodes.push(shadow); container.append(shadow);
      }
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(part.width); canvas.height = Math.round(part.height);
      canvas.setAttribute('aria-hidden', 'true');
      canvas.className = 'office-object';
      const host = canvas;
      host.dataset.roomObject = part.asset;
      if (part.courtyard) host.dataset.courtyard = 'true';
      host.dataset.worldWidth = String(part.width); host.dataset.worldHeight = String(part.height);
      host.style.left = `${part.x / 8}%`; host.style.top = `${part.y / 5}%`;
      host.style.width = `${part.width / 8}%`; host.style.height = `${part.height / 5}%`;
      host.style.zIndex = String(Math.round(part.depth));
      this.nodes.push(host); container.append(host);
      return canvasFor(part.asset).then(async sprite => {
        const timberReference = ['beamH', 'beamV', 'partition', 'wall'].includes(part.asset)
          ? await canvasFor('entrance') : undefined;
        if (this.disposed) return;
        const ctx = canvas.getContext('2d')!;
        ctx.imageSmoothingEnabled = false;
        if (part.repeat) {
          if (part.asset === 'parquet' && part.width === 68) {
            // Continue the last floor row through the recess above the lower sill.
            const floor = createRoomFloor(436, 302, true);
            ctx.drawImage(floor, part.x - 32, floor.height - part.height, part.width, part.height, 0, 0, part.width, part.height);
          } else {
            ctx.drawImage(createRoomFloor(part.width, part.height, part.asset === 'parquet'), 0, 0);
          }
        } else {
          const key = `${part.asset}:${part.width}:${part.height}`;
          if (!styled.has(key)) {
            const frames: Partial<Record<AssetId, [number, number]>> = {
              beamH: [96, 16], beamV: [16, 96], partition: [20, 64],
            };
            const frame = frames[part.asset];
            styled.set(key, part.asset === 'entrance' || part.asset === 'managerFront'
              ? createPixelSprite(createFrontSection(createPixelSprite(sprite, 264, 44, {preserveColors:true}), part.asset === 'entrance'), part.width, part.height, {preserveColors:true})
              : part.asset === 'eave'
              ? createPixelSprite(extendRoof(createPixelSprite(sprite, 192, 6, {preserveColors:true})), 768, 6, {preserveColors:true})
              : frame
              ? fitPixelFrame(createPixelSprite(sprite, ...frame, { preserveColors: true }), part.width, part.height)
              : createPixelSprite(sprite, part.width, part.height, {
                outline: !['wall', 'passageWood', 'grass', 'flowers'].includes(part.asset),
                preserveColors: true,
              }));
            if (['partition', 'beamV', 'passageWood'].includes(part.asset)) {
              finishTimber(styled.get(key)!, part.asset === 'passageWood',
                part.asset === 'beamV' || (part.asset === 'partition' && part.y > 200));
            }
            if (timberReference) matchFrameTimber(styled.get(key)!, timberReference);
          }
          this.renderer.attach(canvas, styled.get(key)!);
        }
        host.dataset.objectState = 'ready';
      });
    });
    for (const [text, x, y] of [['Tomade', 78, 40], ['부장실', 506, 48]] as const) {
      const label = document.createElement('span');
      label.className = 'office-room-label'; label.textContent = text;
      label.style.left = `${x / 8}%`; label.style.top = `${y / 5}%`;
      label.setAttribute('aria-hidden', 'true');
      this.nodes.push(label); container.append(label);
    }
    void Promise.allSettled(draws).then(results => {
      if (this.disposed) return;
      const failed = results.filter(result => result.status === 'rejected');
      container.dataset.roomState = failed.length ? 'error' : 'ready';
      if (failed.length) {
        const message = document.createElement('p');
        message.className = 'room-load-error'; message.setAttribute('role', 'alert');
        message.textContent = '사무실 소품 일부를 불러오지 못했습니다. 새로고침해 주세요.';
        this.nodes.push(message); container.append(message);
        console.error('Office assets failed to load', failed);
      }
    });
  }

  /** Release owned buttons and objects when the page really unloads, not on bfcache entry. */
  dispose(): void {
    this.disposed = true;
    this.renderer.dispose();
    this.nodes.forEach(node => node.remove());
  }
}
