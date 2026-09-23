import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataCenter } from "@/app/data/data-center";

/**
 * A stand-in for the backend: answers the four data-page endpoints from
 * mutable state, so a test can move a job from running to finished.
 */
function fakeBackend() {
  const state = {
    status: { latest_date: null as string | null, securities: 0, bar_rows: 0, recent_jobs: [] as unknown[] },
    quality: { missing_sessions: [] as string[], gaps: [] as unknown[], untradable_rows: 0, untradable_on_latest: 0 },
    current: null as unknown,
    posts: 0,
    refuseSync: null as string | null,
  };
  const fetch = vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname;
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (input.method === "POST" && path === "/api/data/sync") {
      state.posts += 1;
      if (state.refuseSync) return json({ detail: state.refuseSync }, 409);
      state.current = { id: "job1", kind: "sync", state: "queued", submitted_at: "2026-09-24T18:00:00+09:00", started_at: null, progress: null };
      return json({ job_id: "job1" }, 202);
    }
    if (path === "/api/data/status") return json(state.status);
    if (path === "/api/data/quality") return json(state.quality);
    if (path === "/api/jobs/current") return json(state.current);
    return json({ detail: "not found" }, 404);
  });
  return { state, fetch };
}

const FINISHED_SYNC = {
  id: "job0",
  kind: "sync",
  status: "succeeded",
  started_at: "2026-09-24T18:00:00+09:00",
  finished_at: "2026-09-24T18:02:10+09:00",
  summary: { first_session: "2026-09-24", last_session: "2026-09-24", rows_written: 4210, not_published_yet: false },
  warnings: ["2026-09-22 是开市日，但 J-Quants 没有返回日线"],
  error: null,
};

let backend: ReturnType<typeof fakeBackend>;

beforeEach(() => {
  backend = fakeBackend();
  vi.stubGlobal("fetch", backend.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("数据页", () => {
  it("显示数据到哪一天、证券数、行数，最近任务结果与警告", async () => {
    backend.state.status = { latest_date: "2026-09-24", securities: 4210, bar_rows: 5123456, recent_jobs: [FINISHED_SYNC] };

    render(<DataCenter pollMs={10} />);

    expect(await screen.findByText("2026-09-24", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("4,210")).toBeInTheDocument();
    expect(screen.getByText("5,123,456")).toBeInTheDocument();
    const jobs = screen.getByRole("region", { name: "最近任务" });
    expect(within(jobs).getByText(/成功/)).toBeInTheDocument();
    expect(within(jobs).getByText(/写入 4,210 行/)).toBeInTheDocument();
    expect(within(jobs).getByText("2026-09-22 是开市日，但 J-Quants 没有返回日线")).toBeInTheDocument();
  });

  it("显示现算的质量警告", async () => {
    backend.state.quality = {
      missing_sessions: ["2026-09-22"],
      gaps: [{ code: "13020", missing_sessions: 3 }],
      untradable_rows: 17,
      untradable_on_latest: 2,
    };

    render(<DataCenter pollMs={10} />);

    const quality = await screen.findByRole("region", { name: "质量警告" });
    expect(within(quality).getByText(/2026-09-22/)).toBeInTheDocument();
    expect(within(quality).getByText(/13020/)).toBeInTheDocument();
    expect(within(quality).getByText(/不可交易.*17/)).toBeInTheDocument();
  });

  it("点「立即同步」排入同步，显示进度，结束后刷新", async () => {
    render(<DataCenter pollMs={10} />);
    const button = await screen.findByRole("button", { name: "立即同步" });

    await userEvent.click(button);
    expect(backend.state.posts).toBe(1);

    backend.state.current = {
      id: "job1", kind: "sync", state: "running", submitted_at: "2026-09-24T18:00:00+09:00",
      started_at: "2026-09-24T18:00:01+09:00",
      progress: { sessions_done: 3, sessions_total: 10, current_session: "2026-09-18" },
    };
    expect(await screen.findByText(/3 \/ 10/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即同步" })).toBeDisabled();

    backend.state.status = { latest_date: "2026-09-24", securities: 1, bar_rows: 1, recent_jobs: [FINISHED_SYNC] };
    backend.state.current = null;
    expect(await screen.findByText("2026-09-24", { selector: "dd" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "立即同步" })).toBeEnabled());
  });

  it("已有任务在运行时，「立即同步」被拒，并显示原因", async () => {
    backend.state.refuseSync = "另一个任务正在运行（var/job.lock 已被占用），请稍后再试";
    render(<DataCenter pollMs={10} />);

    await userEvent.click(await screen.findByRole("button", { name: "立即同步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("另一个任务正在运行（var/job.lock 已被占用），请稍后再试");
    expect(screen.getByRole("button", { name: "立即同步" })).toBeEnabled();
  });
});
