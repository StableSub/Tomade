import { OfficeScene, paintPortrait, type AgentActivity, type AgentId } from "./office-scene";
import { OfficeRoom } from "./office-room";
import { createOfficeCamera } from "./office-camera";
import { PortfolioCharacter } from "./portfolio-character";
import { showRequestConnection } from "./settings";

type WorkerId = Exclude<AgentId, "upper_agent">;
type NodeName = AgentId | WorkerId | "request_parser";
type NodeState = "idle" | "running" | "done" | "skipped" | "error";
type NodeOutput = string | Record<string, unknown>;
type Phase = "ready" | "planning" | "validating" | "researching" | "synthesizing" | "done" | "error" | "pending";
interface SseEvent { type: string; data: Record<string, unknown> }
interface Conversation { id: string; title: string }
interface SavedMessage { role: "user" | "assistant"; content: string; status: "pending" | "completed" | "error" | "interrupted" }
const workers: WorkerId[] = ["business", "macro_sector", "event_catalyst", "technical", "sentiment"];
const nodes: NodeName[] = ["upper_agent", "request_parser", ...workers];
const labels: Record<NodeName, string> = { upper_agent: "부장 Agent", request_parser: "질문 확인", business: "패트 - 비즈니스", macro_sector: "매트 - 섹터", event_catalyst: "게왹이 - 이벤트", technical: "뚱이 - 기술 분석", sentiment: "스폰지밥 - 투자 심리" };
const workerLabels: Record<WorkerId, string> = { business: "비즈니스", macro_sector: "매크로·섹터", event_catalyst: "이벤트", technical: "기술 분석", sentiment: "YouTube 반응" };
const reportFields: Partial<Record<NodeName, string>> = { business: "business_report", macro_sector: "macro_sector_report", event_catalyst: "event_catalyst_report", technical: "technical_report", sentiment: "sentiment_report", upper_agent: "final_answer" };
const reportStatusLabels: Record<string, string> = { complete: "조사 완료", partial: "일부 근거 확보", unavailable: "근거 없음", error: "조사 오류" };
const welcome = "어떤 기업을 함께 살펴볼까요?";

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`필수 화면 요소를 찾을 수 없습니다: ${id}`);
  return found as T;
}
const form = element<HTMLFormElement>("researchForm");
const researchInput = element<HTMLTextAreaElement>("researchInput");
const runButton = element<HTMLButtonElement>("runButton");
const managerDialog = element("managerDialog");
const managerSpeech = element("managerSpeech");
const chatMessages = element("chatMessages");
const officeApp = document.querySelector<HTMLElement>(".office-app")!;
const officeWorld = element("officeWorld");
const returnToOffice = element<HTMLButtonElement>("returnToOffice");
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const sessionState = element("sessionState");
const conversationSelect = element<HTMLSelectElement>("conversationSelect");
const newConversation = element<HTMLButtonElement>("newConversation");
const deleteConversation = element<HTMLButtonElement>("deleteConversation");
const agentJournal = element<HTMLDialogElement>("agentJournal");
const portfolioDialog = element<HTMLDialogElement>("portfolioDialog");
let conversationId: string | null = null;
let messages: SavedMessage[] = [];
let chatBusy = true;
let pendingResponse = false;
let phase: Phase = "ready";
let latestAnswer = welcome;
let latestIsMarkdown = false;
let selectedWorkers = new Set<WorkerId>();
let nodeOutputs: Partial<Record<NodeName, NodeOutput>> = {};
let nodeBuffers: Partial<Record<NodeName, string>> = {};
let nodeStates: Partial<Record<NodeName, NodeState>> = {};
let managerTrigger: HTMLElement | null = null;
let portfolioLoaded = false;
let planSeen = false;
let roomTransition: Animation | null = null;

const selectAgent = (id: AgentId, trigger: HTMLButtonElement) => {
  if (id === "upper_agent") openManager(trigger, true);
  else openAgentJournal(id);
};
const room = new OfficeRoom(officeWorld);
const camera = createOfficeCamera(element("officeScroll"), element("officeZoom"));
const scene = new OfficeScene(officeWorld, selectAgent, motionPreference);
const portfolioCharacter = new PortfolioCharacter(element<HTMLCanvasElement>("portfolioSprite"), motionPreference);
paintPortrait(element<HTMLCanvasElement>("managerPortrait"), "upper_agent");
paintPortrait(element<HTMLCanvasElement>("replyPortrait"), "upper_agent");

// Every worker has a clickable character; only the parser is not an office actor.
function isOfficeAgent(id: NodeName): id is AgentId {
  return id !== "request_parser";
}
function setActivity(id: NodeName, activity: AgentActivity): void {
  if (isOfficeAgent(id)) scene.setActivity(id, activity);
}
for (const containerId of ["researchWorkers", "journalWorkers"]) {
  for (const id of workers) {
    const button = document.createElement("button");
    button.type = "button"; button.dataset.worker = id;
    button.setAttribute("aria-haspopup", "dialog");
    button.addEventListener("click", () => openAgentJournal(id));
    element(containerId).append(button);
  }
}

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function renderInline(value: string): string {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}
// Model output is escaped before the supported Markdown subset is rendered.
function renderMarkdown(source: string): string {
  let html = "";
  let list: "ul" | "ol" | null = null;
  let code: string[] | null = null;
  const closeList = () => { if (list) html += `</${list}>`; list = null; };
  for (const raw of source.trim().split("\n")) {
    const line = raw.trim();
    if (line.startsWith("```")) {
      closeList();
      if (code) { html += `<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`; code = null; }
      else code = [];
      continue;
    }
    if (code) { code.push(raw); continue; }
    if (!line) { closeList(); continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const item = line.match(/^([-*]|\d+\.)\s+(.+)$/);
    if (heading) { closeList(); html += `<h${heading[1].length}>${renderInline(heading[2])}</h${heading[1].length}>`; }
    else if (item) {
      const kind = /^\d/.test(item[1]) ? "ol" : "ul";
      if (list !== kind) { closeList(); list = kind; html += `<${kind}>`; }
      html += `<li>${renderInline(item[2])}</li>`;
    } else { closeList(); html += `<p>${renderInline(line)}</p>`; }
  }
  closeList();
  if (code) html += `<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`;
  return html;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function textList(value: unknown): string {
  return Array.isArray(value) && value.length ? `<ul>${value.map(item => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>` : "";
}
function renderEvidenceContent(value: unknown): string {
  if (value === null || value === undefined) return "<span>값 없음</span>";
  if (Array.isArray(value)) return `<ul>${value.map(item => `<li>${renderEvidenceContent(item)}</li>`).join("")}</ul>`;
  if (typeof value === "object") return `<dl class="evidence-values">${Object.entries(value).map(([key, item]) => `<dt>${escapeHtml(key)}</dt><dd>${renderEvidenceContent(item)}</dd>`).join("")}</dl>`;
  return escapeHtml(String(value));
}
function renderWorkerReport(report: Record<string, unknown>): string {
  const status = typeof report.status === "string" ? report.status : "";
  let html = `<p class="report-status" data-status="${escapeHtml(status)}">${escapeHtml(reportStatusLabels[status] ?? "조사 결과")}</p>`;
  if (status === "error") return html + `<p>${escapeHtml(String(report.message ?? "조사를 완료하지 못했습니다."))}</p>`;
  const evidence = Array.isArray(report.evidence) ? report.evidence.map(record) : [];
  const findings = Array.isArray(report.findings) ? report.findings.map(record) : [];
  if (findings.length) html += "<h3>조사 결과</h3>" + findings.map(finding => {
    const refs = Array.isArray(finding.evidence_ids) ? finding.evidence_ids.map(id => evidence.findIndex(item => item.evidence_id === id)).filter(index => index >= 0) : [];
    const links = refs.map(index => `<a href="#research-evidence-${index}">근거 ${index + 1}</a>`).join(" · ");
    const label = finding.kind === "inference" ? "해석" : "확인한 사실";
    return `<article class="report-finding"><span class="finding-kind">${label}</span>${renderMarkdown(String(finding.statement ?? ""))}${links ? `<p class="evidence-links">${links}</p>` : ""}</article>`;
  }).join("");
  const unanswered = Array.isArray(report.unanswered_questions) ? report.unanswered_questions.map(record) : [];
  if (unanswered.length) html += "<h3>확인하지 못한 내용</h3><ul>" + unanswered.map(item => `<li>${typeof item.question_index === "number" ? `질문 ${item.question_index + 1}: ` : ""}${escapeHtml(String(item.reason ?? "근거 부족"))}</li>`).join("") + "</ul>";
  if (Array.isArray(report.limitations) && report.limitations.length) html += "<h3>해석 범위와 한계</h3>" + textList(report.limitations);
  if (evidence.length) html += "<h3>근거 자료</h3>" + evidence.map((item, index) => {
    const source = record(item.source);
    const title = String(source.title ?? source.provider ?? source.name ?? "원문 자료");
    const url = typeof source.url === "string" && /^https?:\/\//.test(source.url) ? source.url : undefined;
    const link = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(title)} ↗</a>` : escapeHtml(title);
    const dates = [["공개", item.published_at], ["관측 시작", item.observation_start], ["관측 종료", item.observation_end], ["수집", item.retrieved_at]].filter(([, value]) => value).map(([label, value]) => `${label}: ${escapeHtml(String(value))}`).join(" · ");
    const location = source.location ? `<p>${escapeHtml(String(source.location))}</p>` : "";
    return `<section class="report-evidence" id="research-evidence-${index}"><h3>근거 ${index + 1} · ${link}</h3>${location}${typeof item.content === "string" ? renderMarkdown(item.content) : renderEvidenceContent(item.content)}${dates ? `<p class="evidence-dates">${dates}</p>` : ""}${textList(item.limitations)}</section>`;
  }).join("");
  return html;
}
function setSpeech(text: string, markdown = false): void {
  const followLatest = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 80;
  latestAnswer = text;
  latestIsMarkdown = markdown;
  if (markdown) managerSpeech.innerHTML = renderMarkdown(text);
  else { managerSpeech.replaceChildren(); const p = document.createElement("p"); p.textContent = text; p.style.whiteSpace = "pre-line"; managerSpeech.append(p); }
  if (followLatest) chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Saved turns and the current question share one transcript; streaming only updates the final reply.
function renderTranscript(): void {
  const history = element("chatHistory");
  history.replaceChildren();
  const priorMessages = messages.at(-1)?.role === "assistant" ? messages.slice(0, -1) : messages;
  for (const message of priorMessages) {
    const article = document.createElement("article");
    article.className = "chat-message";
    article.dataset.role = message.role;
    article.setAttribute("aria-label", message.role === "user" ? "나의 질문" : "부장 답변");
    if (message.role === "assistant") {
      const avatar = document.createElement("canvas");
      avatar.className = "chat-avatar";
      avatar.setAttribute("aria-hidden", "true");
      paintPortrait(avatar, "upper_agent");
      article.append(avatar);
    }
    const content = document.createElement("div");
    content.className = "message-content";
    if (message.role === "assistant") {
      content.classList.add("markdown-body");
      if (message.status === "completed") content.innerHTML = renderMarkdown(message.content);
      else content.textContent = message.content;
    } else content.textContent = message.content;
    article.append(content);
    history.append(article);
  }
}

// Animate the same live room between its full view and miniature, without cloning the agents.
function setOfficeMode(chatting: boolean): void {
  if (officeApp.classList.contains("is-chatting") === chatting) return;
  const before = officeWorld.getBoundingClientRect();
  roomTransition?.cancel();
  camera.setEnabled(!chatting);
  officeApp.classList.toggle("is-chatting", chatting);
  returnToOffice.hidden = !chatting;
  for (const actor of officeWorld.querySelectorAll<HTMLElement>(".office-agent, .portfolio-character")) actor.inert = chatting;
  if (motionPreference.matches) return;
  const after = officeWorld.getBoundingClientRect();
  roomTransition = officeWorld.animate([
    { transform: `translate(${before.left - after.left}px, ${before.top - after.top}px) scale(${before.width / after.width})` },
    { transform: "translate(0, 0) scale(1)" },
  ], { duration: 350, easing: "cubic-bezier(.22,.68,0,1)" });
}

function openManager(trigger: HTMLElement | null = null, focusInput = false): void {
  if (agentJournal.open) agentJournal.close();
  managerTrigger = trigger ?? managerTrigger;
  scene.setSelected("upper_agent");
  setSpeech(latestAnswer, latestIsMarkdown);
  managerDialog.hidden = false;
  setOfficeMode(true);
  element("talkToManager").hidden = true;
  chatMessages.scrollTop = chatMessages.scrollHeight;
  if (focusInput && !researchInput.disabled) researchInput.focus({ preventScroll: true });
  else managerDialog.focus({ preventScroll: true });
  if (pendingResponse && !chatBusy && conversationId) {
    const id = conversationId;
    void changeConversation(() => openConversation(id));
  }
}
function closeManager(): void {
  managerDialog.hidden = true;
  setOfficeMode(false);
  element("talkToManager").hidden = false;
  scene.setSelected(null);
  (managerTrigger ?? element("talkToManager")).focus({ preventScroll: true });
}
function announceAnswer(): void {
  // Native modal dialogs otherwise cover the manager and prevent the arrival focus.
  const hadModal = [agentJournal, portfolioDialog].some(dialog => dialog.open);
  for (const dialog of [agentJournal, portfolioDialog]) if (dialog.open) dialog.close();
  if (managerDialog.hidden || hadModal) openManager();
  element("announcement").textContent = phase === "done" ? "부장의 답변이 도착했습니다." : "요청을 완료하지 못했습니다. 부장의 안내를 확인하세요.";
}
function updateStatus(): void {
  const done = [...selectedWorkers].filter(id => nodeStates[id] === "done" || nodeStates[id] === "error").length;
  const text: Record<Phase, string> = {
    ready: "자유 시간", planning: "부장이 질문을 읽는 중", validating: "조사 준비 중",
    researching: `조사 중 ${done} / ${selectedWorkers.size}`, synthesizing: "부장이 결과를 정리하는 중",
    done: "답변 도착", error: "안내를 확인해 주세요", pending: "이전 답변 생성 중",
  };
  sessionState.querySelector("span")!.textContent = text[phase];
  sessionState.dataset.state = ["ready", "done", "error"].includes(phase) ? phase : "running";
  managerDialog.dataset.busy = String(chatBusy && phase !== "ready");
  element("researchWorkers").hidden = !planSeen && !selectedWorkers.size;
  for (const button of document.querySelectorAll<HTMLButtonElement>("[data-worker]")) {
    const id = button.dataset.worker as WorkerId;
    const report = nodeOutputs[id];
    const status = typeof report === "object" && typeof report.status === "string" ? report.status : undefined;
    const state = nodeStates[id] ?? "idle";
    const stateLabel = status && reportStatusLabels[status] || { idle: "대기", running: "조사 중", done: "조사 완료", skipped: "미배정", error: "조사 오류" }[state];
    button.textContent = `${workerLabels[id]} · ${stateLabel}`;
    button.dataset.state = status ?? state;
    button.setAttribute("aria-pressed", String(agentJournal.open && agentJournal.dataset.agent === id));
  }
}
function setChatBusy(busy: boolean): void {
  chatBusy = busy;
  conversationSelect.disabled = busy || !conversationSelect.options.length;
  newConversation.disabled = busy;
  deleteConversation.disabled = busy || !conversationId || pendingResponse;
  element<HTMLButtonElement>("refreshConversation").disabled = busy;
  element("refreshConversation").hidden = !pendingResponse;
  researchInput.disabled = busy || !conversationId || pendingResponse;
  runButton.disabled = researchInput.disabled;
  runButton.setAttribute("aria-label", busy ? "답변을 기다리는 중" : "질문 보내기");
  element("composerHint").textContent = pendingResponse ? "이전 답변을 생성 중입니다. 아래 답변 확인을 눌러 주세요." : busy ? "답변을 기다리고 있습니다." : "Enter로 전달 · Shift + Enter로 줄바꿈";
  element("composerStatus").hidden = !pendingResponse;
  element("composerStatus").textContent = pendingResponse ? "이전 답변을 생성 중입니다. 답변 확인을 눌러 저장 상태를 확인해 주세요." : "";
  updateStatus();
}
function resetResearch(): void {
  nodeStates = {}; nodeOutputs = {}; nodeBuffers = {}; selectedWorkers = new Set(); planSeen = false;
  scene.reset();
  if (agentJournal.open) agentJournal.close();
  updateStatus();
}
function refreshJournal(): void {
  const id = agentJournal.dataset.agent as WorkerId | undefined;
  if (!id) return;
  const state = nodeStates[id] ?? "idle";
  const stateLabels: Record<NodeState, string> = { idle: "자유 시간", running: "조사 중", done: "보고 완료", skipped: "이번 조사에는 참여하지 않아요", error: "조사가 중단되었어요" };
  element("journalTitle").textContent = labels[id];
  const scope = element("journalScope");
  scope.hidden = id !== "technical" && id !== "sentiment";
  scope.textContent = id === "technical"
    ? "코드로 계산한 이동평균·가격 이격률·거래량·변동성을 해석합니다. 지표만으로 향후 상승이나 매수를 단정하지 않습니다."
    : id === "sentiment" ? "수집된 YouTube 댓글 표본의 기대와 우려를 해석합니다. 시장 전체 투자자의 심리를 대표하지 않습니다." : "";
  const output = nodeOutputs[id];
  const reportStatus = typeof output === "object" && typeof output.status === "string" ? reportStatusLabels[output.status] : undefined;
  element("journalState").textContent = reportStatus ?? stateLabels[state];
  const target = element("journalOutput");
  if (typeof output === "string" && output) target.innerHTML = renderMarkdown(output);
  else if (typeof output === "object") target.innerHTML = renderWorkerReport(output);
  else {
    const empty: Record<NodeState, string> = {
      idle: "아직 조사한 내용이 없습니다.",
      running: "조사 중입니다. 내용이 도착하면 여기에 표시됩니다.",
      done: "조사를 마쳤지만 전달된 보고서가 없습니다.",
      skipped: "이번 질문에는 배정된 조사가 없습니다.",
      error: "조사를 마치지 못했어요. 부장의 안내를 확인해 주세요.",
    };
    target.textContent = empty[state];
  }
}
function openAgentJournal(id: WorkerId): void {
  scene.setSelected(isOfficeAgent(id) ? id : null);
  agentJournal.dataset.agent = id;
  refreshJournal();
  if (!agentJournal.open) agentJournal.showModal();
  updateStatus();
}
async function conversationRequest<T>(path = "", method = "GET"): Promise<T> {
  const response = await fetch(`/api/conversations${path}`, { method });
  if (!response.ok) {
    const error = await response.json() as { detail?: unknown };
    throw new Error(typeof error.detail === "string" ? error.detail : `대화 요청에 실패했습니다. (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
async function refreshConversationList(): Promise<Conversation[]> {
  const conversations = await conversationRequest<Conversation[]>();
  conversationSelect.replaceChildren(...conversations.map(conversation => {
    const option = document.createElement("option"); option.value = conversation.id; option.textContent = conversation.title; return option;
  }));
  if (conversationId) conversationSelect.value = conversationId;
  element("conversationTitle").textContent = messages.length ? conversations.find(item => item.id === conversationId)?.title ?? "" : "";
  return conversations;
}
async function openConversation(id: string): Promise<void> {
  const conversation = await conversationRequest<Conversation & { messages: SavedMessage[] }>(`/${id}`);
  conversationId = conversation.id;
  conversationSelect.value = conversation.id;
  history.replaceState(null, "", `#conversation=${conversation.id}`);
  messages = conversation.messages;
  pendingResponse = messages.some(message => message.status === "pending");
  resetResearch();
  const last = [...messages].reverse().find(message => message.role === "assistant");
  setSpeech(last?.status === "pending" ? "이전 답변을 생성 중입니다. 잠시 후 대화를 다시 열어주세요." : last?.content || welcome, last?.status === "completed");
  phase = pendingResponse ? "pending" : last?.status === "completed" ? "done" : last ? "error" : "ready";
  researchInput.value = ""; researchInput.style.height = "auto";
  element("conversationTitle").textContent = messages.length ? conversation.title : "";
  renderTranscript(); updateStatus();
  chatMessages.scrollTop = chatMessages.scrollHeight;
  if (!managerDialog.hidden) scene.setSelected("upper_agent");
}
async function loadConversations(preferred?: string): Promise<void> {
  const conversations = await refreshConversationList();
  if (!conversations.length) {
    const created = await conversationRequest<Conversation>("", "POST");
    await refreshConversationList(); await openConversation(created.id);
  } else await openConversation(conversations.find(item => item.id === preferred)?.id ?? conversations[0].id);
}
async function changeConversation(action: () => Promise<void>): Promise<void> {
  setChatBusy(true);
  try { await action(); element("historyNote").hidden = true; }
  catch (error) {
    setSpeech(error instanceof Error ? error.message : "대화를 불러오지 못했습니다.");
    if (conversationId) conversationSelect.value = conversationId;
    phase = "error"; openManager();
  } finally { setChatBusy(false); }
}

function parseSseFrame(frame: string): SseEvent | null {
  let type = "message";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { type, data: JSON.parse(data.join("\n")) as Record<string, unknown> } : null;
}
async function* readSseEvents(response: Response): AsyncGenerator<SseEvent> {
  if (!response.body) throw new Error("응답 연결을 열지 못했습니다.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) { const event = parseSseFrame(frame); if (event) yield event; }
      if (done) break;
    }
    if (buffer.trim()) { const event = parseSseFrame(buffer); if (event) yield event; }
  } finally { await reader.cancel(); reader.releaseLock(); }
}
function stopWithError(message: string): void {
  for (const id of workers) {
    if (nodeStates[id] === "running") nodeStates[id] = "error";
    setActivity(id, nodeStates[id] === "error" ? "error" : "idle");
  }
  nodeStates.upper_agent = "error";
  scene.setActivity("upper_agent", "error");
  setSpeech(message); phase = "error";
  updateStatus(); refreshJournal(); announceAnswer();
}
function handleResearchEvent(event: SseEvent): boolean {
  if (event.type === "run.started") showRequestConnection(event.data.connection);
  const rawNode = event.data.node;
  const node = typeof rawNode === "string" && nodes.includes(rawNode as NodeName) ? rawNode as NodeName : undefined;
  if (event.type === "node.started" && node) {
    nodeStates[node] = "running";
    // The manager runs twice: planning completion must never trigger the final dialogue.
    nodeBuffers[node] = "";
    if (node === "upper_agent") {
      phase = planSeen ? "synthesizing" : "planning";
      scene.setActivity(node, "working");
      setSpeech(planSeen ? "팀원들의 조사 결과를 모아 답변을 정리하고 있어요." : "질문을 확인하고 있어요. 필요한 조사를 정해볼게요.");
    } else if (node === "request_parser") { phase = "validating"; setSpeech("회사와 조사 기간을 확인하고 있어요."); }
    else { selectedWorkers.add(node); setActivity(node, "working"); phase = "researching"; setSpeech("각 에이전트가 조사 중이에요. 위의 조사 항목을 누르면 근거와 진행 상황을 볼 수 있어요."); }
  } else if (event.type === "node.delta" && node) {
    nodeBuffers[node] = (nodeBuffers[node] ?? "") + String(event.data.delta ?? "");
    nodeOutputs[node] = nodeBuffers[node]!;
    if (node === "upper_agent") setSpeech(nodeBuffers[node]!, true);
  } else if (event.type === "node.completed" && node) {
    const output = (event.data.output ?? {}) as Record<string, unknown>;
    const field = reportFields[node];
    const report = field ? output[field] : undefined;
    nodeOutputs[node] = typeof report === "string" || report && typeof report === "object" ? report as NodeOutput : output;
    nodeStates[node] = report && typeof report === "object" && (report as Record<string, unknown>).status === "error" ? "error" : "done";
    if (node === "upper_agent" && output.intent === "research" && !output.final_answer) {
      planSeen = true;
      const plan = output.research_plan as { tasks?: { agent?: string }[] } | undefined;
      selectedWorkers = new Set((plan?.tasks ?? []).map(task => task.agent).filter((id): id is WorkerId => workers.includes(id as WorkerId)));
      phase = "validating";
      setSpeech("조사할 내용을 정했어요. 입력을 확인한 뒤 팀원들에게 전달할게요.");
    } else if (workers.includes(node as WorkerId)) setActivity(node, nodeStates[node] === "error" ? "error" : "done");
  } else if (event.type === "node.skipped" && node) {
    nodeStates[node] = "skipped";
    if (node !== "request_parser") { selectedWorkers.delete(node as WorkerId); setActivity(node, "idle"); }
  } else if (event.type === "run.completed") {
    setSpeech(String(event.data.final_answer ?? "전달된 최종 답변이 없습니다."), true);
    nodeOutputs.upper_agent = latestAnswer; nodeStates.upper_agent = "done";
    // Clear any unfinished visual state even if the server short-circuits a research run.
    for (const id of workers) if (nodeStates[id] === "running") { nodeStates[id] = "skipped"; setActivity(id, "idle"); }
    scene.setActivity("upper_agent", "done"); phase = "done";
    updateStatus(); refreshJournal(); announceAnswer(); return true;
  } else if (event.type === "run.error") {
    stopWithError(String(event.data.message ?? "조사 중 문제가 생겼어요. 잠시 후 다시 질문해 주세요.")); return true;
  }
  updateStatus(); if (agentJournal.open) refreshJournal(); return false;
}
async function runGraph(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const message = researchInput.value.trim();
  if (!message || chatBusy || !conversationId || pendingResponse) return;
  resetResearch();
  messages.push({ role: "user", content: message, status: "completed" });
  const reply: SavedMessage = { role: "assistant", content: "", status: "pending" }; messages.push(reply);
  researchInput.value = ""; researchInput.style.height = "auto";
  phase = "planning"; scene.setActivity("upper_agent", "working");
  setSpeech("질문을 확인하고 있어요. 필요한 조사를 정해볼게요.");
  setChatBusy(true); renderTranscript();
  chatMessages.scrollTop = chatMessages.scrollHeight;
  let terminal = false;
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    if (!response.ok) {
      const error = await response.json() as { detail?: unknown };
      throw new Error(typeof error.detail === "string" ? error.detail : `요청에 실패했습니다. (${response.status})`);
    }
    for await (const streamEvent of readSseEvents(response)) {
      terminal = handleResearchEvent(streamEvent);
      if (terminal) break;
    }
    if (!terminal) throw new Error("완료 전에 연결이 끊겼어요. 대화 기록에서 저장 상태를 확인한 뒤 다시 질문해 주세요.");
  } catch (error) {
    if (!terminal) stopWithError(error instanceof Error ? error.message : "서버와 연결하지 못했어요.");
  } finally {
    reply.content = latestAnswer; reply.status = nodeStates.upper_agent === "done" ? "completed" : "error";
    try { await refreshConversationList(); }
    catch { element("historyNote").hidden = false; element("historyNote").textContent = "대화 목록을 갱신하지 못했습니다. 새로고침해 저장 상태를 확인해 주세요."; }
    setChatBusy(false);
  }
}

form.addEventListener("submit", event => void runGraph(event));
researchInput.addEventListener("input", () => { researchInput.style.height = "auto"; researchInput.style.height = `${Math.min(researchInput.scrollHeight, 96)}px`; });
researchInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
});
element("talkToManager").addEventListener("click", event => openManager(event.currentTarget as HTMLElement, true));
element("closeManager").addEventListener("click", closeManager);
returnToOffice.addEventListener("click", closeManager);
element("refreshConversation").addEventListener("click", () => {
  if (!chatBusy && conversationId) {
    const id = conversationId;
    void changeConversation(() => openConversation(id));
  }
});
for (const button of document.querySelectorAll<HTMLButtonElement>("[data-close]")) button.addEventListener("click", () => element<HTMLDialogElement>(button.dataset.close!).close());
agentJournal.addEventListener("close", () => { scene.setSelected(managerDialog.hidden ? null : "upper_agent"); updateStatus(); });
agentJournal.addEventListener("click", event => {
  const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href^="#research-evidence-"]') : null;
  if (link) {
    event.preventDefault();
    document.getElementById(link.hash.slice(1))?.scrollIntoView({ block: "nearest" });
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !managerDialog.hidden && ![agentJournal, portfolioDialog, element<HTMLDialogElement>("settingsDialog")].some(dialog => dialog.open)) { event.preventDefault(); closeManager(); }
});
element("portfolioCharacter").addEventListener("click", async () => {
  portfolioCharacter.setPaused(true);
  if (!portfolioDialog.open) portfolioDialog.showModal();
  if (portfolioLoaded) return;
  portfolioLoaded = true;
  try { await import("./portfolio"); }
  catch { portfolioLoaded = false; element("portfolioStatus").textContent = "포트폴리오 화면을 불러오지 못했습니다. 창을 닫고 다시 열어주세요."; }
});
portfolioDialog.addEventListener("close", () => portfolioCharacter.setPaused(false));
conversationSelect.addEventListener("change", () => { if (!chatBusy) void changeConversation(() => openConversation(conversationSelect.value)); });
newConversation.addEventListener("click", () => {
  if (!chatBusy) void changeConversation(async () => {
    const created = await conversationRequest<Conversation>("", "POST");
    await refreshConversationList(); await openConversation(created.id); openManager(null, true);
  });
});
deleteConversation.addEventListener("click", () => {
  if (chatBusy || !conversationId || !window.confirm("이 대화와 저장된 메시지를 삭제할까요?")) return;
  void changeConversation(async () => {
    await conversationRequest(`/${conversationId}`, "DELETE"); conversationId = null; pendingResponse = false; await loadConversations();
  });
});
void changeConversation(() => loadConversations(new URLSearchParams(location.hash.slice(1)).get("conversation") ?? undefined))
  .then(() => { if (phase === "error") openManager(); });
window.addEventListener("resize", () => roomTransition?.cancel());
motionPreference.addEventListener("change", () => { if (motionPreference.matches) roomTransition?.cancel(); });
window.addEventListener("pagehide", event => { if (!event.persisted) { camera.dispose(); scene.dispose(); room.dispose(); portfolioCharacter.dispose(); } });
