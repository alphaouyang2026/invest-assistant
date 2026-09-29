"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { signedPercent, tone, yen } from "@/lib/format";
import { BATCH_STATES, Configuration, message, poll, STATES, unfinished, useSubmit } from "./research-shared";

const readBatch = (id: string, signal: AbortSignal) =>
  api.GET("/api/research/batches/{batch_id}", { params: { path: { batch_id: id } }, signal });
// The client's response type widens the date-pair tuples to arrays, so types come from the call itself.
type Batch = NonNullable<Awaited<ReturnType<typeof readBatch>>["data"]>;
type Segment = Batch["segments"][number];

const ratio = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(1)}%`);

/** One research batch: every segment side by side, then their distribution. Polls while anything is unfinished. */
export function BatchView({ id, onStatus, onDiscovery, onRediscover }: {
  id: string; onStatus?: () => void; onDiscovery?: (id: string) => void; onRediscover?: () => void;
}) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const { busy, send } = useSubmit(setError);
  const callbacks = useRef({ onStatus, onDiscovery });
  callbacks.current = { onStatus, onDiscovery };
  const lastStatus = useRef<string | null>(null);

  useEffect(() => poll(signal => readBatch(id, signal), data => {
    setBatch(data);
    if (lastStatus.current === null && data.discovery_id) callbacks.current.onDiscovery?.(data.discovery_id);
    if (lastStatus.current !== null && lastStatus.current !== data.status) callbacks.current.onStatus?.();
    lastStatus.current = data.status;
    return unfinished(data.status) || data.segments.some(s => unfinished(s.status));
  }, e => setError(message(e))), [id, version]);

  function retry(position: number) {
    setError(null); setStale(null);
    return send({ batch: id, position }, async key => {
      const response = await api.POST("/api/research/batches/{batch_id}/segments/{position}/retry", {
        params: { path: { batch_id: id, position } }, body: { request_key: key },
      });
      if (response.response.status === 412 && response.error) return setStale(message(response.error));
      if (response.error) throw response.error;
      setVersion(v => v + 1);
    });
  }

  if (!batch) return error ? <p role="alert">{error}</p> : <p role="status">正在读取研究批次…</p>;
  const params = batch.config.strategy_params;
  return <section className="stack" aria-label="研究批次结果">
    <section className="card">
      <div className="card-h"><h2>批次 {batch.id.slice(0, 8)} · {BATCH_STATES[batch.status]}</h2>
        <span>固定阈值 {String(params.entry_above)} / {String(params.exit_below)} · {batch.config.strategy}</span></div>
      <div className="card-body"><Configuration config={batch.config} /></div>
      {error && <div role="alert">{error} <button type="button" className="btn" onClick={() => { setError(null); setVersion(v => v + 1); }}>重新读取</button></div>}
      {stale && <div role="alert">行情已变化：{stale}
        {onRediscover && <button type="button" className="btn" onClick={onRediscover}>重新发现</button>}</div>}
      <div className="scroll"><table aria-label="逐段结果"><thead><tr>
        <th>段</th><th>区间</th><th>状态</th><th>进度（开市日）</th><th>收益</th><th>同期 TOPIX</th><th>收益差</th>
        <th>最大回撤</th><th>成交数</th><th>手续费</th><th>期末</th><th>详情</th></tr></thead>
        <tbody>{batch.segments.map(s => <SegmentRow key={s.position} segment={s} busy={busy} onRetry={() => void retry(s.position)} />)}</tbody>
      </table></div>
    </section>
    <Distribution distribution={batch.distribution} />
  </section>;
}

function SegmentRow({ segment: s, busy, onRetry }: { segment: Segment; busy: boolean; onRetry: () => void }) {
  const m = s.metrics;
  const done = s.progress.sessions_done;
  const total = s.progress.sessions_total;
  return <tr>
    <td>第 {s.position} 段{s.interval_id !== null && <span className="meta">区间 #{s.interval_id}</span>}</td>
    <td>{s.start_date} — {s.end_date}</td>
    <td>{STATES[s.status]}{s.attempts.length > 1 && `（第 ${s.attempts.length} 次尝试）`}
      {s.status === "failed" && <><p>{s.error}</p>
        <button type="button" className="btn" disabled={busy} onClick={onRetry}>重试此段</button></>}</td>
    <td>{String(done ?? 0)} / {String(total ?? "—")}</td>
    <td className={tone(m?.total_return)}>{signedPercent(m?.total_return)}</td>
    <td className={tone(m?.topix_return)}>{signedPercent(m?.topix_return)}</td>
    <td className={tone(m?.excess_return)}>{signedPercent(m?.excess_return)}</td>
    <td>{m ? signedPercent(-m.max_drawdown) : "—"}</td>
    <td>{m ? m.trades : "—"}</td>
    <td>{m ? `¥${yen(m.fees)}` : "—"}</td>
    <td>{m ? `持仓 ${m.holdings} 只 · 挂单 ${m.pending} 笔` : "—"}</td>
    <td><Link href={`/accounts/research?run=${s.run_id}`}>查看详情</Link></td>
  </tr>;
}

function Distribution({ distribution: d }: { distribution: Batch["distribution"] }) {
  const n = d.denominator;
  return <section className="card" aria-label="结果分布">
    <div className="card-h"><h2>结果分布</h2><span>按已完成 {n} 段等权</span></div>
    <div className="card-body">
      <p>已选 {d.selected} 段：已完成 {d.completed} 段，失败 {d.failed} 段，未完成 {d.unfinished} 段。
        下面的统计按已完成 {n} 段等权，分母 = {n}；失败和未完成的段不计入，也不当作 0 收益。</p>
    </div>
    {n === 0 ? <p className="empty">还没有已完成的段，暂无分布。</p> : <>
      <dl className="kpis">{[
        ["收益中位数", signedPercent(d.median_return)], ["收益差中位数（相对 TOPIX）", signedPercent(d.median_excess)],
        ["盈利段比例", `${ratio(d.profitable_ratio)}（${d.profitable} / ${n}）`],
        ["跑赢 TOPIX 比例", `${ratio(d.beat_ratio)}（${d.beat_topix} / ${n}）`],
      ].map(([label, value]) => <div className="kpi" key={label}><dt>{label}</dt><dd className="v">{value}</dd></div>)}</dl>
      <div className="card-body">
        <p>盈利 {d.profitable} 段 · 持平 {d.flat} 段 · 亏损 {d.losing} 段（收益严格大于 0 才算盈利）</p>
        <p>跑赢 TOPIX {d.beat_topix} 段 · 与 TOPIX 持平 {d.tied_topix} 段 · 落后 {d.behind_topix} 段（收益差严格大于 0 才算跑赢）</p>
        {d.worst && <p>收益最差：第 {d.worst.position} 段 {d.worst.start_date} — {d.worst.end_date}，{signedPercent(d.worst.total_return)}</p>}
        {d.worst_excess && <p>收益差最差：第 {d.worst_excess.position} 段 {d.worst_excess.start_date} — {d.worst_excess.end_date}，{signedPercent(d.worst_excess.excess_return)}</p>}
        <p>日期覆盖：已完成的段共 {d.coverage.sessions} 个开市日{d.coverage.first && `，${d.coverage.first} — ${d.coverage.last}`}；
          {d.coverage.ranges.map(([from, to]) => `${from} — ${to}`).join("、")}</p>
        <p>各段收益（从低到高，每段独立资金，不连乘）：{[...d.returns].sort((a, b) => a - b).map((r, i) =>
          <span key={i} className={tone(r)}>{i > 0 && "、"}{signedPercent(r)}</span>)}</p>
        <p>各段收益差（从低到高）：{[...d.excess_returns].sort((a, b) => a - b).map((r, i) =>
          <span key={i} className={tone(r)}>{i > 0 && "、"}{signedPercent(r)}</span>)}</p>
      </div>
    </>}
  </section>;
}
