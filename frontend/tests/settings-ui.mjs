/** Mock API로 로그인·방식 전환·모바일 설정창을 검증한다. 실제 계정/모델 호출은 차단한다. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const browser = await chromium.launch({ headless: true, channel: process.env.OFFICE_BROWSER_CHANNEL });
const out = '/tmp/stock-settings-ui';
await mkdir(out, { recursive: true });
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 } });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let loggedIn = false; let provider = 'openai'; let busy = false; let login = null;
    let authFailure = false; let serverDown = false;
    const settings = () => ({ provider, auth_mode: provider === 'openai_codex' ? 'subscription' : 'api_key',
      models: { planner: 'gpt-5.6-luna', parser: 'gpt-5.6-luna', worker: 'gpt-5.6-luna', summary: 'gpt-5.6-luna' },
      busy, api_keys: { openai: true, openrouter: false },
      codex: { state: loggedIn ? 'signed_in' : 'signed_out', message: loggedIn ? '구독 로그인이 저장돼 있습니다.' : '저장된 구독 로그인이 없습니다.' }, login });
    await context.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname; const method = route.request().method();
      const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (path === '/api/settings/models') {
        if (serverDown) return json({ detail: '서버 연결 실패' }, 503);
        if (method === 'PUT') { if (busy) return json({ detail: '진행 중인 답변이 끝난 뒤 변경하세요.' }, 409); provider = route.request().postDataJSON().provider; }
        return json(settings());
      }
      if (path === '/api/settings/codex/login') {
        if (authFailure) return json({ detail: '기기 코드 로그인을 활성화하세요.' }, 502);
        login = { id: 'mock-login', state: 'pending', user_code: 'MOCK-CODE', interval: 1, expires_in: 900, message: '브라우저에서 로그인하세요.' };
        return json(login);
      }
      if (path.endsWith('/mock-login/poll')) {
        loggedIn = true; login = { ...login, state: 'completed', user_code: null, message: '로그인 완료. 이 방식 사용을 눌러 적용하세요.' }; return json(login);
      }
      if (path.endsWith('/mock-login') && method === 'DELETE') { login = null; return json({ cancelled: true }); }
      if (path === '/api/conversations') return json([{ id: 'mock-chat', title: '새 대화' }]);
      if (path === '/api/conversations/mock-chat') return json({ id: 'mock-chat', title: '새 대화', messages: [] });
      throw new Error(`Unexpected API request: ${method} ${path}`);
    });
    await page.goto(process.env.OFFICE_BASE_URL || 'http://127.0.0.1:5173');
    await page.getByRole('button', { name: '모델 연결 설정', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('activeConnection').textContent === 'OpenAI · API Key');
    await page.selectOption('#modelProvider', 'openai_codex');
    assert.equal(await page.locator('#applyProvider').isDisabled(), true);
    await page.locator('#startCodexLogin').click();
    await page.locator('#deviceUserCode').filter({ hasText: 'MOCK-CODE' }).waitFor();
    await page.screenshot({ path: `${out}/login-${width}.png` });
    await page.waitForFunction(() => document.getElementById('codexLoginStatus').textContent.includes('저장돼'));
    assert.equal(await page.locator('#connectionBadge').textContent(), 'OpenAI · API Key', 'Login alone must not change active provider');
    await page.locator('#applyProvider').click();
    await page.waitForFunction(() => document.getElementById('connectionBadge').textContent === 'Codex · 구독 인증');
    await page.screenshot({ path: `${out}/connected-${width}.png` });
    assert.equal(await page.locator('#modelRoles dd').count(), 4);
    const box = await page.locator('#settingsDialog').boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width && box.y >= 0);
    await page.keyboard.press('Escape'); assert.equal(await page.locator('#settingsDialog').isVisible(), false);
    assert.equal(await page.locator('#openSettings').evaluate(el => document.activeElement === el), true);
    await page.locator('#openSettings').click();
    busy = true; await page.locator('#refreshSettings').click(); await page.selectOption('#modelProvider', 'openai');
    await page.waitForFunction(() => document.getElementById('providerAvailability').textContent.includes('진행 중'));
    assert.equal(await page.locator('#applyProvider').isDisabled(), true);
    busy = false; login = null; await page.locator('#refreshSettings').click();
    await page.waitForFunction(() => !document.getElementById('startCodexLogin').disabled);
    await page.locator('#startCodexLogin').click(); await page.locator('#deviceLogin').waitFor();
    await page.locator('#cancelCodexLogin').click();
    await page.waitForFunction(() => document.getElementById('settingsNotice').textContent.includes('취소'));
    authFailure = true; await page.locator('#startCodexLogin').click();
    await page.waitForFunction(() => document.getElementById('settingsNotice').textContent.includes('활성화'));
    serverDown = true; await page.locator('#refreshSettings').click();
    await page.waitForFunction(() => document.getElementById('connectionBadge').textContent === '연결 방식 확인 불가');
    assert.deepEqual(errors, []);
    await context.close(); console.log(`settings UI ${width}px passed`);
  }
} finally { await browser.close(); }
