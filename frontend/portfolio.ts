// 종목 조사 상태·SSE와 독립적인 계좌 조회 및 진단 화면.
export {};
interface PortfolioReport {
  fetched_at: string;
  source: string;
  scope: string;
  total_amount: string;
  total_purchase_amount: string;
  total_profit_loss: string;
  total_profit_loss_pct: string | null;
  top_one_pct: string;
  top_three_pct: string;
  holdings: { symbol: string; name: string; amount: string; purchase_amount: string; profit_loss: string; profit_loss_pct: string | null; weight_pct: string; sector: string; reason: string }[];
  sectors: { sector: string; amount: string; weight_pct: string }[];
  scenario: { name: string; shock_pct: string; impact_amount: string; impact_pct: string };
  excluded: { symbol: string; name: string; reason: string }[];
  explanation: { summary: string; observations: string[]; limitations: string[] };
}

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`화면 요소 없음: ${id}`);
  return found as T;
}

const status = element("portfolioStatus");
const result = element("portfolioResult");

async function requestJson(url: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(url, { cache: "no-store", ...init });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "요청 형식을 확인하세요.");
  return payload;
}

function paragraph(parent: HTMLElement, text: string, tag = "p"): void {
  const node = document.createElement(tag);
  node.textContent = text;
  parent.appendChild(node);
}
function section(title: string): HTMLElement {
  const node = document.createElement("section");
  node.className = "portfolio-card";
  paragraph(node, title, "h2");
  result.appendChild(node);
  return node;
}
function table(parent: HTMLElement, labels: string[], rows: string[][]): void {
  const scroll = document.createElement("div");
  scroll.className = "portfolio-table-scroll";
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", `${parent.querySelector("h2")?.textContent ?? "포트폴리오"} 표`);
  const node = document.createElement("table");
  const head = node.createTHead().insertRow();
  labels.forEach(label => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    head.appendChild(th);
  });
  const body = node.createTBody();
  rows.forEach(values => {
    const row = body.insertRow();
    values.forEach(value => { row.insertCell().textContent = value; });
  });
  scroll.appendChild(node);
  parent.appendChild(scroll);
}
const money = (value: string) => `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
const percent = (value: string) => `${Number(value).toFixed(2)}%`;
const pnlPercent = (value: string | null) => value === null ? "산정 불가 (매입금액 0원)" : percent(value);

export function renderReport(report: PortfolioReport): void {
  result.replaceChildren();
  const scope = section("분석 범위");
  paragraph(scope, `${report.scope} · 총 ${money(report.total_amount)}`);
  paragraph(scope, `수집 시각: ${new Date(report.fetched_at).toLocaleString("ko-KR")} · ${report.source}`);
  paragraph(scope, "수집 시각은 계좌 데이터의 평가 시각과 다를 수 있습니다. 계좌 전체 자산의 위험도나 과거 투자 성과가 아닙니다.");
  if (report.excluded.length) table(scope, ["제외 종목", "사유"], report.excluded.map(row => [`${row.name} (${row.symbol})`, row.reason]));
  const totals = document.createElement("dl"); totals.className = "portfolio-metrics";
  for (const [label, value] of [
    ["총 매입금액", money(report.total_purchase_amount)], ["현재 평가금액", money(report.total_amount)],
    ["평가손익", money(report.total_profit_loss)], ["평가손익률", pnlPercent(report.total_profit_loss_pct)],
  ]) {
    const item = document.createElement("div");
    paragraph(item, label, "dt"); paragraph(item, value, "dd"); totals.append(item);
  }
  scope.append(totals);
  paragraph(scope, "현재 보유분의 매입금액 대비 평가손익입니다. 별도 세금·수수료 공제 전이며, 매도한 거래의 실현손익·배당은 포함하지 않습니다. 전체 손익률은 합산 매입금액 기준입니다.");
  const holdings = section("보유 주식과 AI 추정 업종");
  table(holdings, ["종목", "매입금액", "현재 평가금액", "평가손익", "평가손익률", "비중", "추정 업종", "분류 이유"], report.holdings.map(row => [
    `${row.name} (${row.symbol})`, money(row.purchase_amount), money(row.amount),
    money(row.profit_loss), pnlPercent(row.profit_loss_pct), percent(row.weight_pct), row.sector, row.reason,
  ]));
  const sectors = section("집중도");
  paragraph(sectors, `최대 종목 ${percent(report.top_one_pct)} · 상위 ${Math.min(3, report.holdings.length)}종목 ${percent(report.top_three_pct)}`);
  table(sectors, ["AI 추정 업종", "평가금액", "비중"], report.sectors.map(row => [row.sector, money(row.amount), percent(row.weight_pct)]));
  paragraph(sectors, "공식 산업 분류가 아닙니다. 분류 오류와 복합 사업 단순화가 업종 집중도에 영향을 줄 수 있습니다.");
  const explanation = section("AI 해설");
  paragraph(explanation, report.explanation.summary);
  report.explanation.observations.forEach(value => paragraph(explanation, value));
}

async function loadPortfolio(): Promise<void> {
  result.replaceChildren();
  result.setAttribute("aria-busy", "true");
  try {
    const connection = await requestJson("/api/portfolio/configuration") as { configured: boolean };
    if (!connection.configured) {
      status.textContent = "Toss 키가 설정되지 않았습니다. 종목 조사는 그대로 사용할 수 있습니다.";
      return;
    }
    status.textContent = "보유 주식을 자동 진단하고 있습니다. 업종 분류·해설에 LLM 호출이 발생합니다…";
    const payload = await requestJson("/api/portfolio/diagnose", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }) as PortfolioReport;
    renderReport(payload);
    status.textContent = "자동 진단 완료 · 첫 번째 종합매매 계좌 기준 · 수치는 코드 계산, 업종·해설은 AI 추정입니다.";
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "진단 중 연결이 끊겼습니다.";
  } finally {
    result.setAttribute("aria-busy", "false");
  }
}

// app.ts가 포트폴리오 창을 처음 열 때만 이 모듈을 불러온다. 폴링·자동 재시도는 없다.
void loadPortfolio();
