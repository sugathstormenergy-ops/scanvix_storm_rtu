"""
Storm Energy RTU Platform - Protocol Test Log retention (30 days by default).

purge_expired() deletes rows of dbo.ProtocolDiagnosticLogs whose ReceivedAt is older
than the retention window, in bounded batches. It is idempotent (re-running deletes
nothing more) and touches NO other table: the statement is built only from the
ProtocolDiagnosticLog model, and the SQL login is granted DELETE on that one table only
(database/006_protocol_diagnostics.sql), so even a coding error could not delete
telemetry or device data.

Runs as a background task inside storm-api (app.main), never in response to an API call.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import ProtocolDiagnosticLog
from app.timezone import now_ist

logger = logging.getLogger(__name__)

_TABLE = "ProtocolDiagnosticLogs"


def cutoff_for(now: datetime, retention_days: int) -> datetime:
    return now - timedelta(days=retention_days)


def purge_statement(cutoff: datetime, batch_size: int):
    ids = (select(ProtocolDiagnosticLog.Id)
           .where(ProtocolDiagnosticLog.ReceivedAt < cutoff)
           .order_by(ProtocolDiagnosticLog.Id)
           .limit(batch_size))
    stmt = delete(ProtocolDiagnosticLog).where(ProtocolDiagnosticLog.Id.in_(ids.scalar_subquery()))
    assert stmt.table.name == _TABLE, "retention may only delete from ProtocolDiagnosticLogs"
    return stmt


def purge_expired(db: Session, *, retention_days: int, batch_size: int,
                  now: Optional[datetime] = None, max_batches: int = 1000) -> int:
    """Delete diagnostic rows older than `retention_days`. Commits per batch. Returns rows deleted."""
    cutoff = cutoff_for(now or now_ist(), retention_days)
    total = 0
    for _ in range(max_batches):
        deleted = db.execute(purge_statement(cutoff, batch_size)).rowcount or 0
        db.commit()
        total += deleted
        if deleted < batch_size:
            break
    return total


def run_purge_once() -> int:
    from app.database.database import db_session
    s = get_settings()
    with db_session() as db:
        n = purge_expired(db, retention_days=s.DIAG_RETENTION_DAYS, batch_size=s.DIAG_PURGE_BATCH_SIZE)
    if n:
        logger.info("Protocol diagnostics retention: %d record(s) older than %d days deleted", n, s.DIAG_RETENTION_DAYS)
    return n


async def retention_loop(first_delay: float = 60.0) -> None:
    """Background task: purge shortly after startup, then every DIAG_PURGE_INTERVAL_SECONDS."""
    s = get_settings()
    loop = asyncio.get_running_loop()
    await asyncio.sleep(first_delay)
    while True:
        try:
            await loop.run_in_executor(None, run_purge_once)
        except Exception as exc:
            logger.warning("Protocol diagnostics retention run failed: %s", exc)
        await asyncio.sleep(s.DIAG_PURGE_INTERVAL_SECONDS)
