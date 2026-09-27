"use client";

import { AreaSeries, LineSeries, LineStyle, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { chartOptions } from "@/lib/chart";
import { faded, usePalette } from "@/lib/palette";

export type NavPoint = { date: string; nav: number; nav_curve: number; topix_curve: number; drawdown: number };

/** NAV against TOPIX, both from 1 on the first session; the drawdown below. */
export function NavChart({ points }: { points: NavPoint[] }) {
  const container = useRef<HTMLDivElement>(null);
  const palette = usePalette();

  useEffect(() => {
    if (!container.current || !palette) return;
    const chart = createChart(container.current, chartOptions(palette, 420));
    const nav = chart.addSeries(LineSeries, { color: palette.up, lineWidth: 2, title: "账户" }, 0);
    nav.setData(points.map((p) => ({ time: p.date, value: p.nav_curve })));
    nav.createPriceLine({ price: 1, color: palette.muted, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    chart
      .addSeries(LineSeries, { color: palette.topix, lineWidth: 1, title: "TOPIX" }, 0)
      .setData(points.map((p) => ({ time: p.date, value: p.topix_curve })));
    chart
      .addSeries(
        AreaSeries,
        {
          lineColor: palette.down, lineWidth: 1, topColor: faded(palette.down, 0.05), bottomColor: faded(palette.down, 0.3),
          title: "回撤", priceFormat: { type: "percent" },
        },
        1,
      )
      .setData(points.map((p) => ({ time: p.date, value: -p.drawdown * 100 })));
    chart.panes()[1]?.setHeight(110);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points, palette]);

  return <div ref={container} className="nav-chart" />;
}
