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
let refused: boolean;
let current: Schemas["ResearchDetail"];
let orderTotal: number;

beforeEach(() => {
  submitted = []; refused = false; current = completed; orderTotal = 0;
  window.history.replaceState(null, "", "/accounts/research");
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (request.method === "POST") {
      submitted.push(await request.json());
      return refused ? response({ detail: "另一个任务正在运行，请稍后重试" }, 409) : response({ id: "run-one" }, 202);
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
  refused = true;
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
