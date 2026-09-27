"use client";

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { chartOptions } from "@/lib/chart";
import { faded, usePalette } from "@/lib/palette";

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

export function PriceChart({ data }: { data: ChartData }) {
  const container = useRef<HTMLDivElement>(null);
  const palette = usePalette();

  useEffect(() => {
    if (!container.current || !palette) return;
    const chart = createChart(container.current, chartOptions(palette, 600));
    const candles = chart.addSeries(
      CandlestickSeries,
      {
        upColor: palette.up, downColor: palette.down, borderVisible: false,
        wickUpColor: palette.up, wickDownColor: palette.down,
      },
      PRICE_PANE,
    );
    candles.setData(data.candles);
    chart
      .addSeries(HistogramSeries, { priceFormat: { type: "volume" }, color: faded(palette.topix, 0.6) }, VOLUME_PANE)
      .setData(data.volume);
    data.lines.forEach((line, n) => {
      const pane = line.pane === "price" ? PRICE_PANE : SEPARATE_PANE;
      chart
        .addSeries(
          LineSeries,
          { color: palette.lines[n % palette.lines.length], lineWidth: 1, title: line.name, priceLineVisible: false },
          pane,
        )
        .setData(line.points);
    });
    createSeriesMarkers(
      candles,
      // no text: the legend says what the arrows are, and words crowd where entries are close together
      data.entries.map((time) => ({ time, position: "belowBar" as const, shape: "arrowUp" as const, color: palette.up })),
    );
    const panes = chart.panes();
    panes[VOLUME_PANE]?.setHeight(80);
    panes[SEPARATE_PANE]?.setHeight(120);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, palette]);

  return <div ref={container} className="price-chart" />;
}
