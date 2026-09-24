import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SignalBoard } from "@/app/signals/signal-board";

/**
 * A stand-in for the backend: answers `/api/signals` and `/api/instruments`
 * and records what the page asked for.
 */
function fakeBackend() {
  const asked: string[] = [];
  const fetch = vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    asked.push(url.pathname + url.search);
    const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
    if (url.pathname === "/api/signals") {
      const strategy = url.searchParams.get("strategy");
      return json({
        strategy,
        date: url.searchParams.get("date") ?? "2026-09-24",
        candidates:
          strategy === "trend_pullback_v1"
            ? [{ code: "72030", name: "トヨタ自動車", market: "0111", priority: 0.2718, reason_codes: ["ema_uptrend", "rsi_recovery"] }]
            : [{ code: "67580", name: "ソニーグループ", market: "0111", priority: 0.61, reason_codes: ["strong_buy"] }],
      });
    }
    if (url.pathname === "/api/instruments") {
      return json([{ code: "72030", name: "トヨタ自動車", name_en: "TOYOTA MOTOR", market: "0111" }]);
    }
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
  return { asked, fetch };
}

let backend: ReturnType<typeof fakeBackend>;

beforeEach(() => {
  backend = fakeBackend();
  vi.stubGlobal("fetch", backend.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("信号页", () => {
  it("默认显示 Trend-Pullback 在最新交易日的入场候选", async () => {
    render(<SignalBoard />);

    const table = await screen.findByRole("table", { name: "入场候选" });
    const [, row] = within(table).getAllByRole("row");
    expect(within(row).getByRole("link", { name: "72030" })).toHaveAttribute("href", "/signals/72030?strategy=trend_pullback_v1");
    expect(within(row).getByText("トヨタ自動車")).toBeInTheDocument();
    expect(within(row).getByText("Prime")).toBeInTheDocument();
    expect(within(row).getByText("0.27")).toBeInTheDocument();
    expect(within(row).getByText(/EMA20 在 EMA60 之上/)).toBeInTheDocument();
    expect(screen.getByLabelText("日期")).toHaveValue("2026-09-24");
    expect(backend.asked[0]).toBe("/api/signals?strategy=trend_pullback_v1");
  });

  it("换策略、换日期都重新读取", async () => {
    const user = userEvent.setup();
    render(<SignalBoard />);
    await screen.findByRole("table", { name: "入场候选" });

    await user.selectOptions(screen.getByLabelText("策略"), "技术评级 v1");
    expect(await screen.findByRole("link", { name: "67580" })).toHaveAttribute(
      "href", "/signals/67580?strategy=technical_rating_v1",
    );
    expect(screen.getByText("强烈买入")).toBeInTheDocument();

    // A date input takes a whole date at once; typing it digit by digit
    // passes through invalid values, which the input throws away.
    fireEvent.change(screen.getByLabelText("日期"), { target: { value: "2026-09-18" } });
    await waitFor(() => expect(backend.asked.at(-1)).toBe("/api/signals?strategy=technical_rating_v1&date=2026-09-18"));
  });

  it("搜索证券，结果链接到详情页", async () => {
    const user = userEvent.setup();
    render(<SignalBoard />);
    await screen.findByRole("table", { name: "入场候选" });

    await user.type(screen.getByLabelText("搜索证券"), "トヨタ");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    const results = await screen.findByRole("list", { name: "搜索结果" });
    expect(within(results).getByRole("link", { name: /72030.*トヨタ自動車/ })).toHaveAttribute(
      "href", "/signals/72030?strategy=trend_pullback_v1",
    );
    expect(decodeURIComponent(backend.asked.at(-1) ?? "")).toBe("/api/instruments?q=トヨタ");
  });
});
