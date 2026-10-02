import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewAccount } from "@/app/accounts/new/new-account";

const pushed: string[] = [];
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: (href: string) => pushed.push(href) }) }));

const STOCK_RULES = { max_positions: 10, max_weight: 0.1, cash_floor: 0.05 };
const STRATEGIES = [
  { name: "trend_pullback_v1", defaults: { warmup_sessions: 180, rsi_oversold: 30 },
    universe_rule: "prime_common_stock", suggested_rules: STOCK_RULES },
  { name: "technical_rating_v1", defaults: { warmup_sessions: 260, entry_above: 0.5, exit_below: -0.1 },
    universe_rule: "prime_common_stock", suggested_rules: STOCK_RULES },
  { name: "topix_buy_and_hold_v1", defaults: { warmup_sessions: 1 },
    universe_rule: "topix_etf", suggested_rules: { max_positions: 1, max_weight: 1, cash_floor: 0.05 } },
];

function fakeBackend(created: { status: number; body: unknown }) {
  const posted: unknown[] = [];
  const fetch = vi.fn(async (input: Request) => {
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const path = new URL(input.url).pathname;
    if (path === "/api/strategies") return json(STRATEGIES);
    if (path === "/api/accounts" && input.method === "POST") {
      posted.push(await input.json());
      return json(created.body, created.status);
    }
    return json({ detail: "not found" }, 404);
  });
  return { posted, fetch };
}

let backend: ReturnType<typeof fakeBackend>;

beforeEach(() => {
  pushed.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("新建账户", () => {
  it("按默认值填好表单，只送出改过的策略参数，百分比换成小数，建好后去账户页", async () => {
    backend = fakeBackend({ status: 201, body: { id: 7, advance_job_id: "job1", advance_refused: null } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.click(await screen.findByRole("radio", { name: /技术评级 v1/ }));
    expect(screen.getByLabelText("入场线")).toHaveValue(0.5);
    expect(screen.getByLabelText("单只上限")).toHaveValue(10); // %
    await user.type(screen.getByLabelText("账户名称"), "技术评级三年");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2023-09-19" } });
    await user.clear(screen.getByLabelText("入场线"));
    await user.type(screen.getByLabelText("入场线"), "0.6");
    await user.clear(screen.getByLabelText("单只上限"));
    await user.type(screen.getByLabelText("单只上限"), "12.5");
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    await vi.waitFor(() => expect(pushed).toEqual(["/accounts/7"]));
    expect(backend.posted).toEqual([{
      name: "技术评级三年", strategy: "technical_rating_v1", start_date: "2023-09-19",
      strategy_params: { entry_above: 0.6 },
      initial_cash: 10000000, max_positions: 10, max_weight: 0.125, cash_floor: 0.05,
      commission_rate: 0, commission_min: 0, slippage: 0.001,
    }]);
  });

  it("选 TOPIX ETF 一直持有就按它的建议填组合规则，填好后可以再改，切回个股策略时恢复", async () => {
    backend = fakeBackend({ status: 201, body: { id: 8, advance_job_id: "job2", advance_refused: null } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);
    const rules = () => ["最多持有", "单只上限", "现金下限"].map((label) => screen.getByLabelText(label));

    await user.click(await screen.findByRole("radio", { name: /TOPIX ETF 一直持有/ }));
    rules().forEach((input, n) => expect(input).toHaveValue([1, 100, 5][n])); // 只, %, %
    await user.clear(screen.getByLabelText("现金下限"));
    await user.type(screen.getByLabelText("现金下限"), "3");
    expect(screen.getByLabelText("现金下限")).toHaveValue(3);

    await user.click(screen.getByRole("radio", { name: /技术评级 v1/ }));
    rules().forEach((input, n) => expect(input).toHaveValue([10, 10, 5][n]));

    await user.click(screen.getByRole("radio", { name: /TOPIX ETF 一直持有/ }));
    await user.type(screen.getByLabelText("账户名称"), "对照组");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2022-10-06" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    await vi.waitFor(() => expect(pushed).toEqual(["/accounts/8"]));
    expect(backend.posted).toEqual([{
      name: "对照组", strategy: "topix_buy_and_hold_v1", start_date: "2022-10-06", strategy_params: {},
      initial_cash: 10000000, max_positions: 1, max_weight: 1, cash_floor: 0.05,
      commission_rate: 0, commission_min: 0, slippage: 0.001,
    }]);
  });

  it("建不了时显示原因", async () => {
    backend = fakeBackend({ status: 422, body: { detail: "起始日 2023-09-17 不是开市日" } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.type(await screen.findByLabelText("账户名称"), "周日");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2023-09-17" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("起始日 2023-09-17 不是开市日");
    expect(pushed).toEqual([]);
  });
});
