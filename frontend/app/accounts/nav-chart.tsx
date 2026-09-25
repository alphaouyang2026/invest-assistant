"use client";

import { AreaSeries, LineSeries, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

export type NavPoint = { date: string; nav: number; nav_curve: number; topix_curve: number; drawdown: number };

/** NAV against TOPIX, both from 1 on the first session; the drawdown below. */
export function NavChart({ points }: { points: NavPoint[] }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, { autoSize: true, height: 480 });
    chart
      .addSeries(LineSeries, { color: "#2962ff", lineWidth: 2, title: "账户" }, 0)
      .setData(points.map((p) => ({ time: p.date, value: p.nav_curve })));
    chart
      .addSeries(LineSeries, { color: "#9e9e9e", lineWidth: 1, title: "TOPIX" }, 0)
      .setData(points.map((p) => ({ time: p.date, value: p.topix_curve })));
    chart
      .addSeries(
        AreaSeries,
        { lineColor: "#c62828", topColor: "rgba(198,40,40,0.1)", bottomColor: "rgba(198,40,40,0.4)", title: "回撤" },
        1,
      )
      .setData(points.map((p) => ({ time: p.date, value: -p.drawdown })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);

  return <div ref={container} className="nav-chart" />;
}
