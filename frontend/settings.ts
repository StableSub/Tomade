/** 실행 중인 백엔드의 호출 방식과 프로젝트 전용 구독 로그인을 표시한다. */
type Provider = "openai" | "openrouter" | "openai_codex";
interface Connection { provider: Provider | null; auth_mode: string | null; models: Record<string, string>; busy: boolean }
interface Login { id: string; state: string; message: string; user_code: string | null; interval: number; expires_in: number }
interface Settings extends Connection { api_keys: Record<string, boolean>; codex: { state: string; message: string }; login: Login | null }
const labels: Record<Provider, string> = { openai: "OpenAI · API Key", openrouter: "OpenRouter · API Key", openai_codex: "Codex · 구독 인증" };
const roles: Record<string, string> = { planner: "부장 / 계획", parser: "질문 해석", worker: "조사", summary: "대화 요약" };
const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const dialog = el<HTMLDialogElement>("settingsDialog");
const selector = el<HTMLSelectElement>("modelProvider");
const apply = el<HTMLButtonElement>("applyProvider");
const start = el<HTMLButtonElement>("startCodexLogin");
const notice = el("settingsNotice");
let settings: Settings | null = null;
let login: Login | null = null;
let timer: number | undefined;
let generation = 0;
let changing = false;

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/settings${path}`, {
    method, cache: "no-store", headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let message = "설정을 불러오지 못했습니다. 서버 실행 상태를 확인하세요.";
    try { const data = await response.json(); if (typeof data.detail === "string") message = data.detail; } catch { /* HTML 오류 응답도 동일하게 처리한다. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "연결에 실패했습니다. 잠시 후 다시 시도하세요.";
}

function renderChoice() {
  const provider = selector.value as Provider;
  const ready = !!settings && (provider === "openai_codex"
    ? ["signed_in", "expired"].includes(settings.codex.state) : settings.api_keys[provider]);
  apply.disabled = changing || !ready || !!settings?.busy || settings?.provider === provider;
  start.disabled = changing || !settings || login?.state === "pending";
  el("providerAvailability").textContent = !settings ? "서버 상태를 확인하세요." : settings.busy
    ? "답변 또는 진단이 진행 중입니다. 완료 후 새로고침해 변경하세요."
    : provider === "openai_codex" ? (ready ? "저장된 구독 인증을 사용합니다. 계정의 구독 한도를 소비합니다." : "아래에서 먼저 구독 로그인을 완료하세요.")
    : ready ? "서버에 API 키가 설정되어 있습니다. API 사용량에 따라 과금됩니다." : "서버의 .env에 해당 API 키를 설정해주세요.";
}

function renderSettings(resetSelection = false) {
  const label = settings?.provider ? labels[settings.provider] : "인증 방식 미설정";
  el("connectionBadge").textContent = label;
  el("activeConnection").textContent = label;
  el("codexLoginStatus").textContent = settings?.codex.message ?? "상태 확인 불가";
  if (resetSelection && settings?.provider) selector.value = settings.provider;
  const list = el("modelRoles"); list.replaceChildren();
  for (const [role, model] of Object.entries(settings?.models ?? {})) {
    const term = document.createElement("dt"); term.textContent = roles[role] ?? role;
    const value = document.createElement("dd"); value.textContent = model;
    list.append(term, value);
  }
  renderChoice();
}

function renderLogin() {
  el("deviceLogin").hidden = login?.state !== "pending";
  el("deviceUserCode").textContent = login?.user_code ?? "";
  el("deviceLoginMessage").textContent = login ? `${login.message} (남은 시간 약 ${Math.ceil(login.expires_in / 60)}분)` : "";
  if (login && login.state !== "pending") notice.textContent = login.message;
  renderChoice();
}

function schedulePoll() {
  window.clearTimeout(timer);
  if (!dialog.open || login?.state !== "pending") return;
  const current = generation; const id = login.id;
  timer = window.setTimeout(async () => {
    try {
      const result = await request<Login>(`/codex/login/${id}/poll`, "POST");
      if (current !== generation || !dialog.open) return;
      login = result; renderLogin();
      if (result.state === "completed") {
        await refresh(); selector.value = "openai_codex"; renderChoice();
      } else schedulePoll();
    } catch (error) { if (current === generation) notice.textContent = errorMessage(error); }
  }, Math.max(1, login.interval) * 1000);
}

async function refresh(resetSelection = false) {
  try {
    settings = await request<Settings>("/models");
    login = settings.login;
    renderSettings(resetSelection); renderLogin(); schedulePoll();
  } catch (error) {
    settings = null; renderChoice();
    el("connectionBadge").textContent = "연결 방식 확인 불가";
    el("activeConnection").textContent = "상태 확인 불가";
    notice.textContent = errorMessage(error);
  }
}

/** 해당 요청의 run.started에 서버가 포함한 인증 방식. 인증 성공 판정과는 구분한다. */
export function showRequestConnection(value: unknown) {
  if (!value || typeof value !== "object" || !("provider" in value)) return;
  const provider = value.provider;
  if (typeof provider !== "string" || !(provider in labels)) return;
  const label = labels[provider as Provider];
  el("connectionBadge").textContent = label;
  el("lastRequestConnection").hidden = false;
  el("lastRequestConnection").textContent = `최근 대화 요청 방식: ${label}`;
}

el("openSettings").addEventListener("click", () => {
  notice.textContent = "";
  dialog.showModal(); void refresh(true);
});
dialog.addEventListener("close", () => { generation++; window.clearTimeout(timer); });
selector.addEventListener("change", renderChoice);
el("refreshSettings").addEventListener("click", () => { notice.textContent = ""; void refresh(); });
apply.addEventListener("click", async () => {
  changing = true; notice.textContent = "호출 방식을 적용하고 있습니다…"; renderChoice();
  try {
    settings = await request<Settings>("/models", "PUT", { provider: selector.value });
    renderSettings(true);
    notice.textContent = "적용했습니다. 다음 요청부터 이 방식으로 호출합니다.";
  } catch (error) { notice.textContent = errorMessage(error); }
  finally { changing = false; renderChoice(); }
});
start.addEventListener("click", async () => {
  generation++; const current = generation;
  changing = true; notice.textContent = "로그인 코드를 발급하고 있습니다…"; renderChoice();
  try {
    const result = await request<Login>("/codex/login", "POST");
    if (current !== generation) return;
    login = result; notice.textContent = ""; renderLogin(); schedulePoll();
  } catch (error) { if (current === generation) notice.textContent = errorMessage(error); }
  finally { changing = false; renderChoice(); }
});
el("cancelCodexLogin").addEventListener("click", async () => {
  if (!login) return;
  const id = login.id; generation++; window.clearTimeout(timer);
  changing = true; renderChoice();
  try {
    await request(`/codex/login/${id}`, "DELETE"); login = null; renderLogin();
    notice.textContent = "로그인 요청을 취소했습니다.";
  } catch (error) { notice.textContent = errorMessage(error); }
  finally { changing = false; renderChoice(); }
});
window.addEventListener("focus", () => { if (!changing) void refresh(); });
window.addEventListener("pagehide", () => { generation++; window.clearTimeout(timer); });
void refresh();
