"use client";

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

/** What the chart draws; dates are `YYYY-MM-DD`. */
export type ChartData = {
  candles: { time: string; open: number; high: number; low: number; close: number }[];
  volume: { time: string; value: number }[];
  lines: { name: string; pane: string; points: { time: string; value: number }[] }[];
  entries: string[];
};

const PRICE_PANE = 0;
const VOLUME_PANE = 1;
const SEPARATE_PANE = 2; // every line not drawn over the price shares one pane
const LINE_COLORS = ["#2962ff", "#ff6d00", "#00897b", "#8e24aa", "#c62828", "#546e7a"];

export function PriceChart({ data }: { data: ChartData }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, { autoSize: true, height: 560 });
    const candles = chart.addSeries(CandlestickSeries, {}, PRICE_PANE);
    candles.setData(data.candles);
    chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" } }, VOLUME_PANE).setData(data.volume);
    data.lines.forEach((line, n) => {
      const pane = line.pane === "price" ? PRICE_PANE : SEPARATE_PANE;
      chart
        .addSeries(LineSeries, { color: LINE_COLORS[n % LINE_COLORS.length], lineWidth: 1, title: line.name }, pane)
        .setData(line.points);
    });
    createSeriesMarkers(
      candles,
      data.entries.map((time) => ({ time, position: "belowBar" as const, shape: "arrowUp" as const, color: "#2962ff", text: "入场" })),
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return <div ref={container} className="price-chart" />;
}
