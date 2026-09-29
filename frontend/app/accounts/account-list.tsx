"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { signedPercent, tone } from "@/lib/format";
import { ACCOUNT_STATUSES, strategyLabel } from "@/lib/labels";

type Summary = Schemas["AccountSummaryOut"];

export function StatusBadge({ status }: { status: string }) {
  const shown = ACCOUNT_STATUSES[status] ?? { label: status, tone: "" };
  return (
    <span className={`badge ${shown.tone}`}>
      {shown.tone === "ok" && <span className="dot" />}
      {shown.label}
    </span>
  );
}

/** A drawdown is a fall: shown with a minus, in the losses' colour. */
export const drawdown = (value: number | null | undefined) => signedPercent(value ? -value : value);

export function AccountList() {
  const [accounts, setAccounts] = useState<Summary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const { data, error: failed } = await api.GET("/api/accounts");
      if (failed) setError("读取账户失败，请确认后端服务在运行");
      else setAccounts(data);
    })();
  }, []);

  return (
    <section className="page">
      <div className="head">
        <div>
          <h1>模拟账户</h1>
          <div className="meta">
            <span>回测与模拟交易是同一个账户：从起始日推进到今天，之后随每日同步继续推进</span>
          </div>
        </div>
        <div className="actions">
          <Link href="/accounts/new" className="btn primary">
            新建账户
          </Link>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      {accounts && (
        <div className="card">
          {accounts.length === 0 ? (
            <div className="empty">
              <div>还没有模拟账户</div>
              <div className="sub">新建一个，选好策略和起始日，就会从起始日开始回测</div>
            </div>
          ) : (
            <>
              <div className="scroll">
                <table aria-label="模拟账户">
                  <thead>
                    <tr>
                      <th>账户</th>
                      <th>起始日</th>
                      <th>推进到</th>
                      <th className="r">总收益</th>
                      <th className="r">年化</th>
                      <th className="r">最大回撤</th>
                      <th className="r">相对 TOPIX</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accounts.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <Link href={`/accounts/${a.id}`} className="code strong">
                            {a.name}
                          </Link>
                          <div className="sub">{strategyLabel(a.strategy)}</div>
                          {a.strategy === "technical_rating_v1" && (
                            <Link href={`/accounts/research?source=${a.id}`} className="code">回测此策略</Link>
                          )}
                        </td>
                        <td className="num">{a.start_date}</td>
                        <td className="num">{a.advanced_through ?? <span className="sub">尚未推进</span>}</td>
                        <td className={`r ${tone(a.total_return)}`}>{signedPercent(a.total_return)}</td>
                        <td className={`r ${tone(a.annualised_return)}`}>{signedPercent(a.annualised_return)}</td>
                        <td className={`r ${a.max_drawdown ? "down" : ""}`}>{drawdown(a.max_drawdown)}</td>
                        <td className={`r ${tone(a.excess_annualised_return)}`}>
                          {signedPercent(a.excess_annualised_return)}
                        </td>
                        <td>
                          <StatusBadge status={a.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="foot">
                <span>{accounts.length} 个账户 · 收益不含分红、不含税</span>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
