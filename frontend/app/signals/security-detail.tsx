"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { displayCode } from "@/lib/format";
import { STRATEGIES, type StrategyName, market } from "@/lib/labels";
import { usePalette } from "@/lib/palette";

import { type ChartData, PriceChart } from "./price-chart";

type SecurityBars = Schemas["SecurityBarsOut"];
type Instrument = Schemas["InstrumentOut"];

/** A signal that holds for several sessions in a row is one entry: only
 * the first session of each run is kept. */
function firstOfRuns(entries: string[], sessions: string[]): string[] {
  const entered = new Set(entries);
  return sessions.filter((day, n) => entered.has(day) && (n === 0 || !entered.has(sessions[n - 1])));
}

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
    entries: firstOfRuns(body.entries, body.bars.map((bar) => bar.date)),
  };
}

export function SecurityDetail({ code, strategy }: { code: string; strategy: StrategyName }) {
  const [data, setData] = useState<ChartData | null>(null);
  const [instrument, setInstrument] = useState<Instrument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const palette = usePalette();

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

  useEffect(() => {
    void (async () => {
      const { data: found } = await api.GET("/api/instruments", { params: { query: { q: code } } });
      setInstrument((Array.isArray(found) ? found : []).find((i) => i.code === code) ?? null);
    })();
  }, [code]);

  return (
    <section className="page">
      <div className="crumb">
        <Link href="/signals">信号</Link> / {displayCode(code)}
      </div>
      <div className="head">
        <div>
          <h1>
            <span className="mono" style={{ fontSize: "inherit" }}>{displayCode(code)}</span>
            {instrument && <span>{instrument.name}</span>}
            {instrument && <span className="badge">{market(instrument.market)}</span>}
          </h1>
          {instrument && (
            <div className="meta">
              <span>{instrument.name_en}</span>
            </div>
          )}
        </div>
        <nav className="seg" aria-label="策略">
          {STRATEGIES.map((s) => (
            <Link key={s.name} href={`/signals/${code}?strategy=${s.name}`}
                  aria-current={s.name === strategy ? "page" : undefined}>
              {s.label}
            </Link>
          ))}
        </nav>
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <section className="card" aria-labelledby="chart">
          <div className="card-h">
            <h2 id="chart">K 线与指标</h2>
            <div className="legend">
              {palette &&
                data.lines.map((line, n) => (
                  <span key={line.name}>
                    <span className="swatch" style={{ background: palette.lines[n % palette.lines.length] }} />
                    {line.name}
                  </span>
                ))}
              <span>
                <span className="up">▲</span> 入场信号（连续几天只标第一天）
              </span>
            </div>
          </div>
          <div className="chart">
            <PriceChart data={data} />
          </div>
          <div className="foot">
            <span>K 线是研究价格：按之后的拆股、合股等调整，可以跨期比较；不含现金分红</span>
          </div>
        </section>
      )}
    </section>
  );
}
