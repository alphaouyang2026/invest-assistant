import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RegimeWorkspace } from "@/app/accounts/research/regime-workspace";
import { ResearchWorkspace } from "@/app/accounts/research/research-workspace";

vi.mock("@/app/accounts/nav-chart", () => ({ NavChart: () => <div>净值图表</div> }));

const config = { name: "技术账户", strategy: "technical_rating_v1", strategy_params: { entry_above: .5, exit_below: -.1 },
  portfolio_rules: { initial_cash: "10000000", max_positions: 10, max_weight: "0.1", cash_floor: "0.05" },
  costs: { commission_rate: "0", commission_min: "0", slippage: "0.001" }, start_date: "2025-01-06", end_date: null };
const sources = [{ id: 1, name: "技术账户", config }];
const formulas = { ma200: "MA200 公式", gap: "偏离公式", slope20: "斜率公式", trend: "趋势规则", rv20: "RV20 公式",
  rv_threshold: "波动阈值公式", vol: "波动规则", unknown: "未知规则" };
const rules = { version: "topix_trend_vol_v1", index: "TOPIX", field: "close", ma_sessions: 200, slope_sessions: 20,
  gap_threshold: "0.01", rv_sessions: 20, annualisation: 252, rv_history: 252, short_sessions: 20,
  trend_min_closes: 220, full_min_closes: 273, formulas };
const definition = { ...rules, topix_from: "2021-09-24", topix_through: "2026-09-28" };
const interval = (id: number, start: string, end: string, extra: object = {}) => ({
  id, start_date: start, end_date: end, sessions: 30, topix_start: 2000, topix_end: 2100, topix_return: .05,
  rv20_min: .1, rv20_max: .2, single_day: false, short: false, truncated_start: false, at_search_end: false,
  sessions_before: 500, ...extra });
const discovery = (id: string, intervals: ReturnType<typeof interval>[], extra: object = {}) => ({
  id, status: "completed", error: null, created_at: "2026-09-29T00:00:00", finished_at: "2026-09-29T00:00:01",
  definition_version: "topix_trend_vol_v1", definition: rules,
  parameters: { search_from: "2022-01-04", search_to: "2026-09-28", trend: "up", volatility: null },
  fingerprint: { sha256: "x", definition_version: "topix_trend_vol_v1", from: "2021-01-04", through: "2026-09-28", sessions: 1200 },
  diagnostics: { search_sessions: 1150, matched_sessions: 61, warmup_unknown: [["2022-01-04", "2022-10-20"]], gap_unknown: [],
    gaps: [], trend_counts: { up: 61, down: 300, neutral: 500, unknown: 289 }, vol_counts: { high: 500, low: 500, unknown: 150 } },
  intervals, max_batch_runs: 20, batches: [], ...extra });
const metrics = (total: number, topix: number) => ({ sessions: 30, total_return: total, topix_return: topix,
  excess_return: total - topix, max_drawdown: .03, trades: 4, fees: 1200, realised_pnl: 0, unrealised_pnl: 0, holdings: 2, pending: 0 });
const segment = (position: number, status: string, extra: object = {}) => ({
  position, interval_id: position, start_date: `2024-0${position}-01`, end_date: `2024-0${position}-20`, status,
  run_id: `run-${position}`, progress: { sessions_done: 30, sessions_total: 30 }, error: null,
  attempts: [{ attempt: 1, run_id: `run-${position}`, status, error: null, created_at: "2026-09-29", retry_of: null }],
  metrics: null, ...extra });
const batch = {
  id: "batch-1", created_at: "2026-09-29T00:00:02", discovery_id: "disc-1", selection: { interval_ids: [1, 2, 3], candidate_count: 3 },
  config: { name: "技术账户", strategy: "technical_rating_v1", strategy_params: { entry_above: .5, exit_below: -.1 },
    portfolio_rules: config.portfolio_rules, costs: config.costs, source_account_id: 1 },
  classification_fingerprint: null, code_version: "sha256:code", status: "partial", max_batch_runs: 20,
  segments: [
    segment(1, "completed", { metrics: metrics(.08, .05) }),
    segment(2, "completed", { metrics: metrics(0, 0) }),
    segment(3, "failed", { error: "策略在该段第 3 天出错", progress: { sessions_done: 2, sessions_total: 30 } }),
  ],
  distribution: { weighting: "equal_per_completed_segment", selected: 3, completed: 2, failed: 1, unfinished: 0, denominator: 2,
    returns: [.08, 0], excess_returns: [.03, 0], median_return: .04, median_excess: .015,
    profitable: 1, flat: 1, losing: 0, profitable_ratio: .5, beat_topix: 1, tied_topix: 1, behind_topix: 0, beat_ratio: .5,
    worst: { position: 2, start_date: "2024-02-01", end_date: "2024-02-20", total_return: 0 },
    worst_excess: { position: 2, start_date: "2024-02-01", end_date: "2024-02-20", excess_return: 0 },
    coverage: { sessions: 60, first: "2024-01-01", last: "2024-02-20", ranges: [["2024-01-01", "2024-01-20"], ["2024-02-01", "2024-02-20"]] } },
};

let posts: { path: string; body: Record<string, unknown> }[];
let discoveries: Record<string, ReturnType<typeof discovery>>;
let batchRefusal: { status: number; detail: unknown } | null;
let discoveryRefusal: string | null;
let batchOverride: typeof batch | null;

beforeEach(() => {
  posts = []; batchRefusal = null; discoveryRefusal = null; batchOverride = null;
  discoveries = {
    "disc-1": discovery("disc-1", [
      interval(1, "2023-01-05", "2023-02-20", { truncated_start: true }),
      interval(2, "2024-03-01", "2024-03-01", { sessions: 1, single_day: true, short: true, topix_return: 0 }),
      interval(3, "2026-08-01", "2026-09-28", { at_search_end: true, topix_return: -.02 }),
      interval(4, "2022-10-21", "2022-11-30", { sessions_before: 250 }),
    ]),
    "disc-0": discovery("disc-0", [], { diagnostics: { ...discovery("x", []).diagnostics, matched_sessions: 0 } }),
  };
  window.history.replaceState(null, "", "/accounts/research");
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const path = url.pathname;
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (request.method === "POST") {
      posts.push({ path, body: await request.json() });
      if (path.endsWith("/discoveries")) return discoveryRefusal ? response({ detail: discoveryRefusal }, 422) : response({ id: "disc-1" }, 202);
      if (path.endsWith("/retry")) return response({ id: "batch-1", run_id: "run-3b" }, 202);
      if (batchRefusal) return response({ detail: batchRefusal.detail }, batchRefusal.status);
      return response({ id: "batch-1" }, 202);
    }
    if (path.endsWith("/sources")) return response(sources);
    if (path.endsWith("/runs")) return response({ total: 0, page: 1, page_size: 10, runs: [] });
    if (path.endsWith("/regimes/definition")) return response(definition);
    if (path.includes("/discoveries/")) return response(discoveries[path.split("/").pop()!]);
    if (path.endsWith("/batches")) return response({ total: 1, page: 1, page_size: 10, batches: [{ id: "batch-1",
      created_at: "2026-09-29T00:00:02", discovery_id: "disc-1", source_account_id: 1, source_name: "技术账户",
      entry_above: .5, exit_below: -.1, status: "partial", segments: 3, completed: 2, failed: 1 }] });
    if (path.includes("/batches/")) return response(batchOverride ?? batch);
    return response({ detail: "未知路径" }, 404);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

it("切换到按市场形势模式再切回，手动表单和已填内容都还在", async () => {
  render(<ResearchWorkspace sourceId="1" />);
  await screen.findByRole("option", { name: "技术账户" });
  fireEvent.change(screen.getByLabelText("结束日"), { target: { value: "2025-01-10" } });
  fireEvent.click(screen.getByRole("button", { name: "按市场形势选择区间" }));
  expect(await screen.findByRole("button", { name: "查找区间" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "运行回测" })).not.toBeInTheDocument();
  expect(window.location.search).toContain("mode=regime");
  fireEvent.click(screen.getByRole("button", { name: "手动指定区间" }));
  expect(screen.getByRole("button", { name: "运行回测" })).toBeVisible();
  expect(screen.getByLabelText("结束日")).toHaveValue("2025-01-10");
  expect(window.location.search).not.toContain("mode=regime");
  expect(posts).toHaveLength(0);
});

it("查找区间后列出全部候选及标注，勾选两段提交时带上发现编号和区间编号", async () => {
  render(<RegimeWorkspace sources={sources} sourceId="1" />);
  await waitFor(() => expect(screen.getByLabelText("搜索结束日")).toHaveValue("2026-09-28"));
  expect(screen.getByText("MA200 公式")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查找区间" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ path: "/api/research/discoveries",
    body: { search_from: "2021-09-24", search_to: "2026-09-28", trend: "up", volatility: null } });
  const table = await screen.findByRole("table", { name: "候选区间列表" });
  expect(within(table).getAllByRole("checkbox")).toHaveLength(4);
  for (const badge of ["单日", "起点被截断", "可能延续到搜索范围之后", "策略预热不足"]) expect(within(table).getByText(badge)).toBeInTheDocument();
  expect(screen.getByText(/预热不足）：2022-01-04 — 2022-10-20/)).toBeInTheDocument();
  expect(window.location.search).toContain("discovery=disc-1");

  fireEvent.click(screen.getByRole("checkbox", { name: /#3 / }));
  fireEvent.click(screen.getByRole("checkbox", { name: /#1 / }));
  expect(screen.getByText(/已选 2 段 \/ 单批上限 20 段/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "对所选区间运行" }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1]).toMatchObject({ path: "/api/research/batches",
    body: { discovery_id: "disc-1", interval_ids: [1, 3], source_account_id: 1, entry_above: .5, exit_below: -.1 } });
  expect(posts[1].body).toHaveProperty("request_key");
  expect(await screen.findByRole("table", { name: "逐段结果" })).toBeInTheDocument();
  expect(window.location.search).toContain("batch=batch-1");
});

it("选择超过单批上限时提示并禁止运行，而不是悄悄截掉", async () => {
  discoveries["disc-1"] = { ...discoveries["disc-1"], max_batch_runs: 2 };
  render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-1" />);
  await screen.findByRole("table", { name: "候选区间列表" });
  fireEvent.click(screen.getByRole("button", { name: "全选" }));
  expect(screen.getByText(/超过单批上限 2 段/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "对所选区间运行" })).toBeDisabled();
});

it("零匹配时明确说明，而不是显示空表", async () => {
  render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-0" />);
  expect(await screen.findByText(/没有符合条件的区间（零匹配）/)).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "候选区间列表" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "对所选区间运行" })).not.toBeInTheDocument();
});

it("逐段显示状态和指标，失败段显示原因并可单独重试", async () => {
  render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-1" initialBatch="batch-1" />);
  const table = await screen.findByRole("table", { name: "逐段结果" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getByText("已完成")).toBeInTheDocument();
  expect(within(rows[0]).getByText("+8.00%")).toBeInTheDocument();
  expect(within(rows[0]).getByRole("link", { name: "查看详情" })).toHaveAttribute("href", "/accounts/research?run=run-1");
  expect(within(rows[2]).getByText(/失败/)).toBeInTheDocument();
  expect(within(rows[2]).getByText("策略在该段第 3 天出错")).toBeInTheDocument();
  expect(within(rows[2]).getByText("2 / 30")).toBeInTheDocument();
  expect(within(rows[0]).queryByRole("button", { name: "重试此段" })).not.toBeInTheDocument();
  fireEvent.click(within(rows[2]).getByRole("button", { name: "重试此段" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].path).toBe("/api/research/batches/batch-1/segments/3/retry");
  expect(posts[0].body).toHaveProperty("request_key");
});

it("结果分布写明分母，只按已完成段等权，平手单独列出", async () => {
  render(<RegimeWorkspace sources={sources} sourceId="1" initialBatch="batch-1" />);
  const panel = await screen.findByRole("region", { name: "结果分布" });
  expect(within(panel).getByText("按已完成 2 段等权")).toBeInTheDocument();
  expect(within(panel).getByText(/已完成 2 段，失败 1 段，未完成 0 段/)).toBeInTheDocument();
  expect(within(panel).getByText(/分母 = 2；失败和未完成的段不计入，也不当作 0 收益/)).toBeInTheDocument();
  expect(within(panel).getByText("盈利 1 段 · 持平 1 段 · 亏损 0 段（收益严格大于 0 才算盈利）")).toBeInTheDocument();
  expect(within(panel).getByText(/跑赢 TOPIX 1 段 · 与 TOPIX 持平 1 段 · 落后 0 段/)).toBeInTheDocument();
  expect(within(panel).getAllByText("50.0%（1 / 2）", { selector: "dd" })).toHaveLength(2);
  expect(within(panel).getByText(/收益最差：第 2 段 2024-02-01 — 2024-02-20/)).toBeInTheDocument();
  expect(within(panel).getByText(/共 60 个开市日/)).toBeInTheDocument();
  expect(screen.getByText(/净值不拼接、收益不连乘，也没有合并的总回撤/)).toBeInTheDocument();
  expect(screen.getByText(/不能据此声称能实时择时/)).toBeInTheDocument();
});

it("发现后行情变化时提示并可重新发现，忙时显示服务端原因", async () => {
  batchRefusal = { status: 412, detail: "行情自区间发现后已变化，请重新发现后再运行" };
  render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-1" />);
  fireEvent.click(await screen.findByRole("checkbox", { name: /#1 / }));
  fireEvent.click(screen.getByRole("button", { name: "对所选区间运行" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("行情已变化：行情自区间发现后已变化");
  fireEvent.click(within(alert).getByRole("button", { name: "重新发现" }));
  await waitFor(() => expect(posts.at(-1)?.path).toBe("/api/research/discoveries"));
  expect(posts.at(-1)?.body).toMatchObject({ search_from: "2022-01-04", search_to: "2026-09-28", trend: "up" });

  batchRefusal = { status: 409, detail: "另一个任务正在运行，请稍后重试" };
  fireEvent.click(await screen.findByRole("checkbox", { name: /#1 / }));
  fireEvent.click(screen.getByRole("button", { name: "对所选区间运行" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("另一个任务正在运行");
  expect(screen.getByRole("button", { name: "对所选区间运行" })).not.toBeDisabled();
});

it("服务端逐字段的 422 错误按字段显示；搜索日期被拒时说明原因", async () => {
  batchRefusal = { status: 422, detail: [
    { type: "greater_than_equal", loc: ["body", "exit_below"], msg: "Input should be greater than or equal to -1", input: -2, ctx: { ge: -1 } },
    { type: "too_short", loc: ["body", "interval_ids"], msg: "List should have at least 1 item after validation, not 0", input: [] },
  ] };
  render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-1" />);
  fireEvent.click(await screen.findByRole("checkbox", { name: /#1 / }));
  fireEvent.click(screen.getByRole("button", { name: "对所选区间运行" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("退出阈值：不能小于 -1");
  expect(alert).toHaveTextContent("所选区间：至少要有一项");
  expect(alert).not.toHaveTextContent("网络");

  discoveryRefusal = "搜索结束日超出已有行情（TOPIX 到 2026-09-28）";
  fireEvent.click(screen.getByRole("button", { name: "查找区间" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("搜索结束日超出已有行情"));
});

it("离开页面后不再轮询区间发现和批次", async () => {
  discoveries["disc-1"] = { ...discoveries["disc-1"], status: "running" };
  const running = { ...batch, status: "running", segments: [segment(1, "running", { progress: { sessions_done: 3, sessions_total: 30 } })] };
  batchOverride = running;
  const reads = (part: string) => vi.mocked(fetch).mock.calls
    .filter(([r]) => (r as Request).method === "GET" && new URL((r as Request).url).pathname.endsWith(part)).length;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const { unmount } = render(<RegimeWorkspace sources={sources} sourceId="1" initialDiscovery="disc-1" initialBatch="batch-1" />);
    await screen.findByText("正在按 TOPIX 行情划分区间…");
    await screen.findByText("3 / 30");
    const first = [reads("/disc-1"), reads("/batch-1")];
    await vi.advanceTimersByTimeAsync(1600);
    await waitFor(() => expect([reads("/disc-1"), reads("/batch-1")].every((n, i) => n > first[i])).toBe(true));
    unmount();
    const seen = [reads("/disc-1"), reads("/batch-1")];
    await vi.advanceTimersByTimeAsync(10_000);
    expect([reads("/disc-1"), reads("/batch-1")]).toEqual(seen);
  } finally { vi.useRealTimers(); }
});

it("刷新时凭地址里的批次编号恢复批次和它的候选区间，不重新提交", async () => {
  render(<ResearchWorkspace initialMode="regime" initialBatch="batch-1" />);
  expect(await screen.findByRole("table", { name: "逐段结果" })).toBeInTheDocument();
  expect(await screen.findByRole("table", { name: "候选区间列表" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "按市场形势选择区间" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: "运行回测" })).not.toBeInTheDocument();
  expect(window.location.search).toContain("discovery=disc-1");
  expect(posts).toHaveLength(0);
});
