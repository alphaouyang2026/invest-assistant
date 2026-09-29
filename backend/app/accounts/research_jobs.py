"""How the research services accept work and what every record carries.

Runs, batches and discoveries are each accepted as one job under the shared
writer lock, idempotently on the client's request key, and stored with a
timestamp, JSON-ready values and the code version that produced them.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, Table, select

from app.jobs import Job, Jobs, JobsBusy

RunStatus = Literal["queued", "running", "completed", "failed"]
QUEUED: RunStatus = "queued"
RUNNING: RunStatus = "running"
COMPLETED: RunStatus = "completed"
FAILED: RunStatus = "failed"
UNFINISHED: tuple[RunStatus, ...] = (QUEUED, RUNNING)

KEY_REUSED = "请求标识已用于不同参数，请重新提交"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plain_json(value: Any) -> Any:
    """`value` as it will read back from a JSON column; ValueError on NaN or infinity."""
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def code_version() -> str:
    """Every application source file and the dependency lock, hashed."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    lock = root.parent / "uv.lock"
    if lock.exists():
        digest.update(lock.read_bytes())
    return "sha256:" + digest.hexdigest()


def find_request(engine: Engine, table: Table, key: str, request: Any) -> str | None:
    """The id `table` already holds for `key`, or None. The same key with a
    different request is refused rather than answered with the old id."""
    with engine.connect() as con:
        row = con.execute(select(table.c.id, table.c.request).where(table.c.request_key == key)).one_or_none()
    if row is None:
        return None
    if row.request != request:
        raise ValueError(KEY_REUSED)
    return row.id


class _AlreadyAccepted(Exception):
    def __init__(self, found: str) -> None:
        self.found = found


def submit_once(jobs: Jobs, job: Job, *, prepare: Callable[[], None], find: Callable[[], str | None],
                new_id: str) -> str:
    """Accept `job` as `new_id`, unless `find` returns what this request key
    was already accepted as. `find` is asked before, again under the writer
    lock and again after a busy refusal, so the same request sent twice at
    once gets one id — never a second record, a 409 or a duplicate-key error."""
    if (found := find()) is not None:
        return found

    def guarded() -> None:
        if (found := find()) is not None:
            raise _AlreadyAccepted(found)
        prepare()

    try:
        jobs.submit(job, prepare=guarded)
    except _AlreadyAccepted as already:
        return already.found
    except JobsBusy:
        if (found := find()) is not None:
            return found
        raise
    return new_id
