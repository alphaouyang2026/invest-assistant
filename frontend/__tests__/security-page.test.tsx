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

let asked: string[];

beforeEach(() => {
  asked = [];
  drawn.data = null;
  vi.stubGlobal("fetch", vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    asked.push(url.pathname + url.search);
    return new Response(JSON.stringify(BARS), { headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("证券详情页", () => {
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
