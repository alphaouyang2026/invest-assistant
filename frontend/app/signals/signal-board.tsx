"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { displayCode } from "@/lib/format";
import { DEFAULT_STRATEGY, STRATEGIES, type StrategyName, market, reason, reasonTone } from "@/lib/labels";

import { Pager, range } from "../pager";

type Signals = Schemas["SignalsOut"];
type Instrument = Schemas["InstrumentOut"];

const PAGE_SIZE = 50;

export function StrategySwitch({ value, onChange }: { value: StrategyName; onChange: (name: StrategyName) => void }) {
  return (
    <div className="seg" role="group" aria-label="策略">
      {STRATEGIES.map((s) => (
        <button key={s.name} type="button" aria-pressed={s.name === value} onClick={() => onChange(s.name)}>
          {s.label}
        </button>
      ))}
    </div>
  );
}

export function SignalBoard() {
  const id = useId();
  const [strategy, setStrategy] = useState<StrategyName>(DEFAULT_STRATEGY);
  const [date, setDate] = useState<string | null>(null); // null: the latest session
  const [signals, setSignals] = useState<Signals | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Instrument[] | null>(null);
  const [pools, setPools] = useState<Record<string, string[]>>({});

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
      setPage(1);
    })();
    return () => {
      current = false;
    };
  }, [strategy, date]);

  // The codes each strategy's universe rule names: a strategy that buys
  // only 1306, with no candidate, is saying it would not buy 1306.
  useEffect(() => {
    void (async () => {
      const { data } = await api.GET("/api/strategies");
      if (Array.isArray(data)) setPools(Object.fromEntries(data.map((s) => [s.name, s.pool_codes])));
    })();
  }, []);

  const candidates = signals?.candidates ?? [];
  const [only] = pools[strategy] ?? [];
  const pages = Math.max(1, Math.ceil(candidates.length / PAGE_SIZE));
  const shown = candidates.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <section className="page">
      <div>
        <h1>入场候选</h1>
        <div className="meta">
          <span>每个交易日收盘后，从股票池里找出按策略可以买入的证券，下一个开市日开盘才会成交</span>
        </div>
      </div>

      <section className="card" aria-label="条件">
        <div className="toolbar">
          <div className="field">
            <span className="label">策略</span>
            <StrategySwitch value={strategy} onChange={setStrategy} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-date`}>收盘日</label>
            <input id={`${id}-date`} className="input" type="date" style={{ width: 170 }}
                   value={date ?? signals?.date ?? ""} onChange={(event) => setDate(event.target.value || null)} />
          </div>
          <form
            className="field search"
            onSubmit={(event) => {
              event.preventDefault();
              void search();
            }}
          >
            <label htmlFor={`${id}-q`}>查证券</label>
            <div className="affix">
              <input id={`${id}-q`} className="input" value={query} placeholder="代码或名称，例如 7203 或 トヨタ"
                     onChange={(event) => setQuery(event.target.value)} />
              <button type="submit" className="btn">
                搜索
              </button>
            </div>
          </form>
        </div>
        {found && (
          <ul className="results" aria-label="搜索结果">
            {found.map((i) => (
              <li key={i.code}>
                <Link href={`/signals/${i.code}?strategy=${strategy}`} className="code">
                  <span className="mono">{displayCode(i.code)}</span> {i.name}
                </Link>
                <span className="badge">{market(i.market)}</span>
              </li>
            ))}
            {found.length === 0 && <li className="sub">没有找到</li>}
          </ul>
        )}
      </section>

      {error && <p role="alert">{error}</p>}

      {signals && (
        <section className="card" aria-labelledby="candidates">
          <div className="card-h">
            <h2 id="candidates">{candidates.length} 只入场候选</h2>
            <span className="aside">{signals.date} 收盘 · 按排序值从高到低</span>
          </div>
          {candidates.length === 0 && only ? (
            <div className="empty">
              {/* Seen from holding nothing, as every candidate is: an account
                  already holding it may well keep it. */}
              <span>空仓的话，{date ? "这一天" : "今天"}收盘后不会买入 {displayCode(only)}</span>
              <Link href={`/signals/${only}?strategy=${strategy}`}>看 {displayCode(only)} 的详情</Link>
            </div>
          ) : candidates.length === 0 ? (
            <div className="empty">这一天没有入场候选</div>
          ) : (
            <>
              <div className="scroll">
                <table aria-label="入场候选">
                  <thead>
                    <tr>
                      <th className="r">#</th>
                      <th>代码</th>
                      <th>名称</th>
                      <th>市场</th>
                      <th className="r">排序值</th>
                      <th>理由</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((c, n) => (
                      <tr key={c.code}>
                        <td className="r sub">{(page - 1) * PAGE_SIZE + n + 1}</td>
                        <td>
                          <Link href={`/signals/${c.code}?strategy=${strategy}`} className="code mono">
                            {displayCode(c.code)}
                          </Link>
                        </td>
                        <td>{c.name}</td>
                        <td>
                          <span className="badge">{market(c.market)}</span>
                        </td>
                        <td className="r">
                          {c.priority === null ? "" : c.priority.toFixed(2)}
                          {c.priority !== null && (
                            <span className="bar" aria-hidden="true">
                              <i style={{ width: `${Math.max(0, Math.min(1, c.priority)) * 100}%` }} />
                            </span>
                          )}
                        </td>
                        <td className="wrap">
                          <span className="badges">
                            {c.reason_codes.map((code) => (
                              <span key={code} className={`badge ${reasonTone(code)}`}>
                                {reason(code)}
                              </span>
                            ))}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="foot">
                <span>{range(page, PAGE_SIZE, candidates.length, "只")} · 每页 {PAGE_SIZE} 只</span>
                <Pager page={page} pages={pages} onPage={setPage} />
              </div>
            </>
          )}
        </section>
      )}
    </section>
  );
}
