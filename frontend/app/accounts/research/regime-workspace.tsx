"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { signedPercent, tone } from "@/lib/format";
import { Pager } from "../../pager";
import { BatchView } from "./batch-view";
import { BATCH_STATES, Configuration, message, STATES } from "./research-shared";

type Definition = Schemas["RegimeDefinition"];
const readDiscovery = (id: string, signal: AbortSignal) =>
  api.GET("/api/research/discoveries/{discovery_id}", { params: { path: { discovery_id: id } }, signal });
// The client's response type widens the date-pair tuples to arrays, so types come from the call itself.
type Discovery = NonNullable<Awaited<ReturnType<typeof readDiscovery>>["data"]>;
type Interval = Discovery["intervals"][number];
type Parameters = Schemas["DiscoveryParameters"];

const TRENDS = { up: "上涨", down: "下跌", neutral: "中性（震荡候选）" } as const;
const VOLS = { high: "高波动", low: "低波动" } as const;
const TREND_COUNTS = { up: "上涨", down: "下跌", neutral: "中性", unknown: "未知" } as const;
const VOL_COUNTS = { high: "高波动", low: "低波动", unknown: "未知" } as const;
/** technical_rating_v1 needs this many sessions before a range starts unless the source says otherwise. */
const DEFAULT_WARMUP = 260;

const span = ([from, to]: string[]) => (from === to ? from : `${from} — ${to}`);
const rvPercent = (value: number | null) => (value === null ? "—" : `${(value * 100).toFixed(1)}%`);

function setQuery(values: Record<string, string>) {
  const url = new URL(window.location.href);
  url.searchParams.set("mode", "regime");
  for (const [name, value] of Object.entries(values)) {
    if (value) url.searchParams.set(name, value); else url.searchParams.delete(name);
  }
  window.history.replaceState(null, "", url);
}

export function RegimeWorkspace({ sources, sourceId = "", initialDiscovery = "", initialBatch = "" }: {
  sources: Schemas["ResearchSource"][]; sourceId?: string; initialDiscovery?: string; initialBatch?: string;
}) {
  const [definition, setDefinition] = useState<Definition | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [trend, setTrend] = useState<Parameters["trend"]>("up");
  const [vol, setVol] = useState<"" | "high" | "low">("");
  const [discoveryId, setDiscoveryId] = useState(initialDiscovery);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [discoveryVersion, setDiscoveryVersion] = useState(0);
  const [checked, setChecked] = useState<number[]>([]);
  const [source, setSource] = useState(sourceId);
  const [entry, setEntry] = useState("0.5");
  const [exit, setExit] = useState("-0.1");
  const [batchId, setBatchId] = useState(initialBatch);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const sending = useRef(false);
  // Reuse the key after a lost HTTP response; changing inputs creates a new attempt.
  const request = useRef({ input: "", key: "" });
  const chosen = sources.find(s => String(s.id) === source);
  const warmup = Number(chosen?.config.strategy_params.warmup_sessions ?? DEFAULT_WARMUP);

  useEffect(() => { if (!source && sourceId) setSource(sourceId); }, [source, sourceId]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await api.GET("/api/research/regimes/definition", { signal: controller.signal });
        if (!response.data) throw new Error("读取分类定义失败");
        setDefinition(response.data);
        setFrom(current => current || (response.data.topix_from ?? ""));
        setTo(current => current || (response.data.topix_through ?? ""));
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!discoveryId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setDiscovery(current => (current?.id === discoveryId ? current : null));
    const poll = async () => {
      try {
        const response = await readDiscovery(discoveryId, controller.signal);
        if (response.error) throw response.error;
        if (controller.signal.aborted) return;
        setDiscovery(response.data);
        if (["queued", "running"].includes(response.data.status)) timer = setTimeout(poll, 1500);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [discoveryId, discoveryVersion]);

  // A restored discovery puts its own search back into the form.
  const shownParameters = discovery?.parameters;
  useEffect(() => {
    if (!shownParameters) return;
    setFrom(shownParameters.search_from); setTo(shownParameters.search_to);
    setTrend(shownParameters.trend); setVol(shownParameters.volatility ?? "");
  }, [shownParameters?.search_from, shownParameters?.search_to, shownParameters?.trend, shownParameters?.volatility]); // eslint-disable-line react-hooks/exhaustive-deps

  function openDiscovery(id: string) {
    setDiscoveryId(id); setChecked([]); setBatchId(""); setStale(null);
    setQuery({ discovery: id, batch: "" });
  }

  function openBatch(id: string) {
    setBatchId(id);
    setQuery({ discovery: discoveryId, batch: id });
  }

  async function send<T>(input: unknown, call: (key: string) => Promise<T>) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true); setError(null); setStale(null);
    const text = JSON.stringify(input);
    if (request.current.input !== text) request.current = { input: text, key: crypto.randomUUID() };
    try {
      await call(request.current.key);
      request.current = { input: "", key: "" };
    } catch (e) { setError(message(e)); }
    finally { sending.current = false; setBusy(false); }
  }

  const discover = (parameters: Parameters) => send({ discover: parameters }, async key => {
    const response = await api.POST("/api/research/discoveries", { body: { ...parameters, request_key: key } });
    if (response.error) throw response.error;
    openDiscovery(response.data.id);
  });

  const runBatch = () => {
    const body = { discovery_id: discoveryId, interval_ids: [...checked].sort((a, b) => a - b),
      source_account_id: Number(source), entry_above: Number(entry), exit_below: Number(exit) };
    return send({ batch: body }, async key => {
      const response = await api.POST("/api/research/batches", { body: { ...body, request_key: key } });
      if (response.response.status === 412 && response.error) {
        setStale(message(response.error));
        return;
      }
      if (response.error) throw response.error;
      openBatch(response.data.id);
      setDiscoveryVersion(v => v + 1);
    });
  };

  const intervals = discovery?.intervals ?? [];
  const cap = discovery?.max_batch_runs ?? 0;
  const over = checked.length > cap;
  const toggle = (id: number) => setChecked(c => (c.includes(id) ? c.filter(x => x !== id) : [...c, id]));

  return <>
    {error && <div role="alert">{error} <button className="btn" onClick={() => { setError(null); setDiscoveryVersion(v => v + 1); }}>重新读取</button></div>}
    <form className="card" onSubmit={e => {
      e.preventDefault();
      void discover({ search_from: from, search_to: to, trend, volatility: vol || null });
    }}>
      <div className="card-h"><h2>按 TOPIX 市场形势查找区间</h2><span>{definition?.version ?? "读取分类定义…"}</span></div>
      <div className="form">
        <div className="field"><label htmlFor="regime-from">搜索起始日</label>
          <input id="regime-from" className="input" type="date" required min={definition?.topix_from ?? undefined}
            max={to || undefined} value={from} onChange={e => setFrom(e.target.value)} /></div>
        <div className="field"><label htmlFor="regime-to">搜索结束日</label>
          <input id="regime-to" className="input" type="date" required min={from || undefined}
            max={definition?.topix_through ?? undefined} value={to} onChange={e => setTo(e.target.value)} /></div>
        <div className="field"><label htmlFor="regime-trend">TOPIX 趋势</label>
          <select id="regime-trend" className="input" value={trend} onChange={e => setTrend(e.target.value as Parameters["trend"])}>
            {Object.entries(TRENDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></div>
        <div className="field"><label htmlFor="regime-vol">波动水平</label>
          <select id="regime-vol" className="input" value={vol} onChange={e => setVol(e.target.value as "" | "high" | "low")}>
            <option value="">不限</option>
            {Object.entries(VOLS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></div>
      </div>
      {definition && <DefinitionText definition={definition} />}
      <div className="foot"><span>TOPIX 行情：{definition?.topix_from ?? "—"} — {definition?.topix_through ?? "—"}。只看 TOPIX 收盘和开市日历，与策略参数无关。</span>
        <button className="btn primary" disabled={busy || !definition}>{busy ? "提交中…" : "查找区间"}</button></div>
    </form>

    {discoveryId && !discovery && <p role="status">正在读取区间发现结果…</p>}
    {discovery && <section className="card" aria-label="候选区间">
      <div className="card-h"><h2>候选区间 · {STATES[discovery.status]}</h2>
        <span>{discovery.parameters.search_from} — {discovery.parameters.search_to} · {TRENDS[discovery.parameters.trend]}
          {discovery.parameters.volatility ? ` · ${VOLS[discovery.parameters.volatility]}` : " · 波动不限"} · {discovery.definition_version}</span></div>
      {["queued", "running"].includes(discovery.status) && <p role="status">正在按 TOPIX 行情划分区间…</p>}
      {discovery.status === "failed" && <p role="alert">区间发现失败：{discovery.error}</p>}
      {discovery.status === "completed" && <>
        {discovery.diagnostics && <Diagnostics diagnostics={discovery.diagnostics} count={intervals.length} />}
        {intervals.length === 0
          ? <p className="empty">搜索范围内没有符合条件的区间（零匹配）。可以换一种市场形势或放宽搜索范围；这不是错误。</p>
          : <IntervalTable intervals={intervals} checked={checked} toggle={toggle} warmup={warmup}
              onAll={() => setChecked(intervals.map(i => i.id))} onNone={() => setChecked([])} />}
      </>}
    </section>}

    {discovery?.status === "completed" && intervals.length > 0 && <form className="card" aria-label="运行所选区间"
      onSubmit={e => { e.preventDefault(); void runBatch(); }}>
      <div className="card-h"><h2>策略配置（所有所选区间共用）</h2><span>technical_rating_v1</span></div>
      <div className="form">
        <div className="field wide"><label htmlFor="regime-source">来源账户</label>
          <select id="regime-source" className="input" value={source} required onChange={e => setSource(e.target.value)}>
            <option value="">请选择</option>{sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></div>
        <div className="field"><label htmlFor="regime-entry">入场阈值 entry_above</label>
          <input id="regime-entry" className="input" type="number" min={-1} max={1} step="0.1" required value={entry} onChange={e => setEntry(e.target.value)} /></div>
        <div className="field"><label htmlFor="regime-exit">退出阈值 exit_below</label>
          <input id="regime-exit" className="input" type="number" min={-1} max={1} step="0.1" required value={exit} onChange={e => setExit(e.target.value)} /></div>
      </div>
      {chosen && <Configuration config={chosen.config} />}
      {over && <p className="notice">已选 {checked.length} 段，超过单批上限 {cap} 段；请减少勾选（不会自动截掉多余的段）。</p>}
      {stale && <div role="alert">行情已变化：{stale}
        <button type="button" className="btn" disabled={busy} onClick={() => void discover(discovery.parameters)}>重新发现</button></div>}
      <div className="foot"><span>已选 {checked.length} 段 / 单批上限 {cap} 段。每段各自用来源账户的初始资金空仓启动。</span>
        <button className="btn primary" disabled={busy || !chosen || checked.length === 0 || over}>{busy ? "提交中…" : "对所选区间运行"}</button></div>
    </form>}

    {discovery && discovery.batches.length > 0 && <section className="card"><div className="card-h"><h2>由本次发现发起的批次</h2><span>保留每次的选择记录</span></div>
      <div className="scroll"><table aria-label="本次发现的批次"><thead><tr><th>批次</th><th>创建时间</th><th>所选区间</th><th>状态</th></tr></thead>
        <tbody>{discovery.batches.map(b => <tr key={b.id}>
          <td><button type="button" className="btn" onClick={() => openBatch(b.id)}>{b.id.slice(0, 8)}</button></td>
          <td>{b.created_at.slice(0, 16).replace("T", " ")}</td>
          <td>{b.selection.interval_ids?.map(id => `#${id}`).join("、")}（共 {b.selection.candidate_count ?? "—"} 段候选）</td>
          <td>{BATCH_STATES[b.status]}</td></tr>)}</tbody></table></div>
    </section>}

    {batchId && <BatchView key={batchId} id={batchId} onStatus={() => setDiscoveryVersion(v => v + 1)}
      onDiscovery={id => { if (!discoveryId) { setDiscoveryId(id); setQuery({ discovery: id, batch: batchId }); } }}
      onRediscover={discovery ? () => void discover(discovery.parameters) : undefined} />}

    <BatchHistory key={batchId} onOpen={(id, discoveryOf) => {
      if (discoveryOf && discoveryOf !== discoveryId) { setDiscoveryId(discoveryOf); setChecked([]); }
      setBatchId(id); setQuery({ discovery: discoveryOf ?? "", batch: id });
    }} />

    <section className="card" aria-label="结果解读须知"><div className="card-h"><h2>解读须知</h2></div>
      <ul className="list">
        <li>各段长度不同，却按每段一票等权统计；相邻的几个短段可能属于同一次行情。</li>
        <li>区间边界要等行情走完才知道，是事后划分的，不能据此声称能实时择时。</li>
        <li>每段都用来源账户的初始资金空仓独立启动：净值不拼接、收益不连乘，也没有合并的总回撤。</li>
        <li>TOPIX 是价格指数，不含分红；结果不含税。这些是探索性的历史结果，不代表未来有效。</li>
      </ul></section>
  </>;
}

function DefinitionText({ definition }: { definition: Definition }) {
  const f = definition.formulas;
  return <details className="card-body"><summary>分类定义 {definition.version}（查看公式）</summary>
    <ul>
      {[f.ma200, f.gap, f.slope20, f.trend, f.rv20, f.rv_threshold, f.vol, f.unknown].map(text => <li key={text}>{text}</li>)}
    </ul>
    <p className="meta">固定的工程默认，不可在页面修改；改动规则会成为新版本。短段 = 少于 {definition.short_sessions} 个开市日，只作提示，不会被剔除。</p>
  </details>;
}

function Diagnostics({ diagnostics: d, count }: { diagnostics: NonNullable<Discovery["diagnostics"]>; count: number }) {
  return <div className="card-body">
    <p>搜索范围共 {d.search_sessions} 个开市日，其中 {d.matched_sessions} 个符合条件，连成 {count} 段候选区间（全部列出，未剔除任何一段）。</p>
    <p className="meta">
      <span>趋势：{Object.entries(TREND_COUNTS).map(([k, label]) => `${label} ${d.trend_counts[k] ?? 0}`).join("，")}</span>
      <span>波动：{Object.entries(VOL_COUNTS).map(([k, label]) => `${label} ${d.vol_counts[k] ?? 0}`).join("，")}</span>
    </p>
    {d.warmup_unknown.length > 0 && <p className="notice">历史不够、无法判断（预热不足）：{d.warmup_unknown.map(span).join("；")}</p>}
    {d.gap_unknown.length > 0 && <p className="notice">附近有数据缺口、无法判断：{d.gap_unknown.map(span).join("；")}</p>}
    {d.gaps.length > 0 && <p className="notice">缺少或不为正的 TOPIX 收盘（不补值）：{d.gaps.join("、")}</p>}
  </div>;
}

function IntervalTable({ intervals, checked, toggle, warmup, onAll, onNone }: {
  intervals: Interval[]; checked: number[]; toggle: (id: number) => void; warmup: number; onAll: () => void; onNone: () => void;
}) {
  return <>
    <div className="card-body actions">
      <button type="button" className="btn" onClick={onAll}>全选</button>
      <button type="button" className="btn" onClick={onNone}>清空</button>
    </div>
    <div className="scroll"><table aria-label="候选区间列表"><thead><tr><th>选择</th><th>区间</th><th>开市日数</th><th>TOPIX 变化</th><th>RV20 范围</th><th>标注</th></tr></thead>
      <tbody>{intervals.map(i => <tr key={i.id}>
        <td><input type="checkbox" aria-label={`选择区间 #${i.id} ${i.start_date} — ${i.end_date}`}
          checked={checked.includes(i.id)} onChange={() => toggle(i.id)} /></td>
        <td>#{i.id} {i.start_date} — {i.end_date}</td>
        <td>{i.sessions}</td>
        <td className={tone(i.topix_return)}>{signedPercent(i.topix_return)}（{i.topix_start.toFixed(2)} → {i.topix_end.toFixed(2)}）</td>
        <td>{rvPercent(i.rv20_min)} — {rvPercent(i.rv20_max)}</td>
        <td><span className="badges">
          {i.single_day && <span className="badge warn">单日</span>}
          {i.short && !i.single_day && <span className="badge warn">短段</span>}
          {i.truncated_start && <span className="badge">起点被截断</span>}
          {i.at_search_end && <span className="badge">可能延续到搜索范围之后</span>}
          {i.sessions_before < warmup && <span className="badge down" title={`起点前只有 ${i.sessions_before} 个开市日，策略需要 ${warmup} 个；提交时会被拒绝`}>策略预热不足</span>}
        </span></td>
      </tr>)}</tbody></table></div>
    <p className="card-body meta">起点被截断：搜索起始日前一天也符合条件，真实区间更早开始。可能延续：区间止于搜索结束日，之后的行情没有读取。策略预热不足：起点之前不足 {warmup} 个开市日，服务端会拒绝含这类区间的批次。</p>
  </>;
}

function BatchHistory({ onOpen }: { onOpen: (id: string, discovery: string | null) => void }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Schemas["BatchHistory"] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const response = await api.GET("/api/research/batches", {
        params: { query: { page, page_size: 10 } }, signal: controller.signal,
      }).catch(() => null);
      if (response?.data && !controller.signal.aborted) setData(response.data);
    })();
    return () => controller.abort();
  }, [page]);
  if (!data || data.total === 0) return null;
  return <section className="card"><div className="card-h"><h2>全部研究批次</h2><span>共 {data.total} 个</span></div>
    <div className="scroll"><table aria-label="研究批次历史"><thead><tr><th>批次</th><th>创建时间</th><th>来源与阈值</th><th>段数</th><th>状态</th></tr></thead>
      <tbody>{data.batches.map(b => <tr key={b.id}>
        <td><button type="button" className="btn" onClick={() => onOpen(b.id, b.discovery_id)}>{b.id.slice(0, 8)}</button></td>
        <td>{b.created_at.slice(0, 16).replace("T", " ")}</td>
        <td>{b.source_name} · {b.entry_above} / {b.exit_below}</td>
        <td>完成 {b.completed} / 失败 {b.failed} / 共 {b.segments}</td>
        <td>{BATCH_STATES[b.status]}</td></tr>)}</tbody></table></div>
    <Pager page={page} pages={Math.max(1, Math.ceil(data.total / 10))} onPage={setPage} />
  </section>;
}
