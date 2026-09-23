"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";

type Status = Schemas["DataStatus"];
type Quality = Schemas["DataQuality"];
type Current = Schemas["JobStatusOut"] | null;
type JobResult = Schemas["JobResultOut"];

const STATE_LABELS: Record<string, string> = {
  queued: "即将开始",
  running: "进行中",
};

const KIND_LABELS: Record<string, string> = { sync: "同步" };

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
    <section>
      <h1>数据</h1>
      {error && <p role="alert">{error}</p>}

      <dl className="figures">
        <dt>数据到</dt>
        <dd>{status?.latest_date ?? "尚无数据"}</dd>
        <dt>证券数</dt>
        <dd>{count(status?.securities ?? 0)}</dd>
        <dt>日线行数</dt>
        <dd>{count(status?.bar_rows ?? 0)}</dd>
      </dl>

      <p>
        <button type="button" onClick={syncNow} disabled={current !== null}>
          立即同步
        </button>
      </p>
      {current && <CurrentJob job={current} />}

      <section aria-label="最近任务">
        <h2>最近任务</h2>
        {status && status.recent_jobs.length === 0 && <p>还没有运行过任务。</p>}
        <ul>
          {status?.recent_jobs.map((job) => <JobLine key={job.id} job={job} />)}
        </ul>
      </section>

      <section aria-label="质量警告">
        <h2>质量警告</h2>
        {quality && <QualityWarnings quality={quality} />}
      </section>
    </section>
  );
}

function CurrentJob({ job }: { job: NonNullable<Current> }) {
  const progress = job.progress as { sessions_done?: number; sessions_total?: number; current_session?: string } | null;
  return (
    <p>
      {KIND_LABELS[job.kind] ?? job.kind}{STATE_LABELS[job.state] ?? job.state}
      {progress?.sessions_total ? `：${progress.sessions_done} / ${progress.sessions_total} 个开市日（${progress.current_session}）` : ""}
    </p>
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
  return (
    <li>
      <p>
        {minute(job.finished_at)} {KIND_LABELS[job.kind] ?? job.kind} · {job.status === "succeeded" ? "成功" : "失败"}
        {job.status === "succeeded" && ` · ${range}写入 ${count(summary.rows_written ?? 0)} 行`}
      </p>
      {job.error && <p>错误：{job.error}</p>}
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
    return <p>没有发现问题。</p>;
  }
  return (
    <ul>
      {missing_sessions.length > 0 && <li>全市场都没有日线的开市日：{missing_sessions.join("、")}</li>}
      {gaps.length > 0 && (
        <li>
          上市期间缺日线的证券 {gaps.length} 只：
          {gaps.slice(0, GAPS_SHOWN).map((gap) => `${gap.code}（缺 ${gap.missing_sessions} 天）`).join("、")}
          {gaps.length > GAPS_SHOWN ? " 等" : ""}
        </li>
      )}
      <li>
        不可交易（停牌等）的日线共 {count(untradable_rows)} 行，最新一日 {count(untradable_on_latest)} 行
      </li>
    </ul>
  );
}
