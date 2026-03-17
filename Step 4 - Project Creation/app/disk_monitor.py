import os
import shutil
import logging

from app.config import DB_PATH
from app.database import get_db, get_config

logger = logging.getLogger("sqh.disk")


def get_disk_usage() -> dict:
    """Return disk usage stats for the partition containing the database."""
    db_dir = os.path.dirname(DB_PATH) or "/"
    try:
        usage = shutil.disk_usage(db_dir)
    except OSError:
        usage = shutil.disk_usage("/")

    total_gb = round(usage.total / (1024 ** 3), 1)
    used_gb = round(usage.used / (1024 ** 3), 1)
    free_gb = round(usage.free / (1024 ** 3), 1)
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0
    threshold = int(get_config("disk_cleanup_threshold") or 70)
    threshold_gb = round(total_gb * threshold / 100, 1)
    until_cleanup = round(threshold_gb - used_gb, 1)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "percent": percent,
        "threshold": threshold,
        "threshold_gb": threshold_gb,
        "until_cleanup_gb": max(until_cleanup, 0),
        "needs_cleanup": percent >= threshold,
    }


def get_storage_breakdown() -> list[dict]:
    """Return a breakdown of storage consumption."""
    result_size = 0
    db_size = 0
    try:
        if os.path.exists(DB_PATH):
            db_size = os.path.getsize(DB_PATH)
    except OSError:
        pass

    with get_db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) as total FROM query_results").fetchone()
        result_size = row["total"]

    return [
        {"label": "Query Results Data", "bytes": result_size},
        {"label": "SQLite Database", "bytes": db_size},
    ]


def run_fifo_cleanup():
    """Delete oldest query results until disk usage drops below threshold."""
    disk = get_disk_usage()
    if not disk["needs_cleanup"]:
        return 0

    logger.warning(
        "Disk at %.1f%% (threshold %d%%) — starting FIFO cleanup",
        disk["percent"], disk["threshold"],
    )
    deleted = 0

    with get_db() as conn:
        rows = conn.execute(
            "SELECT qr.id, qr.history_id, qr.size_bytes "
            "FROM query_results qr "
            "JOIN query_history qh ON qr.history_id = qh.id "
            "ORDER BY qr.created_at ASC"
        ).fetchall()

        for row in rows:
            conn.execute("DELETE FROM query_results WHERE id = ?", (row["id"],))
            deleted += 1
            logger.info("FIFO deleted result id=%d (history_id=%d, %d bytes)", row["id"], row["history_id"], row["size_bytes"])

            current = get_disk_usage()
            if not current["needs_cleanup"]:
                break

    logger.info("FIFO cleanup complete — deleted %d result sets", deleted)
    return deleted


def run_retention_cleanup():
    """Delete query results older than the configured retention period."""
    retention_days = int(get_config("retention_days") or 0)
    if retention_days <= 0:
        return 0

    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM query_results WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        if result.rowcount > 0:
            logger.info("Retention cleanup: deleted %d result sets older than %d days", result.rowcount, retention_days)
        return result.rowcount
