"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { ORDER_KINDS, ORDER_STATUSES, outcome, percent, reason, strategyLabel } from "@/lib/labels";

import { STATUS_LABELS } from "./account-list";
import { NavChart, type NavPoint } from "./nav-chart";

type Detail = Schemas["AccountDetailOut"];
type Order = Schemas["OrderOut"];

const yen = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : Math.round(value).toLocaleString("en-US");
const fixed = (value: number | null | undefined, digits: number) =>
  value === null || value === undefined ? "—" : value.toFixed(digits);
const reasons = (order: Order) => ((order.reason.reason_codes as string[] | undefined) ?? []).map(reason).join("；");

export function AccountDetail({ id, pollMs = 2000 }: { id: number; pollMs?: number }) {
  const router = useRouter();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [nav, setNav] = useState<NavPoint[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const path = { params: { path: { account_id: id } } };
    const [d, n, o, job] = await Promise.all([
      api.GET("/api/accounts/{account_id}", path),
      api.GET("/api/accounts/{account_id}/nav", path),
      api.GET("/api/accounts/{account_id}/orders", path),
      api.GET("/api/jobs/current"),
    ]);
    if (d.error || n.error || o.error) {
      setError(d.error && typeof d.error.detail === "string" ? d.error.detail : "读取账户失败");
      return;
    }
    setError(null);
    setDetail(d.data);
    setNav(n.data);
    setOrders(o.data);
    setRunning(Boolean(job.data));
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

  if (error) return <p role="alert">{error}</p>;
  if (!detail) return null;
  const f = detail.figures;

  return (
    <section>
      <p>
        <Link href="/accounts">← 账户</Link>
      </p>
      <h1>{detail.name}</h1>
      <p>
        {strategyLabel(detail.strategy)} · 起始 {detail.start_date} · 推进到 {detail.advanced_through ?? "尚未推进"} ·{" "}
        {STATUS_LABELS[detail.status] ?? detail.status}
      </p>
      {running && <p>后台任务进行中，完成后自动刷新。</p>}
      <p>
        {detail.status === "active" && (
          <button type="button" onClick={() => void stop()}>
            停用
          </button>
        )}{" "}
        <button type="button" onClick={() => void remove()}>
          删除
        </button>
      </p>

      <section aria-label="统计">
        <h2>统计</h2>
        <p>不含分红、不含税。</p>
        {f ? (
          <dl className="figures">
            <dt>总收益</dt>
            <dd>{percent(f.total_return)}</dd>
            <dt>年化收益</dt>
            <dd>{percent(f.annualised_return)}</dd>
            <dt>最大回撤</dt>
            <dd>{percent(f.max_drawdown)}</dd>
            <dt>夏普比率</dt>
            <dd>{fixed(f.sharpe, 2)}</dd>
            <dt>胜率</dt>
            <dd>{percent(f.win_rate)}</dd>
            <dt>平均持有交易日数</dt>
            <dd>{fixed(f.average_holding_sessions, 1)}</dd>
            <dt>年化换手率</dt>
            <dd>{fixed(f.annual_turnover, 2)}</dd>
            <dt>相对 TOPIX 超额年化</dt>
            <dd>{percent(f.excess_annualised_return)}</dd>
          </dl>
        ) : (
          <p>尚未推进，还没有统计。</p>
        )}
      </section>

      {nav.length > 0 && <NavChart points={nav} />}

      <h2>持仓</h2>
      <table aria-label="持仓">
        <thead>
          <tr>
            <th>代码</th>
            <th>股数</th>
            <th>开仓日</th>
            <th>成本</th>
            <th>收盘价</th>
            <th>市值</th>
          </tr>
        </thead>
        <tbody>
          {detail.holdings.map((h) => (
            <tr key={h.code}>
              <td>
                <Link href={`/signals/${h.code}?strategy=${detail.strategy}`}>{h.code}</Link>
              </td>
              <td>{h.quantity}</td>
              <td>{h.opened_on}</td>
              <td>{yen(h.cost)}</td>
              <td>{h.close}</td>
              <td>{yen(h.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>明日订单</h2>
      <table aria-label="明日订单">
        <thead>
          <tr>
            <th>执行日</th>
            <th>方向</th>
            <th>代码</th>
            <th>计划股数</th>
            <th>排序值</th>
            <th>理由</th>
          </tr>
        </thead>
        <tbody>
          {detail.pending.map((o) => (
            <tr key={o.id ?? `${o.kind}-${o.code}`}>
              <td>{o.execution_date}</td>
              <td>{ORDER_KINDS[o.kind] ?? o.kind}</td>
              <td>{o.code}</td>
              <td>{o.planned_quantity}</td>
              <td>{fixed(o.priority, 2)}</td>
              <td>{reasons(o)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>历史订单与账户事件</h2>
      <table aria-label="历史订单与账户事件">
        <thead>
          <tr>
            <th>信号日</th>
            <th>执行日</th>
            <th>类别</th>
            <th>代码</th>
            <th>状态</th>
            <th>原因</th>
            <th>股数</th>
            <th>成交价</th>
            <th>现金变动</th>
            <th>理由</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id ?? `${o.kind}-${o.code}-${o.execution_date}`}>
              <td>{o.signal_date}</td>
              <td>{o.execution_date}</td>
              <td>{ORDER_KINDS[o.kind] ?? o.kind}</td>
              <td>{o.code}</td>
              <td>{ORDER_STATUSES[o.status] ?? o.status}</td>
              <td>{outcome(o.outcome_reason)}</td>
              <td>{o.filled_quantity || o.planned_quantity}</td>
              <td>{o.fill_price ?? ""}</td>
              <td>{yen(o.cash_delta)}</td>
              <td>{reasons(o)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
