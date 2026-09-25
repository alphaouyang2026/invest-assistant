"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { percent, strategyLabel } from "@/lib/labels";

type Summary = Schemas["AccountSummaryOut"];

export const STATUS_LABELS: Record<string, string> = { active: "运行中", stopped: "已停用" };

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
    <section>
      <h1>账户</h1>
      <p>
        <Link href="/accounts/new">新建账户</Link>
      </p>
      {error && <p role="alert">{error}</p>}
      {accounts && accounts.length === 0 && <p>还没有模拟账户。</p>}
      {accounts && accounts.length > 0 && (
        <table aria-label="模拟账户">
          <thead>
            <tr>
              <th>名称</th>
              <th>策略</th>
              <th>起始日</th>
              <th>推进到</th>
              <th>总收益</th>
              <th>最大回撤</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link href={`/accounts/${a.id}`}>{a.name}</Link>
                </td>
                <td>{strategyLabel(a.strategy)}</td>
                <td>{a.start_date}</td>
                <td>{a.advanced_through ?? "尚未推进"}</td>
                <td>{percent(a.total_return)}</td>
                <td>{percent(a.max_drawdown)}</td>
                <td>{STATUS_LABELS[a.status] ?? a.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
