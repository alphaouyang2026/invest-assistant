"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { displayCode } from "@/lib/format";

type Status = Schemas["DataStatus"];
type Quality = Schemas["DataQuality"];
type Current = Schemas["JobStatusOut"] | null;
type JobResult = Schemas["JobResultOut"];

const STATE_LABELS: Record<string, string> = {
  queued: "即将开始",
  running: "进行中",
};

const KIND_LABELS: Record<string, string> = {
  sync: "同步", advance: "推进账户", research: "指定区间回测",
  regime_discovery: "按市场形势查找区间", research_batch: "研究批次（逐段回测）",
};

const GAPS_SHOWN = 20;

const count = (n: number) => n.toLocaleString("en-US");
const minute = (iso: string) => iso.slice(0, 16).replace("T", " ");

export function DataCenter({ pollMs = 2000 }: { pollMs?: number }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [current, setCurrent] = useState<Current>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [s, q, c] = await Promise.all([
      api.GET("/api/data/status"),
      api.GET("/api/data/quality"),
      api.GET("/api/jobs/current"),
    ]);
    if (s.error || q.error || c.error) {
      setError("读取数据状态失败，请确认后端服务在运行");
      return;
    }
    setError(null);
    setStatus(s.data);
    setQuality(q.data);
    setCurrent(c.data ?? null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While a job is queued or running, watch it; when it is gone, the
  // status and quality it changed are read again.
  const watching = current !== null;
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(async () => {
      const { data } = await api.GET("/api/jobs/current");
      if (data) setCurrent(data);
      else void refresh();
    }, pollMs);
    return () => clearInterval(timer);
  }, [watching, pollMs, refresh]);

  const syncNow = async () => {
    const { error: refused } = await api.POST("/api/data/sync");
    if (refused) {
      // 409: a job is already running, here or in another process
      setError(refused.detail);
      return;
    }
    setError(null);
    const { data } = await api.GET("/api/jobs/current");
    setCurrent(data ?? null);
  };

  return (
    <section className="page">
      <div className="head">
        <div>
          <h1>数据</h1>
          <div className="meta">
            <span>日线行情来自 J-Quants；信号和账户都只用这里已经同步的数据</span>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="btn primary" onClick={syncNow} disabled={current !== null}>
            立即同步
          </button>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      {current && <CurrentJob job={current} />}

      <section className="card" aria-label="概况">
        <dl className="kpis three">
          <div className="kpi">
            <dt className="l">数据到</dt>
            <dd className="v">{status ? (status.latest_date ?? "尚无数据") : "…"}</dd>
          </div>
          <div className="kpi">
            <dt className="l">证券数</dt>
            <dd className="v">{status ? count(status.securities) : "…"}</dd>
          </div>
          <div className="kpi">
            <dt className="l">日线行数</dt>
            <dd className="v">{status ? count(status.bar_rows) : "…"}</dd>
          </div>
        </dl>
      </section>

      <section className="card" aria-labelledby="jobs">
        <div className="card-h">
          <h2 id="jobs">最近任务</h2>
        </div>
        {status && status.recent_jobs.length === 0 && <div className="empty">还没有运行过任务</div>}
        {status && status.recent_jobs.length > 0 && (
          <ul className="list">
            {status.recent_jobs.map((job) => <JobLine key={job.id} job={job} />)}
          </ul>
        )}
      </section>

      <section className="card" aria-labelledby="quality">
        <div className="card-h">
          <h2 id="quality">质量警告</h2>
          <span className="aside">每次打开时现算</span>
        </div>
        {quality && <QualityWarnings quality={quality} />}
      </section>
    </section>
  );
}

function CurrentJob({ job }: { job: NonNullable<Current> }) {
  const progress = job.progress as { sessions_done?: number; sessions_total?: number; current_session?: string } | null;
  const share = progress?.sessions_total ? (progress.sessions_done ?? 0) / progress.sessions_total : null;
  return (
    <div className="card card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <p style={{ margin: 0 }}>
        {KIND_LABELS[job.kind] ?? job.kind}{STATE_LABELS[job.state] ?? job.state}
        {progress?.sessions_total ? `：${progress.sessions_done} / ${progress.sessions_total} 个开市日（${progress.current_session}）` : ""}
      </p>
      {share !== null && (
        <div className="progress" aria-hidden="true">
          <i style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  );
}

function JobLine({ job }: { job: JobResult }) {
  const summary = job.summary as {
    first_session?: string | null;
    last_session?: string | null;
    rows_written?: number;
    not_published_yet?: boolean;
  };
  const range = summary.first_session ? `${summary.first_session} → ${summary.last_session}，` : "";
  const succeeded = job.status === "succeeded";
  return (
    <li>
      <p className="actions">
        <span className="num">{minute(job.finished_at)}</span>
        <span>{KIND_LABELS[job.kind] ?? job.kind}</span>
        <span className={succeeded ? "badge ok" : "badge down"}>{succeeded ? "成功" : "失败"}</span>
        {succeeded && job.kind === "sync" && <span className="sub">{range}写入 {count(summary.rows_written ?? 0)} 行</span>}
      </p>
      {job.error && <p className="down">错误：{job.error}</p>}
      {job.warnings.length > 0 && (
        <ul>
          {job.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function QualityWarnings({ quality }: { quality: Quality }) {
  const { missing_sessions, gaps, untradable_rows, untradable_on_latest } = quality;
  if (missing_sessions.length === 0 && gaps.length === 0 && untradable_rows === 0) {
    return <div className="empty">没有发现问题</div>;
  }
  return (
    <ul className="list">
      {missing_sessions.length > 0 && <li>全市场都没有日线的开市日：{missing_sessions.join("、")}</li>}
      {gaps.length > 0 && (
        <li>
          上市期间缺日线的证券 {gaps.length} 只：
          {gaps
            .slice(0, GAPS_SHOWN)
            .map((gap) => `${displayCode(gap.code)}（缺 ${gap.missing_sessions} 天）`)
            .join("、")}
          {gaps.length > GAPS_SHOWN ? " 等" : ""}
        </li>
      )}
      <li>
        不可交易（停牌等）的日线共 {count(untradable_rows)} 行，最新一日 {count(untradable_on_latest)} 行
      </li>
    </ul>
  );
}
