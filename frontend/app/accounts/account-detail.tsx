"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { displayCode, fixed, signedPercent, signedYen, tone, yen } from "@/lib/format";
import { ORDER_GROUPS, ORDER_KINDS, ORDER_STATUSES, type OrderGroup, outcome, reason, reasonTone, strategyLabel } from "@/lib/labels";

import { Pager, range } from "../pager";
import { StatusBadge, drawdown } from "./account-list";
import { NavChart, type NavPoint } from "./nav-chart";

type Detail = Schemas["AccountDetailOut"];
type Figures = Schemas["FiguresOut"];
type Order = Schemas["OrderOut"];
type OrdersPage = Schemas["OrdersPageOut"];

const PAGE_SIZE = 50;

export function AccountDetail({ id, pollMs = 2000 }: { id: number; pollMs?: number }) {
  const router = useRouter();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [nav, setNav] = useState<NavPoint[]>([]);
  const [running, setRunning] = useState(false);
  const [version, setVersion] = useState(0); // counts reloads, so the history reloads with the rest
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const path = { params: { path: { account_id: id } } };
    const [d, n, job] = await Promise.all([
      api.GET("/api/accounts/{account_id}", path),
      api.GET("/api/accounts/{account_id}/nav", path),
      api.GET("/api/jobs/current"),
    ]);
    if (d.error || n.error) {
      setError(d.error && typeof d.error.detail === "string" ? d.error.detail : "读取账户失败");
      return;
    }
    setError(null);
    setDetail(d.data);
    setNav(n.data);
    setRunning(Boolean(job.data));
    setVersion((v) => v + 1);
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // While a job runs (this account's backtest, or a sync advancing it), read again once it ends.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(async () => {
      const { data } = await api.GET("/api/jobs/current");
      if (!data) void load();
    }, pollMs);
    return () => clearInterval(timer);
  }, [running, pollMs, load]);

  const stop = async () => {
    await api.POST("/api/accounts/{account_id}/stop", { params: { path: { account_id: id } } });
    void load();
  };

  const remove = async () => {
    if (!window.confirm("删除这个账户和它的全部订单？此操作不能撤销。")) return;
    await api.DELETE("/api/accounts/{account_id}", { params: { path: { account_id: id } } });
    router.push("/accounts");
  };

  if (error) {
    return (
      <section className="page">
        <p role="alert">{error}</p>
      </section>
    );
  }
  if (!detail) return null;

  return (
    <section className="page">
      <div className="crumb">
        <Link href="/accounts">账户</Link> / {detail.name}
      </div>
      <div className="head">
        <div>
          <h1>
            {detail.name} <StatusBadge status={detail.status} />
          </h1>
          <div className="meta">
            <span>{strategyLabel(detail.strategy)}</span>
            <span className="num">{detail.start_date} 起</span>
            <span className="num">{detail.advanced_through ? `推进到 ${detail.advanced_through}` : "尚未推进"}</span>
            {nav.length > 0 && <span>{nav.length} 个交易日</span>}
          </div>
        </div>
        <div className="actions">
          {detail.status === "active" && (
            <button type="button" className="btn" onClick={() => void stop()}>
              停用
            </button>
          )}
          <button type="button" className="btn danger" onClick={() => void remove()}>
            删除账户
          </button>
        </div>
      </div>
      {running && <p className="notice">后台任务进行中，完成后自动刷新。</p>}

      <section className="card" aria-labelledby="figures">
        <div className="card-h">
          <h2 id="figures">统计</h2>
          <span className="aside">不含分红、不含税</span>
        </div>
        {detail.figures ? (
          <FigureGrid figures={detail.figures} initialCash={detail.rules.initial_cash} />
        ) : (
          <div className="empty">尚未推进，还没有统计</div>
        )}
      </section>

      {nav.length > 0 && <NavCard points={nav} />}
      <Holdings detail={detail} />
      <Pending detail={detail} />
      <History id={id} strategy={detail.strategy} version={version} />
    </section>
  );
}

function FigureGrid({ figures: f, initialCash }: { figures: Figures; initialCash: number | undefined }) {
  const topix =
    f.annualised_return === null || f.excess_annualised_return === null
      ? null
      : f.annualised_return - f.excess_annualised_return;
  const figures = [
    { label: "总收益", value: signedPercent(f.total_return), tone: tone(f.total_return),
      sub: initialCash === undefined ? "" : `起始资金 ¥${yen(initialCash)}` },
    { label: "年化收益", value: signedPercent(f.annualised_return), tone: tone(f.annualised_return),
      sub: "按 245 个交易日折算" },
    { label: "最大回撤", value: drawdown(f.max_drawdown), tone: f.max_drawdown ? "down" : "",
      sub: "净值从高点回落的最大幅度" },
    { label: "相对 TOPIX 超额年化", value: signedPercent(f.excess_annualised_return),
      tone: tone(f.excess_annualised_return), sub: topix === null ? "" : `同期 TOPIX 年化 ${signedPercent(topix)}` },
    { label: "夏普比率", value: fixed(f.sharpe, 2), tone: "", sub: "无风险利率按 0" },
    { label: "胜率", value: f.win_rate === null ? "—" : `${(f.win_rate * 100).toFixed(1)}%`, tone: "",
      sub: `已结束的 ${f.closed_positions} 笔持仓` },
    { label: "平均持有", value: f.average_holding_sessions === null ? "—" : `${fixed(f.average_holding_sessions, 1)} 天`,
      tone: "", sub: "交易日" },
    { label: "年化换手率", value: f.annual_turnover === null ? "—" : `${fixed(f.annual_turnover, 2)} 倍`, tone: "",
      sub: "（买入额 + 卖出额）÷ 2 ÷ 平均净值" },
  ];
  return (
    <dl className="kpis">
      {figures.map((figure) => (
        <div className="kpi" key={figure.label}>
          <dt className="l">{figure.label}</dt>
          <dd className={`v ${figure.tone}`}>{figure.value}</dd>
          {figure.sub && <dd className="s">{figure.sub}</dd>}
        </div>
      ))}
    </dl>
  );
}

function NavCard({ points }: { points: NavPoint[] }) {
  const last = points[points.length - 1];
  return (
    <section className="card" aria-labelledby="nav">
      <div className="card-h">
        <h2 id="nav">净值与 TOPIX</h2>
        <div className="legend">
          <span>
            <span className="swatch" style={{ background: "var(--up)" }} />
            账户<b>{last.nav_curve.toFixed(2)}</b>
          </span>
          <span>
            <span className="swatch" style={{ background: "var(--topix)" }} />
            TOPIX<b>{last.topix_curve.toFixed(2)}</b>
          </span>
          <span>
            <span className="swatch" style={{ background: "var(--down)" }} />
            回撤
          </span>
          <span>起始日 = 1</span>
        </div>
      </div>
      <div className="chart">
        <NavChart points={points} />
      </div>
    </section>
  );
}

function Security({ code, name, strategy }: { code: string; name: string | null; strategy: string }) {
  return (
    <>
      <Link href={`/signals/${code}?strategy=${strategy}`} className="code mono">
        {displayCode(code)}
      </Link>
      {name && <span className="sub"> {name}</span>}
    </>
  );
}

function Reasons({ order }: { order: Order }) {
  const codes = (order.reason.reason_codes as string[] | undefined) ?? [];
  return (
    <span className="badges">
      {codes.map((code) => (
        <span key={code} className={`badge ${reasonTone(code)}`}>
          {reason(code)}
        </span>
      ))}
    </span>
  );
}

function Holdings({ detail }: { detail: Detail }) {
  const { holdings } = detail;
  const cost = holdings.reduce((sum, h) => sum + h.cost, 0);
  const value = holdings.reduce((sum, h) => sum + h.value, 0);
  return (
    <section className="card" aria-labelledby="holdings">
      <div className="card-h">
        <h2 id="holdings">持仓</h2>
        {detail.advanced_through && <span className="aside">收盘价为 {detail.advanced_through} 的成交价格</span>}
      </div>
      {holdings.length === 0 ? (
        <div className="empty">没有持仓</div>
      ) : (
        <div className="scroll">
          <table aria-label="持仓">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th className="r">股数</th>
                <th>开仓日</th>
                <th className="r">成本（含费用）</th>
                <th className="r">收盘价</th>
                <th className="r">市值</th>
                <th className="r">浮动盈亏</th>
                <th className="r">盈亏比例</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const pnl = h.value - h.cost;
                return (
                  <tr key={h.code}>
                    <td>
                      <Link href={`/signals/${h.code}?strategy=${detail.strategy}`} className="code mono">
                        {displayCode(h.code)}
                      </Link>
                    </td>
                    <td>{h.name ?? ""}</td>
                    <td className="r">{h.quantity.toLocaleString("en-US")}</td>
                    <td className="num">{h.opened_on}</td>
                    <td className="r">{yen(h.cost)}</td>
                    <td className="r">{h.close.toLocaleString("en-US", { maximumFractionDigits: 1 })}</td>
                    <td className="r">{yen(h.value)}</td>
                    <td className={`r ${tone(pnl)}`}>{signedYen(pnl)}</td>
                    <td className={`r ${tone(pnl)}`}>{signedPercent(h.cost ? pnl / h.cost : null)}</td>
                  </tr>
                );
              })}
              <tr className="total">
                <td colSpan={4}>合计 {holdings.length} 只</td>
                <td className="r">{yen(cost)}</td>
                <td />
                <td className="r">{yen(value)}</td>
                <td className={`r ${tone(value - cost)}`}>{signedYen(value - cost)}</td>
                <td className={`r ${tone(value - cost)}`}>{signedPercent(cost ? (value - cost) / cost : null)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Pending({ detail }: { detail: Detail }) {
  return (
    <section className="card" aria-labelledby="pending">
      <div className="card-h">
        <h2 id="pending">明日订单</h2>
        <span className="aside">下一个开市日开盘执行</span>
      </div>
      {detail.pending.length === 0 ? (
        <div className="empty">
          <div>下一个开市日开盘没有要执行的订单</div>
          {detail.advanced_through && <div className="sub">{detail.advanced_through} 收盘后没有产生新的买卖</div>}
        </div>
      ) : (
        <div className="scroll">
          <table aria-label="明日订单">
            <thead>
              <tr>
                <th>执行日</th>
                <th>方向</th>
                <th>证券</th>
                <th className="r">计划股数</th>
                <th className="r">排序值</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              {detail.pending.map((o) => (
                <tr key={o.id ?? `${o.kind}-${o.code}`}>
                  <td className="num">{o.execution_date}</td>
                  <td className={o.kind === "buy" ? "up" : o.kind === "sell" ? "down" : ""}>
                    {ORDER_KINDS[o.kind] ?? o.kind}
                  </td>
                  <td>
                    <Security code={o.code} name={o.name} strategy={detail.strategy} />
                  </td>
                  <td className="r">{o.planned_quantity.toLocaleString("en-US")}</td>
                  <td className="r">{fixed(o.priority, 2)}</td>
                  <td>
                    <Reasons order={o} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** "2026-09-18 → 09-24": the execution date's year only when it differs. */
const dates = (order: Order) => {
  const sameYear = order.signal_date.slice(0, 4) === order.execution_date.slice(0, 4);
  return `${order.signal_date} → ${sameYear ? order.execution_date.slice(5) : order.execution_date}`;
};

function History({ id, strategy, version }: { id: number; strategy: string; version: number }) {
  const [group, setGroup] = useState<OrderGroup>("all");
  const [page, setPage] = useState(1);
  const [shown, setShown] = useState<OrdersPage | null>(null);

  useEffect(() => {
    let current = true;
    void (async () => {
      const { data } = await api.GET("/api/accounts/{account_id}/orders", {
        params: { path: { account_id: id }, query: { page, page_size: PAGE_SIZE, kind: group } },
      });
      if (current && data) setShown(data);
    })();
    return () => {
      current = false;
    };
  }, [id, group, page, version]);

  const pages = shown ? Math.max(1, Math.ceil(shown.total / PAGE_SIZE)) : 1;

  return (
    <section className="card" aria-labelledby="history">
      <div className="card-h">
        <h2 id="history">历史订单与账户事件</h2>
        {shown && (
          <div className="chips" role="group" aria-label="类别">
            {ORDER_GROUPS.map((g) => (
              <button key={g.kind} type="button" className="chip" aria-pressed={g.kind === group}
                      onClick={() => {
                        setGroup(g.kind);
                        setPage(1);
                      }}>
                {g.label} <span className="n">{shown.counts[g.kind] ?? 0}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {shown && shown.orders.length === 0 && <div className="empty">这一类还没有记录</div>}
      {shown && shown.orders.length > 0 && (
        <>
          <div className="scroll">
            <table aria-label="历史订单与账户事件">
              <thead>
                <tr>
                  <th>信号日 → 执行日</th>
                  <th>类别</th>
                  <th>证券</th>
                  <th>状态</th>
                  <th className="r">股数</th>
                  <th className="r">成交价</th>
                  <th className="r">现金变动</th>
                  <th>理由</th>
                </tr>
              </thead>
              <tbody>
                {shown.orders.map((o) => {
                  const status = ORDER_STATUSES[o.status] ?? { label: o.status, tone: "" };
                  return (
                    <tr key={o.id ?? `${o.kind}-${o.code}-${o.execution_date}`}>
                      <td className="num">{dates(o)}</td>
                      <td>{ORDER_KINDS[o.kind] ?? o.kind}</td>
                      <td>
                        <Security code={o.code} name={o.name} strategy={strategy} />
                      </td>
                      <td>
                        <span className={`badge ${status.tone}`}>{status.label}</span>
                        {o.outcome_reason && <span className="sub"> {outcome(o.outcome_reason)}</span>}
                      </td>
                      <td className="r">{(o.filled_quantity || o.planned_quantity).toLocaleString("en-US")}</td>
                      <td className="r">
                        {o.fill_price === null ? "—" : o.fill_price.toLocaleString("en-US", { minimumFractionDigits: 1 })}
                      </td>
                      <td className={`r ${tone(o.cash_delta)}`}>{o.cash_delta ? signedYen(o.cash_delta) : "—"}</td>
                      <td>
                        <Reasons order={o} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="foot">
            <span>{range(page, PAGE_SIZE, shown.total, "条")} · 每页 {PAGE_SIZE} 条 · 最新在前</span>
            <Pager page={page} pages={pages} onPage={setPage} />
          </div>
        </>
      )}
    </section>
  );
}
