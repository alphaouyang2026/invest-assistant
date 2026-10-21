"use client";

import { type ReactNode, useEffect, useState } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { displayCode, fixed, signedYen, tone, yen } from "@/lib/format";
import { DISPOSITIONS, ORDER_KINDS, ORDER_STATUSES, outcome, percent } from "@/lib/labels";
import { Pager } from "../../pager";
import { Reasons } from "./experiment-shared";
import { message } from "./research-shared";

type Day = Schemas["DayRecord"];

const PAGE_SIZE = 20;

const count = (n: number) => n.toLocaleString("en-US");

/** A base-cost replay day by day: a page of sessions, and everything one of them decided and did. */
export function DayBrowser({ id, position, title }: { id: string; position: number; title: string }) {
  const [page, setPage] = useState(1);
  const [decisionOnly, setDecisionOnly] = useState(false);
  const [data, setData] = useState<Schemas["ExperimentDays"] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void (async () => {
      try {
        const response = await api.GET("/api/experiments/{experiment_id}/replays/{position}/days", {
          params: { path: { experiment_id: id, position }, query: { page, page_size: PAGE_SIZE, decision_only: decisionOnly } },
          signal: controller.signal,
        });
        if (response.error) throw response.error;
        setData(response.data);
        setChosen(current => (response.data.days.some(d => d.date === current) ? current : response.data.days[0]?.date ?? null));
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [id, position, page, decisionOnly]);

  const filter = (only: boolean) => { setDecisionOnly(only); setPage(1); };
  const day = data?.days.find(d => d.date === chosen);
  return <>
    <section className="card" aria-label="逐日决定">
      <div className="card-h"><h2>逐日决定 · {title}</h2>
        <div className="chips" role="group" aria-label="哪些日子">
          <button type="button" className="chip" aria-pressed={!decisionOnly} onClick={() => filter(false)}>全部开市日</button>
          <button type="button" className="chip" aria-pressed={decisionOnly} onClick={() => filter(true)}>只看决策日</button>
        </div></div>
      {error && <p role="alert">{error}</p>}
      {data?.total === 0 && <p className="empty">没有逐日记录</p>}
      <div className="scroll"><table aria-label="逐日列表"><thead><tr><th>日期</th><th>决策</th><th>折</th><th className="r">股票池 / 有分数</th>
        <th className="r">计划单</th><th className="r">开盘成交 / 过期</th><th className="r">收盘持仓</th><th className="r">现金</th><th className="r">净值</th><th /></tr></thead>
        <tbody>{data?.days.map(d => {
          const filled = d.executions.filter(e => e.status === "filled").length;
          return <tr key={d.date}><td className="num">{d.date}</td>
            <td>{d.decision_day ? (d.model_available ? <span className="badge up">决策日</span> : <span className="badge down">决策日 · 模型无分数</span>) : "—"}</td>
            <td>{d.fold === null ? "—" : `第 ${d.fold} 折`}</td>
            <td className="r">{count(d.universe)} / {d.decision_day ? count(d.scored) : "—"}</td>
            <td className="r">{d.orders.length}</td><td className="r">{filled} / {d.executions.length - filled}</td>
            <td className="r">{d.holdings.length} 只</td><td className="r">{yen(d.cash)}</td><td className="r">{yen(d.nav)}</td>
            <td><button type="button" className="btn" aria-pressed={d.date === chosen} onClick={() => setChosen(d.date)}>查看 {d.date}</button></td></tr>;
        })}</tbody></table></div>
      <Pager page={page} pages={Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))} onPage={setPage} />
    </section>
    {day && <DayDetail key={day.date} day={day} />}
  </>;
}

function Block({ title, empty, children }: { title: string; empty?: string | false; children: ReactNode }) {
  return <>
    <div className="day-h">{title}</div>
    {empty ? <p className="empty">{empty}</p> : <div className="scroll">{children}</div>}
  </>;
}

function DayDetail({ day: d }: { day: Day }) {
  const held = new Set(d.holdings_decisions.map(h => h.code));
  const target = new Map(d.target.map(t => [t.code, t.quantity]));
  const actual = new Map(d.holdings.map(h => [h.code, h.quantity]));
  const codes = [...new Set([...actual.keys(), ...target.keys()])].sort();
  const c = d.constraints;
  const skipped = Object.entries(c.skipped);
  const model = d.model_available === null ? "非决策日，不打分" : d.model_available ? "有分数" : "没有分数（某折训练失败等）：不开新仓，已有持仓保留";
  return <section className="card" aria-label={`${d.date} 的决定`}>
    <div className="card-h"><h2>{d.date} · {d.decision_day ? "决策日" : "非决策日"}{d.fold !== null && ` · 第 ${d.fold} 折`}</h2>
      <span>现金 ¥{yen(d.cash)} · 净值 ¥{yen(d.nav)} · 现金占比 {percent(d.nav ? d.cash / d.nav : null)}</span></div>
    <p className="card-body meta"><span>模型：{model}</span><span>当天股票池 {count(d.universe)} 只</span>
      {d.decision_day && <span>有分数 {count(d.scored)} 只</span>}<span>可买入的候选 {count(d.candidates)} 只（有分数、没持有的都算）</span></p>

    <Block title="当天早上的持仓怎么处理" empty={d.holdings_decisions.length === 0 && "当天早上空仓"}>
      <table aria-label="持仓处置"><thead><tr><th>证券</th><th>处置</th><th>理由</th><th className="r">分数</th></tr></thead>
        <tbody>{d.holdings_decisions.map(h => <tr key={h.code}><td className="mono">{displayCode(h.code)}</td>
          <td className={h.disposition === "exit" ? "down" : ""}>{h.disposition ? DISPOSITIONS[h.disposition] ?? h.disposition : "没有信号"}</td>
          <td><Reasons codes={h.reason_codes} /></td><td className="r">{fixed(h.score, 4)}</td></tr>)}</tbody></table>
    </Block>

    {d.decision_day && <Block title={`模型分数前 ${d.top_scores.length} 名`} empty={d.top_scores.length === 0 && "这一天没有分数"}>
      <table aria-label="分数前列"><thead><tr><th className="r">名次</th><th>证券</th><th className="r">分数</th><th>当天早上</th></tr></thead>
        <tbody>{d.top_scores.map(s => <tr key={s.code}><td className="r">{s.rank}</td><td className="mono">{displayCode(s.code)}</td>
          <td className="r">{fixed(s.score, 4)}</td><td>{held.has(s.code) ? "已持有" : ""}</td></tr>)}</tbody></table>
    </Block>}

    <Block title="收盘计划的订单（最早下一个开市日开盘执行）" empty={d.orders.length === 0 && "收盘没有计划新的买卖"}>
      <table aria-label="计划订单"><thead><tr><th className="r">序号</th><th>方向</th><th>证券</th><th>执行日</th><th className="r">计划股数</th>
        <th className="r">排序值</th><th>理由</th><th>最终结果</th></tr></thead>
        <tbody>{d.orders.map(o => {
          const status = ORDER_STATUSES[o.status] ?? { label: o.status, tone: "" };
          return <tr key={o.sequence}><td className="r">{o.sequence}</td>
            <td className={o.kind === "buy" ? "up" : o.kind === "sell" ? "down" : ""}>{ORDER_KINDS[o.kind] ?? o.kind}</td>
            <td className="mono">{displayCode(o.code)}</td><td className="num">{o.execution_date}</td>
            <td className="r">{o.planned_quantity.toLocaleString("en-US")}</td><td className="r">{fixed(o.priority, 4)}</td>
            <td><Reasons codes={o.reason_codes} capped={o.capped} />{o.replaces !== null && <span className="sub"> 替换第 {o.replaces} 笔</span>}</td>
            <td><span className={`badge ${status.tone}`}>{status.label}</span>{o.outcome_reason && <span className="sub"> {outcome(o.outcome_reason)}</span>}</td></tr>;
        })}</tbody></table>
    </Block>

    <Block title="当天开盘成交或过期的订单，以及账户事件" empty={d.executions.length === 0 && "当天开盘没有要执行的订单"}>
      <table aria-label="开盘执行"><thead><tr><th>方向</th><th>证券</th><th>信号日</th><th>结果</th><th className="r">成交股数</th>
        <th className="r">成交价</th><th className="r">费用</th><th className="r">现金变动</th></tr></thead>
        <tbody>{d.executions.map(e => {
          const status = ORDER_STATUSES[e.status] ?? { label: e.status, tone: "" };
          return <tr key={e.sequence}><td>{ORDER_KINDS[e.kind] ?? e.kind}</td><td className="mono">{displayCode(e.code)}</td>
            <td className="num">{e.signal_date}</td>
            <td><span className={`badge ${status.tone}`}>{status.label}</span>{e.outcome_reason && <span className="sub"> {outcome(e.outcome_reason)}</span>}</td>
            <td className="r">{e.filled_quantity.toLocaleString("en-US")}</td><td className="r">{e.fill_price ?? "—"}</td>
            <td className="r">{yen(e.fees)}</td><td className={`r ${tone(e.cash_delta)}`}>{e.cash_delta ? signedYen(e.cash_delta) : "—"}</td></tr>;
        })}</tbody></table>
    </Block>

    <Block title="目标与实际持仓（目标 = 收盘持仓减去计划卖出、加上计划买入）" empty={codes.length === 0 && "收盘空仓，也没有计划买入"}>
      <table aria-label="目标与实际持仓"><thead><tr><th>证券</th><th className="r">收盘实际股数</th><th className="r">计划后的目标股数</th><th className="r">差额</th></tr></thead>
        <tbody>{codes.map(code => {
          const now = actual.get(code) ?? 0;
          const wanted = target.get(code) ?? 0;
          return <tr key={code}><td className="mono">{displayCode(code)}</td><td className="r">{now.toLocaleString("en-US")}</td>
            <td className="r">{wanted.toLocaleString("en-US")}</td>
            <td className={`r ${tone(wanted - now)}`}>{wanted === now ? "—" : `${wanted > now ? "+" : "−"}${Math.abs(wanted - now).toLocaleString("en-US")}`}</td></tr>;
        })}</tbody></table>
    </Block>

    <div className="day-h">约束触发</div>
    <div className="card-body">
      <p>{skipped.length > 0 ? `计划时放弃：${skipped.map(([code, n]) => `${outcome(code)} ${n} 笔`).join("、")}` : "没有放弃的订单"}；
        按成交额上限压缩 {c.adv20_capped} 笔；跌出持有名单卖出 {c.ranked_out} 只。</p>
      {c.unplaced_candidates > 0 && <p className="sub">另有 {count(c.unplaced_candidates)} 只候选排在空位之外没买：决策日股票池里有分数、没持有的证券都算候选，这个数接近股票池只数，只说明空位有限。</p>}
    </div>
  </section>;
}
