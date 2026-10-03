import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewAccount } from "@/app/accounts/new/new-account";
import type { Schemas } from "@/lib/api/client";

const pushed: string[] = [];
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: (href: string) => pushed.push(href) }) }));

const STOCK_RULES = { max_positions: 10, max_weight: 0.1, cash_floor: 0.05 };
const ONE_ETF = { max_positions: 1, max_weight: 1, cash_floor: 0.05 };
type Pool = Pick<Schemas["StrategyOut"], "universe_rule" | "pool_codes" | "suggested_rules">;
const STOCKS: Pool = { universe_rule: "prime_common_stock", pool_codes: [], suggested_rules: STOCK_RULES };
const TOPIX_ETF: Pool = { universe_rule: "topix_etf", pool_codes: ["13060"], suggested_rules: ONE_ETF };
const STRATEGIES: Schemas["StrategyOut"][] = [
  { name: "trend_pullback_v1", defaults: { warmup_sessions: 180, rsi_oversold: 30 }, warmup_follows: null, ...STOCKS },
  { name: "technical_rating_v1", defaults: { warmup_sessions: 260, entry_above: 0.5, exit_below: -0.1 },
    warmup_follows: null, ...STOCKS },
  { name: "topix_buy_and_hold_v1", defaults: { warmup_sessions: 1 }, warmup_follows: null, ...TOPIX_ETF },
  { name: "topix_ma_v1", defaults: { ma_sessions: 200, band: 0.01, warmup_sessions: 200 },
    warmup_follows: { parameter: "ma_sessions", extra: 0 }, ...TOPIX_ETF },
  { name: "topix_momentum_v1", defaults: { lookback_sessions: 252, warmup_sessions: 253 },
    warmup_follows: { parameter: "lookback_sessions", extra: 1 }, ...TOPIX_ETF },
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

  it("TOPIX 均线：参数有均线窗口和缓冲带，预热期和它的提示跟着均线窗口变", async () => {
    backend = fakeBackend({ status: 201, body: { id: 9, advance_job_id: "job3", advance_refused: null } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.click(await screen.findByRole("radio", { name: /TOPIX 均线/ }));
    expect(screen.getByRole("radio", { name: /TOPIX 均线/ })).toHaveAccessibleName(/超过缓冲带（默认 1%）就买入/);
    expect(screen.getByLabelText("均线窗口")).toHaveValue(200);
    expect(screen.getByLabelText("缓冲带")).toHaveValue(0.01);
    expect(screen.getByText(/比例，0\.01 表示 1%/)).toBeInTheDocument();
    expect(screen.getByText(/之前至少有 200 个交易日的数据/)).toBeInTheDocument();
    expect(["最多持有", "单只上限", "现金下限"].map((label) => screen.getByLabelText(label))
      .map((input) => (input as HTMLInputElement).value)).toEqual(["1", "100", "5"]);

    await user.clear(screen.getByLabelText("均线窗口"));
    await user.type(screen.getByLabelText("均线窗口"), "120");
    expect(screen.getByLabelText("预热期")).toHaveValue(120);
    expect(screen.getByText(/之前至少有 120 个交易日的数据/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("账户名称"), "均线 120");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2022-10-06" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    await vi.waitFor(() => expect(pushed).toEqual(["/accounts/9"]));
    expect(backend.posted).toEqual([{
      name: "均线 120", strategy: "topix_ma_v1", start_date: "2022-10-06",
      strategy_params: { ma_sessions: 120, warmup_sessions: 120 },
      initial_cash: 10000000, max_positions: 1, max_weight: 1, cash_floor: 0.05,
      commission_rate: 0, commission_min: 0, slippage: 0.001,
    }]);
  });

  it("TOPIX 动量：说明写明每月第一个开市日判断，参数有回看长度，预热期比它多 1 并跟着它变", async () => {
    backend = fakeBackend({ status: 201, body: { id: 10, advance_job_id: "job4", advance_refused: null } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.click(await screen.findByRole("radio", { name: /TOPIX 动量/ }));
    const chosen = screen.getByRole("radio", { name: /TOPIX 动量/ });
    expect(chosen).toHaveAccessibleName(/每月第一个开市日判断，月中建的账户等到下个月才可能买入/);
    expect(chosen).toHaveAccessibleName(/过去收益.*为正就买入，为负就全部卖出/);
    expect(screen.getByLabelText("回看长度")).toHaveValue(252);
    expect(screen.getByLabelText("预热期")).toHaveValue(253);
    expect(screen.getByText(/252 约 12 个月/)).toBeInTheDocument();
    expect(screen.getByText(/之前至少有 253 个交易日的数据/)).toBeInTheDocument();
    expect(["最多持有", "单只上限", "现金下限"].map((label) => screen.getByLabelText(label))
      .map((input) => (input as HTMLInputElement).value)).toEqual(["1", "100", "5"]);

    await user.clear(screen.getByLabelText("回看长度"));
    await user.type(screen.getByLabelText("回看长度"), "126");
    expect(screen.getByLabelText("预热期")).toHaveValue(127);
    expect(screen.getByText(/之前至少有 127 个交易日的数据/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("账户名称"), "动量半年");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2022-10-06" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    await vi.waitFor(() => expect(pushed).toEqual(["/accounts/10"]));
    expect(backend.posted).toEqual([{
      name: "动量半年", strategy: "topix_momentum_v1", start_date: "2022-10-06",
      strategy_params: { lookback_sessions: 126, warmup_sessions: 127 },
      initial_cash: 10000000, max_positions: 1, max_weight: 1, cash_floor: 0.05,
      commission_rate: 0, commission_min: 0, slippage: 0.001,
    }]);
  });

  it("预热期设得比均线窗口短时，送出的就是填的值，被拒绝并说明原因", async () => {
    const why = "topix_ma_v1 的预热期 100 比均线窗口 200 短：均线还算不出来";
    backend = fakeBackend({ status: 422, body: { detail: why } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.click(await screen.findByRole("radio", { name: /TOPIX 均线/ }));
    await user.clear(screen.getByLabelText("预热期"));
    await user.type(screen.getByLabelText("预热期"), "100");
    await user.type(screen.getByLabelText("账户名称"), "太短");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2022-10-06" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(why);
    expect(backend.posted).toEqual([expect.objectContaining({ strategy_params: { warmup_sessions: 100 } })]);
    expect(pushed).toEqual([]);
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
