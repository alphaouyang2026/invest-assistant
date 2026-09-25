import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewAccount } from "@/app/accounts/new/new-account";

const pushed: string[] = [];
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: (href: string) => pushed.push(href) }) }));

const STRATEGIES = [
  { name: "trend_pullback_v1", defaults: { warmup_sessions: 180, rsi_oversold: 30 } },
  { name: "technical_rating_v1", defaults: { warmup_sessions: 260, entry_above: 0.5, exit_below: -0.1 } },
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
  it("按默认值填好表单，只送出改过的策略参数，建好后去账户页", async () => {
    backend = fakeBackend({ status: 201, body: { id: 7, advance_job_id: "job1", advance_refused: null } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.selectOptions(await screen.findByLabelText("策略"), "技术评级 v1");
    expect(screen.getByLabelText("entry_above")).toHaveValue(0.5);
    await user.type(screen.getByLabelText("名称"), "技术评级三年");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2023-09-19" } });
    await user.clear(screen.getByLabelText("entry_above"));
    await user.type(screen.getByLabelText("entry_above"), "0.6");
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    await vi.waitFor(() => expect(pushed).toEqual(["/accounts/7"]));
    expect(backend.posted).toEqual([{
      name: "技术评级三年", strategy: "technical_rating_v1", start_date: "2023-09-19",
      strategy_params: { entry_above: 0.6 },
      initial_cash: 10000000, max_positions: 10, max_weight: 0.1, cash_floor: 0.05,
      commission_rate: 0, commission_min: 0, slippage: 0.001,
    }]);
  });

  it("建不了时显示原因", async () => {
    backend = fakeBackend({ status: 422, body: { detail: "起始日 2023-09-17 不是开市日" } });
    vi.stubGlobal("fetch", backend.fetch);
    const user = userEvent.setup();
    render(<NewAccount />);

    await user.type(await screen.findByLabelText("名称"), "周日");
    fireEvent.change(screen.getByLabelText("起始日"), { target: { value: "2023-09-17" } });
    await user.click(screen.getByRole("button", { name: "新建并开始回测" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("起始日 2023-09-17 不是开市日");
    expect(pushed).toEqual([]);
  });
});
