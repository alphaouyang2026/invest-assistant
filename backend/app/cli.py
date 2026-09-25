"""Command line.

    python -m app.cli sync                  # the sync the service runs, in the foreground
    python -m app.cli advance [--account ID]  # one account, or every active one

The first five-year backfill takes about 40 minutes; running it here shows
progress in the terminal. It takes the same `var/job.lock` as the service,
and refuses to start while the service holds it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from app.config import Settings
from app.jobs import JobsBusy, run_now
from app.log import configure_logging
from app.market_data.jquants import JQuantsClient
from app.runtime import advance_job, build_accounts, build_market, sync_job
from app.strategies import Strategy


def main(
    argv: Sequence[str] | None = None,
    *,
    client: JQuantsClient | None = None,
    today: Callable[[], date] | None = None,
    build_strategy: Callable[[str, Mapping[str, Any]], Strategy] | None = None,
) -> int:
    """`client`, `today` and `build_strategy` are for tests."""
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="同步 J-Quants 行情（库为空时回填 5 年）")
    advance = commands.add_parser("advance", help="把模拟账户推进到最新交易日")
    advance.add_argument("--account", type=int, help="账户 ID；不给则推进所有 active 账户")
    args = parser.parse_args(argv)

    settings = Settings()
    market = build_market(settings, client=client, today=today)
    if args.command == "advance":
        return _advance(settings, build_accounts(settings, market, strategies=build_strategy), args.account)

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


def _advance(settings: Settings, accounts, account_id: int | None) -> int:
    def show(progress: dict) -> None:
        print(f"推进 {progress['account']}（{progress['accounts_done'] + 1}/{progress['accounts_total']}）", flush=True)

    try:
        result = run_now(advance_job(accounts, account_id), settings.runtime_dir, progress=show)
    except JobsBusy as busy:
        print(busy, file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"警告：{warning}")
    if result.status == "failed":
        print(f"推进失败：{result.error}", file=sys.stderr)
        return 1
    for account in result.summary["accounts"]:
        print(f"完成：{account['name']} 推进了 {account['sessions']} 个交易日，到 {account['through'] or '（已是最新）'}")
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
