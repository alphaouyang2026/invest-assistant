"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { signedPercent, yen, signedYen } from "@/lib/format";
import { ORDER_KINDS, ORDER_STATUSES, outcome, reason } from "@/lib/labels";
import { NavChart } from "../nav-chart";
import { Pager } from "../../pager";

type Run = Schemas["ResearchDetail"];
type Config = Schemas["ResearchConfig"];
const STATES = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败" };
const message = (error: unknown) => {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") return error.detail;
  return "请求失败，请检查网络和后端服务后重试";
};

export function ResearchWorkspace({ sourceId = "", initialRun = "" }: { sourceId?: string; initialRun?: string }) {
  const [sources, setSources] = useState<Schemas["ResearchSource"][]>([]);
  const [loaded, setLoaded] = useState(false);
  const [source, setSource] = useState(sourceId);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [entry, setEntry] = useState("0.5");
  const [exit, setExit] = useState("-0.1");
  const [selected, setSelected] = useState(initialRun);
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<Schemas["ResearchHistory"] | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  // Reuse the key after a lost HTTP response; changing inputs creates a new attempt.
  const request = useRef({ input: "", key: "" });
  const config = sources.find(s => String(s.id) === source)?.config;

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await api.GET("/api/research/sources", { signal: controller.signal });
        if (!response.data) throw new Error("读取来源账户失败");
        setSources(response.data);
        setLoaded(true);
        setSource(current => current || String(response.data[0]?.id ?? ""));
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => { if (config) setStart(config.start_date); }, [config]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await api.GET("/api/research/runs", {
          params: { query: { page: historyPage, page_size: 10 } }, signal: controller.signal,
        });
        if (response.error) throw response.error;
        setHistory(response.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [historyPage, version, run?.status]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setRun(null);
    const poll = async () => {
      try {
        const response = await api.GET("/api/research/runs/{run_id}", {
          params: { path: { run_id: selected } }, signal: controller.signal,
        });
        if (response.error) throw response.error;
        if (controller.signal.aborted) return;
        setRun(response.data);
        if (["queued", "running"].includes(response.data.status)) timer = setTimeout(poll, 1500);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [selected, version]);

  function choose(id: string) {
    setSelected(id);
    const url = new URL(window.location.href);
    url.searchParams.set("run", id);
    if (source) url.searchParams.set("source", source);
    window.history.replaceState(null, "", url);
  }

  async function submit(retry = false) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true); setError(null);
    const body = { source_account_id: Number(source), start_date: start, end_date: end,
      entry_above: Number(entry), exit_below: Number(exit) };
    const input = JSON.stringify(retry ? { retry: selected } : body);
    if (request.current.input !== input) request.current = { input, key: crypto.randomUUID() };
    try {
      const response = retry
        ? await api.POST("/api/research/runs/{run_id}/retry", {
            params: { path: { run_id: selected } }, body: { request_key: request.current.key },
          })
        : await api.POST("/api/research/runs", { body: { ...body, request_key: request.current.key } });
      if (response.error) throw response.error;
      choose(response.data.id);
      setVersion(v => v + 1);
      request.current = { input: "", key: "" };
    } catch (e) { setError(message(e)); }
    finally { sending.current = false; setBusy(false); }
  }

  return <section className="page">
    <div className="crumb"><Link href="/accounts">账户</Link> / 指定区间回测</div>
    <h1>指定区间策略回测</h1>
    <p className="meta">独立空仓启动，不复制当前持仓、不修改来源账户。收盘信号最早次日开盘成交。</p>
    {error && <div role="alert">{error} <button className="btn" onClick={() => { setError(null); setVersion(v => v + 1); }}>重新读取结果</button></div>}
    {loaded && sources.length === 0 && <p>没有技术评级来源账户，请先<Link href="/accounts/new">新建账户</Link>。已有研究仍可查看。</p>}
    <form className="card" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className="card-h"><h2>区间与策略参数</h2><span>technical_rating_v1</span></div>
      <div className="form">
        <div className="field wide"><label htmlFor="research-source">来源账户</label>
          <select id="research-source" className="input" value={source} required onChange={e => setSource(e.target.value)}>
            <option value="">请选择</option>{sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></div>
        <div className="field"><label htmlFor="research-start">起始日</label>
          <input id="research-start" className="input" type="date" required value={start} onChange={e => setStart(e.target.value)} /></div>
        <div className="field"><label htmlFor="research-end">结束日</label>
          <input id="research-end" className="input" type="date" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></div>
        <div className="field"><label htmlFor="research-entry">入场阈值 entry_above</label>
          <input id="research-entry" className="input" type="number" min={-1} max={1} step="0.1" required value={entry} onChange={e => setEntry(e.target.value)} /></div>
        <div className="field"><label htmlFor="research-exit">退出阈值 exit_below</label>
          <input id="research-exit" className="input" type="number" min={-1} max={1} step="0.1" required value={exit} onChange={e => setExit(e.target.value)} /></div>
      </div>
      {config && <Configuration config={config} />}
      <div className="foot"><span>起止日须为有数据的开市日，并有足够预热历史。</span>
        <button className="btn primary" disabled={busy || !config}>{busy ? "提交中…" : "运行回测"}</button></div>
    </form>
    {selected && !run && <p role="status">正在读取研究结果…</p>}
    {run && <section className="stack" aria-label="研究结果">
      <div className="card-h"><h2>运行 {run.id.slice(0, 8)} · {STATES[run.status]}</h2>
        <span>{run.config.start_date} — {run.config.end_date}</span></div>
      <Configuration config={run.config} />
      <p>固定阈值：{String(run.config.strategy_params.entry_above)} / {String(run.config.strategy_params.exit_below)} · {run.config.strategy}</p>
      {["queued", "running"].includes(run.status) && <p role="status">{STATES[run.status]}：{String(run.progress.sessions_done ?? 0)} / {String(run.progress.sessions_total ?? "—")} 个交易日</p>}
      {run.error && <div role="alert">{run.error} <button className="btn" disabled={busy} onClick={() => void submit(true)}>重试（新运行）</button></div>}
      {run.result && <Result run={run} />}
      <details><summary>输入与版本记录</summary><pre>{JSON.stringify({ input: run.input_identity, code: run.code_version, retry_of: run.retry_of }, null, 2)}</pre></details>
    </section>}
    <section className="card"><div className="card-h"><h2>全部运行记录</h2></div>
      <div className="scroll"><table aria-label="研究运行历史"><thead><tr><th>运行</th><th>区间</th><th>阈值</th><th>状态</th></tr></thead>
        <tbody>{history?.runs.map(r => <tr key={r.id}><td><button className="btn" onClick={() => choose(r.id)}>{r.id.slice(0, 8)}</button></td>
          <td>{r.config.start_date} — {r.config.end_date}</td><td>{String(r.config.strategy_params.entry_above)} / {String(r.config.strategy_params.exit_below)}</td><td>{STATES[r.status]}</td></tr>)}</tbody></table></div>
      {history?.total === 0 && <p className="empty">尚无研究运行</p>}
      <Pager page={historyPage} pages={Math.max(1, Math.ceil((history?.total ?? 0) / 10))} onPage={setHistoryPage} />
    </section>
    <p className="meta">探索性历史结果，不代表未来有效；不含分红、不含税。期末按市值估值，未强制清仓，挂单不在区间外执行。</p>
  </section>;
}

function Configuration({ config }: { config: Config }) {
  const rules = config.portfolio_rules;
  return <p className="meta">来源：{config.name} · 初始资金 ¥{yen(Number(rules.initial_cash))} ·
    最多 {String(rules.max_positions)} 只 · 单股上限 {Number(rules.max_weight) * 100}% ·
    现金底线 {Number(rules.cash_floor) * 100}% · 手续费率 {Number(config.costs.commission_rate) * 100}% ·
    最低手续费 ¥{config.costs.commission_min} · 每边滑点 {Number(config.costs.slippage) * 100}%</p>;
}

function Result({ run }: { run: Run }) {
  const r = run.result!;
  return <>
    <dl className="kpis">{[
      ["净收益（含期末浮盈亏）", signedPercent(r.total_return)], ["同期 TOPIX", signedPercent(r.topix_return)],
      ["收益差", signedPercent(r.excess_return)], ["最大回撤", signedPercent(-r.max_drawdown)],
      ["成交数", String(r.trades)], ["实际手续费", `¥${yen(r.fees)}`],
      ["已实现盈亏", signedYen(r.realised_pnl)], ["未实现盈亏", signedYen(r.unrealised_pnl)],
    ].map(([label, value]) => <div className="kpi" key={label}><dt>{label}</dt><dd className="v">{value}</dd></div>)}</dl>
    {r.trades === 0 && <p>区间内没有成交；可能是区间太短、没有入场信号或受账户／成交限制，并不意味着策略无效。</p>}
    {r.warnings.map(w => <p key={w} role="alert">{w}</p>)}
    <section className="card"><div className="card-h"><h2>净值、TOPIX 与回撤</h2><span>起始日 = 1</span></div><NavChart points={r.nav} /></section>
    <section className="card"><div className="card-h"><h2>期末持仓</h2><span>现金 ¥{yen(r.cash)}</span></div>
      {r.holdings.length === 0 ? <p className="empty">期末空仓</p> : <div className="scroll"><table aria-label="期末持仓">
        <thead><tr><th>证券</th><th>股数</th><th>成本（含费用）</th><th>市值</th><th>浮盈亏</th></tr></thead>
        <tbody>{r.holdings.map(h => <tr key={h.code}><td>{h.code}</td><td>{h.quantity}</td><td>{yen(h.cost)}</td><td>{yen(h.value)}</td><td>{signedYen(h.value - h.cost)}</td></tr>)}</tbody>
      </table></div>}
      <p>期末未执行订单：{r.pending.length} 笔（详见下方账本中的待执行记录，不会继续推进）</p>
    </section>
    <ResearchOrders key={run.id} id={run.id} />
  </>;
}

function ResearchOrders({ id }: { id: string }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Schemas["ResearchOrders"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(null);
    void (async () => {
      try {
        const r = await api.GET("/api/research/runs/{run_id}/orders", {
          params: { path: { run_id: id }, query: { page, page_size: 50 } }, signal: controller.signal,
        });
        if (r.error) throw r.error;
        setData(r.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [id, page]);
  return <section className="card"><div className="card-h"><h2>交易记录与期末挂单</h2></div>
    {error && <p role="alert">{error}</p>}
    {data?.total === 0 && <p className="empty">没有订单或账户事件</p>}
    <div className="scroll"><table aria-label="研究交易记录"><thead><tr><th>信号日 → 执行日</th><th>证券</th><th>方向</th><th>状态</th><th>计划／成交股数</th><th>成交价</th><th>费用</th><th>理由</th></tr></thead>
      <tbody>{data?.orders.map(o => <tr key={o.id}><td>{o.signal_date} → {o.execution_date}</td><td>{o.code}</td>
        <td>{ORDER_KINDS[o.kind] ?? o.kind}</td><td>{ORDER_STATUSES[o.status]?.label ?? o.status}</td>
        <td>{o.planned_quantity} / {o.filled_quantity}</td><td>{o.fill_price ?? "—"}</td><td>{yen(o.fees)}</td>
        <td>{Array.isArray(o.reason.reason_codes) ? o.reason.reason_codes.map(c => reason(String(c))).join("、") : ""} {o.outcome_reason && outcome(o.outcome_reason)}</td></tr>)}</tbody>
    </table></div>
    <Pager page={page} pages={Math.max(1, Math.ceil((data?.total ?? 0) / 50))} onPage={setPage} />
  </section>;
}
