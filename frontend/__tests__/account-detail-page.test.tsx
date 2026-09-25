import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountDetail } from "@/app/accounts/account-detail";
import type { NavPoint } from "@/app/accounts/nav-chart";

const pushed: string[] = [];
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: (href: string) => pushed.push(href) }) }));

/** Drawn on a canvas, which jsdom lacks: a stand-in keeps what it is given. */
const drawn: { points: NavPoint[] | null } = { points: null };
vi.mock("@/app/accounts/nav-chart", () => ({
  NavChart: ({ points }: { points: NavPoint[] }) => {
    drawn.points = points;
    return <div data-testid="nav-chart" />;
  },
}));

const DETAIL = {
  id: 1, name: "技术评级三年", strategy: "technical_rating_v1", strategy_params: {},
  rules: { initial_cash: 10000000, max_positions: 10, max_weight: 0.1, cash_floor: 0.05 },
  costs: { commission_rate: 0, commission_min: 0, slippage: 0.001 },
  start_date: "2023-09-19", advanced_through: "2026-09-18", status: "active", backtest_data_mark: null,
  figures: { total_return: 0.24918, annualised_return: 0.07709, max_drawdown: 0.21868, sharpe: 0.4659,
             win_rate: 0.3679, average_holding_sessions: 25.58, annual_turnover: 7.53, excess_annualised_return: -0.1112 },
  holdings: [{ code: "72030", quantity: 300, opened_on: "2026-08-03", cost: 900300, close: 3025, value: 907500 }],
  pending: [{ id: 9, kind: "sell", code: "67580", signal_date: "2026-09-18", execution_date: "2026-09-24",
              planned_quantity: 200, priority: null, reason: { disposition: "exit", reason_codes: ["strong_sell"] },
              status: "pending", outcome_reason: null, filled_quantity: 0, fill_price: null, fees: 0, cash_delta: 0 }],
};
const NAV = [
  { date: "2023-09-19", nav: 10000000, nav_curve: 1, topix_curve: 1, drawdown: 0 },
  { date: "2023-09-20", nav: 10100000, nav_curve: 1.01, topix_curve: 0.99, drawdown: 0 },
];
const ORDERS = [
  { id: 1, kind: "buy", code: "72030", signal_date: "2026-07-31", execution_date: "2026-08-03", planned_quantity: 300,
    priority: 0.64, reason: { disposition: "hold", reason_codes: ["strong_buy"] }, status: "filled", outcome_reason: null,
    filled_quantity: 300, fill_price: 3001, fees: 0, cash_delta: -900300 },
  { id: 2, kind: "buy", code: "99840", signal_date: "2026-08-10", execution_date: "2026-08-11", planned_quantity: 100,
    priority: 0.55, reason: { disposition: "hold", reason_codes: ["strong_buy"] }, status: "expired",
    outcome_reason: "limit_up_open", filled_quantity: 0, fill_price: null, fees: 0, cash_delta: 0 },
];

function fakeBackend() {
  const asked: string[] = [];
  const fetch = vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname;
    asked.push(`${input.method} ${path}`);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (input.method !== "GET") return new Response(null, { status: 204 });
    if (path === "/api/accounts/1") return json(DETAIL);
    if (path === "/api/accounts/1/nav") return json(NAV);
    if (path === "/api/accounts/1/orders") return json(ORDERS);
    if (path === "/api/jobs/current") return json(null);
    return json({ detail: "not found" }, 404);
  });
  return { asked, fetch };
}

let backend: ReturnType<typeof fakeBackend>;

beforeEach(() => {
  pushed.length = 0;
  drawn.points = null;
  backend = fakeBackend();
  vi.stubGlobal("fetch", backend.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("账户详情", () => {
  it("统计、净值对 TOPIX 与回撤、持仓、明日订单与理由、历史订单", async () => {
    render(<AccountDetail id={1} />);

    const figures = await screen.findByRole("region", { name: "统计" });
    expect(within(figures).getByText("24.92%")).toBeInTheDocument();
    expect(within(figures).getByText("-11.12%")).toBeInTheDocument();
    expect(screen.getByText(/不含分红、不含税/)).toBeInTheDocument();
    await waitFor(() => expect(drawn.points).toEqual(NAV));

    const holdings = screen.getByRole("table", { name: "持仓" });
    expect(within(holdings).getByRole("link", { name: "72030" })).toHaveAttribute(
      "href", "/signals/72030?strategy=technical_rating_v1");
    const tomorrow = screen.getByRole("table", { name: "明日订单" });
    expect(within(tomorrow).getByText("卖出")).toBeInTheDocument();
    expect(within(tomorrow).getByText("强烈卖出")).toBeInTheDocument();
    const history = await screen.findByRole("table", { name: "历史订单与账户事件" });
    expect(within(history).getByText("开盘涨停，买不到")).toBeInTheDocument();
  });

  it("停用与删除", async () => {
    vi.stubGlobal("confirm", () => true);
    const user = userEvent.setup();
    render(<AccountDetail id={1} />);

    await user.click(await screen.findByRole("button", { name: "停用" }));
    await waitFor(() => expect(backend.asked).toContain("POST /api/accounts/1/stop"));

    await user.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(pushed).toEqual(["/accounts"]));
    expect(backend.asked).toContain("DELETE /api/accounts/1");
  });
});
