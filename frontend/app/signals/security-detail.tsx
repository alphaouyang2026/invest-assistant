"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { STRATEGIES, type StrategyName } from "@/lib/labels";

import { type ChartData, PriceChart } from "./price-chart";

type SecurityBars = Schemas["SecurityBarsOut"];

/** Halted days and days before a line has a value are left undrawn. */
function chartData(body: SecurityBars): ChartData {
  const traded = body.bars.filter((bar) => bar.close !== null);
  return {
    candles: traded.map((bar) => ({
      time: bar.date, open: bar.open as number, high: bar.high as number, low: bar.low as number, close: bar.close as number,
    })),
    volume: traded.filter((bar) => bar.volume !== null).map((bar) => ({ time: bar.date, value: bar.volume as number })),
    lines: body.plots.map((plot) => ({
      name: plot.indicator,
      pane: plot.pane,
      points: (body.lines[plot.indicator] ?? [])
        .filter((point) => point.value !== null)
        .map((point) => ({ time: point.date, value: point.value as number })),
    })),
    entries: body.entries,
  };
}

export function SecurityDetail({ code, strategy }: { code: string; strategy: StrategyName }) {
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void (async () => {
      const { data: body, error: failed } = await api.GET("/api/instruments/{code}/bars", {
        params: { path: { code }, query: { strategy } },
      });
      if (!current) return;
      if (failed) {
        setError(typeof failed.detail === "string" ? failed.detail : "读取行情失败");
        return;
      }
      setError(null);
      setData(chartData(body));
    })();
    return () => {
      current = false;
    };
  }, [code, strategy]);

  const label = STRATEGIES.find((s) => s.name === strategy)?.label ?? strategy;
  return (
    <section>
      <p>
        <Link href="/signals">← 信号</Link>
      </p>
      <h1>
        {code}
        <small> {label}</small>
      </h1>
      {error && <p role="alert">{error}</p>}
      {data && <PriceChart data={data} />}
    </section>
  );
}
