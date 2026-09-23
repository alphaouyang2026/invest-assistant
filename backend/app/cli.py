"""Command line.

    python -m app.cli sync     # the sync the service runs, in the foreground

The first five-year backfill takes about 40 minutes; running it here shows
progress in the terminal. It takes the same `var/job.lock` as the service,
and refuses to start while the service holds it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date

from app.config import Settings
from app.jobs import JobsBusy, run_now
from app.log import configure_logging
from app.market_data.jquants import JQuantsClient
from app.runtime import build_market, sync_job


def main(
    argv: Sequence[str] | None = None,
    *,
    client: JQuantsClient | None = None,
    today: Callable[[], date] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="同步 J-Quants 行情（库为空时回填 5 年）")
    parser.parse_args(argv)

    settings = Settings()
    market = build_market(settings, client=client, today=today)

    def show(progress: dict) -> None:
        print(f"{progress['current_session']}  {progress['sessions_done']}/{progress['sessions_total']}", flush=True)

    try:
        result = run_now(sync_job(market), settings.runtime_dir, progress=show)
    except JobsBusy as busy:
        print(busy, file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"警告：{warning}")
    if result.status == "failed":
        print(f"同步失败：{result.error}", file=sys.stderr)
        return 1
    summary = result.summary
    if summary["first_session"] is None:
        print(f"完成：没有新的开市日可同步，写入 {summary['rows_written']} 行")
    else:
        print(f"完成：{summary['first_session']} → {summary['last_session']}，写入 {summary['rows_written']} 行")
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
