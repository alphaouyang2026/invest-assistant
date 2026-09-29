import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResearchWorkspace } from "@/app/accounts/research/research-workspace";
import type { Schemas } from "@/lib/api/client";

vi.mock("@/app/accounts/nav-chart", () => ({ NavChart: () => <div>净值图表</div> }));
const config = { name: "技术账户", strategy: "technical_rating_v1", strategy_params: { entry_above: .5, exit_below: -.1 },
  portfolio_rules: { initial_cash: "10000000", max_positions: 10, max_weight: "0.1", cash_floor: "0.05" },
  costs: { commission_rate: "0", commission_min: "0", slippage: "0.001" }, start_date: "2025-01-06", end_date: "2025-01-10" };
const completed: Schemas["ResearchDetail"] = { id: "run-one", config, status: "completed", created_at: "2026-09-29", finished_at: "2026-09-29",
  progress: { sessions_done: 5, sessions_total: 5 }, error: null, code_version: "sha256:code", input_identity: { sha256: "data" }, retry_of: null,
  result: { total_return: .1, topix_return: .05, excess_return: .05, max_drawdown: .02, trades: 1, fees: 0,
    realised_pnl: 0, unrealised_pnl: 1000000, cash: 9000000, holdings: [], pending: [], warnings: [],
    nav: [{ date: "2025-01-06", nav: 10000000, nav_curve: 1, topix_curve: 1, drawdown: 0 }] } };
let submitted: unknown[];
let refusal: { status: number; detail: unknown } | null;
let current: Schemas["ResearchDetail"];
let orderTotal: number;

beforeEach(() => {
  submitted = []; refusal = null; current = completed; orderTotal = 0;
  window.history.replaceState(null, "", "/accounts/research");
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (request.method === "POST") {
      submitted.push(await request.json());
      return refusal ? response({ detail: refusal.detail }, refusal.status) : response({ id: "run-one" }, 202);
    }
    if (url.pathname.endsWith("/sources")) return response([{ id: 1, name: "技术账户", config }]);
    if (url.pathname.endsWith("/orders")) return response({ total: orderTotal, page: Number(url.searchParams.get("page") ?? 1), page_size: 50, orders: [] });
    if (url.pathname.endsWith("/runs")) return response({ total: 1, page: 1, page_size: 10, runs: [current] });
    return response(current);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

it("手选区间提交，显示实际报告并将运行 ID 写入地址用于刷新恢复", async () => {
  render(<ResearchWorkspace sourceId="1" />);
  await screen.findByRole("option", { name: "技术账户" });
  await waitFor(() => expect(screen.getByLabelText("起始日")).toHaveValue("2025-01-06"));
  fireEvent.change(screen.getByLabelText("结束日"), { target: { value: "2025-01-10" } });
  fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
  expect(await screen.findByText("净值图表")).toBeInTheDocument();
  expect(screen.getByText("+10.00%")).toBeInTheDocument();
  expect(submitted).toHaveLength(1);
  expect(submitted[0]).toMatchObject({ source_account_id: 1, start_date: "2025-01-06", end_date: "2025-01-10", entry_above: .5, exit_below: -.1 });
  expect(window.location.search).toContain("run=run-one");
  expect(screen.getByText(/探索性历史结果/)).toBeInTheDocument();
});

it("初始运行 ID 直接恢复已存报告和分页账本，不重新提交", async () => {
  orderTotal = 51;
  render(<ResearchWorkspace initialRun="run-one" />);
  await screen.findByText("净值图表");
  const table = await screen.findByRole("table", { name: "研究交易记录" });
  const section = table.closest("section")!;
  await waitFor(() => expect(within(section).getByRole("button", { name: "下一页" })).not.toBeDisabled());
  fireEvent.click(within(section).getByRole("button", { name: "下一页" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([r]) => String((r as Request).url).includes("page=2"))).toBe(true));
  expect(submitted).toHaveLength(0);
});

it("忙时显示服务端错误，表单可再次提交而非永久 loading", async () => {
  refusal = { status: 409, detail: "另一个任务正在运行，请稍后重试" };
  render(<ResearchWorkspace sourceId="1" />);
  await screen.findByRole("option", { name: "技术账户" });
  fireEvent.change(screen.getByLabelText("结束日"), { target: { value: "2025-01-10" } });
  fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("另一个任务正在运行");
  expect(screen.getByRole("button", { name: "运行回测" })).not.toBeDisabled();
});

it("失败运行可显式重试并保留原运行标识", async () => {
  current = { ...completed, status: "failed", result: null, error: "服务中断" };
  render(<ResearchWorkspace initialRun="run-one" />);
  fireEvent.click(await screen.findByRole("button", { name: "重试（新运行）" }));
  await waitFor(() => expect(submitted).toHaveLength(1));
  expect(submitted[0]).toHaveProperty("request_key");
});

it("运行中显示持久进度而不是空报告", async () => {
  current = { ...completed, status: "running", result: null };
  const { unmount } = render(<ResearchWorkspace initialRun="run-one" />);
  expect(await screen.findByText("运行中：5 / 5 个交易日")).toBeInTheDocument();
  expect(screen.queryByText("净值图表")).not.toBeInTheDocument();
  unmount();
});

async function fillAndRun(end = "2025-01-10") {
  await screen.findByRole("option", { name: "技术账户" });
  await waitFor(() => expect(screen.getByLabelText("起始日")).toHaveValue("2025-01-06"));
  fireEvent.change(screen.getByLabelText("结束日"), { target: { value: end } });
  fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
}

it("服务端逐字段的 422 错误按字段显示，而不是笼统的网络错误", async () => {
  refusal = { status: 422, detail: [
    { type: "less_than_equal", loc: ["body", "entry_above"], msg: "Input should be less than or equal to 1", input: 2, ctx: { le: 1 } },
    { type: "date_from_datetime_parsing", loc: ["body", "end_date"], msg: "Input should be a valid date", input: "x" },
  ] };
  render(<ResearchWorkspace sourceId="1" />);
  await fillAndRun();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("入场阈值：不能大于 1");
  expect(alert).toHaveTextContent("结束日：日期格式不对");
  expect(alert).not.toHaveTextContent("网络");
  expect(screen.getByRole("button", { name: "运行回测" })).not.toBeDisabled();
});

it("服务端拒绝的日期（非开市日、预热不足）原样说明原因", async () => {
  refusal = { status: 422, detail: "预热期不足，需要起始日前 260 个开市日" };
  render(<ResearchWorkspace sourceId="1" />);
  await fillAndRun();
  expect(await screen.findByRole("alert")).toHaveTextContent("预热期不足，需要起始日前 260 个开市日");
  expect(window.location.search).not.toContain("run=");
});

it("阈值超出 [-1,1] 或结束日早于起始日时，浏览器校验拦下，不发请求", async () => {
  render(<ResearchWorkspace sourceId="1" />);
  await fillAndRun("2025-01-03");
  expect(screen.getByLabelText("结束日")).toBeInvalid();
  fireEvent.change(screen.getByLabelText("结束日"), { target: { value: "2025-01-10" } });
  fireEvent.change(screen.getByLabelText("入场阈值 entry_above"), { target: { value: "1.5" } });
  fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
  expect(screen.getByLabelText("入场阈值 entry_above")).toBeInvalid();
  fireEvent.change(screen.getByLabelText("入场阈值 entry_above"), { target: { value: "0.5" } });
  fireEvent.change(screen.getByLabelText("退出阈值 exit_below"), { target: { value: "-2" } });
  fireEvent.click(screen.getByRole("button", { name: "运行回测" }));
  expect(screen.getByLabelText("退出阈值 exit_below")).toBeInvalid();
  expect(submitted).toHaveLength(0);
});

it("刷新恢复运行时，表单显示这次运行自己的日期和阈值", async () => {
  current = { ...completed, config: { ...config, source_account_id: 1, start_date: "2025-03-03", end_date: "2025-03-31",
    strategy_params: { entry_above: .6, exit_below: -.2 } } };
  render(<ResearchWorkspace initialRun="run-one" />);
  await screen.findByText("净值图表");
  await screen.findByRole("option", { name: "技术账户" });
  await waitFor(() => expect(screen.getByLabelText("起始日")).toHaveValue("2025-03-03"));
  expect(screen.getByLabelText("结束日")).toHaveValue("2025-03-31");
  expect(screen.getByLabelText("入场阈值 entry_above")).toHaveValue(.6);
  expect(screen.getByLabelText("退出阈值 exit_below")).toHaveValue(-.2);
  expect(screen.getByLabelText("来源账户")).toHaveValue("1");
});

it("离开页面后不再轮询运行状态", async () => {
  current = { ...completed, status: "running", result: null };
  const reads = () => vi.mocked(fetch).mock.calls
    .filter(([r]) => new URL((r as Request).url).pathname === "/api/research/runs/run-one").length;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const { unmount } = render(<ResearchWorkspace initialRun="run-one" />);
    await screen.findByText("运行中：5 / 5 个交易日");
    const first = reads();
    await vi.advanceTimersByTimeAsync(1600);
    await waitFor(() => expect(reads()).toBeGreaterThan(first));
    unmount();
    const seen = reads();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(reads()).toBe(seen);
  } finally { vi.useRealTimers(); }
});
