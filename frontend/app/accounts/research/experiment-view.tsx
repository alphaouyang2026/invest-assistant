"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { displayCode, fixed, percentText, signedPercent, signedYen, tone, yen } from "@/lib/format";
import {
  ACTIONS, EXPERIMENT_EVIDENCE, FEATURES, ORDER_KINDS, ORDER_STATUSES, outcome, percent, stage, trainerLabel,
} from "@/lib/labels";
import { NavChart } from "../nav-chart";
import { Pager } from "../../pager";
import { DayBrowser } from "./experiment-days";
import { bps, minute, modelLabel, modelName, Reasons, replayName, shortHash, smallPercent } from "./experiment-shared";
import { message, poll, STATES, unfinished, useSubmit } from "./research-shared";

const readExperiment = (id: string, signal: AbortSignal) =>
  api.GET("/api/experiments/{experiment_id}", { params: { path: { experiment_id: id } }, signal });

type Detail = Schemas["ExperimentDetail"];
type Contract = Schemas["ExperimentContract"];
type Report = Schemas["ExperimentReport"];
type Summary = Schemas["ReplaySummary"];
type Metrics = Schemas["ReplayMetrics"];

const DATA: Record<string, string> = {
  source: "数据来源", prices: "价格口径", available: "可得时点", universe: "股票池口径", point_in_time: "能证明什么",
};
const UNIVERSES: Record<string, string> = { prime_common_stock: "Prime 普通股", topix_etf: "TOPIX ETF" };
const BENCHMARKS: Record<string, string> = { topix_price: "TOPIX 价格指数", eligible_equal_weight: "合格池等权" };

const counts = (byReason: Record<string, number>) =>
  Object.entries(byReason).map(([code, n]) => `${outcome(code)} ${n} 笔`).join("、");

/** One model experiment: its frozen contract, folds, diagnostics, replays and evidence. Polls while it runs. */
export function ExperimentView({ id, onOpen, onStatus }: { id: string; onOpen: (id: string) => void; onStatus?: () => void }) {
  const [experiment, setExperiment] = useState<Detail | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const { busy, send } = useSubmit(setError);
  const callbacks = useRef({ onStatus });
  callbacks.current = { onStatus };
  const lastStatus = useRef<string | null>(null);

  useEffect(() => poll(signal => readExperiment(id, signal), data => {
    setExperiment(data);
    if (lastStatus.current !== null && lastStatus.current !== data.status) callbacks.current.onStatus?.();
    lastStatus.current = data.status;
    return unfinished(data.status);
  }, e => setError(message(e))), [id, version]);

  function retry() {
    setError(null);
    return send({ retry: id }, async key => {
      const response = await api.POST("/api/experiments/{experiment_id}/retry", {
        params: { path: { experiment_id: id } }, body: { request_key: key },
      });
      if (response.error) throw response.error;
      onOpen(response.data.id);
      callbacks.current.onStatus?.();
    });
  }

  if (!experiment) return error ? <p role="alert">{error}</p> : <p role="status">正在读取模型实验…</p>;
  const x = experiment;
  const c = x.contract;
  return <section className="stack" aria-label="模型实验结果">
    <section className="card">
      <div className="card-h"><h2>实验 {x.id.slice(0, 8)}{x.name && ` · ${x.name}`} · {STATES[x.status]}</h2>
        <span>测试段 {c.test_from} — {c.test_to} · 契约 {shortHash(x.contract_hash)}</span></div>
      <div className="card-body stack">
        <p className="meta"><span>登记于 {minute(x.created_at)}</span>{x.finished_at && <span>结束于 {minute(x.finished_at)}</span>}
          {x.retry_of && <span>这是 <button type="button" className="btn" onClick={() => onOpen(x.retry_of!)}>{x.retry_of.slice(0, 8)}</button> 的重试，契约相同</span>}
          {x.retried_by.length > 0 && <span>已重试为 {x.retried_by.map(r =>
            <button key={r} type="button" className="btn" onClick={() => onOpen(r)}>{r.slice(0, 8)}</button>)}</span>}</p>
        {unfinished(x.status) && <Progress status={x.status} progress={x.progress} contract={c} />}
        {x.status === "failed" && <div role="alert">实验失败：{x.error ?? "原因未记录"}（这次尝试的记录保留，不会被覆盖）
          <button type="button" className="btn" disabled={busy} onClick={() => void retry()}>重试（新尝试）</button></div>}
        {error && <div role="alert">{error} <button type="button" className="btn" onClick={() => { setError(null); setVersion(v => v + 1); }}>重新读取</button></div>}
        {x.status === "completed" && !x.report && <p className="notice">实验已完成，但没有保存报告。</p>}
      </div>
    </section>
    {x.report && <Evidence report={x.report} />}
    <ContractTerms detail={x} />
    {x.report && <Folds report={x.report} detail={x} />}
    {x.report && <Diagnostics report={x.report} contract={c} />}
    {x.report && <Comparison report={x.report} contract={c} />}
    {x.report && x.report.replays.length > 0 && <ReplayPanel id={x.id} report={x.report} contract={c} />}
    <details className="card card-body"><summary>输入与版本记录</summary>
      <pre>{JSON.stringify({ contract_hash: x.contract_hash, input: x.input_fingerprint, code: x.code_version, retry_of: x.retry_of,
        read_from: x.report?.read_from, timings: x.report?.timings }, null, 2)}</pre></details>
  </section>;
}

function Progress({ status, progress: p, contract }: { status: Detail["status"]; progress: Detail["progress"]; contract: Contract }) {
  const code = typeof p.stage === "string" ? p.stage : undefined;
  const n = (key: string) => Number(p[key] ?? 0);
  let text = stage(code);
  if (code === "training" && typeof p.model === "string") text += `：${modelLabel(contract, p.model)}`;
  const replaying = code === "replaying" && n("replays_total") > 0;
  if (replaying) {
    text += ` 第 ${n("replays_done") + 1} / ${n("replays_total")} 个：${n("sessions_done")} / ${n("sessions_total")} 个开市日（${String(p.current_session ?? "")}）`;
  }
  const share = replaying ? (n("replays_done") + n("sessions_done") / Math.max(1, n("sessions_total"))) / n("replays_total") : null;
  return <>
    <p role="status">{STATES[status]}：{text}</p>
    {share !== null && <div className="progress" aria-hidden="true"><i style={{ width: `${share * 100}%` }} /></div>}
  </>;
}

function Evidence({ report }: { report: Report }) {
  const e = report.evidence;
  const status = EXPERIMENT_EVIDENCE[e.status] ?? { label: e.status, tone: "" };
  return <section className="card" aria-label="证据状态">
    <div className="card-h"><h2>证据状态</h2><span className={`badge ${status.tone}`}>{status.label}</span></div>
    <ul className="list">{e.reasons.map((r, i) => <li key={`${r.code}-${i}`}>{r.message}</li>)}</ul>
    {report.warnings.length > 0 && <div className="card-body stack">{report.warnings.map(w => <p key={w} className="notice">{w}</p>)}</div>}
    <p className="card-body meta">本步只给出「探索性」或「证据不足」，不会判定通过。已看过的折：{e.viewed_folds.length > 0
      ? e.viewed_folds.map(f => `第 ${f} 折`).join("、") : "没有"}。</p>
  </section>;
}

function ContractTerms({ detail: x }: { detail: Detail }) {
  const c = x.contract;
  const r = c.portfolio_rules;
  const p = c.policy;
  const rows: [string, string][] = [
    ["契约", `${c.version} · sha256 ${x.contract_hash}`],
    ["名称", c.name || "—"],
    ["任务", `${c.task.name}：${c.task.decision}`],
    ["标签", `${c.task.label}（持有 ${c.task.horizon} 个开市日，标签要 ${c.task.label_sessions} 个开市日后才知道）`],
    // The labelled notes in their reading order, then any the page does not know yet.
    ...[...Object.keys(DATA), ...Object.keys(c.data).filter(key => !(key in DATA))].filter(key => key in c.data)
      .map((key): [string, string] => [DATA[key] ?? key, c.data[key]]),
    ["特征", `${c.features.version}：${c.features.names.map(n => FEATURES[n] ?? n).join("、")}`],
    ["股票池", UNIVERSES[c.universe_rule] ?? c.universe_rule],
    ["测试段", `${c.test_from} — ${c.test_to}`],
    ["日期折", `训练窗 ${c.folds.train_sessions} 个开市日${c.folds.expanding ? "（扩展：从最早可用的日子起）" : ""} · 每折测试段 ${c.folds.test_sessions} 个开市日`],
    ["政策", `${p.strategy} · 锚点 ${p.anchor} · 每 ${p.rebalance_sessions} 个开市日决策一次 · 最长持有 ${p.max_holding_sessions ? `${p.max_holding_sessions} 个开市日` : "不限"}`],
    ["缺分数时", p.missing_scores],
    ["某只没有分数时", p.score_missing],
    ["组合规则", `初始资金 ¥${yen(Number(r.initial_cash))} · 最多 ${r.max_positions} 只 · 单只上限 ${percentText(Number(r.max_weight))}% · 现金下限 ${percentText(Number(r.cash_floor))}% · 成交额上限 ${r.max_adv20_fraction ? `${percentText(Number(r.max_adv20_fraction))}% ADV20` : "不设"}`],
    ["基础成本", `手续费率 ${percentText(Number(c.costs.commission_rate))}% · 最低手续费 ¥${yen(Number(c.costs.commission_min))} · 每边滑点 ${bps(c.costs.slippage)}`],
    ["压力场景", `${c.stress_slippages.map(s => `每边滑点 ${bps(s)}`).join("、")}（只换主模型回放的滑点，手续费不变）`],
    ["主模型", `${trainerLabel(c.model.trainer)} · 参数 ${JSON.stringify(c.model.params)} · 搜索预算 ${c.model.search_budget}`],
    ["规则基线", c.baselines.map(b => trainerLabel(b.trainer)).join("、")],
    ["基准", c.benchmarks.map(b => BENCHMARKS[b] ?? b).join("、")],
    ["最低要求", `平均覆盖率 ${percentText(c.minimums.coverage)}% · 主模型基础成本回放至少 ${c.minimums.trades} 笔成交`],
    ["已看过截至", c.viewed_through ?? "登记时还没有看过任何历史"],
    ["动作能力", c.actions.map(a => ACTIONS[a] ?? a).join("、")],
    ["来源账户", c.source_account_id === null ? "不用" : `#${c.source_account_id}（只复制了初始资金、组合规则和费用）`],
  ];
  return <section className="card" aria-label="冻结契约">
    <div className="card-h"><h2>冻结契约</h2><span>登记时冻结，之后不改；重试沿用同一份</span></div>
    <div className="scroll"><table aria-label="冻结契约"><tbody>
      {rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td className="wrap">{value}</td></tr>)}
    </tbody></table></div>
  </section>;
}

function Folds({ report, detail }: { report: Report; detail: Detail }) {
  const viewed = report.folds.filter(f => f.viewed).length;
  const result = (model: string, fold: number) => detail.fold_results.find(r => r.model === model && r.fold === fold);
  return <section className="card" aria-label="日期折">
    <div className="card-h"><h2>日期折</h2>
      <span>{report.folds.length} 折 · 已看过 {viewed} 折 · 已看过截至 {detail.contract.viewed_through ?? "—"}</span></div>
    <div className="scroll"><table aria-label="日期折列表"><thead><tr><th>折</th><th>训练段</th><th>测试段</th><th>标记</th>
      {report.models.map(m => <th key={m.key}>{modelName(m.key)}：样本 · 工件</th>)}</tr></thead>
      <tbody>{report.folds.map(f => <tr key={f.number}>
        <td>第 {f.number} 折</td><td>{f.train_from} — {f.train_to}</td><td>{f.test_from} — {f.test_to}</td>
        <td>{f.viewed ? <span className="badge warn">探索性（已看过）</span> : <span className="badge ok">登记前未看过</span>}</td>
        {report.models.map(m => {
          const r = result(m.key, f.number);
          return <td key={m.key}>{!r ? "—" : r.error ? <span className="down">训练失败：{r.error}</span>
            : <>{r.samples.toLocaleString("en-US")} 个 · <span className="mono">{shortHash(r.artifact_hash)}</span></>}</td>;
        })}
      </tr>)}</tbody></table></div>
    <p className="card-body meta">训练只用标签在训练截止日前已经结束的样本（标签要 {detail.contract.task.label_sessions} 个开市日后才知道）；同一天的所有证券在同一折。
      测试段第一天不晚于「已看过截至」的折标「探索性（已看过）」。工件是每折拟合结果的 JSON，后面是它的 sha256 前 12 位。</p>
    {detail.fold_results.length > 0 && <details className="card-body"><summary>查看各折工件</summary>
      <pre>{JSON.stringify(detail.fold_results.map(r => ({ model: r.model, fold: r.fold, seconds: r.seconds,
        artifact_hash: r.artifact_hash, error: r.error, artifact: r.artifact })), null, 2)}</pre></details>}
  </section>;
}

function Diagnostics({ report, contract }: { report: Report; contract: Contract }) {
  return <section className="card" aria-label="预测效果">
    <div className="card-h"><h2>预测效果（模型诊断）</h2><span>只看分数排得准不准，不含成交和费用</span></div>
    <div className="scroll"><table aria-label="模型诊断"><thead><tr><th>模型</th><th className="r">决策日</th><th className="r">模型不可用</th>
      <th className="r">Rank IC 均值</th><th className="r">Rank IC 标准差</th><th className="r">算 IC 的天数</th>
      <th className="r">平均覆盖率</th><th className="r">最低覆盖率</th><th>训练失败的折</th></tr></thead>
      <tbody>{report.models.map(m => {
        const d = m.diagnostics;
        return <tr key={m.key}><td>{modelLabel(contract, m.key)}</td><td className="r">{d.decision_days}</td>
          <td className={`r ${d.unavailable_days ? "down" : ""}`}>{d.unavailable_days} 天</td>
          <td className={`r ${tone(d.ic_mean)}`}>{fixed(d.ic_mean, 3)}</td><td className="r">{fixed(d.ic_std, 3)}</td>
          <td className="r">{d.ic_days}</td><td className="r">{percent(d.coverage_mean)}</td><td className="r">{percent(d.coverage_min)}</td>
          <td>{m.failed_folds.length ? <span className="down">{m.failed_folds.map(f => `第 ${f} 折`).join("、")}</span> : "没有"}</td></tr>;
      })}</tbody></table></div>
    <p className="card-body meta">Rank IC：每个决策日把分数和标签（t+1 开盘到 t+6 开盘的收益）各自排名后算相关系数，再对日子取平均；标签越过测试终点的决策日不算。
      覆盖率 = 当天有分数的证券 ÷ 当天股票池，模型不可用的决策日记 0。</p>
    <details className="card-body"><summary>逐折诊断</summary>
      <div className="scroll"><table aria-label="逐折诊断"><thead><tr><th>折</th><th>模型</th><th className="r">决策日</th><th className="r">模型不可用</th>
        <th className="r">Rank IC 均值</th><th className="r">Rank IC 标准差</th><th className="r">平均覆盖率</th></tr></thead>
        <tbody>{report.folds.flatMap(f => report.models.map(m => {
          const d = m.diagnostics.folds.find(x => x.fold === f.number);
          return <tr key={`${f.number}-${m.key}`}><td>第 {f.number} 折</td><td>{modelName(m.key)}</td>
            <td className="r">{d?.decision_days ?? "—"}</td><td className="r">{d?.unavailable_days ?? "—"}</td>
            <td className={`r ${tone(d?.ic_mean)}`}>{fixed(d?.ic_mean, 3)}</td><td className="r">{fixed(d?.ic_std, 3)}</td>
            <td className="r">{percent(d?.coverage_mean)}</td></tr>;
        }))}</tbody></table></div></details>
  </section>;
}

function Comparison({ report, contract }: { report: Report; contract: Contract }) {
  const topix = report.benchmarks.topix_price;
  const pool = report.benchmarks.eligible_equal_weight;
  const dash = (n: number) => Array.from({ length: n }, (_, i) => <td key={i} className="r">—</td>);
  const sameAsBase = contract.stress_slippages.some(s => Number(s) === Number(contract.costs.slippage));
  return <section className="card" aria-label="组合效果">
    <div className="card-h"><h2>组合效果（回放与基准对比）</h2><span>{report.sessions} 个开市日 · {report.decision_days} 个决策日</span></div>
    <div className="scroll"><table aria-label="回放与基准对比"><thead><tr><th>回放</th><th>每边滑点</th><th className="r">净收益</th>
      <th className="r">相对 TOPIX</th><th className="r">相对合格池</th><th className="r">年化</th><th className="r">最大回撤</th><th className="r">夏普</th>
      <th className="r">平均现金占比</th><th className="r">年化换手</th><th className="r">成交</th><th className="r">成交率</th>
      <th className="r">订单 ÷ ADV20（中位 / 最大）</th><th className="r">手续费</th></tr></thead>
      <tbody>{report.replays.map(r => {
        const m = r.metrics;
        const overPool = pool.total_return === null ? null : m.total_return - pool.total_return;
        return <tr key={r.position}><td>{modelLabel(contract, r.model)} · {r.scenario === "base" ? "基础成本" : "压力场景"}</td>
          <td>{bps(r.costs.slippage)}</td>
          <td className={`r ${tone(m.total_return)}`}>{signedPercent(m.total_return)}</td>
          <td className={`r ${tone(m.excess_return)}`}>{signedPercent(m.excess_return)}</td>
          <td className={`r ${tone(overPool)}`}>{signedPercent(overPool)}</td>
          <td className={`r ${tone(m.annualised_return)}`}>{signedPercent(m.annualised_return)}</td>
          <td className="r">{signedPercent(-m.max_drawdown)}</td><td className="r">{fixed(m.sharpe, 2)}</td>
          <td className="r">{percent(m.average_cash_share)}</td><td className="r">{fixed(m.annual_turnover, 1)}</td>
          <td className="r">{m.trades}</td><td className="r">{percent(m.fill_rate.rate)}</td>
          <td className="r">{smallPercent(m.adv20.median)} / {smallPercent(m.adv20.max)}</td><td className="r">¥{yen(m.fees)}</td></tr>;
      })}
        <tr><td>TOPIX 价格指数（参照）</td><td>—</td><td className={`r ${tone(topix.total_return)}`}>{signedPercent(topix.total_return)}</td>{dash(11)}</tr>
        <tr><td>合格池等权（参照，未扣费）</td><td>—</td><td className={`r ${tone(pool.total_return)}`}>{signedPercent(pool.total_return)}</td>{dash(11)}</tr>
      </tbody></table></div>
    <div className="card-body">
      <p><b>TOPIX 口径：</b>{topix.basis}。</p>
      <p><b>合格池等权口径：</b>{pool.basis}（共 {pool.periods.length} 期）。</p>
      <p className="meta">「相对」都是净收益直接相减。两个参照都不是可成交的账户：合格池不扣费用、不受整手和现金约束，不能当作扣费后的对手。回放的收益含期末浮盈亏、不含分红和税。</p>
      {sameAsBase && <p className="meta">压力场景里有一个的滑点和基础成本相同（每边 {bps(contract.costs.slippage)}），它和基础成本回放逐笔相同，用来核对回放是否一致。</p>}
    </div>
  </section>;
}

function ReplayPanel({ id, report, contract }: { id: string; report: Report; contract: Contract }) {
  const [position, setPosition] = useState(report.replays[0].position);
  const [detail, setDetail] = useState<Schemas["ReplayDetail"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const summary = report.replays.find(r => r.position === position) ?? report.replays[0];

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setError(null);
    void (async () => {
      try {
        const response = await api.GET("/api/experiments/{experiment_id}/replays/{position}", {
          params: { path: { experiment_id: id, position } }, signal: controller.signal,
        });
        if (response.error) throw response.error;
        setDetail(response.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [id, position]);

  const base = report.replays.find(r => r.model === summary.model && r.scenario === "base");
  return <section className="stack" aria-label="回放详情">
    <section className="card">
      <div className="card-h"><h2>回放 · {modelLabel(contract, summary.model)}</h2>
        <div className="chips" role="group" aria-label="选择回放">{report.replays.map(r =>
          <button key={r.position} type="button" className="chip" aria-pressed={r.position === position}
            onClick={() => setPosition(r.position)}>{replayName(r)}</button>)}</div></div>
      <Kpis metrics={summary.metrics} />
      {summary.metrics.trades === 0 && <p className="card-body">这个回放没有成交；可能是模型一直不可用、分数都不够、或受资金和成交规则限制，并不意味着模型无效。</p>}
      {error && <p role="alert">{error}</p>}
      {detail ? <div className="chart"><NavChart points={detail.result.nav} /></div> : !error && <p role="status" className="card-body">正在读取回放…</p>}
      <Periods summary={summary} />
      <FillAndCapacity metrics={summary.metrics} />
    </section>
    {detail && <EndState detail={detail} />}
    {summary.scenario === "base"
      ? <DayBrowser key={`days-${summary.position}`} id={id} position={summary.position} title={replayName(summary)} />
      : <p className="notice">压力场景回放只保存订单和净值；逐日决定看「{base ? replayName(base) : "基础成本"}」，两者只差滑点。</p>}
    <ReplayOrders key={`orders-${summary.position}`} id={id} position={summary.position} />
  </section>;
}

function Kpis({ metrics: m }: { metrics: Metrics }) {
  return <dl className="kpis">{[
    ["净收益（含期末浮盈亏）", signedPercent(m.total_return)], ["同期 TOPIX", signedPercent(m.topix_return)],
    ["收益差", signedPercent(m.excess_return)], ["最大回撤", signedPercent(-m.max_drawdown)],
    ["年化收益", signedPercent(m.annualised_return)], ["夏普", fixed(m.sharpe, 2)],
    ["平均现金占比", percent(m.average_cash_share)], ["年化换手", fixed(m.annual_turnover, 1)],
    ["成交数", String(m.trades)], ["实际手续费", `¥${yen(m.fees)}`],
    ["已实现盈亏", signedYen(m.realised_pnl)], ["未实现盈亏", signedYen(m.unrealised_pnl)],
  ].map(([label, value]) => <div className="kpi" key={label}><dt>{label}</dt><dd className="v">{value}</dd></div>)}</dl>;
}

function Periods({ summary }: { summary: Summary }) {
  const rows = [
    ...summary.folds.map((f, i) => ({ key: `f${i}`, label: `第 ${f?.fold ?? i + 1} 折`, period: f })),
    ...summary.years.map(y => ({ key: `y${y.year}`, label: `${y.year} 年`, period: y })),
  ];
  return <div className="scroll"><table aria-label="逐折与逐年收益"><thead><tr><th>段</th><th>区间</th><th className="r">开市日</th>
    <th className="r">净收益</th><th className="r">同期 TOPIX</th><th className="r">收益差</th></tr></thead>
    <tbody>{rows.map(({ key, label, period: p }) => <tr key={key}><td>{label}</td>
      {p ? <><td>{p.start} — {p.end}</td><td className="r">{p.sessions}</td>
        <td className={`r ${tone(p.net_return)}`}>{signedPercent(p.net_return)}</td>
        <td className={`r ${tone(p.topix_return)}`}>{signedPercent(p.topix_return)}</td>
        <td className={`r ${tone(p.excess_return)}`}>{signedPercent(p.excess_return)}</td></>
        : <td colSpan={5}>这一折没有回放日</td>}</tr>)}</tbody></table></div>;
}

function FillAndCapacity({ metrics: m }: { metrics: Metrics }) {
  const f = m.fill_rate;
  const a = m.adv20;
  const skipped = Object.values(f.skipped_reasons).reduce((sum, n) => sum + n, 0);
  return <div className="card-body">
    <p>成交 {f.filled} 笔，开盘过期 {f.expired} 笔{f.expired ? `（${counts(f.expired_reasons)}）` : ""}，成交率 {percent(f.rate)}；
      计划时就放弃 {skipped} 笔{skipped ? `（${counts(f.skipped_reasons)}）` : ""}。未成交的卖单不算已经降低了风险。</p>
    <p>订单金额 ÷ ADV20（前 20 个开市日平均成交额）：{a.orders} 笔，中位数 {smallPercent(a.median)}、95 分位 {smallPercent(a.p95)}、最大 {smallPercent(a.max)}；
      上限 {a.cap === null ? "不设" : smallPercent(a.cap)}，超过上限 {a.over_cap} 笔{a.without_adv20 ? `，没有 ADV20 的 ${a.without_adv20} 笔` : ""}。</p>
  </div>;
}

function EndState({ detail }: { detail: Schemas["ReplayDetail"] }) {
  const r = detail.result;
  return <section className="card" aria-label="回放期末">
    <div className="card-h"><h2>期末持仓</h2><span>现金 ¥{yen(r.metrics.cash)} · 期末未执行订单 {r.pending.length} 笔（不会继续推进）</span></div>
    {r.warnings.map(w => <p key={w} className="notice">{w}</p>)}
    {r.holdings.length === 0 ? <p className="empty">期末空仓</p> : <div className="scroll"><table aria-label="回放期末持仓">
      <thead><tr><th>证券</th><th className="r">股数</th><th>开仓日</th><th className="r">成本（含费用）</th><th className="r">市值</th><th className="r">浮盈亏</th></tr></thead>
      <tbody>{r.holdings.map(h => <tr key={h.code}><td className="mono">{displayCode(h.code)}</td><td className="r">{h.quantity.toLocaleString("en-US")}</td>
        <td className="num">{h.opened_on}</td><td className="r">{yen(h.cost)}</td><td className="r">{yen(h.value)}</td>
        <td className={`r ${tone(h.value - h.cost)}`}>{signedYen(h.value - h.cost)}</td></tr>)}</tbody></table></div>}
  </section>;
}

function ReplayOrders({ id, position }: { id: string; position: number }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Schemas["ExperimentOrders"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void (async () => {
      try {
        const r = await api.GET("/api/experiments/{experiment_id}/replays/{position}/orders", {
          params: { path: { experiment_id: id, position }, query: { page, page_size: 50 } }, signal: controller.signal,
        });
        if (r.error) throw r.error;
        setData(r.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [id, position, page]);
  return <section className="card" aria-label="回放订单"><div className="card-h"><h2>交易记录与期末挂单</h2>{data && <span>共 {data.total} 笔，新的在前</span>}</div>
    {error && <p role="alert">{error}</p>}
    {data?.total === 0 && <p className="empty">没有订单或账户事件</p>}
    <div className="scroll"><table aria-label="实验回放交易记录"><thead><tr><th>信号日 → 执行日</th><th>证券</th><th>方向</th><th>状态</th>
      <th className="r">计划 / 成交股数</th><th className="r">成交价</th><th className="r">费用</th><th className="r">排序值</th><th>理由</th></tr></thead>
      <tbody>{data?.orders.map((o, i) => {
        const status = ORDER_STATUSES[o.status] ?? { label: o.status, tone: "" };
        return <tr key={o.id ?? i}><td className="num">{o.signal_date} → {o.execution_date}</td><td className="mono">{displayCode(o.code)}</td>
          <td className={o.kind === "buy" ? "up" : o.kind === "sell" ? "down" : ""}>{ORDER_KINDS[o.kind] ?? o.kind}</td>
          <td><span className={`badge ${status.tone}`}>{status.label}</span>{o.outcome_reason && <span className="sub"> {outcome(o.outcome_reason)}</span>}</td>
          <td className="r">{o.planned_quantity.toLocaleString("en-US")} / {o.filled_quantity.toLocaleString("en-US")}</td>
          <td className="r">{o.fill_price ?? "—"}</td><td className="r">{yen(o.fees)}</td><td className="r">{fixed(o.priority, 4)}</td>
          <td><Reasons codes={o.reason.reason_codes} capped={o.reason.capped} /></td></tr>;
      })}</tbody></table></div>
    <Pager page={page} pages={Math.max(1, Math.ceil((data?.total ?? 0) / 50))} onPage={setPage} />
  </section>;
}
