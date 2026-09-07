import "./portfolio";

type NodeName =
  | "upper_agent"
  | "request_parser"
  | "business"
  | "macro_sector"
  | "event_catalyst";

type NodeState = "running" | "done" | "skipped" | "error";
type NodeOutput = string | Record<string, unknown>;

interface SseEvent {
  type: string;
  data: Record<string, unknown>;
}

const nodes: NodeName[] = [
  "request_parser",
  "upper_agent",
  "business",
  "macro_sector",
  "event_catalyst",
];
const nodeLabels: Record<NodeName, string> = {
  upper_agent: "상위 Agent",
  request_parser: "Request / Mandate",
  business: "Business",
  macro_sector: "Macro / Sector",
  event_catalyst: "Event / Catalyst",
};
const reportFields: Partial<Record<NodeName, string>> = {
  business: "business_report",
  macro_sector: "macro_sector_report",
  event_catalyst: "event_catalyst_report",
  upper_agent: "final_answer",
};

function getElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`필수 화면 요소를 찾을 수 없습니다: ${selector}`);
  return element;
}

const form = getElement<HTMLFormElement>("#researchForm");
const runButton = getElement<HTMLButtonElement>("#runButton");
const sessionState = getElement<HTMLElement>("#sessionState");
const researchInput = getElement<HTMLTextAreaElement>("#researchInput");
const chatMessages = getElement<HTMLElement>("#chatMessages");
const nodePopover = getElement<HTMLElement>("#nodePopover");
const popoverTitle = getElement<HTMLElement>("#popoverTitle");
const popoverState = getElement<HTMLElement>("#popoverState");
const popoverOutput = getElement<HTMLElement>("#popoverOutput");
const conversationSelect = getElement<HTMLSelectElement>("#conversationSelect");
const newConversation = getElement<HTMLButtonElement>("#newConversation");
const deleteConversation = getElement<HTMLButtonElement>("#deleteConversation");

interface Conversation { id: string; title: string }
interface SavedMessage {
  role: "user" | "assistant";
  content: string;
  status: "pending" | "completed" | "error" | "interrupted";
}
let conversationId: string | null = null;
let chatBusy = true;
let pendingResponse = false;

let nodeOutputs: Partial<Record<NodeName, NodeOutput>> = {};
let nodeBuffers: Partial<Record<NodeName, string>> = {};
let showTimer: number | undefined;
let hideTimer: number | undefined;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInline(value: string): string {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/_([^_]+)_/g, "<em>$1</em>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>',
    );
}

function renderMarkdown(source: string): string {
  const lines = source.trim().split("\n");
  let html = "";
  let listType: "ul" | "ol" | null = null;
  const closeList = () => {
    if (listType) {
      html += `</${listType}>`;
      listType = null;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const unordered = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (!line) {
      closeList();
      continue;
    }
    if (heading) {
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${renderInline(heading[2])}</h${level}>`;
      continue;
    }
    if (unordered) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html += "<ul>";
      }
      html += `<li>${renderInline(unordered[1])}</li>`;
      continue;
    }
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html += "<ol>";
      }
      html += `<li>${renderInline(ordered[1])}</li>`;
      continue;
    }
    closeList();
    html += `<p>${renderInline(line)}</p>`;
  }
  closeList();
  return html;
}

function renderNodeOutput(output: NodeOutput): string {
  if (typeof output === "string") return renderMarkdown(output);
  return `<pre><code>${escapeHtml(JSON.stringify(output, null, 2))}</code></pre>`;
}

function setNodeState(name: NodeName, state?: NodeState): void {
  const node = document.querySelector<HTMLElement>(`[data-node="${name}"]`);
  if (!node) return;
  if (state) node.dataset.state = state;
  else delete node.dataset.state;
}

function getNodeState(name: NodeName): string {
  return document.querySelector<HTMLElement>(`[data-node="${name}"]`)?.dataset.state ?? "idle";
}

function addMessage(
  role: "user" | "assistant",
  text: string,
  className = "",
  markdown = false,
): HTMLElement {
  const row = document.createElement("div");
  row.className = `chat-row ${role}`;
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${className}${markdown ? " markdown-body" : ""}`.trim();
  if (markdown) bubble.innerHTML = renderMarkdown(text);
  else bubble.textContent = text;
  row.appendChild(bubble);
  chatMessages.appendChild(row);
  chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: "smooth" });
  return bubble;
}

function setChatBusy(busy: boolean): void {
  chatBusy = busy;
  conversationSelect.disabled = busy || !conversationSelect.options.length;
  newConversation.disabled = busy;
  deleteConversation.disabled = busy || !conversationId || pendingResponse;
  researchInput.disabled = busy || !conversationId || pendingResponse;
  runButton.disabled = researchInput.disabled;
}

async function conversationRequest<T>(path = "", method = "GET"): Promise<T> {
  const response = await fetch(`/api/conversations${path}`, { method });
  if (!response.ok) {
    const error = await response.json() as { detail?: string };
    throw new Error(error.detail ?? `대화 요청에 실패했습니다. (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

async function refreshConversationList(): Promise<Conversation[]> {
  const conversations = await conversationRequest<Conversation[]>();
  conversationSelect.replaceChildren(...conversations.map(conversation => {
    const option = document.createElement("option");
    option.value = conversation.id;
    option.textContent = conversation.title;
    return option;
  }));
  if (conversationId) conversationSelect.value = conversationId;
  return conversations;
}

async function openConversation(id: string): Promise<void> {
  const conversation = await conversationRequest<Conversation & { messages: SavedMessage[] }>(`/${id}`);
  conversationId = conversation.id;
  conversationSelect.value = conversation.id;
  history.replaceState(null, "", `#conversation=${conversation.id}`);
  chatMessages.replaceChildren();
  pendingResponse = conversation.messages.some(message => message.status === "pending");
  for (const message of conversation.messages) {
    addMessage(message.role, message.status === "pending"
      ? "답변을 생성 중입니다. 잠시 후 대화를 다시 열어주세요."
      : message.content, "", message.role === "assistant" && message.status === "completed");
  }
  if (!conversation.messages.length) addMessage("assistant", "무엇이 궁금하세요? 일반 질문, 종목 조사, 내 보유 기업 분석을 요청하세요.");
  nodeOutputs = {};
  nodeBuffers = {};
  for (const node of nodes) setNodeState(node);
  scheduleHide();
  researchInput.value = "";
  researchInput.dispatchEvent(new Event("input"));
  getElement<HTMLElement>("#chatRouteStatus").textContent = "실행 그래프는 새 질문을 보낼 때 표시됩니다";
  setSessionState(pendingResponse ? "running" : "ready", pendingResponse ? "생성 중" : "준비");
}

async function loadConversations(preferred?: string): Promise<void> {
  const conversations = await refreshConversationList();
  if (!conversations.length) {
    const created = await conversationRequest<Conversation>("", "POST");
    await refreshConversationList();
    await openConversation(created.id);
  } else {
    await openConversation(conversations.find(item => item.id === preferred)?.id ?? conversations[0].id);
  }
}

async function changeConversation(action: () => Promise<void>): Promise<void> {
  setChatBusy(true);
  try {
    await action();
  } catch (error) {
    addMessage("assistant", error instanceof Error ? error.message : "대화를 불러오지 못했습니다.");
    if (conversationId) conversationSelect.value = conversationId;
    setSessionState("error", "대화 오류");
  } finally {
    setChatBusy(false);
  }
}

function positionPopover(trigger: HTMLElement): void {
  const rect = trigger.getBoundingClientRect();
  const popRect = nodePopover.getBoundingClientRect();
  const gap = 12;
  let left = rect.right + gap;
  if (left + popRect.width > window.innerWidth - gap) left = rect.left - popRect.width - gap;
  left = Math.max(gap, Math.min(left, window.innerWidth - popRect.width - gap));
  let top = rect.top + (rect.height - popRect.height) / 2;
  top = Math.max(gap, Math.min(top, window.innerHeight - popRect.height - gap));
  nodePopover.style.left = `${Math.round(left)}px`;
  nodePopover.style.top = `${Math.round(top)}px`;
}

function showNodePopover(name: NodeName, trigger: HTMLElement): void {
  window.clearTimeout(hideTimer);
  const state = getNodeState(name);
  const labels: Record<string, string> = {
    idle: "실행 전",
    running: "실행 중",
    done: "완료",
    skipped: "선택 안 됨",
    error: "오류",
  };
  let output = nodeOutputs[name];
  if (!output && state === "skipped") output = "_이번 질문의 Research Plan에서 선택되지 않았습니다._";
  if (!output && state === "running") output = "_노드가 실행 중입니다._";
  if (!output && state === "error") output = "_노드 실행 중 오류가 발생했습니다._";
  if (!output) output = "_조사 실행 후 이 노드의 출력 결과가 표시됩니다._";

  nodePopover.dataset.node = name;
  popoverTitle.textContent = nodeLabels[name];
  popoverState.textContent = labels[state] ?? "실행 전";
  popoverOutput.innerHTML = renderNodeOutput(output);
  nodePopover.style.visibility = "hidden";
  nodePopover.hidden = false;
  positionPopover(trigger);
  nodePopover.classList.remove("is-visible");
  void nodePopover.offsetWidth;
  nodePopover.style.visibility = "";
  nodePopover.classList.add("is-visible");
}

function refreshOpenPopover(name: NodeName): void {
  if (nodePopover.hidden || nodePopover.dataset.node !== name) return;
  const output = nodeOutputs[name];
  if (output) popoverOutput.innerHTML = renderNodeOutput(output);
  popoverState.textContent = getNodeState(name) === "done" ? "완료" : "실행 중";
}

function scheduleShow(name: NodeName, trigger: HTMLElement, delay = 320): void {
  window.clearTimeout(showTimer);
  window.clearTimeout(hideTimer);
  showTimer = window.setTimeout(() => showNodePopover(name, trigger), delay);
}

function scheduleHide(): void {
  window.clearTimeout(showTimer);
  window.clearTimeout(hideTimer);
  hideTimer = window.setTimeout(() => {
    nodePopover.classList.remove("is-visible");
    nodePopover.hidden = true;
  }, 140);
}

for (const name of nodes) {
  const node = getElement<HTMLElement>(`[data-node="${name}"]`);
  node.addEventListener("pointerenter", () => scheduleShow(name, node));
  node.addEventListener("pointerleave", scheduleHide);
  node.addEventListener("focus", () => scheduleShow(name, node, 0));
  node.addEventListener("blur", scheduleHide);
}
nodePopover.addEventListener("pointerenter", () => window.clearTimeout(hideTimer));
nodePopover.addEventListener("pointerleave", scheduleHide);
window.addEventListener("scroll", scheduleHide);
window.addEventListener("resize", scheduleHide);

researchInput.addEventListener("input", () => {
  researchInput.style.height = "auto";
  researchInput.style.height = `${Math.min(researchInput.scrollHeight, 96)}px`;
});
researchInput.dispatchEvent(new Event("input"));
researchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function parseSseFrame(frame: string): SseEvent | null {
  let type = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return {
    type,
    data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>,
  };
}

async function* readSseEvents(response: Response): AsyncGenerator<SseEvent> {
  if (!response.body) throw new Error("Streaming 응답 본문이 없습니다.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) yield event;
    }
    if (done) break;
  }

  if (buffer.trim()) {
    const event = parseSseFrame(buffer);
    if (event) yield event;
  }
}

function extractNodeOutput(name: NodeName, output: Record<string, unknown>): NodeOutput {
  const field = reportFields[name];
  if (field && typeof output[field] === "string") return output[field] as string;
  return output;
}

function setSessionState(state: "ready" | "running" | "done" | "error", label: string): void {
  sessionState.className = state === "ready" ? "session-state" : `session-state ${state}`;
  const text = sessionState.querySelector("span");
  if (text) text.textContent = label;
}

function handleResearchEvent(event: SseEvent, reply: HTMLElement): boolean {
  const node = event.data.node as NodeName | undefined;

  if (event.type === "node.started" && node) {
    setNodeState(node, "running");
    reply.textContent = `${nodeLabels[node]} 실행 중...`;
    if (node === "upper_agent") getElement<HTMLElement>("#chatRouteStatus").textContent = "상위 Agent 실행 중";
    return false;
  }

  if (event.type === "node.delta" && node) {
    const delta = String(event.data.delta ?? "");
    nodeBuffers[node] = (nodeBuffers[node] ?? "") + delta;
    nodeOutputs[node] = nodeBuffers[node] ?? "";
    refreshOpenPopover(node);
    if (node === "upper_agent") {
      reply.classList.remove("thinking");
      reply.classList.add("markdown-body");
      reply.innerHTML = renderMarkdown(nodeBuffers[node] ?? "");
    }
    return false;
  }

  if (event.type === "node.completed" && node) {
    const output = event.data.output as Record<string, unknown>;
    if (node === "upper_agent" && typeof output.intent === "string") {
      const labels: Record<string, string> = { general: "일반 답변", research: "종목 조사" };
      getElement<HTMLElement>("#chatRouteStatus").textContent = `질문 분류 → ${labels[output.intent] ?? output.intent}`;
    }
    nodeOutputs[node] = extractNodeOutput(node, output);
    setNodeState(node, "done");
    refreshOpenPopover(node);
    return false;
  }

  if (event.type === "node.skipped" && node) {
    setNodeState(node, "skipped");
    return false;
  }

  if (event.type === "run.completed") {
    const finalAnswer = String(event.data.final_answer ?? "최종 답변이 없습니다.");
    reply.classList.remove("thinking");
    reply.classList.add("markdown-body");
    reply.innerHTML = renderMarkdown(finalAnswer);
    setSessionState("done", "완료");
    return true;
  }

  if (event.type === "run.error") {
    if (node) setNodeState(node, "error");
    reply.classList.remove("thinking");
    reply.textContent = String(event.data.message ?? "리서치 실행 중 오류가 발생했습니다.");
    setSessionState("error", "오류");
    return true;
  }

  return false;
}

async function runGraph(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const message = researchInput.value.trim();
  if (!message || chatBusy || !conversationId || pendingResponse) return;

  nodeOutputs = {};
  nodeBuffers = {};
  for (const node of nodes) setNodeState(node);
  addMessage("user", message);
  const reply = addMessage("assistant", "조사를 시작하고 있어요…", "thinking");
  researchInput.value = "";
  researchInput.style.height = "auto";
  setChatBusy(true);
  setSessionState("running", "분석 중");

  let finished = false;
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    if (!response.ok) {
      const error = (await response.json()) as { detail?: string };
      throw new Error(error.detail ?? `요청에 실패했습니다. (${response.status})`);
    }

    for await (const streamEvent of readSseEvents(response)) {
      finished = handleResearchEvent(streamEvent, reply) || finished;
    }
    if (!finished) throw new Error("Research Stream이 완료 이벤트 없이 종료됐습니다.");
  } catch (error) {
    reply.classList.remove("thinking");
    reply.textContent = error instanceof Error ? error.message : "서버 연결에 실패했습니다.";
    setSessionState("error", "오류");
  } finally {
    try {
      await refreshConversationList();
    } catch {
      addMessage("assistant", "대화 목록을 갱신하지 못했습니다. 다시 열어 저장 상태를 확인해주세요.");
    }
    setChatBusy(false);
    researchInput.focus();
    chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: "smooth" });
  }
}

form.addEventListener("submit", (event) => void runGraph(event));
conversationSelect.addEventListener("change", () => {
  if (!chatBusy) void changeConversation(() => openConversation(conversationSelect.value));
});
newConversation.addEventListener("click", () => {
  if (!chatBusy) void changeConversation(async () => {
    const created = await conversationRequest<Conversation>("", "POST");
    await refreshConversationList();
    await openConversation(created.id);
  });
});
deleteConversation.addEventListener("click", () => {
  if (chatBusy || !conversationId || !window.confirm("이 대화와 저장된 메시지를 삭제할까요?")) return;
  void changeConversation(async () => {
    await conversationRequest(`/${conversationId}`, "DELETE");
    conversationId = null;
    pendingResponse = false;
    chatMessages.replaceChildren();
    await loadConversations();
  });
});
void changeConversation(() => loadConversations(new URLSearchParams(location.hash.slice(1)).get("conversation") ?? undefined));
