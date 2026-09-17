/**
 * Browser regression coverage for the office UI, using only in-memory API data.
 * Run with Node and an installed Playwright module, for example:
 * PLAYWRIGHT_MODULE_PATH=/path/to/node_modules/playwright node frontend/tests/office-ui.mjs
 * OFFICE_BASE_URL defaults to http://127.0.0.1:5173. No live backend is contacted.
 * Set OFFICE_BROWSER_CHANNEL=chrome to use an existing Chrome installation.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const modulePath = process.env.PLAYWRIGHT_MODULE_PATH;
let playwright;
try {
  playwright = modulePath
    ? require(modulePath)
    : await import('playwright');
} catch (error) {
  throw new Error('Playwright를 찾지 못했습니다. PLAYWRIGHT_MODULE_PATH에 설치된 모듈 경로를 지정하세요.', { cause: error });
}

const baseUrl = process.env.OFFICE_BASE_URL ?? 'http://127.0.0.1:5173';
const screenshots = process.env.OFFICE_SCREENSHOTS_DIR ?? '/tmp/stock-office-ui-test';
const workers = ['business', 'macro_sector', 'event_catalyst'];
const agent = id => `.office-agent[data-agent="${id}"]`;
const finalAnswer = '모의 종합 답변: 매출 성장과 신규 계약을 확인했습니다.';
const businessReport = '비즈니스 조사: 모의 매출은 전년 대비 12% 증가했습니다.';
const eventReport = '이벤트 조사: 모의 신규 계약 발표를 확인했습니다.';
const savedAnswer = '저장된 부장 답변: 장기 관점의 기업 분석입니다.';
const sourceMarker = 'worker-only-report-must-not-appear-in-saved-history';

// Independent source contracts: files/frames are design inputs, not renderer output.
// Atlas coordinates are normalized, before removing the keyed padding.
const propSourceContracts = [
  { id: 'workerDesk', file: 'office-objects-v3/worker-desk-trial.png', gaps: [[.4, .85]] },
  { id: 'trialDesk', file: 'office-objects-v3/worker-desk-trial.png', gaps: [[.4, .85]] },
  { id: 'managerDesk', file: 'office-objects-v4/furniture-atlas.png', frame: [0, 0, .36, 1/3], gaps: [[.5, .82]] },
  { id: 'blueChair', file: 'office-objects-v4/furniture-atlas.png', frame: [.4, 0, .63, 1/3], gaps: [[.5, .26], [.5, .88]] },
  { id: 'greenChair', file: 'office-objects-v4/furniture-atlas.png', frame: [.7, 0, 1, 1/3], gaps: [[.5, .26], [.5, .88]] },
  { id: 'businessMonitor', file: 'office-objects-v4/details-atlas.png', frame: [0, 0, 1/3, 1/3] },
  { id: 'tomatoPlanter', file: 'office-courtyard-v2/garden-atlas.png', frame: [2/3, 0, 1, 1/3] },
];

const event = (type, data = {}) => ({ type, data: { run_id: 'office-mock-run', ...data } });
const started = node => event('node.started', { node });
const completed = (node, output) => event('node.completed', { node, output });

/** Each browser context owns isolated conversations and intercepts every API route. */
async function fixture(browser, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ...options });
  const conversations = new Map([
    ['office-main', { id: 'office-main', title: '새 대화', messages: [] }],
    ['office-saved', {
      id: 'office-saved', title: '기존 기업 분석',
      messages: [
        { role: 'user', content: '기업을 장기적으로 분석해줘.', status: 'completed' },
        { role: 'assistant', content: savedAnswer, status: 'completed' },
      ],
      // Even if extra server fields exist, only saved user/assistant messages belong in history.
      business_report: sourceMarker,
    }],
    ['office-pending', {
      id: 'office-pending', title: '다른 창에서 조사 중',
      messages: [
        { role: 'user', content: '아직 처리 중인 질문', status: 'completed' },
        { role: 'assistant', content: '', status: 'pending' },
      ],
    }],
  ]);
  let nextId = 1;
  const apiRequests = [];
  const unexpectedRequests = [];
  const errors = [];
  await context.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    apiRequests.push({ method, path });
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/settings/models' && method === 'GET') return json({ provider: 'openai', auth_mode: 'api_key', models: { planner: 'mock-model' }, busy: false, api_keys: { openai: true, openrouter: false }, codex: { state: 'signed_out', message: '구독 로그인 없음' }, login: null });
    if (path === '/api/conversations' && method === 'GET') {
      return json([...conversations.values()].map(({ id, title }) => ({ id, title })));
    }
    if (path === '/api/conversations' && method === 'POST') {
      const conversation = { id: `office-new-${nextId++}`, title: '새 대화', messages: [] };
      conversations.set(conversation.id, conversation);
      return json(conversation, 201);
    }
    const match = path.match(/^\/api\/conversations\/([^/]+)$/);
    if (match && method === 'GET') {
      return conversations.has(match[1]) ? json(conversations.get(match[1])) : json({ detail: '대화 없음' }, 404);
    }
    if (match && method === 'DELETE') {
      conversations.delete(match[1]);
      return route.fulfill({ status: 204 });
    }
    if (path === '/api/portfolio/configuration' && method === 'GET') return json({ configured: false });
    // Fail closed: an unmocked endpoint never falls through to the real backend.
    unexpectedRequests.push({ method, path });
    return json({ detail: `허용하지 않은 테스트 API: ${method} ${path}` }, 501);
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.exposeFunction('__officeRecordMockChat', payload => {
    const conversation = conversations.get(payload.conversation_id);
    assert.ok(conversation, 'Chat must use an existing mock conversation');
    conversation.messages.push({ role: 'user', content: payload.message, status: 'completed' });
    conversation.messages.push({ role: 'assistant', content: '', status: 'pending' });
    conversation.title = payload.message.slice(0, 30);
  });
  await page.exposeFunction('__officeRecordMockTerminal', ({ conversationId, content, status }) => {
    const conversation = conversations.get(conversationId);
    const reply = conversation.messages.at(-1);
    Object.assign(reply, { content, status });
  });
  // Only chat uses a controllable stream. The test advances actual SSE frames through
  // fetch/Response/ReadableStream, leaving production code and its event reader intact.
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const mock = {
      requests: [], controller: null, conversationId: null, terminal: false,
      async emit(events) {
        if (!this.controller) throw new Error('No mock chat stream is open');
        for (const item of events) {
          if (item.type === 'run.completed' || item.type === 'run.error') {
            this.terminal = true;
            await window.__officeRecordMockTerminal({
              conversationId: this.conversationId,
              content: String(item.data.final_answer ?? item.data.message ?? ''),
              status: item.type === 'run.completed' ? 'completed' : 'error',
            });
          }
          this.controller.enqueue(encoder.encode(`event: ${item.type}\ndata: ${JSON.stringify(item.data)}\n\n`));
        }
      },
      async close() {
        if (!this.terminal) {
          await window.__officeRecordMockTerminal({
            conversationId: this.conversationId, content: '중단된 모의 응답', status: 'interrupted',
          });
        }
        this.controller.close();
        this.controller = null;
      },
    };
    window.__officeMockTest = mock;
    window.fetch = async (input, init = {}) => {
      const url = new URL(typeof input === 'string' ? input : input.url ?? input.href, location.href);
      if (url.pathname !== '/api/chat/stream') return originalFetch(input, init);
      const payload = JSON.parse(init.body);
      mock.requests.push(payload);
      mock.conversationId = payload.conversation_id;
      mock.terminal = false;
      await window.__officeRecordMockChat(payload);
      return new Response(new ReadableStream({ start(controller) { mock.controller = controller; } }), {
        status: 200, headers: { 'Content-Type': 'text/event-stream' },
      });
    };
  });
  await page.goto(`${baseUrl}/#conversation=office-main`);
  await page.waitForFunction(() => document.querySelector('#researchInput')?.disabled === false);
  await page.waitForFunction(() => document.querySelector('#officeWorld')?.dataset.roomState === 'ready');
  await page.waitForFunction(() => [...document.querySelectorAll('.agent-sprite, #managerPortrait, #portfolioSprite')]
    .every(canvas => canvas.dataset.spriteState === 'ready'));
  return {
    page, context, conversations, apiRequests,
    check() {
      assert.deepEqual(unexpectedRequests, [], 'No unknown API endpoint may be called');
      assert.deepEqual(errors, [], 'The browser must not raise uncaught application errors');
    },
    async dispose() { await context.close(); },
  };
}

async function state(page, id, activity, motion) {
  await page.waitForFunction(({ selector, activity, motion }) => {
    const node = document.querySelector(selector);
    return node?.dataset.activity === activity && (!motion || node.dataset.motion === motion);
  }, { selector: agent(id), activity, motion }, { timeout: 35_000 });
}

async function idle(page) {
  await page.waitForFunction(ids => ids.every(id => document.querySelector(`.office-agent[data-agent="${id}"]`)?.dataset.activity === 'idle'), workers);
}

async function emit(page, events, close = false) {
  await page.evaluate(async ({ events, close }) => {
    await window.__officeMockTest.emit(events);
    if (close) await window.__officeMockTest.close();
  }, { events, close });
}

async function submit(page, question) {
  if (!await page.locator('#managerDialog').isVisible()) await page.locator('#talkToManager').click();
  await page.locator('#researchInput').fill(question);
  const count = await page.evaluate(() => window.__officeMockTest.requests.length);
  await page.locator('#runButton').click();
  await page.waitForFunction(previous => window.__officeMockTest.requests.length === previous + 1 && window.__officeMockTest.controller !== null, count);
  assert.equal(await page.locator('#runButton').isDisabled(), true, 'A running request disables duplicate submission');
  assert.equal(await page.locator('#conversationSelect').isDisabled(), true, 'Conversation switching is disabled during a request');
}

async function waitReady(page) {
  await page.waitForFunction(() => document.querySelector('#runButton')?.disabled === false);
}

async function openWorker(page, id) {
  if (await page.locator('#managerDialog').isVisible()) await page.locator('#returnToOffice').click();
  // Native keyboard activation is deterministic even when the character is walking.
  await page.locator(agent(id)).focus();
  await page.locator(agent(id)).press('Enter');
  await page.locator('#agentJournal').waitFor({ state: 'visible' });
}

async function closePanel(page, id) {
  const selector = { '#closeJournal': '[data-close="agentJournal"]', '#closeHistory': '#closeManager' }[id] ?? id;
  await page.locator(selector).click();
}

async function containedInViewport(page, selector) {
  const box = await page.locator(selector).boundingBox();
  const viewport = page.viewportSize();
  assert.ok(box && box.width > 0 && box.height > 0, `${selector} must be visible`);
  assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1,
    `${selector} must fit inside ${viewport.width}×${viewport.height}: ${JSON.stringify(box)}`);
}

async function fullRoomFitting(browser) {
  const f = await fixture(browser, { reducedMotion: 'reduce' });
  const { page } = f;
  try {
    if (await page.locator('#managerDialog').isVisible()) await closePanel(page, '#closeManager');
    const imageAspect = await page.locator('#officeWorld').evaluate(room => room.clientWidth / room.clientHeight);
    assert.ok(Math.abs(imageAspect - 1.6) < 0.01, 'The two-room house keeps its approved landscape framing');
    const spritePixels = await page.locator('.agent-sprite, #managerPortrait').evaluateAll(canvases => canvases.map(canvas => {
      const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
      let opaque = 0, clear = 0, magenta = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] === 0) clear++;
        else {
          opaque++;
          if (data[i] > 180 && data[i + 2] > 180 && data[i + 1] < 80) magenta++;
        }
      }
      return { opaque, clear, magenta };
    }));
    for (const pixels of spritePixels) {
      assert.ok(pixels.opaque > 100 && pixels.clear > 100, 'Every reference sprite and portrait renders visible artwork with transparent surrounding pixels');
      assert.equal(pixels.magenta, 0, 'The atlas key backdrop must not leak into the office or portrait');
    }
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 900, height: 1000 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport);
      await containedInViewport(page, '#officeWorld');
      const room = await page.locator('#officeWorld').boundingBox();
      for (const id of ['upper_agent', ...workers]) {
        await containedInViewport(page, agent(id));
        const sprite = await page.locator(`${agent(id)} .agent-sprite`).boundingBox();
        const hitArea = await page.locator(agent(id)).boundingBox();
        const relativeHeight = { upper_agent: 0.12, business: 0.108, macro_sector: 0.108, event_catalyst: 0.084 }[id];
        assert.ok(Math.abs(sprite.height / room.width - relativeHeight) < 0.001, 'Each cast member keeps its intended size relative to the furniture');
        assert.ok(Math.abs(sprite.width / sprite.height - 0.8) < 0.01, 'Larger characters retain their face and body proportions');
        assert.ok(hitArea.width + 1 >= sprite.width && hitArea.height + 1 >= sprite.height, 'The click target grows with the character');
      }
      // The decorative panorama spans the viewport beyond the scene container's
      // gutters; check page scrolling and individual props, not that backdrop.
      const overflow = await page.evaluate(() => ({
        horizontal: document.documentElement.scrollWidth - innerWidth,
        vertical: document.documentElement.scrollHeight - innerHeight,
      }));
      assert.ok(overflow.horizontal <= 1 && overflow.vertical <= 1, `No room panning should be needed: ${JSON.stringify(overflow)}`);
      for (const garden of await page.locator('[data-room-object][data-courtyard]').all()) {
        const bounds = await garden.boundingBox();
        assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width + 1
          && bounds.y + bounds.height <= viewport.height + 1, 'Every courtyard prop fits without clipping or panning');
      }
      await page.screenshot({ path: `${screenshots}/tomato-office-${viewport.width}x${viewport.height}.png` });
    }
    f.check();
    console.log('PASS room fitting: both rooms and four interactive agents fit desktop, portrait, mobile and landscape without panning');
  } finally { await f.dispose(); }
}

async function modularObjects(browser) {
  const f = await fixture(browser, { reducedMotion: 'reduce' });
  const { page } = f;
  try {
    const objects = await page.locator('[data-room-object]').evaluateAll(nodes => nodes.map(node => ({ asset: node.dataset.roomObject, state: node.dataset.objectState })));
    assert.equal(objects.length, 194, 'Background and furniture are independently placed objects');
    assert.equal(new Set(objects.map(object => object.asset)).size, 49, 'Room assets exclude the removed desk nameplates');
    assert.ok(objects.every(object => object.state === 'ready'));
    assert.equal(objects.filter(object => object.asset === 'trialDesk').length, 1, 'Pat keeps the approved desk placement');
    assert.equal(objects.filter(object => object.asset === 'workerDesk').length, 2, 'Both other employee desks receive the approved style');
    const environment = await page.locator('#officeWorld').evaluate(node => {
      const canopy = [...node.querySelectorAll('[data-room-object="gardenTree"]')];
      const rear = canopy.filter(tree => parseFloat(tree.style.top) < 0);
      const sky = getComputedStyle(node, '::before');
      return {
        panorama: sky.backgroundImage.includes('garden-horizon.webp'),
        grounded: rear.length === 2 && rear.every(tree => parseFloat(tree.style.top) * 5 + Number(tree.dataset.worldHeight) <= -20),
        mature: canopy.every(tree => Number(tree.dataset.worldHeight) >= 160),
        fixedShadow: [...node.querySelectorAll('.office-contact-shadow')].every(shadow =>
          getComputedStyle(shadow).clipPath === 'none' && shadow.style.backgroundImage.includes('data:image/png')),
      };
    });
    assert.ok(environment.panorama && environment.grounded && environment.mature, 'Mature trees stand on rear ground, separated from the eave and backed by a shared panorama');
    assert.ok(environment.fixedShadow, 'Contact shadows use cached pixel images instead of scaled CSS stair steps');
    const joins = await page.evaluate(() => {
      const objects = [...document.querySelectorAll('[data-room-object]')];
      const box = node => ({ x: parseFloat(node.style.left) * 8, y: parseFloat(node.style.top) * 5,
        w: Number(node.dataset.worldWidth), h: Number(node.dataset.worldHeight) });
      const all = asset => objects.filter(node => node.dataset.roomObject === asset).map(box);
      const [floor] = all('parquet');
      const [doorway] = all('passageWood');
      const [entrance] = all('entrance');
      const [managerFront] = all('managerFront');
      const partitions = all('partition');
      return {
        feetAligned: all('stoneFoot').length === 3 && [...all('beamV'), partitions[1]].every(column => all('stoneFoot').some(foot => foot.y + 2 === column.y + column.h && foot.h === 22 && foot.x < column.x && foot.x + foot.w > column.x + column.w)),
        completeFloors: floor.y === all('wall')[0].y + all('wall')[0].h
          && all('checker')[0].y === all('wall')[1].y + all('wall')[1].h,
        continuousEntrance: entrance.x===31 && entrance.w===438 && entrance.y===floor.y+floor.h
          && managerFront.x===487 && managerFront.w===282 && managerFront.h===32
          && entrance.x+entrance.w===partitions[1].x+1 && managerFront.x===partitions[1].x+partitions[1].w-1
          && ['entryJamb','threshold','steps','foundation'].every(id=>all(id).length===0),
        wallCount: all('wall').length,
        doorwayContained: doorway.y === partitions[0].y + partitions[0].h && doorway.y + doorway.h === partitions[1].y,
        flushPartitions: partitions.every(wall => wall.x === floor.x + floor.w && wall.w === doorway.w),
      };
    });
    assert.equal(joins.wallCount, 2, 'Wallpaper remains only on the back walls');
    assert.ok(joins.completeFloors && joins.continuousEntrance, 'Two independent room fronts terminate one unit behind their columns');
    assert.ok(joins.feetAligned && joins.doorwayContained && joins.flushPartitions, 'Column feet and room passage remain aligned');
    const entranceShape = await page.locator('canvas[data-room-object="entrance"]').evaluate(canvas => {
      const ctx=canvas.getContext('2d'), pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
      const alpha=(x,y)=>pixels[(Math.floor(y/44*canvas.height)*canvas.width+Math.floor((x-15)/438*canvas.width))*4+3];
      let stray=0;
      for(let y=35;y<43;y++)for(let x=15;x<453;x++)if((x<214||x>326)&&alpha(x,y))stray++;
      return {open:alpha(270,3)===0, sill:alpha(270,12)===255, upper:alpha(270,25)===255, lower:alpha(270,40)===255, stray};
    });
    assert.ok(entranceShape.open && entranceShape.sill && entranceShape.upper && entranceShape.lower, 'Open entry recess leads into the wooden sill and two stone steps');
    assert.equal(entranceShape.stray,0,'No detached stair pixels repeat below the side foundation');
    const cuts = await page.locator('canvas[data-room-object="entrance"]').evaluate(canvas => {
      const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
      const rgb=(x,y)=>{const i=(Math.floor(y/44*canvas.height)*canvas.width+Math.floor((x-15)/438*canvas.width))*4;return [...data.slice(i,i+4)];};
      return [139,401].map(x=>({x, top:rgb(x,.4), face:rgb(x,2.5), left:rgb(x-2,6), middle:rgb(x,6), right:rgb(x+2,6)}));
    });
    for(const cut of cuts){
      assert.equal(cut.top[3],255,'Rail top remains opaque across crop joins');
      assert.ok(cut.face[0]>75,'No dark notch extends down into the rail highlight at a crop join');
      assert.ok(cut.middle.slice(0,3).every((v,c)=>Math.abs(v-(cut.left[c]+cut.right[c])/2)<28),'Wood colors bridge the crop boundary without a vertical color reset');
    }
    assert.equal(await page.locator('[data-room-object="eave"]').count(),1,'One roof strip avoids doubled inter-asset outlines');

    const garden = await page.locator('[data-room-object][data-courtyard]').evaluateAll(nodes => nodes.map(node => ({
      asset: node.dataset.roomObject, events: getComputedStyle(node).pointerEvents,
    })));
    assert.equal(garden.length, 151, 'Seventeen courtyard asset types form the garden');
    assert.ok(garden.every(node => node.events === 'none'), 'Courtyard decorations never intercept clicks');
    assert.equal(await page.locator('.office-background, .furniture-occluder').count(), 0, 'The old monolithic background and clipped copies are removed');
    assert.equal(await page.evaluate(() => performance.getEntriesByType('resource').some(entry => entry.name.includes('/research-office'))), false, 'The app does not load the old background');
    const floor = await page.locator('canvas[data-room-object="parquet"][data-world-width="436"]').evaluateAll(canvases => {
      let checked = 0, wrong = 0;
      for (const canvas of canvases) {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        const xs = Array.from({length:10},(_,i)=>Math.round(i*canvas.width/9));
        const ys = Array.from({length:7},(_,i)=>Math.round(i*canvas.height/6));
        for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
          const col=xs.findIndex((edge,i)=>i<9 && x>=edge && x<xs[i+1]);
          const row=ys.findIndex((edge,i)=>i<6 && y>=edge && y<ys[i+1]);
          const horizontal=(row+col)%2===0;
          const internal=[1,2].map(i=>horizontal?ys[row]+Math.round(i*(ys[row+1]-ys[row])/3):xs[col]+Math.round(i*(xs[col+1]-xs[col])/3));
          const seam=x===xs[col] || y===ys[row] || internal.includes(horizontal?y:x);
          const i = (y * canvas.width + x) * 4;
          const actualSeam = data[i] === 200 && data[i + 1] === 180 && data[i + 2] === 143;
          if (seam !== actualSeam || data[i + 3] !== 255) wrong++;
          checked++;
        }
      }
      return { checked, wrong };
    });
    assert.ok(floor.checked > 100_000);
    assert.equal(floor.wrong, 0, 'Nine by six complete parquet blocks fill the room with one-pixel seams');
    const checker = await page.locator('canvas[data-room-object="checker"]').evaluate(canvas => {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let wrong = 0;
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        const col=Array.from({length:6},(_,i)=>i).find(i=>x<Math.round((i+1)*canvas.width/6));
        const row=Array.from({length:6},(_,i)=>i).find(i=>y<Math.round((i+1)*canvas.height/6));
        const rgb = (col + row) % 2 ? [197,205,181] : [242,237,218];
        const i = (y * canvas.width + x) * 4;
        if (rgb.some((v,c) => v !== pixels[i+c]) || pixels[i+3] !== 255) wrong++;
      }
      return wrong;
    });
    assert.equal(checker, 0, 'Checker tiles are exact flat colors with no blurry intermediate shades');
    assert.equal(await page.locator('.office-nameplate, #openReport, #openHistory, #openPortfolio, #historyDialog').count(), 0, 'Desk nameplates and old top-right navigation are removed');
    for (const id of workers) {
      await openWorker(page, id);
      assert.ok((await page.locator('#journalTitle').textContent()).length > 0);
      await closePanel(page, '#closeJournal');
    }
    await page.locator(agent('upper_agent')).press('Enter');
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    assert.ok(await page.locator('.office-agent, .portfolio-character').evaluateAll(nodes => nodes.length === 5 && nodes.every(node => node.inert)), 'All five characters are disabled inside the minimap');
    assert.ok(await page.locator('[data-courtyard]').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).visibility === 'hidden')));
    await page.locator('#returnToOffice').click();
    await page.waitForFunction(() => !document.querySelector('#officeWorld').getAnimations().length);
    assert.ok(await page.locator('.office-agent, .portfolio-character').evaluateAll(nodes => nodes.every(node => !node.inert)));
    assert.ok(await page.locator('[data-courtyard]').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).visibility === 'visible')));
    await page.screenshot({ path: `${screenshots}/modular-office.png` });
    f.check();
    console.log('PASS modular room: 49 assets, 194 independent objects, exact floor seams, character navigation and minimap interaction');
  } finally { await f.dispose(); }
}

/** Check the delivered prop pixels against their silhouettes, including open leg/rail gaps. */
async function spriteContours(page) {
  const result = await page.evaluate(async sourceContracts => {
    const native = canvas => {
      const width = Number(canvas.dataset.pixelWidth || canvas.width);
      const height = Number(canvas.dataset.pixelHeight || canvas.height);
      if (canvas.width < width || canvas.height < height) throw new Error('Contour QA requires display pixels for every native cell');
      const displayed = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      const result = document.createElement('canvas'); result.width = width; result.height = height;
      const ctx = result.getContext('2d'), pixels = ctx.createImageData(width, height);
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const source = (Math.floor((y + .5) * canvas.height / height) * canvas.width
          + Math.floor((x + .5) * canvas.width / width)) * 4;
        pixels.data.set(displayed.subarray(source, source + 4), (y * width + x) * 4);
      }
      ctx.putImageData(pixels, 0, 0);
      return result;
    };
    const mask = canvas => {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      return Uint8Array.from({ length: canvas.width * canvas.height }, (_, i) => Number(pixels[i * 4 + 3] >= 96));
    };
    const sprites = new Map(), instances = new Map(), contours = [];
    for (const canvas of document.querySelectorAll('canvas.office-object[data-sampled]')) {
      const id = canvas.closest('[data-room-object]').dataset.roomObject;
      const sprite = native(canvas);
      if (!sprites.has(id)) sprites.set(id, sprite);
      if (!instances.has(id)) instances.set(id, []);
      instances.get(id).push(sprite);
      if (['wall', 'passageWood', 'grass', 'flowers', 'flowerBed'].includes(id)) continue;
      const width = sprite.width, height = sprite.height, silhouette = mask(sprite);
      // Two independent 8-neighbor erosions identify the required inner contour.
      let interior = silhouette;
      for (let pass = 0; pass < 2; pass++) {
        const next = new Uint8Array(interior.length);
        for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) {
          let occupied = 1;
          for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) occupied &= interior[(y + dy) * width + x + dx];
          next[y * width + x] = occupied;
        }
        interior = next;
      }
      const pixels = sprite.getContext('2d').getImageData(0, 0, width, height).data;
      let boundary = 0, broken = 0;
      for (let i = 0; i < silhouette.length; i++) if (silhouette[i] && !interior[i]) {
        boundary++;
        if (pixels[i * 4] !== 25 || pixels[i * 4 + 1] !== 23 || pixels[i * 4 + 2] !== 22 || pixels[i * 4 + 3] !== 255) broken++;
      }
      contours.push({ id, boundary, broken, outline: canvas.dataset.outlinePixels });
    }
    const silhouettes = [];
    for (const { id, file, frame = [0, 0, 1, 1], gaps = [] } of sourceContracts) {
      // Reference projection deliberately does not call the production decoder,
      // palette mapper or contour function: the original PNG owns the footprint.
      const image = new Image(); image.src = `/assets/${file}`; await image.decode();
      const source = document.createElement('canvas');
      const frameLeft = Math.round(frame[0] * image.naturalWidth), frameTop = Math.round(frame[1] * image.naturalHeight);
      source.width = Math.round(frame[2] * image.naturalWidth) - frameLeft;
      source.height = Math.round(frame[3] * image.naturalHeight) - frameTop;
      const ctx = source.getContext('2d');
      ctx.drawImage(image, frameLeft, frameTop, source.width, source.height, 0, 0, source.width, source.height);
      const pixels = ctx.getImageData(0, 0, source.width, source.height);
      let left = source.width, top = source.height, right = -1, bottom = -1;
      for (let y = 0; y < source.height; y++) for (let x = 0; x < source.width; x++) {
        const i = (y * source.width + x) * 4, r = pixels.data[i], g = pixels.data[i + 1], b = pixels.data[i + 2];
        if (r - g > 12 && b - g > 12 && b > r * .6) pixels.data[i + 3] = 0;
        else if (pixels.data[i + 3]) { left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y); }
      }
      // Materialize the integer crop before scaling. Scaling a subrectangle of a
      // larger atlas can choose a neighboring texel at exact sampling boundaries.
      const cropped = document.createElement('canvas');
      cropped.width = right - left + 1; cropped.height = bottom - top + 1;
      cropped.getContext('2d').putImageData(pixels, -left, -top);
      for (const [instance, actual] of instances.get(id).entries()) {
        const projection = document.createElement('canvas');
        projection.width = actual.width; projection.height = actual.height;
        const projected = projection.getContext('2d'); projected.imageSmoothingEnabled = false;
        projected.drawImage(cropped, 0, 0, projection.width, projection.height);
        const expectedMask = mask(projection), actualMask = mask(actual);
        let changed = 0;
        for (let i = 0; i < actualMask.length; i++) if (actualMask[i] !== expectedMask[i]) changed++;
        let colorSamples = 0, colorChanges = 0;
        const expected = projected.getImageData(0, 0, actual.width, actual.height).data;
        const shown = actual.getContext('2d').getImageData(0, 0, actual.width, actual.height).data;
        for (let y = 2; y < actual.height - 2; y++) for (let x = 2; x < actual.width - 2; x++) {
          // Skip the intentional two-cell contour; all material RGB must match the original.
          let interior = true;
          for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
            if (!expectedMask[(y + dy) * actual.width + x + dx]) interior = false;
          }
          if (!interior) continue;
          colorSamples++;
          const i = (y * actual.width + x) * 4;
          if (shown[i] !== expected[i] || shown[i+1] !== expected[i+1] || shown[i+2] !== expected[i+2]) colorChanges++;
        }
        const gapsOpen = gaps.every(([x, y]) => !expectedMask[Math.floor(y * actual.height) * actual.width + Math.floor(x * actual.width)]
          && !actualMask[Math.floor(y * actual.height) * actual.width + Math.floor(x * actual.width)]);
        silhouettes.push({ id: `${id}#${instance + 1}`, changed, gapsOpen, colorSamples, colorChanges });
      }
    }
    const character = native(document.querySelector('.office-agent[data-agent="business"] .agent-sprite'));
    const figures = [['Business character', character], ...['trialDesk', 'workerDesk', 'managerDesk', 'blueChair', 'greenChair', 'businessMonitor', 'stove', 'tomatoPlanter'].map(id => [id, sprites.get(id)])]
      .map(([label, canvas]) => ({ label, width: canvas.width, height: canvas.height, url: canvas.toDataURL() }));
    return { contours, silhouettes, figures };
  }, propSourceContracts);
  assert.equal(result.contours.length, 66, 'Every furniture/decor/structural sprite has a contour; flat walls and tiled floors are excluded');
  for (const { id, boundary, broken, outline } of result.contours) {
    assert.equal(outline, '2', `${id} declares the character-sized two-cell outline`);
    assert.ok(boundary > 0, `${id} has a nonempty visible silhouette`);
    assert.equal(broken, 0, `${id} has no light or missing ink cells on outer/inner contours`);
  }
  for (const { id, changed, gapsOpen, colorSamples, colorChanges } of result.silhouettes) {
    assert.equal(changed, 0, `${id} preserves the original projected alpha without expanding its silhouette`);
    assert.ok(gapsOpen, `${id} preserves its open space between legs and rails`);
    assert.ok(colorSamples > 100, `${id} has enough interior material pixels for a useful source comparison`);
    assert.equal(colorChanges, 0, `${id} material RGB exactly matches the original source projection`);
  }
  const html = `<!doctype html><meta charset="utf-8"><title>Character and prop native pixel comparison</title>
    <style>body{margin:24px;background:#ede8dc;color:#292e2c;font:16px system-ui}main{display:flex;flex-wrap:wrap;align-items:flex-end;gap:28px}figure{margin:0}figcaption{margin:8px 0}img{display:block;image-rendering:pixelated;background:repeating-conic-gradient(#e8e3d8 0% 25%,#f7f3eb 0% 50%) 0 0/32px 32px}</style>
    <p>Actual UI buffers · 4× native pixels · staff and props share the same pixel scale</p><main>${result.figures.map(({ label, width, height, url }) =>
      `<figure><figcaption>${label} · ${width}×${height}</figcaption><img src="${url}" width="${width * 4}" height="${height * 4}"></figure>`).join('')}</main>`;
  await writeFile(`${screenshots}/character-prop-grid-comparison.html`, html);
  const comparison = await page.context().newPage();
  try {
    await comparison.setViewportSize({ width: 2100, height: 1600 });
    await comparison.setContent(html);
    await comparison.screenshot({ path: `${screenshots}/character-prop-grid-comparison.png`, fullPage: true });
  } finally { await comparison.close(); }
  console.log(`PASS contours: ${result.contours.length} actual sprites have uninterrupted inner ink; ${result.silhouettes.length} representative placements preserve source RGB and alpha`);
}

async function spriteRendering(browser) {
  for (const deviceScaleFactor of [1, 2]) {
    const f = await fixture(browser, { reducedMotion: 'reduce', deviceScaleFactor });
    const { page } = f;
    try {
      for (const viewport of [{ width: 1440, height: 1000 }, { width: 1024, height: 768 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(viewport);
        await page.waitForFunction(() => [...document.querySelectorAll('canvas.office-object[data-sampled]')].every(canvas => {
          const style = getComputedStyle(canvas);
          return canvas.width === Math.round(parseFloat(style.width) * devicePixelRatio)
            && canvas.height === Math.round(parseFloat(style.height) * devicePixelRatio);
        }));
        assert.equal(await page.locator('canvas.office-object[data-sampled]').count(), 191, 'Every non-tiled prop renders at its physical display resolution');
        assert.ok(await page.locator('canvas.office-object[data-sampled]').evaluateAll(canvases => canvases.every(canvas => {
          const object = canvas.closest('[data-room-object]');
          const character = document.querySelector('.office-agent[data-agent="business"] .agent-sprite');
          const roomScale = parseFloat(getComputedStyle(document.querySelector('#officeWorld')).width) / 800;
          const characterPixel = parseFloat(getComputedStyle(character).height) / character.height / roomScale;
          return Math.abs(Number(canvas.dataset.pixelGrid) - characterPixel) < .0001
            && Number(canvas.dataset.pixelWidth) === Math.round(Number(object.dataset.worldWidth) / characterPixel)
            && Number(canvas.dataset.pixelHeight) === Math.round(Number(object.dataset.worldHeight) / characterPixel);
        })), 'Every prop uses the staff character canvas density at every viewport/DPR');
        const monitor = await page.locator('[data-room-object="backMonitor"]').boundingBox();
        const desk = await page.locator('[data-room-object="managerDesk"]').boundingBox();
        assert.ok(Math.abs(monitor.x + monitor.width / 2 - desk.x - desk.width / 2) < 1, 'The manager monitor is centered on the desktop');
        assert.ok(monitor.y + monitor.height < desk.y + desk.height * .5, 'The monitor base stays above the front edge of the desktop');
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.waitForFunction(() => {
        const canvas = document.querySelector('canvas[data-room-object="workerDesk"]');
        return canvas.width === Math.round(parseFloat(getComputedStyle(canvas).width) * devicePixelRatio);
      });
      const partialAlpha = await page.evaluate(() => {
        let partialAlpha = 0;
        for (const canvas of document.querySelectorAll('canvas.office-object[data-sampled]')) {
          const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
          for (let i = 0; i < pixels.length; i += 4) {
            if (!pixels[i + 3]) continue;
            if (pixels[i + 3] !== 255) partialAlpha++;
          }
        }
        return partialAlpha;
      });
      assert.equal(partialAlpha, 0, 'All object edges retain binary alpha without soft fringe pixels');
      if (deviceScaleFactor === 2) await spriteContours(page);
      await page.screenshot({ path: `${screenshots}/sprite-office-dpr${deviceScaleFactor}.png` });
      await page.locator('canvas[data-room-object="workerDesk"]').first().screenshot({ path: `${screenshots}/sprite-desk-dpr${deviceScaleFactor}.png` });
      f.check();
    } finally { await f.dispose(); }
  }
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    for (const [folder, count] of [['office-objects-v1', 39], ['office-environment-v1', 11]]) {
      await page.goto(`${baseUrl}/assets/${folder}/index.html`);
      await page.waitForFunction(() => document.body.dataset.ready === 'true');
      assert.equal(await page.locator('.card[data-loaded="true"]').count(), count);
      await page.locator('#grid').screenshot({ path: `${screenshots}/${folder}-rendering.png` });
      for (let i = 0; i < count; i++) {
        await page.locator('.card').nth(i).click();
        const canvas = page.locator('dialog canvas');
        await canvas.waitFor({ state: 'visible' });
        assert.ok(await canvas.evaluate(node => {
          const pixels = node.getContext('2d').getImageData(0, 0, node.width, node.height).data;
          return pixels.some((value, index) => index % 4 === 3 && value > 0);
        }), 'Every object detail contains visible pixels');
        if (i === 0) await page.locator('dialog').screenshot({ path: `${screenshots}/${folder}-detail.png` });
        await page.locator('#close').click();
      }
    }
    assert.deepEqual(errors, [], 'Both viewers remain free of script/ResizeObserver errors');
  } finally { await context.close(); }
  console.log('PASS sprite rendering: staff-matched density, source RGB across office/garden samples, complete contours and 50 working previews');
}

async function walkingMotion(browser) {
  const f = await fixture(browser, { reducedMotion: 'reduce' });
  const { page } = f;
  try {
    if (await page.locator('#managerDialog').isVisible()) await closePanel(page, '#closeManager');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const { samples, frames } = await page.evaluate(async () => {
      const samples = [];
      const frames = {};
      const start = performance.now();
      while (performance.now() - start < 8500) {
        await new Promise(requestAnimationFrame);
        for (const button of document.querySelectorAll('.office-agent')) {
          const canvas = button.querySelector('canvas');
          const sample = {
            id: button.dataset.agent, motion: button.dataset.motion,
            x: Number(button.dataset.x), y: Number(button.dataset.y),
            distance: Number(button.dataset.walkDistance),
            frame: Number(canvas.dataset.spriteFrame), pose: canvas.dataset.spritePose,
            time: performance.now() - start,
          };
          samples.push(sample);
          if (sample.motion === 'walking') {
            const key = `${sample.id}/${sample.pose}/${sample.frame}`;
            if (!frames[key]) frames[key] = canvas.toDataURL();
          }
        }
      }
      return { samples, frames };
    });
    const directions = new Set(samples.filter(s => s.motion === 'walking').map(s => s.pose));
    assert.ok(samples.filter(s => s.id === 'upper_agent').every(s => s.x >= 64), 'The manager wanders only inside the private room');
    assert.ok(samples.filter(s => s.id !== 'upper_agent').every(s => s.x <= 55), 'Idle workers stay in their shared office');
    for (const direction of ['front', 'back', 'left', 'right']) assert.ok(directions.has(`walk-${direction}`), `Walking has actual ${direction} artwork`);
    for (const id of ['upper_agent', ...workers]) {
      const own = samples.filter(s => s.id === id);
      const moving = own.filter(s => s.motion === 'walking');
      assert.equal(new Set(moving.map(s => s.frame)).size, 4, `${id} cycles through four full-body walking frames`);
      const direction = moving.find(s => s.pose === 'walk-back')?.pose ?? moving[0].pose;
      const images = [0, 1, 2, 3].map(frame => frames[`${id}/${direction}/${frame}`]);
      assert.ok(images.every(Boolean), `${id} has four captured frames in one direction`);
      assert.equal(new Set(images).size, 4, `${id} renders four distinct drawings instead of a static sliding sprite`);
      let stopped = false;
      for (let i = 1; i < own.length; i++) {
        const previous = own[i - 1], current = own[i];
        if (previous.motion === 'walking' && current.motion === 'walking' && current.distance >= previous.distance) {
          const actualTravel = Math.hypot(current.x - previous.x, (current.y - previous.y) / 1.6);
          const walked = current.distance - previous.distance;
          // Crossing a corner follows two aisle segments, longer than the endpoint chord.
          const cornerAllowance = current.pose === previous.pose ? 0.01 : 0.15;
          assert.ok(walked >= actualTravel - 0.003 && walked <= actualTravel + cornerAllowance,
            `Footsteps track aisle travel: ${JSON.stringify({ previous, current, walked, actualTravel })}`);
          const phase = current.distance / 1.25;
          if (Math.abs(phase - Math.round(phase)) > 0.001) {
            assert.equal(current.frame, Math.floor(phase) % 4, 'The painted step follows traveled distance');
          }
        }
        if (previous.motion === 'walking' && current.motion === 'idle') {
          stopped = true;
          assert.equal(current.distance, 0, 'Arriving resets the walking cycle');
          assert.equal(current.frame, 0, 'Standing uses a resting pose');
        }
        if (previous.motion === 'idle' && current.motion === 'idle') {
          assert.equal(current.frame, previous.frame, 'Feet do not cycle while standing');
        }
      }
      assert.ok(stopped, `${id} completes a walk and settles into an idle pose`);
      const firstSteps = moving.filter(s => s.distance > 0).slice(0, 20);
      const speeds = firstSteps.slice(1).map((s, i) => (s.distance - firstSteps[i].distance) / ((s.time - firstSteps[i].time) / 1000));
      assert.ok(speeds.at(-1) > speeds[0] + 2, `${id} accelerates into walking`);
    }
    const contactSheet = `<!doctype html><meta charset="utf-8"><title>Tomade walking frames</title><style>body{background:#ded4b4;font:14px sans-serif}section{display:inline-block;margin:12px;padding:12px;background:#eee6ce}img{width:128px;height:160px;image-rendering:pixelated}h2{font-size:14px}</style>${['upper_agent', ...workers].map(id => ['front', 'back', 'left', 'right'].map(direction => {
      const images = [0, 1, 2, 3].map(frame => frames[`${id}/walk-${direction}/${frame}`]);
      return images.every(Boolean) ? `<section><h2>${id} · ${direction}</h2>${images.map(src => `<img src="${src}">`).join('')}</section>` : '';
    }).join('')).join('')}`;
    await writeFile(`${screenshots}/walking-frames.html`, contactSheet);
    const qaPage = await f.context.newPage();
    await qaPage.setContent(contactSheet);
    await qaPage.screenshot({ path: `${screenshots}/walking-frames.png`, fullPage: true });
    await qaPage.close();
    await page.bringToFront();
    await page.screenshot({ path: `${screenshots}/desktop-walking-larger.png` });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.waitForFunction(() => !document.querySelector('.office-agent[data-motion="walking"]'));
    f.check();
    console.log('PASS walking: four directional poses, alternating full-body frames, distance-matched gait, acceleration, resting frames and larger click targets');
  } finally { await f.dispose(); }
}

async function twoRoomReporting(browser) {
  const f = await fixture(browser);
  const { page } = f;
  try {
    await submit(page, '세 직원이 조사한 뒤 부장실로 보고해줘.');
    await emit(page, [started('upper_agent'), ...workers.map(started)]);
    for (const id of ['upper_agent', ...workers]) await state(page, id, 'working', 'seated');
    await page.locator('#returnToOffice').click();
    await page.waitForFunction(() => !document.querySelector('#officeWorld').getAnimations().length);
    await page.screenshot({ path: `${screenshots}/two-room-working.png` });
    // Record the real renderer while mock completion events trigger the new route.
    await page.evaluate(() => {
      window.__reportSamples = [];
      window.__recordReports = true;
      const sample = () => {
        for (const node of document.querySelectorAll('.office-agent')) {
          window.__reportSamples.push({ id: node.dataset.agent, x: Number(node.dataset.x), y: Number(node.dataset.y) });
        }
        if (window.__recordReports) requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await emit(page, workers.map(id => completed(id, { [`${id}_report`]: `${id} 모의 조사 결과` })));
    await Promise.all(workers.map(id => state(page, id, 'done', 'idle')));
    const samples = await page.evaluate(() => { window.__recordReports = false; return window.__reportSamples; });
    for (const id of workers) {
      const own = samples.filter(sample => sample.id === id);
      const crossing = own.filter(sample => sample.x > 59 && sample.x < 61.4);
      assert.ok(crossing.length > 0, `${id} actually crosses the partition to report`);
      assert.ok(crossing.every(sample => sample.y > 48 && sample.y < 58), `${id} passes through the doorway instead of a solid wall`);
      assert.ok(own.some(sample => sample.x >= 69), `${id} reaches a reporting position in the manager room`);
    }
    assert.ok(samples.filter(sample => sample.id === 'upper_agent').every(sample => sample.x >= 64), 'The manager remains in the private room during research and reporting');
    await page.screenshot({ path: `${screenshots}/two-room-reporting.png` });
    await emit(page, [event('run.completed', { final_answer: finalAnswer })], true);
    await waitReady(page);
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    await state(page, 'upper_agent', 'done', 'idle');
    await page.locator('#returnToOffice').click();
    await page.waitForFunction(() => !document.querySelector('#officeWorld').getAnimations().length);
    await page.screenshot({ path: `${screenshots}/two-room-manager-arrived.png` });
    assert.equal(await page.locator('.agent-name[data-agent="upper_agent"]').isVisible(), true, 'The manager keeps a visible name after arriving');
    await page.locator(agent('upper_agent')).click();
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    f.check();
    console.log('PASS two rooms: working poses, doorway-only reporting routes, private manager and final conversation');
  } catch (error) {
    console.error('Two-room state:', await page.locator('.office-agent').evaluateAll(nodes => nodes.map(node => ({ ...node.dataset }))));
    await page.screenshot({ path: `${screenshots}/two-room-failure.png` });
    throw error;
  } finally { await f.dispose(); }
}

async function desktop(browser) {
  const f = await fixture(browser);
  const { page } = f;
  try {
    assert.equal(await page.locator('.office-agent').count(), 4, 'The office has exactly one manager and three workers');
    await page.evaluate(() => {
      // Exercise the page lifecycle handler only; this does not claim real browser
      // back/forward cache eligibility or a cache-backed navigation was verified.
      window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    });
    assert.equal(await page.locator('.office-agent').count(), 4, 'A persisted pagehide preserves the four live characters');
    const positions = await page.locator('.office-agent').evaluateAll(nodes => nodes.map(node => [node.dataset.x, node.dataset.y]));
    await page.waitForFunction(before => [...document.querySelectorAll('.office-agent')].every((node, index) =>
      node.dataset.x !== before[index][0] || node.dataset.y !== before[index][1]), positions, { timeout: 8000 });
    const names = await page.locator('.agent-name').evaluateAll(labels => labels.map(label => {
      const actor = document.querySelector(`.office-agent[data-agent="${label.dataset.agent}"]`);
      return { text: label.textContent, follows: label.style.left === actor.style.left && label.style.top === actor.style.top, visible: getComputedStyle(label).opacity === '1', depth: Number(getComputedStyle(label).zIndex) };
    }));
    assert.deepEqual(names.map(n=>n.text), ['부장', '패트 - 비즈니스', '매트 - 섹터', '게왹이 - 이벤트']);
    assert.ok(names.every(n=>n.follows && n.visible && n.depth >= 1000), 'Permanent names track all moving characters above furniture');
    assert.equal(f.apiRequests.some(request => request.path.startsWith('/api/portfolio')), false, 'Portfolio must not load on office entry');
    await page.screenshot({ path: `${screenshots}/desktop-idle.png` });

    await submit(page, '삼성전자 사업과 신규 계약을 조사해줘.');
    await emit(page, [started('upper_agent'), completed('upper_agent', {
      intent: 'research', research_plan: { planning_summary: '사업과 계약 조사', tasks: [
        { agent: 'business', objective: '사업 조사', questions: ['매출 추세는?'], completion_criteria: ['근거 확인'] },
        { agent: 'event_catalyst', objective: '계약 조사', questions: ['신규 계약은?'], completion_criteria: ['근거 확인'] },
      ] },
    }), started('request_parser'), completed('request_parser', { company_name: '삼성전자' }),
    event('node.skipped', { node: 'macro_sector' }), started('business'), started('event_catalyst')]);
    await state(page, 'business', 'working', 'seated');
    await state(page, 'event_catalyst', 'working', 'seated');
    await state(page, 'macro_sector', 'idle');
    await page.screenshot({ path: `${screenshots}/desktop-working.png` });
    await openWorker(page, 'business');
    await emit(page, [event('node.delta', { node: 'business', delta: '매출 근거를 확인 중입니다.' })]);
    await page.waitForFunction(() => document.querySelector('#journalOutput')?.textContent.includes('매출 근거'));
    await page.screenshot({ path: `${screenshots}/desktop-journal.png` });
    await closePanel(page, '#closeJournal');
    if (await page.locator('#managerDialog').isVisible()) await closePanel(page, '#closeManager');
    await emit(page, [
      completed('business', { business_report: businessReport }),
      completed('event_catalyst', { event_catalyst_report: eventReport }),
      started('upper_agent'), event('node.delta', { node: 'upper_agent', delta: '조사 내용을 정리했습니다.' }),
      completed('upper_agent', { final_answer: finalAnswer }), event('run.completed', { final_answer: finalAnswer }),
    ], true);
    await waitReady(page);
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#historyDialog').count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'managerDialog', 'The arriving manager receives keyboard focus');
    assert.ok((await page.locator('#managerDialog').textContent()).includes(finalAnswer), 'Completion automatically opens the manager with the final answer');
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#managerDialog')).opacity === '1');
    await page.screenshot({ path: `${screenshots}/desktop-completed.png` });
    await state(page, 'upper_agent', 'done');
    await state(page, 'business', 'done');
    await openWorker(page, 'business');
    assert.ok((await page.locator('#journalOutput').textContent()).includes(businessReport), 'A completed worker shows its own report');
    assert.ok((await page.locator('#journalState').textContent()).includes('완료'));
    await closePanel(page, '#closeJournal');

    await submit(page, '안녕, 너는 무엇을 해?');
    await emit(page, [started('upper_agent'), completed('upper_agent', { intent: 'general', final_answer: '안녕하세요. 기업 조사를 도와드려요.' }),
      event('run.completed', { final_answer: '안녕하세요. 기업 조사를 도와드려요.' })], true);
    await waitReady(page);
    await idle(page);

    await submit(page, '실패 경로를 확인해줘.');
    await emit(page, [started('business'), started('event_catalyst'), event('run.error', { node: 'business', message: '모의 외부 자료 오류' })], true);
    await waitReady(page);
    assert.equal(await page.locator('.office-agent[data-activity="working"]').count(), 0, 'An error must clear every active character');
    assert.ok((await page.locator('#managerDialog').textContent()).includes('모의 외부 자료 오류'));

    await submit(page, '연결 중단 경로를 확인해줘.');
    await emit(page, [started('business'), started('macro_sector')], true);
    await waitReady(page);
    assert.equal(await page.locator('.office-agent[data-activity="working"]').count(), 0, 'A truncated stream must clear every active character');
    assert.equal(await page.locator('#sessionState').getAttribute('data-state'), 'error');
    assert.match(await page.locator('#managerSpeech').textContent(), /연결|중단|완료/);

    if (await page.locator('#managerDialog').isVisible()) await closePanel(page, '#closeManager');
    await page.locator('#talkToManager').click();
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    await page.locator('#conversationSelect').selectOption('office-saved');
    await page.waitForFunction(() => document.querySelector('#chatMessages')?.textContent.includes('저장된 부장 답변'));
    assert.equal((await page.locator('#chatMessages').textContent()).includes(sourceMarker), false, 'Saved history excludes worker reports');
    await idle(page);
    await page.locator('#newConversation').click();
    await page.waitForFunction(() => document.querySelector('#conversationSelect')?.value.startsWith('office-new-'));
    await waitReady(page);
    assert.equal((await page.locator('#chatMessages').textContent()).includes(savedAnswer), false, 'New conversation clears the prior conversation');
    await page.locator('#deleteConversation').click();
    await page.waitForFunction(() => !document.querySelector('#conversationSelect')?.value.startsWith('office-new-'));
    await page.locator('#conversationSelect').selectOption('office-pending');
    await page.waitForFunction(() => document.querySelector('#conversationSelect')?.disabled === false && document.querySelector('#researchInput')?.disabled === true);
    assert.equal(await page.locator('#runButton').isDisabled(), true, 'Restored pending replies cannot be submitted twice');
    assert.equal(await page.locator('#deleteConversation').isDisabled(), true, 'Restored pending replies cannot be deleted');
    Object.assign(f.conversations.get('office-pending').messages.at(-1), {
      content: '다른 창에서 완료한 모의 답변입니다.', status: 'completed',
    });
    const pendingFetches = f.apiRequests.filter(request => request.path === '/api/conversations/office-pending').length;
    await closePanel(page, '#closeHistory');
    await page.locator('#talkToManager').click();
    await page.waitForFunction(() => document.querySelector('#chatMessages')?.textContent.includes('다른 창에서 완료한 모의 답변'));
    await waitReady(page);
    assert.equal(f.apiRequests.filter(request => request.path === '/api/conversations/office-pending').length, pendingFetches + 1,
      'Reopening pending history fetches the latest saved conversation');
    assert.equal(await page.locator('#deleteConversation').isDisabled(), false, 'Resolved pending history unlocks conversation actions');
    await page.locator('#conversationSelect').selectOption('office-main');
    await waitReady(page);
    await closePanel(page, '#closeHistory');
    await submit(page, '포트폴리오 창을 보는 동안 답변을 준비해줘.');
    await emit(page, [started('upper_agent')]);
    if (await page.locator('#managerDialog').isVisible()) await page.locator('#returnToOffice').click();
        await page.locator('#portfolioCharacter').click();
    await page.waitForFunction(() => document.querySelector('#portfolioStatus')?.textContent.includes('Toss 키'));
    assert.equal(f.apiRequests.filter(request => request.path === '/api/portfolio/configuration').length, 1, 'Portfolio configuration is loaded only after opening');
    await emit(page, [completed('upper_agent', { intent: 'general', final_answer: finalAnswer }), event('run.completed', { final_answer: finalAnswer })], true);
    await waitReady(page);
    assert.equal(await page.locator('#portfolioDialog').isVisible(), false, 'Completion closes the portfolio modal before showing the manager');
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'managerDialog');
    f.check();
    console.log('PASS desktop: idle movement, selected workers, seating, reports, modal completion, failures, conversations, pending refresh, lazy portfolio and persisted pagehide handler');
  } finally { await f.dispose(); }
}

async function focusMode(browser) {
  const f = await fixture(browser);
  const { page } = f;
  try {
    assert.equal(await page.locator('#managerDialog').isVisible(), false, 'The office is the initial view');
    const fullRoom = await page.locator('#officeWorld').boundingBox();
    await page.evaluate(() => {
      window.__originalOffice = document.querySelector('#officeWorld');
      window.__originalCharacters = [...document.querySelectorAll('.office-agent')];
      window.__roomFrames = [];
      window.__roomProbeDone = false;
      const stop = performance.now() + 700;
      const sample = () => {
        window.__roomFrames.push(document.querySelector('#officeWorld').getBoundingClientRect().width);
        if (performance.now() < stop) requestAnimationFrame(sample);
        else window.__roomProbeDone = true;
      };
      requestAnimationFrame(sample);
    });
    await page.locator(agent('upper_agent')).focus();
    await page.locator(agent('upper_agent')).press('Enter');
    await page.waitForFunction(() => window.__roomProbeDone);
    const miniRoom = await page.locator('#officeWorld').boundingBox();
    const chat = await page.locator('#managerDialog').boundingBox();
    assert.ok(Math.abs(chat.width / page.viewportSize().width - 0.64) < 0.01, 'The first split design reserves 64% for chat and 36% for the office');
    assert.ok(miniRoom.x >= chat.x + chat.width && miniRoom.width < fullRoom.width * 0.6, 'The same office shrinks into the right pane');
    assert.equal(await page.evaluate(({ from, to }) => window.__roomFrames.some(width => width < from - 10 && width > to + 10),
      { from: fullRoom.width, to: miniRoom.width }), true, 'Real animation frames include intermediate room sizes');
    assert.equal(await page.evaluate(() => document.querySelector('#officeWorld') === window.__originalOffice
      && [...document.querySelectorAll('.office-agent')].every((node, i) => node === window.__originalCharacters[i])), true,
    'Switching views preserves the original room and all four live characters');
    assert.equal(await page.locator('.office-agent, .portfolio-character').evaluateAll(nodes => nodes.every(node => node.inert)), true, 'Minimap characters leave keyboard navigation; the whole map is one return target');
    await page.locator('#researchInput').fill('아직 보내지 않은 질문');
    await page.locator('#returnToOffice').click();
    await page.waitForFunction(() => !document.querySelector('#officeWorld').getAnimations().length);
    assert.equal(await page.locator('#managerDialog').isVisible(), false);
    assert.ok(Math.abs((await page.locator('#officeWorld').boundingBox()).width - fullRoom.width) < 1, 'Clicking the miniature restores the full office');
    assert.equal(await page.locator('.office-agent').evaluateAll(nodes => nodes.every(node => !node.inert)), true);
    await page.locator('#talkToManager').click();
    assert.equal(await page.locator('#researchInput').inputValue(), '아직 보내지 않은 질문', 'Returning to the office preserves the draft');

    const firstQuestion = '삼성전자 실적에서 무엇을 먼저 보면 좋을까?';
    await submit(page, firstQuestion);
    assert.equal(await page.locator('#managerDialog').isVisible(), true, 'Sending keeps the focused conversation open');
    assert.equal(await page.locator('#chatHistory [data-role="user"]').last().textContent(), firstQuestion, 'The current user message is visible immediately');
    const firstReply = '사업별 영업이익의 흐름부터 살펴보세요.\n\n어느 사업에서 이익이 늘었는지 함께 보면 실적의 변화를 이해하기 쉬워요.';
    await emit(page, [started('upper_agent'), event('run.completed', { final_answer: firstReply })], true);
    await waitReady(page);
    await submit(page, '반도체 사업부터 같이 볼까?');
    await emit(page, [event('run.completed', { final_answer: '좋아요. 최근 분기의 흐름부터 살펴볼게요.' })], true);
    await waitReady(page);
    assert.equal(await page.locator('.chat-message[data-role="user"]').count(), 2, 'The transcript retains both questions without duplication');
    assert.equal(await page.locator('.chat-message[data-role="assistant"]').count(), 2, 'Each question has one assistant reply');
    assert.ok((await page.locator('#chatMessages').textContent()).includes(firstReply.split('\n')[0]));

    for (const viewport of [{ width: 1440, height: 1000 }, { width: 900, height: 900 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport);
      for (const selector of ['#managerDialog', '#conversationSelect', '#newConversation', '#deleteConversation', '#researchInput', '#runButton', '#returnToOffice', '#officeWorld']) await containedInViewport(page, selector);
      const kirbySize = await page.locator('#portfolioSprite').boundingBox();
      const currentRoom = await page.locator('#officeWorld').boundingBox();
      assert.ok(Math.abs(kirbySize.width-currentRoom.width*.0648)<=.5+1e-3,'Kirby shrinks proportionally inside every minimap');
      const edges = await page.locator('#chatMessages').evaluate(transcript => {
        const style = getComputedStyle(transcript);
        const right = transcript.getBoundingClientRect().left + transcript.clientWidth - parseFloat(style.paddingRight);
        return [...transcript.querySelectorAll('[data-role="user"] .message-content')].map(bubble => ({ expected: right, actual: bubble.getBoundingClientRect().right }));
      });
      assert.ok(edges.every(edge => Math.abs(edge.expected - edge.actual) < 2), 'Every user bubble reaches the right edge of the chat content column');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'The split view has no horizontal overflow');
      await page.screenshot({ path: `${screenshots}/focus-chat-${viewport.width}x${viewport.height}.png` });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await submit(page, '긴 답변과 스크롤을 확인해줘.');
    const longReply = Array.from({ length: 45 }, (_, i) => `문단 ${i + 1}. 사용자 화면 확인용 예시 문장입니다.`).join('\n\n');
    await emit(page, [started('upper_agent'), event('node.delta', { node: 'upper_agent', delta: longReply })]);
    await page.waitForFunction(() => document.querySelector('#managerSpeech').textContent.includes('문단 45'));
    await page.locator('#chatMessages').evaluate(node => { node.scrollTop = 0; });
    await emit(page, [event('run.completed', { final_answer: longReply + '\n\n마지막 문장.' })], true);
    await waitReady(page);
    assert.ok(await page.locator('#chatMessages').evaluate(node => node.scrollTop < 5), 'A completed answer does not pull a reader away from earlier messages');
    await page.reload();
    await waitReady(page);
    await page.locator('#talkToManager').click();
    assert.equal(await page.locator('.chat-message[data-role="user"]').count(), 3, 'Reloading restores the complete saved conversation');
    assert.equal(await page.locator('.chat-message[data-role="assistant"]').count(), 3, 'Reloaded replies do not duplicate the current reply');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.locator('#returnToOffice').click();
    await page.locator('#talkToManager').click();
    assert.equal(await page.locator('#officeWorld').evaluate(node => node.getAnimations().length), 0, 'Reduced motion skips the scaling transition');
    f.check();
    console.log('PASS focus mode: live-room scale transition, minimap return, draft preservation, right-aligned user messages, multi-turn streaming, saved history and responsive layouts');
  } finally { await f.dispose(); }
}

async function mobile(browser) {
  const f = await fixture(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const { page } = f;
  try {
    if (!await page.locator('#managerDialog').isVisible()) await page.locator('#talkToManager').click();
    await containedInViewport(page, '#researchInput');
    await containedInViewport(page, '#runButton');
    await page.screenshot({ path: `${screenshots}/mobile-dialogue.png` });
    await submit(page, '모바일에서 긴 조사 결과를 보여줘.');
    await emit(page, [started('business'), completed('business', {
      business_report: Array.from({ length: 24 }, (_, index) => `${index + 1}. ${businessReport}`).join('\n'),
    }), event('run.completed', { final_answer: Array(16).fill(finalAnswer).join('\n\n') })], true);
    await waitReady(page);
    await containedInViewport(page, '#researchInput');
    await containedInViewport(page, '#runButton');
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#managerDialog')).opacity === '1');
    await page.screenshot({ path: `${screenshots}/mobile-report.png` });
    await closePanel(page, '#closeManager');
    await openWorker(page, 'business');
    await containedInViewport(page, '#agentJournal');
    await containedInViewport(page, '[data-close="agentJournal"]');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Mobile must not overflow horizontally');
    await page.screenshot({ path: `${screenshots}/mobile-journal.png` });
    f.check();
    console.log('PASS mobile: manager input, send action, worker journal and close action fit 390×844');
  } finally { await f.dispose(); }
}

async function reducedMotion(browser) {
  const f = await fixture(browser, { reducedMotion: 'reduce' });
  const { page } = f;
  try {
    const stable = await page.evaluate(async () => {
      const snapshot = () => [...document.querySelectorAll('.office-agent')].map(node => `${node.dataset.x},${node.dataset.y},${node.dataset.frame}`);
      const before = snapshot();
      // Observe real animation frames without depending on wall-clock sleeps.
      for (let count = 0; count < 30; count++) await new Promise(requestAnimationFrame);
      return JSON.stringify(before) === JSON.stringify(snapshot());
    });
    assert.equal(stable, true, 'Reduced motion stops decorative character movement');
    await submit(page, '동작 줄이기 상태에서 조사해줘.');
    await emit(page, [started('upper_agent')]);
    await state(page, 'upper_agent', 'working', 'seated');
    await emit(page, workers.map(started));
    for (const id of workers) await state(page, id, 'working', 'seated');
    await page.locator('#returnToOffice').click();
    const seats = { business: [15.3, 49], macro_sector: [42, 49], event_catalyst: [17.1, 81] };
    for (const id of workers) {
      const position = await page.locator(agent(id)).evaluate(node => [Number(node.dataset.x), Number(node.dataset.y)]);
      assert.deepEqual(position, seats[id], `${id} sits at its relocated tomato-office desk`);
      assert.equal(await page.locator(`${agent(id)} .agent-sprite`).getAttribute('data-sprite-pose'), 'seated', 'Working agents select their reference seated artwork');
      const sprite = await page.locator(`${agent(id)} .agent-sprite`).boundingBox();
      assert.ok(Math.abs(sprite.width / sprite.height - 64 / 80) < 0.01, 'Seated faces preserve the sprite aspect ratio instead of being squeezed by flex layout');
      const hitArea = await page.locator(agent(id)).boundingBox();
      assert.ok(hitArea.width + 1 >= sprite.width && hitArea.height + 1 >= sprite.height, 'Seated click targets cover the enlarged artwork');
    }
    await page.screenshot({ path: `${screenshots}/tomato-office-all-workers-seated.png` });
    assert.equal(await page.locator('.office-agent[data-motion="walking"]').count(), 0, 'Reduced motion moves agents directly to their destinations');
    await openWorker(page, 'business');
    await emit(page, [
      completed('business', { business_report: businessReport }),
      completed('macro_sector', { macro_sector_report: '모의 매크로 조사 보고서입니다.' }),
      completed('event_catalyst', { event_catalyst_report: eventReport }),
      event('run.completed', { final_answer: finalAnswer }),
    ], true);
    await waitReady(page);
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#agentJournal').isVisible(), false, 'Completion closes a worker journal before showing the manager');
    for (const id of workers) await state(page, id, 'done', 'idle');
    const reportPositions = await page.locator('.office-agent:not([data-agent="upper_agent"])').evaluateAll(nodes => nodes.map(node => `${node.dataset.x},${node.dataset.y}`));
    assert.equal(new Set(reportPositions).size, 3, 'Completed workers use three distinct reporting positions');
    assert.ok((await page.locator('#managerDialog').textContent()).includes(finalAnswer));
    await page.screenshot({ path: `${screenshots}/reduced-motion-reporting.png` });
    f.check();
    console.log('PASS reduced motion: stable idle sprites, immediate seating, three distinct report positions and completion over an open worker journal');
  } finally { await f.dispose(); }
}

/** Exercise real frames and travel, without making portfolio requests during animation. */
async function kirbyWalking(browser, deviceScaleFactor = 1) {
  const f = await fixture(browser, { reducedMotion: 'reduce', deviceScaleFactor });
  const { page } = f;
  try {
    const idleSize = await page.locator('#portfolioSprite').evaluate(canvas => {
      const staff = document.querySelector('.office-agent[data-agent="business"] canvas');
      const room = document.querySelector('#officeWorld').getBoundingClientRect();
      const mat=document.querySelector('.office-agent[data-agent="macro_sector"] canvas');
      const pixels=mat.getContext('2d').getImageData(0,0,mat.width,mat.height).data;
      const samples=[];
      const occupied=(x,y)=>pixels[(y*mat.width+x)*4+3]>128;
      const dark=(x,y)=>Math.max(...pixels.slice((y*mat.width+x)*4,(y*mat.width+x)*4+3))<70;
      // Measure flat sections of Mat's existing artwork, not the Kirby configuration.
      for(const side of ['top','left']) {
        const vertical=side==='top',length=vertical?mat.width:mat.height,depth=vertical?mat.height:mat.width;
        const at=(u,v)=>vertical?[u,v]:[v,u];
        const starts=Array.from({length},(_,u)=>{for(let v=0;v<depth;v++)if(occupied(...at(u,v)))return v;return -1;});
        for(let u=1;u<length-1;u++) {
          const start=starts[u];if(start<0||starts[u-1]!==start||starts[u+1]!==start)continue;
          let ink=0;while(start+ink<depth&&occupied(...at(u,start+ink))&&dark(...at(u,start+ink)))ink++;
          if(ink>0&&ink<=8)samples.push(ink);
        }
      }
      const counts=new Map();for(const n of samples)counts.set(n,(counts.get(n)||0)+1);
      const matWeight=[...counts].sort((a,b)=>b[1]-a[1])[0][0];
      const expectedWeight=Math.max(1,Math.round(matWeight*mat.getBoundingClientRect().width/mat.width*devicePixelRatio));
      return { matWeight, expectedWeight, width: canvas.width, height: canvas.height, nativeWidth:Number(canvas.dataset.pixelWidth), dpr:devicePixelRatio, display:canvas.getBoundingClientRect().width,
        ratio: canvas.getBoundingClientRect().width / room.width,
        grid: canvas.getBoundingClientRect().height / Number(canvas.dataset.pixelHeight),
        staffGrid: staff.getBoundingClientRect().height / staff.height };
    });
    assert.equal(idleSize.matWeight,2,'Reference Mat uses a two-cell base outline');
    assert.equal(idleSize.nativeWidth,96); assert.equal(idleSize.width,idleSize.height);
    assert.ok(Math.abs(idleSize.width-idleSize.display*idleSize.dpr)<.02,'One canvas pixel maps to one device pixel without a second resize');
    assert.ok(Math.abs(idleSize.ratio-.0648)<.001 && Math.abs(idleSize.grid-idleSize.staffGrid)<=.5/96/idleSize.dpr+.001,
      'Smaller Kirby uses the same native pixel density as the four staff characters');
    await page.screenshot({path:`${screenshots}/kirby-small-office-dpr${deviceScaleFactor}.png`});
    await page.emulateMedia({reducedMotion:'no-preference'});
    const result = await page.evaluate(async()=>{
      const button = document.querySelector('#portfolioCharacter'), canvas = button.querySelector('canvas');
      const samples=[], frames={}, outlines={};
      const measureOutline=()=>{
        const p=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
        let boundary=0,broken=0;
        for(let y=1;y<canvas.height-1;y++) for(let x=1;x<canvas.width-1;x++) {
          const i=(y*canvas.width+x)*4;
          if(!p[i+3]) continue;
          if([[0,-1],[0,1],[-1,0],[1,0],[-1,-1],[1,-1],[-1,1],[1,1]].some(([dx,dy])=>!p[((y+dy)*canvas.width+x+dx)*4+3])) {
            boundary++;
            if(p[i]!==25||p[i+1]!==23||p[i+2]!==22||p[i+3]!==255)broken++;
          }
        }
        const weights={};
        const occupied=(x,y)=>p[(y*canvas.width+x)*4+3]>128;
        const dark=(x,y)=>Math.max(...p.slice((y*canvas.width+x)*4,(y*canvas.width+x)*4+3))<70;
        for(const side of ['top','bottom','left','right']) {
          const vertical=side==='top'||side==='bottom',length=vertical?canvas.width:canvas.height,depth=vertical?canvas.height:canvas.width;
          const at=(u,v)=>vertical?[u,side==='top'?v:canvas.height-1-v]:[side==='left'?v:canvas.width-1-v,u];
          const starts=Array.from({length},(_,u)=>{for(let v=0;v<depth;v++)if(occupied(...at(u,v)))return v;return -1;});
          const counts=new Map();
          for(let u=1;u<length-1;u++) {
            const start=starts[u];if(start<0||starts[u-1]!==start||starts[u+1]!==start)continue;
            let ink=0;while(start+ink<depth&&occupied(...at(u,start+ink))&&dark(...at(u,start+ink)))ink++;
            if(ink>0&&ink<=8)counts.set(ink,(counts.get(ink)||0)+1);
          }
          weights[side]=[...counts].sort((a,b)=>b[1]-a[1])[0]?.[0];
        }
        return {boundary,broken,weights};
      };
      const start=performance.now();
      while(performance.now()-start<13500){
        await new Promise(requestAnimationFrame);
        const sample={x:Number(button.dataset.x)*8,y:Number(button.dataset.y)*5,
          motion:button.dataset.motion,pose:canvas.dataset.spritePose,frame:Number(canvas.dataset.spriteFrame),
          distance:Number(button.dataset.walkDistance)};
        samples.push(sample);
        if(sample.motion==='walking'&&!frames[`${sample.pose}/${sample.frame}`]) {
          const key=`${sample.pose}/${sample.frame}`;
          frames[key]=canvas.toDataURL(); outlines[key]=measureOutline();
        }
      }
      return {samples,frames,outlines};
    });
    assert.ok(result.samples.every(s=>s.x>=355.99&&s.x<=418.01&&s.y>=337.99&&s.y<=405.01), 'Kirby stays clear of desks, walls and the door');
    for (const direction of ['front','back','right','left']) {
      const frames=[0,1,2,3].map(frame=>result.frames[`walk-${direction}/${frame}`]);
      assert.ok(frames.every(Boolean), `All four ${direction} step frames are drawn during real movement`);
      assert.equal(new Set(frames).size,4,`${direction} uses four distinct foot poses rather than sliding a static image`);
    }
    for(const [pose,outline] of Object.entries(result.outlines)) {
      for(const [side,weight]of Object.entries(outline.weights)) {
        assert.equal(weight,idleSize.expectedWeight, `${pose} ${side} matches Mat's measured outline at DPR ${deviceScaleFactor}`);
      }
      assert.ok(outline.boundary>50 && outline.broken===0, `${pose} has a continuous thin outer contour at DPR ${deviceScaleFactor}`);
    }
    for(const sample of result.samples.filter(s=>s.motion==='walking')) {
      assert.equal(sample.frame,Math.floor(sample.distance/28*4)%4,'Foot poses follow distance traveled');
    }
    const stops=result.samples.filter(s=>s.motion==='idle');
    assert.ok(stops.length>20&&stops.every(s=>s.frame===0),'Rest stops do not keep cycling the feet');
    assert.equal(f.apiRequests.some(r=>r.path.startsWith('/api/portfolio')),false,'Walking never starts a portfolio request');
    const contactSheet=`<!doctype html><meta charset="utf-8"><style>body{background:#e9e6db;font:16px sans-serif}section{margin:16px}img{width:${idleSize.width*3}px;height:${idleSize.height*3}px;image-rendering:pixelated}</style><h1>Kirby · four steps per direction</h1>${['front','back','right','left'].map(direction=>`<section><h2>${direction}</h2>${[0,1,2,3].map(frame=>`<img src="${result.frames[`walk-${direction}/${frame}`]}">`).join('')}</section>`).join('')}`;
    await writeFile(`${screenshots}/kirby-walking-frames-dpr${deviceScaleFactor}.html`,contactSheet);
    const viewer=await f.context.newPage(); await viewer.setContent(contactSheet);
    await viewer.screenshot({path:`${screenshots}/kirby-walking-frames-dpr${deviceScaleFactor}.png`,fullPage:true}); await viewer.close();
    await page.bringToFront();
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>document.querySelector('#portfolioCharacter').dataset.motion==='idle');
    const still=await page.locator('#portfolioCharacter').getAttribute('style');
    await page.waitForTimeout(250);
    assert.equal(await page.locator('#portfolioCharacter').getAttribute('style'),still,'Reduced motion freezes position');
    assert.equal(await page.locator('#portfolioSprite').getAttribute('data-sprite-pose'),'front');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForFunction(()=>document.querySelector('#portfolioCharacter').dataset.motion==='walking');
    await page.locator('#portfolioCharacter').hover();
    const hovered=await page.locator('#portfolioCharacter').getAttribute('style');
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#portfolioCharacter').getAttribute('style'),hovered,'Pointer hover stops Kirby for selection');
    await page.mouse.move(0,0);
    await page.keyboard.press('Tab');
    await page.locator('#portfolioCharacter').focus();
    const focused=await page.locator('#portfolioCharacter').getAttribute('style');
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#portfolioCharacter').getAttribute('style'),focused,'Keyboard focus pauses a moving click target');
    await page.locator('#portfolioCharacter').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#portfolioStatus').textContent.includes('Toss 키'));
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#portfolioCharacter').getAttribute('style'),focused,'The open portfolio panel keeps Kirby at rest');
    await page.locator('[data-close="portfolioDialog"]').click();
    await page.locator('#talkToManager').focus();
    await page.waitForFunction(before=>document.querySelector('#portfolioCharacter').getAttribute('style')!==before,focused);
    await page.evaluate(()=>{
      Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    const hidden=await page.locator('#portfolioCharacter').getAttribute('style');
    await page.waitForTimeout(200);
    assert.equal(await page.locator('#portfolioCharacter').getAttribute('style'),hidden,'Hidden pages stop Kirby movement');
    await page.evaluate(()=>{
      delete document.hidden;
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(before=>document.querySelector('#portfolioCharacter').getAttribute('style')!==before,hidden);
    f.check();
    console.log(`PASS Kirby DPR ${deviceScaleFactor}: device-resolution rendering, 16 unbroken contours with Mat-matched top/side/sole weight, bounded travel, rest/focus/modal/reduced/hidden pause, resume and lazy portfolio`);
  } finally { await f.dispose(); }
}

async function workspacePanels(browser) {
  const report = {
    fetched_at: '2026-09-16T00:00:00Z', source: '모의 계좌', scope: '국내 보유 주식',
    total_amount: '12345678', total_purchase_amount: '10000000', total_profit_loss: '2345678', total_profit_loss_pct: '23.45678',
    top_one_pct: '60', top_three_pct: '100', excluded: [],
    holdings: [{ symbol: '005930', name: '모의 삼성전자', amount: '7407407', purchase_amount: '6000000', profit_loss: '1407407', profit_loss_pct: '23.45678', weight_pct: '60', sector: '반도체', reason: '메모리 및 반도체 사업을 기준으로 한 모의 분류입니다.' }],
    sectors: [{sector:'반도체',amount:'12345678',weight_pct:'100'}],
    explanation: {summary:'모의 포트폴리오 분석입니다.',observations:Array.from({length:12},(_,i)=>`${i+1}. 집중도와 투자 목적을 함께 확인하는 모의 설명입니다.`),limitations:[]},
  };
  for (const variant of ['populated','unconfigured','error']) {
    const f = await fixture(browser, { reducedMotion: 'reduce' });
    const { page } = f;
    let diagnoses = 0;
    try {
      assert.equal(f.apiRequests.some(r=>r.path.startsWith('/api/portfolio')),false);
      await page.waitForFunction(()=>document.querySelector('#portfolioSprite').dataset.spriteState==='ready');
      const kirby = await page.locator('#portfolioSprite').evaluate(canvas=>{
        const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
        let pink=0,clear=0,cyan=0;
        for(let i=0;i<pixels.length;i+=4){
          if(!pixels[i+3]) { clear++; continue; }
          if(pixels[i]>170 && pixels[i]-pixels[i+1]>25 && pixels[i+2]>100) pink++;
          if(pixels[i+1]-pixels[i]>70 && pixels[i+2]-pixels[i]>70 && pixels[i+1]>150) cyan++;
        }
        return {pink,clear,cyan,grid:Number(canvas.dataset.pixelGrid)};
      });
      assert.ok(kirby.pink>100 && kirby.clear>100 && kirby.cyan===0, 'Kirby retains pink color with a transparent keyed backdrop');
      assert.equal(kirby.grid,.54);
      assert.equal(await page.locator('.office-agent').count(),4,'Kirby is a portfolio entry, not another research worker');
      await containedInViewport(page,'#portfolioCharacter');
      const place = await page.locator('#portfolioCharacter').evaluate(button=>({left:button.offsetLeft/button.parentElement.clientWidth, top:button.offsetTop/button.parentElement.clientHeight}));
      assert.ok(Math.abs(place.left-.445)<.002 && Math.abs(place.top-.81)<.002, 'Kirby occupies the empty lower-right area of the employee office');
      await page.route('**/api/portfolio/configuration', route=>route.fulfill({json:{configured:variant!=='unconfigured'}}));
      await page.route('**/api/portfolio/diagnose', route=>{
        diagnoses++;
        return route.fulfill(variant==='error'?{status:503,json:{detail:'모의 계좌 연결 오류입니다. 잠시 후 다시 확인해 주세요.'}}:{json:report});
      });
      for (const viewport of variant==='populated' ? [{width:1440,height:1000},{width:390,height:844}] : [{width:390,height:844}]) {
        await page.setViewportSize(viewport);
        await page.waitForFunction(()=>{
          const canvas=document.querySelector('#portfolioSprite'), room=document.querySelector('#officeWorld');
          return canvas.width===Math.round(parseFloat(getComputedStyle(room).width)*.0648*devicePixelRatio);
        });
        const nameGap = await page.locator('#portfolioCharacter').evaluate(button=>button.querySelector('canvas').getBoundingClientRect().top-button.querySelector('.character-label').getBoundingClientRect().bottom);
        assert.ok(nameGap>=0 && nameGap<10,'The name follows the smaller artwork rather than the minimum touch-target height');
        if(variant==='populated') {
          await page.screenshot({path:`${screenshots}/office-navigation-${viewport.width}.png`});
          await page.locator('#talkToManager').click();
          await page.locator('#conversationSelect').selectOption('office-saved');
          await page.waitForFunction(()=>document.querySelector('#chatMessages')?.textContent.includes('저장된 부장 답변'));
          await waitReady(page);
          const history = await page.locator('#managerDialog').evaluate(dialog=>{
            const area=dialog.querySelector('#chatMessages'), user=area.querySelector('[data-role=user] .message-content'), reply=area.querySelector('[data-role=assistant]');
            return {background:getComputedStyle(dialog).backgroundColor, padding:parseFloat(getComputedStyle(area).paddingRight), right:area.getBoundingClientRect().right-user.getBoundingClientRect().right, separated:user.getBoundingClientRect().left>reply.getBoundingClientRect().left};
          });
          assert.equal(history.background,'rgb(252, 252, 250)');
          assert.ok(Math.abs(history.right-history.padding)<2 && history.separated,'History questions align right like the manager conversation');
          await page.screenshot({path:`${screenshots}/history-modern-${viewport.width}.png`});
          if(viewport.width===1440){
            await page.locator('#newConversation').click();
            await page.waitForFunction(()=>document.querySelector('#conversationSelect').value.startsWith('office-new-'));
            await waitReady(page);
            await page.locator('#closeManager').click();
            await page.locator('#talkToManager').click();
            await page.locator('#deleteConversation').click();
            await page.waitForFunction(()=>!document.querySelector('#conversationSelect').value.startsWith('office-new-'));
            await waitReady(page);
          }
          await page.locator('#closeManager').click();
        }
        if (await page.locator('#managerDialog').isVisible()) await page.locator('#returnToOffice').click();
        await page.locator('#portfolioCharacter').click();
        await page.waitForFunction(()=>document.querySelector('#portfolioResult').getAttribute('aria-busy')==='false');
        if(variant==='populated') {
          assert.equal(await page.locator('.portfolio-metrics dt').count(),4);
          assert.ok((await page.locator('.portfolio-metrics').textContent()).includes('12,345,678원'));
          assert.equal(await page.locator('.portfolio-table-scroll').count(),2);
        } else {
          assert.ok((await page.locator('#portfolioStatus').textContent()).includes(variant==='error'?'모의 계좌 연결 오류':'Toss 키'));
        }
        const layout=await page.locator('#portfolioDialog').evaluate(dialog=>{
          const b=dialog.getBoundingClientRect(), body=dialog.querySelector('.dialog-scroll');
          const head=dialog.querySelector('.journal-heading').getBoundingClientRect().top;
          body.scrollTop=body.scrollHeight;
          return {background:getComputedStyle(dialog).backgroundColor, inside:b.left>=0&&b.right<=innerWidth&&b.top>=0&&b.bottom<=innerHeight, overflow:body.scrollWidth>body.clientWidth+1, fixedHeader:head===dialog.querySelector('.journal-heading').getBoundingClientRect().top};
        });
        assert.equal(layout.background,'rgb(252, 252, 250)');
        assert.ok(layout.inside && !layout.overflow && layout.fixedHeader,'The responsive white report scrolls without moving its close button');
        await page.locator('.dialog-scroll').evaluate(node=>node.scrollTop=0);
        await page.screenshot({path:`${screenshots}/portfolio-modern-${variant}-${viewport.width}.png`});
        await page.locator('[data-close="portfolioDialog"]').click();
      }
      assert.equal(diagnoses,variant==='unconfigured'?0:1,'Restyling never triggers another diagnosis when reopening');
      f.check();
    } finally { await f.dispose(); }
  }
  console.log('PASS workspace panels: in-chat history selection, right-aligned questions, report metrics, fixed headers, responsive tables, unconfigured/error states and one mocked diagnosis');
}


await mkdir(screenshots, { recursive: true });
const browser = await playwright.chromium.launch({ headless: true, channel: process.env.OFFICE_BROWSER_CHANNEL });
try {
  await fullRoomFitting(browser);
  await modularObjects(browser);
  await spriteRendering(browser);
  await walkingMotion(browser);
  await twoRoomReporting(browser);
  await focusMode(browser);
  await desktop(browser);
  await workspacePanels(browser);
  await kirbyWalking(browser);
  await kirbyWalking(browser, 2);
  await mobile(browser);
  await reducedMotion(browser);
  console.log(`Office UI regression checks passed. Screenshots: ${pathToFileURL(screenshots).href}`);
} finally {
  await browser.close();
}
