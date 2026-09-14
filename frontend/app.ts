import { OfficeScene, paintPortrait, type AgentId } from "./office-scene";

type NodeName = AgentId | "request_parser";
type NodeState = "idle" | "running" | "done" | "skipped" | "error";
type NodeOutput = string | Record<string, unknown>;
type Phase = "ready" | "planning" | "validating" | "researching" | "synthesizing" | "done" | "error" | "pending";
interface SseEvent { type: string; data: Record<string, unknown> }
interface Conversation { id: string; title: string }
interface SavedMessage { role: "user" | "assistant"; content: string; status: "pending" | "completed" | "error" | "interrupted" }
const workers: AgentId[] = ["business", "macro_sector", "event_catalyst"];
const nodes: NodeName[] = ["upper_agent", "request_parser", ...workers];
const labels: Record<NodeName, string> = { upper_agent: "부장 Agent", request_parser: "질문 확인", business: "비즈니스", macro_sector: "매크로 / 섹터", event_catalyst: "이벤트 / 카탈리스트" };
const reportFields: Partial<Record<NodeName, string>> = { business: "business_report", macro_sector: "macro_sector_report", event_catalyst: "event_catalyst_report", upper_agent: "final_answer" };
const welcome = "어떤 기업이 궁금한가요?\n질문을 주시면 팀원들과 조사해 드릴게요.";

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
const sessionState = element("sessionState");
const conversationSelect = element<HTMLSelectElement>("conversationSelect");
const newConversation = element<HTMLButtonElement>("newConversation");
const deleteConversation = element<HTMLButtonElement>("deleteConversation");
const agentJournal = element<HTMLDialogElement>("agentJournal");
const historyDialog = element<HTMLDialogElement>("historyDialog");
const portfolioDialog = element<HTMLDialogElement>("portfolioDialog");
let conversationId: string | null = null;
let messages: SavedMessage[] = [];
let chatBusy = true;
let pendingResponse = false;
let phase: Phase = "ready";
let latestAnswer = welcome;
let latestIsMarkdown = false;
let selectedWorkers = new Set<AgentId>();
let nodeOutputs: Partial<Record<NodeName, NodeOutput>> = {};
let nodeBuffers: Partial<Record<NodeName, string>> = {};
let nodeStates: Partial<Record<NodeName, NodeState>> = {};
let managerTrigger: HTMLElement | null = null;
let portfolioLoaded = false;
let planSeen = false;

const scene = new OfficeScene(element("officeWorld"), (id, trigger) => {
  if (id === "upper_agent") openManager(trigger, true);
  else openAgentJournal(id);
});
paintPortrait(element<HTMLCanvasElement>("managerPortrait"), "upper_agent");

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
function setSpeech(text: string, markdown = false): void {
  latestAnswer = text;
  latestIsMarkdown = markdown;
  if (markdown) managerSpeech.innerHTML = renderMarkdown(text);
  else { managerSpeech.replaceChildren(); const p = document.createElement("p"); p.textContent = text; p.style.whiteSpace = "pre-line"; managerSpeech.append(p); }
}
function openManager(trigger: HTMLElement | null = null, focusInput = false): void {
  if (agentJournal.open) agentJournal.close();
  managerTrigger = trigger ?? managerTrigger;
  scene.setSelected("upper_agent");
  setSpeech(latestAnswer, latestIsMarkdown);
  managerDialog.hidden = false;
  element("talkToManager").hidden = true;
  if (focusInput && !researchInput.disabled) researchInput.focus({ preventScroll: true });
  else managerDialog.focus({ preventScroll: true });
}
function closeManager(): void {
  managerDialog.hidden = true;
  element("talkToManager").hidden = false;
  scene.setSelected(null);
  (managerTrigger ?? element("talkToManager")).focus({ preventScroll: true });
}
function announceAnswer(): void {
  // Native modal dialogs otherwise cover the manager and prevent the arrival focus.
  for (const dialog of [agentJournal, historyDialog, portfolioDialog]) if (dialog.open) dialog.close();
  openManager();
  managerDialog.classList.remove("arrival");
  void managerDialog.offsetWidth;
  managerDialog.classList.add("arrival");
  managerSpeech.scrollTop = 0;
  element("announcement").textContent = phase === "done" ? "부장의 답변이 도착했습니다." : "요청을 완료하지 못했습니다. 부장의 안내를 확인하세요.";
}
function updateStatus(): void {
  const done = [...selectedWorkers].filter(id => nodeStates[id] === "done").length;
  const text: Record<Phase, string> = {
    ready: "자유 시간", planning: "부장이 질문을 읽는 중", validating: "조사 준비 중",
    researching: `조사 중 ${done} / ${selectedWorkers.size}`, synthesizing: "부장이 결과를 정리하는 중",
    done: "답변 도착", error: "안내를 확인해 주세요", pending: "이전 답변 생성 중",
  };
  sessionState.querySelector("span")!.textContent = text[phase];
  sessionState.dataset.state = ["ready", "done", "error"].includes(phase) ? phase : "running";
  element("dialogEyebrow").textContent = phase === "done" ? "조사 결과를 함께 살펴볼까요?" : phase === "ready" ? "어서 오세요, 리서치 오피스입니다." : text[phase];
  managerDialog.classList.toggle("has-report", phase === "done" && latestAnswer.length > 170);
  managerDialog.dataset.busy = String(chatBusy && phase !== "ready");
}
function setChatBusy(busy: boolean): void {
  chatBusy = busy;
  conversationSelect.disabled = busy || !conversationSelect.options.length;
  newConversation.disabled = busy;
  deleteConversation.disabled = busy || !conversationId || pendingResponse;
  researchInput.disabled = busy || !conversationId || pendingResponse;
  runButton.disabled = researchInput.disabled;
  runButton.firstChild!.textContent = busy ? "확인 중 " : "말하기 ";
  element("composerHint").textContent = pendingResponse ? "이전 답변을 생성 중입니다. 대화를 다시 열어 확인하세요." : busy ? "팀원들이 확인하고 있어요. 사무실을 둘러보세요." : "Enter로 전달 · Shift + Enter로 줄바꿈";
  updateStatus();
}
function resetResearch(): void {
  nodeStates = {}; nodeOutputs = {}; nodeBuffers = {}; selectedWorkers = new Set(); planSeen = false;
  scene.reset();
  if (agentJournal.open) agentJournal.close();
}
function refreshJournal(): void {
  const id = agentJournal.dataset.agent as AgentId | undefined;
  if (!id) return;
  const state = nodeStates[id] ?? "idle";
  const stateLabels: Record<NodeState, string> = { idle: "자유 시간", running: "조사 중", done: "보고 완료", skipped: "이번 조사에는 참여하지 않아요", error: "조사가 중단되었어요" };
  element("journalTitle").textContent = `${labels[id]} · 조사 노트`;
  element("journalState").textContent = stateLabels[state];
  const output = nodeOutputs[id];
  const target = element("journalOutput");
  if (typeof output === "string" && output) target.innerHTML = renderMarkdown(output);
  else if (output) { const pre = document.createElement("pre"); pre.textContent = JSON.stringify(output, null, 2); target.replaceChildren(pre); }
  else {
    const empty: Record<NodeState, string> = {
      idle: "아직 맡은 조사가 없어요. 부장에게 궁금한 기업을 알려주세요.\n저장된 대화에는 질문과 최종 답변만 남아 있어요.",
      running: "자료를 살펴보고 있어요. 조사 내용이 도착하면 여기에 표시됩니다.",
      done: "조사를 마쳤지만 전달된 보고서가 없습니다.",
      skipped: "부장이 이번 질문에 필요한 다른 팀원에게 조사를 맡겼어요.",
      error: "조사를 마치지 못했어요. 부장의 안내를 확인해 주세요.",
    };
    target.textContent = empty[state];
  }
}
function openAgentJournal(id: AgentId): void {
  scene.setSelected(id);
  agentJournal.dataset.agent = id;
  refreshJournal();
  if (!agentJournal.open) agentJournal.showModal();
}
function renderHistory(): void {
  const entries = element("historyEntries");
  entries.replaceChildren();
  if (!messages.length) { const p = document.createElement("p"); p.className = "empty-note"; p.textContent = "아직 대화가 없어요. 부장에게 첫 질문을 건네보세요."; entries.append(p); }
  for (const message of messages) {
    const article = document.createElement("article"); article.className = "history-entry"; article.dataset.role = message.role;
    const header = document.createElement("header"); header.textContent = message.role === "user" ? "나의 질문" : "부장 Agent";
    if (message.status !== "completed") { const status = document.createElement("span"); status.className = "entry-status"; status.textContent = ({ pending: "생성 중", error: "오류", interrupted: "중단됨" })[message.status]; header.append(status); }
    const content = document.createElement("div"); content.className = "markdown-body";
    if (message.role === "assistant" && message.status === "completed") content.innerHTML = renderMarkdown(message.content);
    else content.textContent = message.content || "답변을 생성 중입니다. 잠시 후 대화를 다시 열어주세요.";
    article.append(header, content); entries.append(article);
  }
}
function openHistory(): void {
  renderHistory();
  if (!historyDialog.open) historyDialog.showModal();
  if (pendingResponse && !chatBusy && conversationId) {
    const id = conversationId;
    void changeConversation(() => openConversation(id));
  }
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
  renderHistory(); updateStatus();
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
  try { await action(); }
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
    scene.setActivity(id, nodeStates[id] === "error" ? "error" : "idle");
  }
  nodeStates.upper_agent = "error";
  scene.setActivity("upper_agent", "error");
  setSpeech(message); phase = "error";
  updateStatus(); refreshJournal(); announceAnswer();
}
function handleResearchEvent(event: SseEvent): boolean {
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
    else { selectedWorkers.add(node); scene.setActivity(node, "working"); phase = "researching"; setSpeech("팀원들이 각자 자리에서 조사하고 있어요. 캐릭터를 누르면 조사 내용을 볼 수 있어요."); }
  } else if (event.type === "node.delta" && node) {
    nodeBuffers[node] = (nodeBuffers[node] ?? "") + String(event.data.delta ?? "");
    nodeOutputs[node] = nodeBuffers[node]!;
    if (node === "upper_agent") setSpeech(nodeBuffers[node]!, true);
  } else if (event.type === "node.completed" && node) {
    const output = (event.data.output ?? {}) as Record<string, unknown>;
    const field = reportFields[node];
    nodeOutputs[node] = field && typeof output[field] === "string" ? output[field] as string : output;
    nodeStates[node] = "done";
    if (node === "upper_agent" && output.intent === "research") {
      planSeen = true;
      const plan = output.research_plan as { tasks?: { agent?: string }[] } | undefined;
      selectedWorkers = new Set((plan?.tasks ?? []).map(task => task.agent).filter((id): id is AgentId => workers.includes(id as AgentId)));
      phase = "validating";
      setSpeech("조사할 내용을 정했어요. 입력을 확인한 뒤 팀원들에게 전달할게요.");
    } else if (workers.includes(node as AgentId)) scene.setActivity(node as AgentId, "done");
  } else if (event.type === "node.skipped" && node) {
    nodeStates[node] = "skipped";
    if (node !== "request_parser") { selectedWorkers.delete(node); scene.setActivity(node, "idle"); }
  } else if (event.type === "run.completed") {
    setSpeech(String(event.data.final_answer ?? "전달된 최종 답변이 없습니다."), true);
    nodeOutputs.upper_agent = latestAnswer; nodeStates.upper_agent = "done";
    // Clear any unfinished visual state even if the server short-circuits a research run.
    for (const id of workers) if (nodeStates[id] === "running") { nodeStates[id] = "skipped"; scene.setActivity(id, "idle"); }
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
  setChatBusy(true); closeManager(); renderHistory();
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
    renderHistory();
    try { await refreshConversationList(); }
    catch { element("historyNote").textContent = "대화 목록을 갱신하지 못했습니다. 다시 열어 저장 상태를 확인해 주세요."; }
    setChatBusy(false);
  }
}

form.addEventListener("submit", event => void runGraph(event));
researchInput.addEventListener("input", () => { researchInput.style.height = "auto"; researchInput.style.height = `${Math.min(researchInput.scrollHeight, 96)}px`; });
researchInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
});
element("talkToManager").addEventListener("click", event => openManager(event.currentTarget as HTMLElement, true));
element("openReport").addEventListener("click", event => openManager(event.currentTarget as HTMLElement));
element("closeManager").addEventListener("click", closeManager);
element("openHistory").addEventListener("click", openHistory);
element("dialogHistory").addEventListener("click", openHistory);
for (const button of document.querySelectorAll<HTMLButtonElement>("[data-close]")) button.addEventListener("click", () => element<HTMLDialogElement>(button.dataset.close!).close());
agentJournal.addEventListener("close", () => scene.setSelected(managerDialog.hidden ? null : "upper_agent"));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !managerDialog.hidden && ![agentJournal, historyDialog, portfolioDialog].some(dialog => dialog.open)) { event.preventDefault(); closeManager(); }
});
element("openPortfolio").addEventListener("click", async () => {
  if (!portfolioDialog.open) portfolioDialog.showModal();
  if (portfolioLoaded) return;
  portfolioLoaded = true;
  try { await import("./portfolio"); }
  catch { portfolioLoaded = false; element("portfolioStatus").textContent = "포트폴리오 화면을 불러오지 못했습니다. 창을 닫고 다시 열어주세요."; }
});
conversationSelect.addEventListener("change", () => { if (!chatBusy) void changeConversation(() => openConversation(conversationSelect.value)); });
newConversation.addEventListener("click", () => {
  if (!chatBusy) void changeConversation(async () => {
    const created = await conversationRequest<Conversation>("", "POST");
    await refreshConversationList(); await openConversation(created.id); historyDialog.close(); openManager(null, true);
  });
});
deleteConversation.addEventListener("click", () => {
  if (chatBusy || !conversationId || !window.confirm("이 대화와 저장된 메시지를 삭제할까요?")) return;
  void changeConversation(async () => {
    await conversationRequest(`/${conversationId}`, "DELETE"); conversationId = null; pendingResponse = false; await loadConversations();
  });
});
void changeConversation(() => loadConversations(new URLSearchParams(location.hash.slice(1)).get("conversation") ?? undefined))
  .then(() => { if (!messages.length || phase === "error") openManager(); });
window.addEventListener("pagehide", event => { if (!event.persisted) scene.dispose(); });
