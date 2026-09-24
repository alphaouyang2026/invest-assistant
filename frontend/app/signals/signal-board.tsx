"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { DEFAULT_STRATEGY, STRATEGIES, type StrategyName, market, reason } from "@/lib/labels";

type Signals = Schemas["SignalsOut"];
type Instrument = Schemas["InstrumentOut"];

export function SignalBoard() {
  const [strategy, setStrategy] = useState<StrategyName>(DEFAULT_STRATEGY);
  const [date, setDate] = useState<string | null>(null); // null: the latest session
  const [signals, setSignals] = useState<Signals | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Instrument[] | null>(null);

  const search = async () => {
    if (!query.trim()) return;
    const { data, error: failed } = await api.GET("/api/instruments", { params: { query: { q: query.trim() } } });
    if (failed) {
      setError("搜索失败");
      return;
    }
    setFound(data);
  };

  useEffect(() => {
    let current = true;
    void (async () => {
      const params = date ? { strategy, date } : { strategy };
      const { data, error: failed } = await api.GET("/api/signals", { params: { query: params } });
      if (!current) return;
      if (failed) {
        setError(typeof failed.detail === "string" ? failed.detail : "读取入场候选失败");
        return;
      }
      setError(null);
      setSignals(data);
    })();
    return () => {
      current = false;
    };
  }, [strategy, date]);

  return (
    <section>
      <h1>信号</h1>
      {error && <p role="alert">{error}</p>}

      <form className="controls" onSubmit={(event) => event.preventDefault()}>
        <label>
          策略
          <select value={strategy} onChange={(event) => setStrategy(event.target.value as StrategyName)}>
            {STRATEGIES.map((s) => (
              <option key={s.name} value={s.name}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          日期
          <input
            type="date"
            value={date ?? signals?.date ?? ""}
            onChange={(event) => setDate(event.target.value || null)}
          />
        </label>
      </form>

      <form
        className="controls"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <label>
          搜索证券
          <input value={query} placeholder="代码或名称" onChange={(event) => setQuery(event.target.value)} />
        </label>
        <button type="submit">搜索</button>
      </form>
      {found && (
        <ul aria-label="搜索结果">
          {found.map((i) => (
            <li key={i.code}>
              <Link href={`/signals/${i.code}?strategy=${strategy}`}>
                {i.code} {i.name}
              </Link>{" "}
              {market(i.market)}
            </li>
          ))}
          {found.length === 0 && <li>没有找到</li>}
        </ul>
      )}

      {signals && (
        <table aria-label="入场候选">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>市场</th>
              <th>排序值</th>
              <th>理由</th>
            </tr>
          </thead>
          <tbody>
            {signals.candidates.map((c) => (
              <tr key={c.code}>
                <td>
                  <Link href={`/signals/${c.code}?strategy=${strategy}`}>{c.code}</Link>
                </td>
                <td>{c.name}</td>
                <td>{market(c.market)}</td>
                <td>{c.priority === null ? "" : c.priority.toFixed(2)}</td>
                <td>{c.reason_codes.map(reason).join("；")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {signals && signals.candidates.length === 0 && <p>这一天没有入场候选。</p>}
    </section>
  );
}
