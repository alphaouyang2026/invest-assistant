import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SignalBoard } from "@/app/signals/signal-board";

const CANDIDATES: Record<string, unknown[]> = {
  trend_pullback_v1: [
    { code: "72030", name: "トヨタ自動車", market: "0111", priority: 0.2718, reason_codes: ["ema_uptrend", "rsi_recovery"] },
  ],
  technical_rating_v1: [
    { code: "67580", name: "ソニーグループ", market: "0111", priority: 0.61, reason_codes: ["strong_buy"] },
  ],
  topix_buy_and_hold_v1: [
    { code: "13060", name: "ＮＥＸＴ　ＦＵＮＤＳ　ＴＯＰＩＸ連動型上場投信", market: "0109", priority: 1, reason_codes: ["always_hold"] },
  ],
};

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
      const strategy = url.searchParams.get("strategy") ?? "";
      return json({
        strategy,
        date: url.searchParams.get("date") ?? "2026-09-24",
        candidates: CANDIDATES[strategy] ?? [],
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
    expect(within(row).getByRole("link", { name: "7203" })).toHaveAttribute("href", "/signals/72030?strategy=trend_pullback_v1");
    expect(within(row).getByText("トヨタ自動車")).toBeInTheDocument();
    expect(within(row).getByText("Prime")).toBeInTheDocument();
    expect(within(row).getByText("0.27")).toBeInTheDocument();
    expect(within(row).getByText(/EMA20 在 EMA60 之上/)).toBeInTheDocument();
    expect(screen.getByLabelText("收盘日")).toHaveValue("2026-09-24");
    expect(backend.asked[0]).toBe("/api/signals?strategy=trend_pullback_v1");
  });

  it("换策略、换日期都重新读取", async () => {
    const user = userEvent.setup();
    render(<SignalBoard />);
    await screen.findByRole("table", { name: "入场候选" });

    await user.click(screen.getByRole("button", { name: "技术评级 v1" }));
    expect(await screen.findByRole("link", { name: "6758" })).toHaveAttribute(
      "href", "/signals/67580?strategy=technical_rating_v1",
    );
    expect(screen.getByText("强烈买入")).toBeInTheDocument();

    // A date input takes a whole date at once; typing it digit by digit
    // passes through invalid values, which the input throws away.
    fireEvent.change(screen.getByLabelText("收盘日"), { target: { value: "2026-09-18" } });
    await waitFor(() => expect(backend.asked.at(-1)).toBe("/api/signals?strategy=technical_rating_v1&date=2026-09-18"));
  });

  it("TOPIX ETF 一直持有的入场候选是 1306：市场显示その他，理由是一直持有（对照组）", async () => {
    const user = userEvent.setup();
    render(<SignalBoard />);
    await screen.findByRole("table", { name: "入场候选" });

    await user.click(screen.getByRole("button", { name: "TOPIX ETF 一直持有" }));

    const link = await screen.findByRole("link", { name: "1306" });
    expect(link).toHaveAttribute("href", "/signals/13060?strategy=topix_buy_and_hold_v1");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("その他")).toBeInTheDocument();
    expect(within(row).getByText("一直持有（对照组）")).toHaveClass("badge", "up");
    expect(within(row).getByText("1.00")).toBeInTheDocument();
  });

  it("搜索证券，结果链接到详情页", async () => {
    const user = userEvent.setup();
    render(<SignalBoard />);
    await screen.findByRole("table", { name: "入场候选" });

    await user.type(screen.getByLabelText("查证券"), "トヨタ");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    const results = await screen.findByRole("list", { name: "搜索结果" });
    expect(within(results).getByRole("link", { name: /7203.*トヨタ自動車/ })).toHaveAttribute(
      "href", "/signals/72030?strategy=trend_pullback_v1",
    );
    expect(decodeURIComponent(backend.asked.at(-1) ?? "")).toBe("/api/instruments?q=トヨタ");
  });

  it("候选多于 50 只时分页，序号接着上一页", async () => {
    const many = Array.from({ length: 120 }, (_, n) => ({
      code: String(10000 + n * 10), name: `会社${n}`, market: "0111", priority: 1 - n / 200, reason_codes: ["buy"],
    }));
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ strategy: "trend_pullback_v1", date: "2026-09-24", candidates: many }),
                   { headers: { "Content-Type": "application/json" } })));
    const user = userEvent.setup();
    render(<SignalBoard />);

    const table = await screen.findByRole("table", { name: "入场候选" });
    expect(within(table).getAllByRole("row")).toHaveLength(51);
    expect(screen.getByText(/第 1–50 只，共 120 只/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "末页" }));
    const rows = within(screen.getByRole("table", { name: "入场候选" })).getAllByRole("row");
    expect(rows).toHaveLength(21);
    expect(within(rows[1]).getByText("101")).toBeInTheDocument();
    expect(within(rows[1]).getByText("会社100")).toBeInTheDocument();
  });
});
