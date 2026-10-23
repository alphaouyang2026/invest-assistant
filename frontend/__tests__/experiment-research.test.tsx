import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExperimentWorkspace } from "@/app/accounts/research/experiment-workspace";
import { ResearchWorkspace } from "@/app/accounts/research/research-workspace";
import type { Schemas } from "@/lib/api/client";

vi.mock("@/app/accounts/nav-chart", () => ({ NavChart: () => <div>净值图表</div> }));

const task = { name: "prime_open_to_open_5d_v1", decision: "t 收盘决策，最早 t+1 开盘成交",
  label: "研究价格开盘 O(t+6) ÷ O(t+1) − 1", horizon: 5, label_sessions: 6 };
const features = { version: "ohlcv_ratios_v1", names: ["ret_1", "ret_5", "ret_20"] };
const defaults: Schemas["ExperimentDefaults"] = {
  defaults: { name: "", train_sessions: 250, test_sessions: 60, expanding: false, rebalance_sessions: 5, max_holding_sessions: 0,
    trainer: "ridge_v1", trainer_params: {}, search_grid: null, validation_sessions: 60, baselines: ["rule_short_reversal_v1"],
    source_account_id: null,
    initial_cash: 10_000_000, max_positions: 10, max_weight: 0.1, cash_floor: 0.05, max_adv20_fraction: 0.05,
    commission_rate: 0, commission_min: 0, slippage: 0.001, stress_bps: [10, 25, 50],
    min_coverage: 0.8, min_training_samples: 20_000, min_labelled_days: 24, min_trades: 30, actions: ["disposition", "priority"] },
  trainers: { ridge_v1: { alpha: 1.0 }, rule_short_reversal_v1: {},
    xgb_rank_ndcg_v1: { max_depth: 3, n_estimators: 100, learning_rate: 0.05, subsample: 0.8, colsample_bytree: 0.8,
      min_child_weight: 1, pairs_per_sample: 10, seed: 7, threads: 4 } },
  searches: { ridge_v1: [{}], rule_short_reversal_v1: [{}],
    xgb_rank_ndcg_v1: [{ max_depth: 3, n_estimators: 100 }, { max_depth: 3, n_estimators: 200 },
      { max_depth: 4, n_estimators: 100 }, { max_depth: 4, n_estimators: 200 }] },
  supported_actions: ["disposition", "priority"], unsupported_actions: ["target_weight", "gross_exposure"],
  task, features, viewed_through: "2026-10-19",
};
const contract: Schemas["ExperimentContract"] = {
  version: "model_experiment_v1", name: "Ridge 冒烟", task,
  data: { source: "J-Quants 日线", point_in_time: "只声称保存下来的运行结果可审计" }, features,
  universe_rule: "prime_common_stock", test_from: "2026-01-05", test_to: "2026-10-16",
  folds: { train_sessions: 250, test_sessions: 60, expanding: false },
  policy: { strategy: "score_top_n_v1", anchor: "2026-01-05", rebalance_sessions: 5, max_holding_sessions: 0, warmup_sessions: 1,
    missing_scores: "决策日模型没有分数：不开新仓，已有持仓保留，不沿用旧分数", score_missing: "某只没有分数：空仓不买，持仓卖出" },
  portfolio_rules: { initial_cash: "10000000", max_positions: 10, max_weight: "0.1", cash_floor: "0.05", max_adv20_fraction: "0.05" },
  costs: { commission_rate: "0.0", commission_min: "0.0", slippage: "0.001" },
  stress: { basis: "压力场景只回放主模型：每边滑点 = 基础滑点 + 登记时声明的加成；手续费率和最低手续费沿用基础成本，不加压",
    scenarios: [{ extra_bps: "10", slippage: "0.002" }, { extra_bps: "25", slippage: "0.0035" }, { extra_bps: "50", slippage: "0.006" }] },
  model: { trainer: "ridge_v1", params: { alpha: 1.0 }, search_budget: 1 }, baselines: [{ trainer: "rule_short_reversal_v1", params: {} }],
  benchmarks: ["topix_price", "eligible_equal_weight"], minimums: { coverage: 0.8, training_samples: 20_000, labelled_days: 24, trades: 30 },
  viewed_through: "2026-03-31",
  actions: ["disposition", "priority"], source_account_id: null,
};
const metrics = (total: number): Schemas["ReplayMetrics"] => ({ sessions: 120, total_return: total, topix_return: .1, excess_return: total - .1,
  annualised_return: total * 2, excess_annualised_return: null, max_drawdown: .08, sharpe: .5, win_rate: .5, closed_positions: 40,
  average_holding_sessions: 6, annual_turnover: 25.8, trades: 80, fees: 0, cash: 3_000_000, average_cash_share: .288,
  realised_pnl: 100_000, unrealised_pnl: -2_000,
  fill_rate: { filled: 80, expired: 2, rate: .9756, expired_reasons: { limit_up_open: 2 }, skipped_reasons: { lot_unaffordable: 7 } },
  adv20: { orders: 80, median: .000384, p95: .0015, max: .0063, over_cap: 0, without_adv20: 0, cap: .05 } });
const period = (fold: number, start: string, end: string) => ({ fold, start, end, sessions: 60, net_return: .02, topix_return: .05, excess_return: -.03 });
const summary = (position: number, model: string, label: string, scenario: "base" | "stress", slippage: string, total: number,
  extra: number | null = null): Schemas["ReplaySummary"] => ({
  position, model, model_label: label, scenario, extra_bps: extra, costs: { commission_rate: "0.0", commission_min: "0.0", slippage },
  metrics: metrics(total),
  folds: [period(1, "2026-01-05", "2026-03-31"), period(2, "2026-04-01", "2026-06-25")],
  years: [{ year: 2026, start: "2026-01-05", end: "2026-10-16", sessions: 120, net_return: .03, topix_return: .1, excess_return: -.07 }] });
const diagnostics = (ic: number): Schemas["Diagnostics"] => ({ decision_days: 24, unavailable_days: 0, ic_days: 23, ic_mean: ic, ic_std: .142,
  coverage_mean: .998, coverage_min: .993, days: [],
  folds: [{ fold: 1, decision_days: 12, unavailable_days: 0, ic_days: 12, ic_mean: .08, ic_std: .14, coverage_mean: .997, coverage_min: .996 }] });
const report: Schemas["ExperimentReport"] = {
  contract_hash: "a168f3ab6b3000d8a725", sessions: 120, decision_days: 24, read_from: "2024-10-01",
  folds: [{ number: 1, train_from: "2025-01-06", train_to: "2025-12-30", test_from: "2026-01-05", test_to: "2026-03-31", viewed: true },
    { number: 2, train_from: "2025-04-01", train_to: "2026-03-31", test_from: "2026-04-01", test_to: "2026-06-25", viewed: false }],
  models: [{ key: "model", role: "model", label: "主模型", trainer: "ridge_v1", params: { alpha: 1 }, failed_folds: [], diagnostics: diagnostics(.004) },
    { key: "baseline_1", role: "baseline", label: "对照 1", trainer: "rule_short_reversal_v1", params: {}, failed_folds: [],
      diagnostics: diagnostics(.021) }],
  benchmarks: { topix_price: { basis: "TOPIX 价格指数，测试首日收盘到末日收盘，不含分红", total_return: .1 },
    eligible_equal_weight: { basis: "每个决策日当天股票池里有标签的证券等权，不扣费用", total_return: .07,
      periods: [{ date: "2026-01-05", codes: 530, mean_return: .01 }] } },
  stress_basis: "压力场景只回放主模型：每边滑点 = 基础滑点 + 登记时声明的加成；手续费率和最低手续费沿用基础成本，不加压",
  replays: [summary(1, "model", "主模型", "base", "0.001", -.325), summary(2, "model", "主模型", "stress", "0.0035", -.497, 25),
    summary(3, "baseline_1", "对照 1", "base", "0.001", .0007)],
  evidence: { status: "exploratory", viewed_folds: [1],
    reasons: [{ code: "history_partly_viewed", message: "第 1 折的测试段在登记前已被查看过（截至 2026-03-31），这部分结果只能算探索性" }] },
  warnings: ["50740 在 2023-06-29 配股：持仓未调整"], timings: { total: 185 },
};
const foldResult = (model: string, fold: number, extra: object = {}) => ({ model, fold, train_from: "2025-01-06", train_to: "2025-12-30",
  test_from: "2026-01-05", test_to: "2026-03-31", samples: 101_891, seconds: 1.2, artifact_hash: `sha256:${model}${fold}feedbeef0123`,
  artifact: { trainer: "ridge_v1", params: { alpha: 1 }, state: {}, train_cutoff: "2025-12-30", samples: 101_891 }, error: null, ...extra });
const completed: Schemas["ExperimentDetail"] = {
  id: "exp-1-aaaaaaaa", name: "Ridge 冒烟", status: "completed", created_at: "2026-10-19T08:00:00", finished_at: "2026-10-19T08:03:05",
  retry_of: null, retried_by: [], progress: { stage: "reporting" }, input_fingerprint: { sha256: "data" }, code_version: "sha256:code",
  error: null, error_code: null, contract, contract_hash: "a168f3ab6b3000d8a725", evidence_status: "exploratory", report,
  data_read: { observed_at: "2026-10-19T08:00:41+00:00", note: "库里没有逐行的历史可得时间，这里只记录本次实验什么时候读到数据",
    sources: [{ kind: "daily_bars", name: "日线", start: "2024-10-01", end: "2026-10-16", rows: 5_280_487, detail: "读入 534 只证券",
      available_from: "t 日的日线在 t 收盘后同步，只用于 t 收盘及以后的决策" },
    { kind: "trading_calendar", name: "交易日历", start: "2024-10-01", end: "2026-10-19", rows: 500, detail: "读取区间的开市日",
      available_from: "交易日历提前同步" }] },
  fold_results: [foldResult("model", 1), foldResult("model", 2), foldResult("baseline_1", 1), foldResult("baseline_1", 2)],
};
const day = (date: string, extra: Partial<Schemas["DayRecord"]> = {}): Schemas["DayRecord"] => ({
  date, decision_day: false, model_available: null, fold: 1, universe: 534, scored: 0, holdings_decisions: [], candidates: 0,
  orders: [], executions: [], target: [], holdings: [], cash: 10_000_000, nav: 10_000_000,
  constraints: { skipped: {}, adv20_capped: 0, ranked_out: 0, unplaced_candidates: 0 }, top_scores: [], ...extra });
const days = [
  day("2026-01-05", { decision_day: true, model_available: true, scored: 532, candidates: 400 }),
  day("2026-01-26", { decision_day: true, model_available: true, scored: 530, candidates: 507, cash: 1_384_178, nav: 10_448_478,
    holdings_decisions: [
      { code: "21570", disposition: "hold", reason_codes: ["model_rank"], score: .006522 },
      { code: "45410", disposition: "hold", reason_codes: ["model_rank"], score: .037344 },
      { code: "33280", disposition: null, reason_codes: ["no_signal"], score: null },
    ],
    top_scores: [{ code: "45410", score: .037344, rank: 1 }, { code: "99840", score: .02, rank: 2 }],
    orders: [
      { sequence: 42, kind: "sell", code: "21570", execution_date: "2026-01-27", planned_quantity: 1100, priority: .006522,
        reason_codes: ["ranked_out"], capped: null, replaces: null, status: "filled", outcome_reason: null },
      { sequence: 43, kind: "buy", code: "99840", execution_date: "2026-01-27", planned_quantity: 300, priority: .02,
        reason_codes: ["model_rank"], capped: "adv20", replaces: null, status: "expired", outcome_reason: "limit_up_open" },
    ],
    executions: [{ sequence: 30, kind: "buy", code: "45410", signal_date: "2026-01-23", status: "filled", outcome_reason: null,
      filled_quantity: 12100, fill_price: 79.079, fees: 0, cash_delta: -956_856 }],
    target: [{ code: "45410", quantity: 12100 }, { code: "33280", quantity: 500 }, { code: "99840", quantity: 300 }],
    holdings: [{ code: "21570", quantity: 1100, opened_on: "2026-01-13", cost: 935_935, close: 894, value: 983_400 },
      { code: "45410", quantity: 12100, opened_on: "2026-01-05", cost: 956_856, close: 72, value: 871_200 },
      { code: "33280", quantity: 500, opened_on: "2026-01-20", cost: 947_446, close: 1962, value: 981_000 }],
    constraints: { skipped: { lot_unaffordable: 2 }, adv20_capped: 1, ranked_out: 1, unplaced_candidates: 500 } }),
];
const replayDetail = (position: number): Schemas["ReplayDetail"] => {
  const s = report.replays.find(r => r.position === position)!;
  return { position, model: s.model, scenario: s.scenario, costs: s.costs, result: {
    nav: [{ date: "2026-01-05", nav: 10_000_000, nav_curve: 1, topix_curve: 1, drawdown: 0, cash: 10_000_000 }],
    holdings: [{ code: "45410", quantity: 12100, opened_on: "2026-01-05", cost: 956_856, close: 72, value: 871_200 }],
    pending: [], warnings: [], metrics: s.metrics, folds: s.folds, years: s.years } };
};
const order = { id: 1, kind: "buy", code: "45410", name: null, signal_date: "2026-01-05", execution_date: "2026-01-06",
  planned_quantity: 12100, priority: .0583, reason: { disposition: "hold", reason_codes: ["model_rank"] }, status: "filled",
  outcome_reason: null, filled_quantity: 12100, fill_price: 79.079, fees: 0, cash_delta: -956_856 };

let posts: { path: string; body: Record<string, unknown> }[];
let experiments: Record<string, Schemas["ExperimentDetail"]>;
let refusal: { status: number; detail: unknown } | null;
let nextId: string;

const reads = (part: string) => vi.mocked(fetch).mock.calls.map(([r]) => new URL((r as Request).url))
  .filter(url => url.pathname.includes(part));

beforeEach(() => {
  posts = []; refusal = null; nextId = "exp-1-aaaaaaaa";
  experiments = { "exp-1-aaaaaaaa": completed };
  window.history.replaceState(null, "", "/accounts/research");
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const path = url.pathname;
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (request.method === "POST") {
      posts.push({ path, body: await request.json() });
      return refusal ? response({ detail: refusal.detail }, refusal.status) : response({ id: nextId }, 202);
    }
    if (path === "/api/experiments/defaults") return response(defaults);
    if (path === "/api/accounts") return response([{ id: 3, name: "动量账户", strategy: "cross_sectional_momentum_v1", start_date: "2024-01-04",
      advanced_through: "2026-10-16", status: "active", total_return: null, annualised_return: null, max_drawdown: null, excess_annualised_return: null }]);
    if (path === "/api/accounts/3") return response({ id: 3, name: "动量账户", strategy: "cross_sectional_momentum_v1", strategy_params: {},
      rules: { initial_cash: 5_000_000, max_positions: 5, max_weight: .2, cash_floor: .05 }, costs: { commission_rate: .001, commission_min: 100, slippage: .002 },
      start_date: "2024-01-04", advanced_through: "2026-10-16", status: "active", backtest_data_mark: null, figures: null, holdings: [], pending: [] });
    if (path === "/api/experiments") return response({ total: Object.keys(experiments).length, page: 1, page_size: 10,
      experiments: Object.values(experiments).map(x => ({ id: x.id, name: x.name, status: x.status, created_at: x.created_at,
        finished_at: x.finished_at, retry_of: x.retry_of, error: x.error, contract_hash: x.contract_hash, evidence_status: x.evidence_status,
        test_from: x.contract.test_from, test_to: x.contract.test_to, trainer: "ridge_v1", baselines: ["rule_short_reversal_v1"],
        source_account_id: null })) });
    const days_ = path.match(/\/replays\/(\d+)\/days$/);
    if (days_) {
      const only = url.searchParams.get("decision_only") === "true";
      const shown = only ? days.filter(d => d.decision_day) : days;
      return response({ total: shown.length, page: 1, page_size: 20, days: shown });
    }
    if (path.endsWith("/orders")) return response({ total: 1, page: 1, page_size: 50, orders: [order] });
    const replay = path.match(/\/replays\/(\d+)$/);
    if (replay) return response(replayDetail(Number(replay[1])));
    const found = experiments[path.split("/").pop()!];
    if (path.startsWith("/api/experiments/") && found) return response(found);
    if (path === "/api/research/sources") return response([]);
    if (path === "/api/research/runs") return response({ total: 0, page: 1, page_size: 10, runs: [] });
    return response({ detail: "未知路径" }, 404);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

it("切到模型实验模式：显示登记表单和实验历史，地址记下模式，切回手动表单还在", async () => {
  render(<ResearchWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "模型实验" }));
  expect(await screen.findByRole("button", { name: "登记并运行" })).toBeVisible();
  expect(screen.getByRole("button", { name: "模型实验" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: "运行回测" })).not.toBeInTheDocument();
  expect(window.location.search).toContain("mode=experiment");
  const history = await screen.findByRole("table", { name: "模型实验历史" });
  expect(within(history).getByText("2026-01-05 — 2026-10-16")).toBeInTheDocument();
  expect(within(history).getByText("探索性")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "手动指定区间" }));
  expect(screen.getByRole("button", { name: "运行回测" })).toBeVisible();
  expect(window.location.search).not.toContain("mode=");
  expect(posts).toHaveLength(0);
});

it("表单默认值来自服务端，提示已看过的历史，登记时按填写的内容提交", async () => {
  render(<ExperimentWorkspace />);
  const form = await screen.findByRole("form", { name: "登记模型实验" });
  expect(within(form).getByLabelText("训练窗")).toHaveValue(250);
  expect(within(form).getByLabelText("单只上限")).toHaveValue(10);
  expect(within(form).getByLabelText("滑点")).toHaveValue(.1);
  expect(within(form).getByLabelText("压力场景：滑点加成")).toHaveValue("10, 25, 50");
  expect(within(form).getByLabelText("决策日间隔")).toHaveValue(5);
  expect(within(form).getByLabelText("每折最少训练样本")).toHaveValue(20_000);
  expect(within(form).getByLabelText("正则强度 alpha")).toHaveValue(1);
  expect(within(form).getByLabelText("主模型")).toHaveValue("ridge_v1");
  expect(within(form).getByRole("checkbox", { name: /规则：短期反转/ })).toBeChecked();
  const frozen = within(form).getByRole("region", { name: "登记后冻结的内容" });
  expect(frozen).toHaveTextContent("登记即冻结，之后不能修改");
  expect(frozen).toHaveTextContent("持有规则能下达的指令种类：只有");
  expect(frozen).toHaveTextContent("目标权重、总敞口尚未实现，契约里声明了会被拒绝登记");
  expect(frozen).toHaveTextContent("共 5 个回放");
  expect(frozen).toHaveTextContent("每边滑点在基础上加 10、25、50 bps，手续费不加压");
  expect(frozen).toHaveTextContent("截至 2026-10-19 的历史已经看过");

  fireEvent.change(within(form).getByLabelText("实验名称"), { target: { value: "Ridge 冒烟" } });
  fireEvent.change(within(form).getByLabelText("测试起点"), { target: { value: "2026-01-05" } });
  fireEvent.change(within(form).getByLabelText("测试终点"), { target: { value: "2026-10-16" } });
  expect(frozen).toHaveTextContent("整个测试段都已看过，这些折会标「探索性（已看过）」");
  fireEvent.change(within(form).getByLabelText("正则强度 alpha"), { target: { value: "2" } });
  fireEvent.change(within(form).getByLabelText("压力场景：滑点加成"), { target: { value: "25，50" } });
  fireEvent.change(within(form).getByLabelText("最少有标签的决策日"), { target: { value: "12" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: /不设上限/ }));
  fireEvent.click(within(form).getByRole("button", { name: "登记并运行" }));

  await waitFor(() => expect(posts).toHaveLength(1));
  const { request_key, ...body } = posts[0].body;
  expect(posts[0].path).toBe("/api/experiments");
  expect(request_key).toEqual(expect.any(String));
  expect(body).toEqual({
    name: "Ridge 冒烟", test_from: "2026-01-05", test_to: "2026-10-16", train_sessions: 250, test_sessions: 60, expanding: false,
    rebalance_sessions: 5, max_holding_sessions: 0, trainer: "ridge_v1", trainer_params: { alpha: 2 },
    baselines: ["rule_short_reversal_v1"], source_account_id: null, initial_cash: 10_000_000, max_positions: 10, max_weight: .1,
    cash_floor: .05, commission_rate: 0, commission_min: 0, slippage: .001, max_adv20_fraction: null,
    stress_bps: [25, 50], min_coverage: .8, min_training_samples: 20_000, min_labelled_days: 12, min_trades: 30,
    actions: ["disposition", "priority"], validation_sessions: 60,
  });
  expect(await screen.findByRole("region", { name: "冻结契约" })).toBeInTheDocument();
  expect(window.location.search).toContain("experiment=exp-1-aaaaaaaa");
});

it("选了来源账户时，资金、组合规则和费用留空交给服务端复制，并说明会复制什么", async () => {
  render(<ExperimentWorkspace />);
  const form = await screen.findByRole("form", { name: "登记模型实验" });
  await within(form).findByRole("option", { name: "动量账户" });
  fireEvent.change(within(form).getByLabelText("来源账户"), { target: { value: "3" } });
  expect(await within(form).findByText(/将从「动量账户」复制：初始资金 ¥5,000,000 · 最多 5 只 · 单只上限 20%/)).toBeInTheDocument();
  expect(within(form).getByLabelText("初始资金")).toBeDisabled();
  expect(within(form).getByRole("region", { name: "登记后冻结的内容" })).toHaveTextContent("持有分数最高的前 5 只");
  fireEvent.change(within(form).getByLabelText("测试起点"), { target: { value: "2026-01-05" } });
  fireEvent.change(within(form).getByLabelText("测试终点"), { target: { value: "2026-10-16" } });
  fireEvent.click(within(form).getByRole("button", { name: "登记并运行" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].body).toMatchObject({ source_account_id: 3, initial_cash: null, max_positions: null, max_weight: null, cash_floor: null,
    commission_rate: null, commission_min: null, slippage: null, max_adv20_fraction: .05 });
});

it("服务端拒绝登记时原样说明原因，按钮可再次提交", async () => {
  refusal = { status: 422, detail: "测试起点 2026-01-04 不是已知开市日" };
  render(<ExperimentWorkspace />);
  const form = await screen.findByRole("form", { name: "登记模型实验" });
  fireEvent.change(within(form).getByLabelText("测试起点"), { target: { value: "2026-01-04" } });
  fireEvent.change(within(form).getByLabelText("测试终点"), { target: { value: "2026-10-16" } });
  fireEvent.click(within(form).getByRole("button", { name: "登记并运行" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("测试起点 2026-01-04 不是已知开市日");
  expect(within(form).getByRole("button", { name: "登记并运行" })).not.toBeDisabled();
  expect(window.location.search).not.toContain("experiment=");
});

it("已完成实验：证据状态、冻结契约与 hash、日期折的已看过标记、预测诊断和带口径的对比表", async () => {
  render(<ExperimentWorkspace initialExperiment="exp-1-aaaaaaaa" />);
  const evidence = await screen.findByRole("region", { name: "证据状态" });
  expect(within(evidence).getByText("探索性")).toBeInTheDocument();
  expect(within(evidence).getByText(/第 1 折的测试段在登记前已被查看过/)).toBeInTheDocument();
  expect(within(evidence).getByText("50740 在 2023-06-29 配股：持仓未调整")).toBeInTheDocument();

  const terms = screen.getByRole("table", { name: "冻结契约" });
  expect(within(terms).getByText("model_experiment_v1 · sha256 a168f3ab6b3000d8a725")).toBeInTheDocument();
  expect(within(terms).getByRole("rowheader", { name: "已看过截至" }).nextSibling).toHaveTextContent("2026-03-31");
  expect(within(terms).getByText(/不开新仓，已有持仓保留，不沿用旧分数/)).toBeInTheDocument();
  expect(within(terms).getByText(/每边滑点 \+10 bps（共 20 bps）、每边滑点 \+25 bps（共 35 bps）、每边滑点 \+50 bps（共 60 bps）。.*手续费率和最低手续费沿用基础成本，不加压/))
    .toBeInTheDocument();
  expect(within(terms).getByRole("rowheader", { name: "持有规则" }).nextSibling).toHaveTextContent(
    "第一个决策日 2026-01-05（测试区间第一天）· 之后每隔 5 个开市日一个决策日");
  expect(within(terms).getByRole("rowheader", { name: "最低要求" }).nextSibling).toHaveTextContent(
    "主模型每折至少 20,000 个训练样本 · 至少 24 个有标签的决策日");

  const read = screen.getByRole("region", { name: "读取的数据" });
  expect(within(read).getByText("本次读取于 2026-10-19 08:00（UTC）")).toBeInTheDocument();
  expect(within(read).getByText(/没有逐行的历史可得时间/)).toBeInTheDocument();
  expect(within(read).getByText("5,280,487")).toBeInTheDocument();
  expect(within(read).getByText(/t 日的日线在 t 收盘后同步/)).toBeInTheDocument();

  const folds = screen.getByRole("table", { name: "日期折列表" });
  const [first, second] = within(folds).getAllByRole("row").slice(1);
  expect(within(first).getByText("探索性（已看过）")).toBeInTheDocument();
  expect(within(second).getByText("登记前未看过")).toBeInTheDocument();
  expect(within(first).getAllByText("101,891 个 ·")).toHaveLength(2);
  expect(within(folds).getByRole("columnheader", { name: "对照 1：样本 · 工件" })).toBeInTheDocument();

  const diag = screen.getByRole("table", { name: "模型诊断" });
  expect(within(diag).getByText("0.004")).toBeInTheDocument();
  expect(within(diag).getByText("对照 1 · 规则：短期反转（rule_short_reversal_v1）")).toBeInTheDocument();
  expect(within(diag).getAllByText("99.80%")).toHaveLength(2);

  const comparison = screen.getByRole("table", { name: "回放与基准对比" });
  const rows = within(comparison).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(5);
  expect(within(rows[0]).getByText("主模型 · Ridge 回归（ridge_v1） · 基础成本")).toBeInTheDocument();
  expect(within(rows[0]).getByText("−32.50%")).toBeInTheDocument();
  expect(within(rows[1]).getByText("主模型 · Ridge 回归（ridge_v1） · 压力 +25 bps")).toBeInTheDocument();
  expect(within(rows[1]).getByText("35 bps")).toBeInTheDocument();
  expect(within(rows[3]).getByText("TOPIX 价格指数（参照）")).toBeInTheDocument();
  expect(within(rows[4]).getByText("合格池等权（参照，未扣费）")).toBeInTheDocument();
  const effect = screen.getByRole("region", { name: "组合效果" });
  expect(within(effect).getByText(/TOPIX 价格指数，测试首日收盘到末日收盘，不含分红/)).toBeInTheDocument();
  expect(within(effect).getByText(/每个决策日当天股票池里有标签的证券等权，不扣费用（共 1 期）/)).toBeInTheDocument();
  expect(within(effect).getByText(/手续费率和最低手续费沿用基础成本，不加压（基础每边滑点 10 bps）/)).toBeInTheDocument();
  expect(within(effect).queryByText(/一致/)).not.toBeInTheDocument();

  expect(await screen.findByText("净值图表")).toBeInTheDocument();
  expect(screen.getByText(/成交 80 笔，开盘过期 2 笔（开盘涨停，买不到 2 笔）/)).toBeInTheDocument();
  expect(posts).toHaveLength(0);
});

it("逐日决定：每天的持仓处置和理由、分数前列、计划单、开盘成交、目标与实际持仓、现金净值和约束触发", async () => {
  render(<ExperimentWorkspace initialExperiment="exp-1-aaaaaaaa" />);
  const list = await screen.findByRole("table", { name: "逐日列表" });
  await waitFor(() => expect(within(list).getAllByRole("row")).toHaveLength(3));
  expect(await screen.findByRole("region", { name: "2026-01-05 的决定" })).toBeInTheDocument();
  fireEvent.click(within(list).getByRole("button", { name: "查看 2026-01-26" }));
  const detail = await screen.findByRole("region", { name: "2026-01-26 的决定" });
  expect(within(detail).getByText(/现金 ¥1,384,178 · 净值 ¥10,448,478/)).toBeInTheDocument();

  const decisions = within(detail).getByRole("table", { name: "持仓处置" });
  expect(within(decisions).getAllByText("按模型分数排名")).toHaveLength(2);
  expect(within(decisions).getByText("当天没有可交易日线")).toBeInTheDocument();
  expect(within(decisions).getByText("0.0373")).toBeInTheDocument();
  expect(within(within(detail).getByRole("table", { name: "分数前列" })).getByText("已持有")).toBeInTheDocument();

  const orders = within(detail).getByRole("table", { name: "计划订单" });
  expect(within(orders).getByText("跌出持有名单")).toBeInTheDocument();
  expect(within(orders).getByText("按成交额上限压缩")).toBeInTheDocument();
  expect(within(orders).getByText("开盘涨停，买不到")).toBeInTheDocument();
  expect(within(within(detail).getByRole("table", { name: "开盘执行" })).getByText("−956,856")).toBeInTheDocument();

  const target = within(detail).getByRole("table", { name: "目标与实际持仓" });
  const row = (code: string) => within(target).getByText(code).closest("tr")!;
  expect(row("2157")).toHaveTextContent("1,1000−1,100");
  expect(row("9984")).toHaveTextContent("0300+300");
  expect(within(detail).getByText(/买不起一手 2 笔.*按成交额上限压缩 1 笔；跌出持有名单卖出 1 只/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "只看决策日" }));
  await waitFor(() => expect(reads("/days").some(u => u.searchParams.get("decision_only") === "true")).toBe(true));
});

it("压力场景回放也能逐日浏览；逐日记录和订单按所选回放分页读取", async () => {
  render(<ExperimentWorkspace initialExperiment="exp-1-aaaaaaaa" />);
  await screen.findByRole("table", { name: "逐日列表" });
  const picker = screen.getByRole("group", { name: "选择回放" });
  fireEvent.click(within(picker).getByRole("button", { name: "主模型 · 压力 +25 bps" }));
  expect(await screen.findByRole("heading", { name: "逐日决定 · 主模型 · 压力 +25 bps" })).toBeInTheDocument();
  await waitFor(() => expect(reads("/replays/2/days")).not.toHaveLength(0));
  expect(await screen.findByRole("table", { name: "逐日列表" })).toBeInTheDocument();
  await waitFor(() => expect(reads("/replays/2/orders")).not.toHaveLength(0));
  const ledger = await screen.findByRole("table", { name: "实验回放交易记录" });
  expect(within(ledger).getByText("4541")).toBeInTheDocument();
});

it("失败的实验显示原因，重试是新尝试并打开它", async () => {
  experiments["exp-1-aaaaaaaa"] = { ...completed, status: "failed", report: null, evidence_status: null, fold_results: [],
    data_read: null, error: "缺数据：实验读取区间有 1 个开市日没有股票日线（2025-03-03），补齐行情后可以重试", error_code: "missing_data" };
  experiments["exp-2-bbbbbbbb"] = { ...completed, id: "exp-2-bbbbbbbb", status: "queued", report: null, evidence_status: null,
    finished_at: null, fold_results: [], progress: {}, retry_of: "exp-1-aaaaaaaa" };
  nextId = "exp-2-bbbbbbbb";
  render(<ExperimentWorkspace initialExperiment="exp-1-aaaaaaaa" />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("缺数据 实验失败：缺数据：实验读取区间有 1 个开市日没有股票日线（2025-03-03）");
  expect(alert).toHaveTextContent("行情、TOPIX 或交易日历还没补齐；补齐后可以重试");
  expect(screen.queryByRole("region", { name: "读取的数据" })).not.toBeInTheDocument();
  expect(screen.getByRole("table", { name: "冻结契约" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "证据状态" })).not.toBeInTheDocument();
  fireEvent.click(within(alert).getByRole("button", { name: "重试（新尝试）" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].path).toBe("/api/experiments/exp-1-aaaaaaaa/retry");
  expect(posts[0].body).toHaveProperty("request_key");
  expect(await screen.findByText(/的重试，契约相同/)).toBeInTheDocument();
  expect(screen.getByText("排队中：等待开始")).toBeInTheDocument();
  expect(window.location.search).toContain("experiment=exp-2-bbbbbbbb");
});

it("运行中显示持久进度，离开页面后不再轮询", async () => {
  experiments["exp-1-aaaaaaaa"] = { ...completed, status: "running", report: null, finished_at: null, fold_results: [],
    progress: { stage: "replaying", replays_done: 1, replays_total: 5, sessions_done: 40, sessions_total: 120, current_session: "2026-03-02" } };
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const { unmount } = render(<ExperimentWorkspace initialExperiment="exp-1-aaaaaaaa" />);
    expect(await screen.findByText("运行中：回放 第 2 / 5 个：40 / 120 个开市日（2026-03-02）")).toBeInTheDocument();
    expect(screen.queryByText("净值图表")).not.toBeInTheDocument();
    const first = reads("/api/experiments/exp-1-aaaaaaaa").length;
    await vi.advanceTimersByTimeAsync(1600);
    await waitFor(() => expect(reads("/api/experiments/exp-1-aaaaaaaa").length).toBeGreaterThan(first));
    unmount();
    const seen = reads("/api/experiments/exp-1-aaaaaaaa").length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(reads("/api/experiments/exp-1-aaaaaaaa")).toHaveLength(seen);
  } finally { vi.useRealTimers(); }
});

it("选 XGBoost 排序作主模型：说明搜索预算和要比较的参数组，由参数组决定的项不再让人填，提交时带上验证段", async () => {
  render(<ExperimentWorkspace />);
  const form = await screen.findByRole("form", { name: "登记模型实验" });
  expect(within(form).getByText(/搜索预算 1：参数登记时固定/)).toBeInTheDocument();
  expect(within(form).queryByLabelText("验证段")).not.toBeInTheDocument();

  fireEvent.change(within(form).getByLabelText("主模型"), { target: { value: "xgb_rank_ndcg_v1" } });
  expect(within(form).getByText(/搜索预算 4：每折在训练窗最后的验证段上比较下面 4 组参数/)).toBeInTheDocument();
  expect(within(form).getByText("第 1 组：树的最大深度 3、树的棵数 100")).toBeInTheDocument();
  expect(within(form).getByText("第 4 组：树的最大深度 4、树的棵数 200")).toBeInTheDocument();
  expect(within(form).queryByLabelText("树的最大深度")).not.toBeInTheDocument();  // the sets give it
  expect(within(form).getByLabelText("学习率")).toHaveValue(0.05);
  expect(within(form).getByLabelText("验证段")).toHaveValue(60);
  expect(within(form).getByRole("region", { name: "登记后冻结的内容" })).toHaveTextContent(
    "参数搜索：主模型每折从 4 组参数里，在训练窗最后 60 个开市日的验证段上选一组");

  fireEvent.click(within(form).getByRole("checkbox", { name: /Ridge 回归/ }));
  fireEvent.change(within(form).getByLabelText("验证段"), { target: { value: "40" } });
  fireEvent.change(within(form).getByLabelText("测试起点"), { target: { value: "2026-01-05" } });
  fireEvent.change(within(form).getByLabelText("测试终点"), { target: { value: "2026-10-16" } });
  fireEvent.click(within(form).getByRole("button", { name: "登记并运行" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].body).toMatchObject({
    trainer: "xgb_rank_ndcg_v1", validation_sessions: 40, baselines: ["rule_short_reversal_v1", "ridge_v1"],
    trainer_params: { max_depth: 3, n_estimators: 100, learning_rate: 0.05, seed: 7, threads: 4 },
  });
});

it("排序模型的实验：契约写出参数搜索，各折写出选了哪组和各组得分，诊断给出前 N 名命中率，工件给出完整链接", async () => {
  const grid = defaults.searches.xgb_rank_ndcg_v1.map(set => ({ ...defaults.trainers.xgb_rank_ndcg_v1, ...set }));
  const tries = grid.map((params, n) => ({ params, samples: 90_000, validation: [.001, .002, -.001, null][n], days: 54,
    error: n === 3 ? "XGBoostError: 内存不足" : null, chosen: n === 1 }));
  const ranker: Schemas["ExperimentDetail"] = {
    ...completed, id: "exp-2-bbbbbbbb", name: "横截面排序 A",
    contract: { ...contract, version: "model_experiment_v2",
      model: { trainer: "xgb_rank_ndcg_v1", params: defaults.trainers.xgb_rank_ndcg_v1, search_budget: 4,
        search: { grid, validation_sessions: 60, top_n: 10, basis: "每折把训练窗最后若干个开市日留作验证段" } },
      baselines: [{ trainer: "ridge_v1", params: { alpha: 1 } }, { trainer: "rule_short_reversal_v1", params: {} }] },
    report: { ...report, models: [
      { ...report.models[0], trainer: "xgb_rank_ndcg_v1",
        diagnostics: { ...diagnostics(.012), top_n_hit_mean: .12, top_n_excess_mean: .0034 } },
      { ...report.models[1], trainer: "ridge_v1" }] },
    fold_results: [
      foldResult("model", 1, { search: tries, artifact: { trainer: "xgb_rank_ndcg_v1", params: grid[1], train_cutoff: "2025-12-30",
        samples: 101_891, state: { groups: 190, booster: { omitted: true, characters: 420_000, sha256: "beef" } } } }),
      foldResult("baseline_1", 1)],
  };
  experiments["exp-2-bbbbbbbb"] = ranker;
  render(<ExperimentWorkspace initialExperiment="exp-2-bbbbbbbb" />);

  const terms = await screen.findByRole("table", { name: "冻结契约" });
  expect(within(terms).getByRole("rowheader", { name: "参数搜索" }).nextSibling).toHaveTextContent(
    "验证段 60 个开市日 · 看前 10 名 · 第 1 组 树的最大深度 3、树的棵数 100；第 2 组 树的最大深度 3、树的棵数 200");
  expect(within(terms).getByRole("rowheader", { name: "主模型" }).nextSibling).toHaveTextContent("搜索预算 4");
  expect(within(terms).getByRole("rowheader", { name: "对照模型" }).nextSibling).toHaveTextContent(
    "Ridge 回归（ridge_v1）、规则：短期反转（rule_short_reversal_v1）");

  const folds = screen.getByRole("table", { name: "日期折列表" });
  expect(within(folds).getByText("选第 2 组：树的最大深度 3、树的棵数 200")).toBeInTheDocument();
  fireEvent.click(screen.getByText("各折参数搜索（每组在验证段上的得分）"));
  const search = screen.getByRole("table", { name: "各折参数搜索" });
  const rows = within(search).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(4);
  expect(within(rows[1]).getByText("选中")).toBeInTheDocument();
  expect(within(rows[1]).getByText("+0.20%")).toBeInTheDocument();
  expect(within(rows[3]).getByText("失败：XGBoostError: 内存不足")).toBeInTheDocument();

  const diag = screen.getByRole("table", { name: "模型诊断" });
  expect(within(diag).getByRole("columnheader", { name: "前 10 名命中率" })).toBeInTheDocument();
  expect(within(diag).getByText("12.00%")).toBeInTheDocument();
  expect(within(diag).getByText("+0.34%")).toBeInTheDocument();

  fireEvent.click(screen.getByText("查看各折工件"));
  expect(screen.getByRole("link", { name: "主模型 第 1 折的完整工件" })).toHaveAttribute(
    "href", "/api/experiments/exp-2-bbbbbbbb/folds/model/1/artifact");
});
