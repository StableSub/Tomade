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
  await page.waitForFunction(() => {
    const background = document.querySelector('.office-background');
    return background?.complete && background.naturalWidth > 0;
  });
  await page.waitForFunction(() => [...document.querySelectorAll('.agent-sprite, #managerPortrait')]
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
  const selector = { '#closeJournal': '[data-close="agentJournal"]', '#closeHistory': '[data-close="historyDialog"]' }[id] ?? id;
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
    const imageAspect = await page.locator('.office-background').evaluate(image => image.naturalWidth / image.naturalHeight);
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
      await containedInViewport(page, '.office-background');
      const room = await page.locator('.office-background').boundingBox();
      for (const id of ['upper_agent', ...workers]) {
        await containedInViewport(page, agent(id));
        const sprite = await page.locator(`${agent(id)} .agent-sprite`).boundingBox();
        const hitArea = await page.locator(agent(id)).boundingBox();
        const relativeHeight = { upper_agent: 0.12, business: 0.108, macro_sector: 0.108, event_catalyst: 0.084 }[id];
        assert.ok(Math.abs(sprite.height / room.width - relativeHeight) < 0.001, 'Each cast member keeps its intended size relative to the furniture');
        assert.ok(Math.abs(sprite.width / sprite.height - 0.8) < 0.01, 'Larger characters retain their face and body proportions');
        assert.ok(hitArea.width + 1 >= sprite.width && hitArea.height + 1 >= sprite.height, 'The click target grows with the character');
      }
      const overflow = await page.locator('#officeScroll').evaluate(room => ({
        horizontal: room.scrollWidth - room.clientWidth,
        vertical: room.scrollHeight - room.clientHeight,
      }));
      assert.ok(overflow.horizontal <= 1 && overflow.vertical <= 1, `No room panning should be needed: ${JSON.stringify(overflow)}`);
      await page.screenshot({ path: `${screenshots}/tomato-office-${viewport.width}x${viewport.height}.png` });
    }
    f.check();
    console.log('PASS room fitting: both rooms and four interactive agents fit desktop, portrait, mobile and landscape without panning');
  } finally { await f.dispose(); }
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
    assert.equal(await page.locator(`${agent('upper_agent')} .agent-talk`).isVisible(), true, 'The manager has a clear conversation entry point after arriving');
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
    await page.locator('#openHistory').click();
    await page.locator('#historyDialog').waitFor({ state: 'visible' });
    await emit(page, [
      completed('business', { business_report: businessReport }),
      completed('event_catalyst', { event_catalyst_report: eventReport }),
      started('upper_agent'), event('node.delta', { node: 'upper_agent', delta: '조사 내용을 정리했습니다.' }),
      completed('upper_agent', { final_answer: finalAnswer }), event('run.completed', { final_answer: finalAnswer }),
    ], true);
    await waitReady(page);
    await page.locator('#managerDialog').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#historyDialog').isVisible(), false, 'Completion closes the history modal so it cannot obscure the answer');
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
    await page.locator('#openHistory').click();
    await page.locator('#historyDialog').waitFor({ state: 'visible' });
    await page.locator('#conversationSelect').selectOption('office-saved');
    await page.waitForFunction(() => document.querySelector('#historyEntries')?.textContent.includes('저장된 부장 답변'));
    assert.equal((await page.locator('#historyEntries').textContent()).includes(sourceMarker), false, 'Saved history excludes worker reports');
    await idle(page);
    await page.locator('#newConversation').click();
    await page.waitForFunction(() => document.querySelector('#conversationSelect')?.value.startsWith('office-new-'));
    await waitReady(page);
    assert.equal((await page.locator('#historyEntries').textContent()).includes(savedAnswer), false, 'New conversation clears the prior conversation');
    if (!await page.locator('#historyDialog').isVisible()) await page.locator('#openHistory').click();
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
    await page.locator('#openHistory').click();
    await page.waitForFunction(() => document.querySelector('#historyEntries')?.textContent.includes('다른 창에서 완료한 모의 답변'));
    await waitReady(page);
    assert.equal(f.apiRequests.filter(request => request.path === '/api/conversations/office-pending').length, pendingFetches + 1,
      'Reopening pending history fetches the latest saved conversation');
    assert.equal(await page.locator('#deleteConversation').isDisabled(), false, 'Resolved pending history unlocks conversation actions');
    await page.locator('#conversationSelect').selectOption('office-main');
    await waitReady(page);
    await closePanel(page, '#closeHistory');
    await submit(page, '포트폴리오 창을 보는 동안 답변을 준비해줘.');
    await emit(page, [started('upper_agent')]);
    await page.locator('#openPortfolio').click();
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
    assert.equal(await page.locator('.office-agent').evaluateAll(nodes => nodes.every(node => node.inert)), true, 'Minimap characters leave keyboard navigation; the whole map is one return target');
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
      for (const selector of ['#managerDialog', '#researchInput', '#runButton', '#returnToOffice', '.office-background']) await containedInViewport(page, selector);
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

await mkdir(screenshots, { recursive: true });
const browser = await playwright.chromium.launch({ headless: true, channel: process.env.OFFICE_BROWSER_CHANNEL });
try {
  await fullRoomFitting(browser);
  await walkingMotion(browser);
  await twoRoomReporting(browser);
  await focusMode(browser);
  await desktop(browser);
  await mobile(browser);
  await reducedMotion(browser);
  console.log(`Office UI regression checks passed. Screenshots: ${pathToFileURL(screenshots).href}`);
} finally {
  await browser.close();
}
