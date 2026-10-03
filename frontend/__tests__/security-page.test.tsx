import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChartData } from "@/app/signals/price-chart";
import { SecurityDetail } from "@/app/signals/security-detail";

/**
 * lightweight-charts draws on a canvas, which jsdom does not have, so the
 * chart is swapped for a stand-in that keeps what it was given. What it
 * looks like drawn is checked by opening the page.
 */
const drawn: { data: ChartData | null } = { data: null };
vi.mock("@/app/signals/price-chart", () => ({
  PriceChart: ({ data }: { data: ChartData }) => {
    drawn.data = data;
    return <div data-testid="chart" />;
  },
}));

const BARS = {
  code: "72030",
  bars: [
    { date: "2026-09-16", open: null, high: null, low: null, close: null, volume: null }, // halted
    { date: "2026-09-17", open: 100, high: 102, low: 99, close: 101, volume: 5000 },
    { date: "2026-09-18", open: 101, high: 104, low: 100, close: 103, volume: 7000 },
  ],
  plots: [
    { indicator: "ema_fast", pane: "price" },
    { indicator: "rsi", pane: "separate" },
  ],
  lines: {
    ema_fast: [
      { date: "2026-09-16", value: null },
      { date: "2026-09-17", value: 100.5 },
      { date: "2026-09-18", value: 101.2 },
    ],
    rsi: [
      { date: "2026-09-16", value: null },
      { date: "2026-09-17", value: 28 },
      { date: "2026-09-18", value: 34 },
    ],
  },
  entries: ["2026-09-18"],
};

// What the strategy list says each universe rule names: the TOPIX ETF
// strategies buy 1306 alone.
const STRATEGY_POOLS = [
  { name: "trend_pullback_v1", pool_codes: [] },
  { name: "topix_ma_v1", pool_codes: ["13060"] },
  { name: "topix_momentum_v1", pool_codes: ["13060"] },
];

let asked: string[];

beforeEach(() => {
  asked = [];
  drawn.data = null;
  stubBackend(BARS);
});

function stubBackend(bars: typeof BARS) {
  vi.stubGlobal("fetch", vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    asked.push(url.pathname + url.search);
    const body = url.pathname === "/api/instruments"
      ? [{ code: "72030", name: "トヨタ自動車", name_en: "TOYOTA MOTOR", market: "0111" }]
      : url.pathname === "/api/strategies"
      ? STRATEGY_POOLS
      : bars;
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("证券详情页", () => {
  it("标题是 4 位代码、名称和市场", async () => {
    render(<SecurityDetail code="72030" strategy="trend_pullback_v1" />);

    expect(await screen.findByRole("heading", { level: 1, name: /7203.*トヨタ自動車.*Prime/ })).toBeInTheDocument();
  });

  it("连续几天都是入场信号时，只在第一天标出来", async () => {
    stubBackend({ ...BARS, entries: ["2026-09-17", "2026-09-18"] });
    render(<SecurityDetail code="72030" strategy="trend_pullback_v1" />);

    await screen.findByTestId("chart");
    expect(drawn.data?.entries).toEqual(["2026-09-17"]);
  });

  it("TOPIX 均线下，1306 的图在单独一栏画 TOPIX 收盘和均线", async () => {
    stubBackend({
      ...BARS,
      code: "13060",
      plots: [{ indicator: "topix_close", pane: "separate" }, { indicator: "topix_ma", pane: "separate" }],
      lines: {
        topix_close: [{ date: "2026-09-17", value: 3120.5 }, { date: "2026-09-18", value: 3150.25 }],
        topix_ma: [{ date: "2026-09-17", value: 2950.1 }, { date: "2026-09-18", value: 2952.3 }],
      } as unknown as typeof BARS.lines,
    });
    render(<SecurityDetail code="13060" strategy="topix_ma_v1" />);

    await screen.findByTestId("chart");
    expect(asked[0]).toBe("/api/instruments/13060/bars?strategy=topix_ma_v1");
    expect(drawn.data?.lines).toEqual([
      { name: "topix_close", pane: "separate", points: [{ time: "2026-09-17", value: 3120.5 }, { time: "2026-09-18", value: 3150.25 }] },
      { name: "topix_ma", pane: "separate", points: [{ time: "2026-09-17", value: 2950.1 }, { time: "2026-09-18", value: 2952.3 }] },
    ]);
    expect(screen.getByRole("link", { name: "TOPIX 均线" })).toHaveAttribute("aria-current", "page");
  });

  it("TOPIX 动量下，1306 的图在单独一栏画过去收益，入场点在每月第一个开市日", async () => {
    const days = ["2026-08-31", "2026-09-01", "2026-09-02"];
    stubBackend({
      ...BARS,
      code: "13060",
      bars: days.map((date) => ({ date, open: 3000, high: 3010, low: 2990, close: 3005, volume: 90000 })),
      plots: [{ indicator: "past_return", pane: "separate" }],
      lines: {
        past_return: days.map((date, n) => ({ date, value: [0.12, 0.11, 0.13][n] })),
      } as unknown as typeof BARS.lines,
      entries: ["2026-09-01"],
    });
    render(<SecurityDetail code="13060" strategy="topix_momentum_v1" />);

    await screen.findByTestId("chart");
    expect(asked[0]).toBe("/api/instruments/13060/bars?strategy=topix_momentum_v1");
    expect(drawn.data?.lines).toEqual([{
      name: "past_return", pane: "separate",
      points: days.map((time, n) => ({ time, value: [0.12, 0.11, 0.13][n] })),
    }]);
    expect(drawn.data?.entries).toEqual(["2026-09-01"]);
    expect(screen.getByRole("link", { name: "TOPIX 动量" })).toHaveAttribute("aria-current", "page");
  });

  it("TOPIX 均线下的 7203 照样画线，但不标入场点，并说明这个策略只交易 1306", async () => {
    stubBackend({
      ...BARS,
      plots: [{ indicator: "topix_close", pane: "separate" }, { indicator: "topix_ma", pane: "separate" }],
      lines: {
        topix_close: [{ date: "2026-09-17", value: 3120.5 }, { date: "2026-09-18", value: 3150.25 }],
        topix_ma: [{ date: "2026-09-17", value: 2950.1 }, { date: "2026-09-18", value: 2952.3 }],
      } as unknown as typeof BARS.lines,
      entries: ["2026-09-18"], // what the strategy would say holding nothing, were 7203 in its universe
    });
    render(<SecurityDetail code="72030" strategy="topix_ma_v1" />);

    await screen.findByTestId("chart");
    expect(drawn.data?.lines.map((line) => line.name)).toEqual(["topix_close", "topix_ma"]);
    expect(drawn.data?.entries).toEqual([]);
    expect(screen.getByText("TOPIX 均线 只交易 1306，这里不标入场信号")).toBeInTheDocument();
    expect(screen.queryByText(/入场信号（连续几天只标第一天）/)).not.toBeInTheDocument();
  });

  it("个股策略下的 7203 照常标入场点", async () => {
    render(<SecurityDetail code="72030" strategy="trend_pullback_v1" />);

    await screen.findByTestId("chart");
    expect(drawn.data?.entries).toEqual(["2026-09-18"]);
    expect(screen.getByText(/入场信号（连续几天只标第一天）/)).toBeInTheDocument();
    expect(screen.queryByText(/只交易/)).not.toBeInTheDocument();
  });

  it("把研究价格 K 线、成交量、策略的指标和历史入场点交给图表", async () => {
    render(<SecurityDetail code="72030" strategy="trend_pullback_v1" />);

    await screen.findByTestId("chart");
    expect(asked[0]).toBe("/api/instruments/72030/bars?strategy=trend_pullback_v1");
    expect(drawn.data).toEqual({
      candles: [
        { time: "2026-09-17", open: 100, high: 102, low: 99, close: 101 },
        { time: "2026-09-18", open: 101, high: 104, low: 100, close: 103 },
      ],
      volume: [
        { time: "2026-09-17", value: 5000 },
        { time: "2026-09-18", value: 7000 },
      ],
      lines: [
        { name: "ema_fast", pane: "price", points: [{ time: "2026-09-17", value: 100.5 }, { time: "2026-09-18", value: 101.2 }] },
        { name: "rsi", pane: "separate", points: [{ time: "2026-09-17", value: 28 }, { time: "2026-09-18", value: 34 }] },
      ],
      entries: ["2026-09-18"],
    });
  });
});
