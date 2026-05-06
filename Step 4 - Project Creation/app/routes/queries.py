import json
import gzip
import time
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.auth import require_auth
from app.s1_client import run_dv_query, cancel_query, is_cancelled, clear_cancelled, get_progress
from app.disk_monitor import run_fifo_cleanup
from app.models import RunQueryRequest
from app.fast_json import dumps as fj_dumps, dumps_str as fj_dumps_str

logger = logging.getLogger("sqh.routes.queries")
router = APIRouter(prefix="/api/queries", tags=["queries"])

_running_tasks: dict[int, asyncio.Task] = {}
CACHE_MAX_AGE_SECONDS = 300  # Serve cached results if same query ran within 5 minutes


def _build_query_dict(row, conn) -> dict:
    params = conn.execute(
        "SELECT name, label, param_type, placeholder, options, sort_order "
        "FROM query_params WHERE query_id = ? ORDER BY sort_order",
        (row["id"],),
    ).fetchall()
    folder_id = None
    try:
        folder_id = row["folder_id"]
    except (IndexError, KeyError):
        pass
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "dv_query": row["dv_query"],
        "folder_id": folder_id,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "modified_at": row["modified_at"],
        "params": [
            {
                "name": p["name"],
                "label": p["label"],
                "param_type": p["param_type"],
                "placeholder": p["placeholder"],
                "options": json.loads(p["options"]) if p["options"] else None,
                "sort_order": p["sort_order"],
            }
            for p in params
        ],
    }


@router.get("")
async def list_queries(request: Request):
    await require_auth(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sq.*, u.username as creator_name, qf.name as folder_name "
            "FROM stored_queries sq "
            "LEFT JOIN users u ON sq.created_by = u.id "
            "LEFT JOIN query_folders qf ON sq.folder_id = qf.id "
            "ORDER BY qf.sort_order, qf.name, sq.category, sq.name"
        ).fetchall()
        queries = []
        for r in rows:
            q = _build_query_dict(r, conn)
            q["creator_name"] = r["creator_name"]
            q["folder_name"] = r["folder_name"]
            queries.append(q)
        folders = conn.execute(
            "SELECT id, name, parent_id, sort_order FROM query_folders ORDER BY sort_order, name"
        ).fetchall()
    return {"queries": queries, "folders": [dict(f) for f in folders]}


@router.get("/running")
async def list_running_queries(request: Request):
    user = await require_auth(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, query_name, category, executed_at FROM query_history "
            "WHERE user_id = ? AND status = 'running' ORDER BY executed_at DESC",
            (user["id"],),
        ).fetchall()
    return {"running": [dict(r) for r in rows]}


@router.get("/{query_id}")
async def get_query(query_id: int, request: Request):
    await require_auth(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM stored_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")
        return {"query": _build_query_dict(row, conn)}


def _is_ai_dashboard_query(name: str) -> bool:
    n = (name or "").lower()
    return ("ai" in n and "detect" in n) or "ai tool" in n or "ai usage" in n


def _find_cached_result(conn, stored_query_id: int, params_json: str):
    """Check if a recent successful run with actual results exists within the cache window.
    Never caches empty results (0 events) — those always trigger a fresh S1 query."""
    row = conn.execute(
        """SELECT qh.id, qh.result_count, qr.result_data, qr.size_bytes
           FROM query_history qh
           JOIN query_results qr ON qr.history_id = qh.id
           WHERE qh.stored_query_id = ?
             AND qh.status = 'success'
             AND qh.result_count > 0
             AND qh.params_json = ?
             AND qh.executed_at > datetime('now', ?)
           ORDER BY qh.executed_at DESC LIMIT 1""",
        (stored_query_id, params_json, f"-{CACHE_MAX_AGE_SECONDS} seconds"),
    ).fetchone()
    return row


async def _execute_in_background(history_id: int, dv_query: str, query_name: str, username: str,
                                  from_date: str = "", to_date: str = "",
                                  stored_query_id: int = 0, params_json: str = "{}",
                                  force_refresh: bool = False):
    """Run the S1 DV query and update the history entry when done.
    If a fresh cached result exists (within CACHE_MAX_AGE_SECONDS), reuse it instantly."""
    logger.info("User %s executing query '%s' (history_id=%d)", username, query_name, history_id)
    dedup = _is_ai_dashboard_query(query_name)
    t0 = time.time()
    try:
        # Check cache first (unless force_refresh)
        if not force_refresh and stored_query_id:
            with get_db() as conn:
                cached = _find_cached_result(conn, stored_query_id, params_json)
            if cached:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE query_history SET status = 'success', result_count = ? WHERE id = ?",
                        (cached["result_count"], history_id),
                    )
                    conn.execute(
                        "INSERT INTO query_results (history_id, result_data, size_bytes) VALUES (?, ?, ?)",
                        (history_id, cached["result_data"], cached["size_bytes"]),
                    )
                logger.info("Cache hit: reused history_id=%d for '%s' (%d results, %.2fs)",
                             cached["id"], query_name, cached["result_count"], time.time() - t0)
                return

        async def _save_live(events_so_far):
            """Save results incrementally so the frontend can display them live."""
            partial_bytes = fj_dumps(events_so_far)
            partial_gz = gzip.compress(partial_bytes, compresslevel=1)
            with get_db() as conn:
                conn.execute(
                    "UPDATE query_history SET result_count = ? WHERE id = ?",
                    (len(events_so_far), history_id),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO query_results (history_id, result_data, size_bytes) VALUES (?, ?, ?)",
                    (history_id, partial_gz, len(partial_bytes)),
                )

        result = await run_dv_query(dv_query, from_date=from_date, to_date=to_date, history_id=history_id, deduplicate=dedup, on_first_page=_save_live)
        elapsed = round(time.time() - t0, 2)
        data = result.get("data", [])
        result_count = result.get("count", 0)

        t_save = time.time()
        raw_bytes = fj_dumps(data)
        compressed = gzip.compress(raw_bytes, compresslevel=1)

        run_fifo_cleanup()

        with get_db() as conn:
            conn.execute(
                "UPDATE query_history SET status = 'success', result_count = ? WHERE id = ?",
                (result_count, history_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO query_results (history_id, result_data, size_bytes) VALUES (?, ?, ?)",
                (history_id, compressed, len(raw_bytes)),
            )
        logger.info("Query complete: %d results in %ss, saved in %ss (history_id=%d, raw=%dKB, gz=%dKB)",
                     result_count, elapsed, round(time.time() - t_save, 2), history_id,
                     len(raw_bytes) // 1024, len(compressed) // 1024)

    except asyncio.CancelledError:
        with get_db() as conn:
            conn.execute(
                "UPDATE query_history SET status = 'cancelled', error_message = 'Cancelled by user' WHERE id = ?",
                (history_id,),
            )
        logger.info("Query cancelled (history_id=%d)", history_id)

    except Exception as exc:
        logger.error("Query execution failed (history_id=%d): %s", history_id, exc)
        with get_db() as conn:
            conn.execute(
                "UPDATE query_history SET status = 'error', error_message = ? WHERE id = ?",
                (str(exc), history_id),
            )
    finally:
        _running_tasks.pop(history_id, None)


@router.post("/{query_id}/run")
async def execute_query(query_id: int, body: RunQueryRequest, request: Request):
    user = await require_auth(request)

    with get_db() as conn:
        row = conn.execute("SELECT * FROM stored_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")

        dv_query = row["dv_query"]
        for key, val in body.param_values.items():
            dv_query = dv_query.replace(f"{{{key}}}", val)

        params_json = json.dumps(body.param_values)
        cursor = conn.execute(
            "INSERT INTO query_history (stored_query_id, query_name, category, params_json, user_id, status) "
            "VALUES (?, ?, ?, ?, ?, 'running')",
            (query_id, row["name"], row["category"], params_json, user["id"]),
        )
        history_id = cursor.lastrowid

    task = asyncio.create_task(
        _execute_in_background(
            history_id, dv_query, row["name"], user["username"],
            body.from_date, body.to_date,
            stored_query_id=query_id, params_json=params_json,
            force_refresh=body.force_refresh,
        )
    )
    _running_tasks[history_id] = task

    return {"history_id": history_id, "status": "running", "query_name": row["name"]}


@router.post("/cancel/{history_id}")
async def cancel_running_query(history_id: int, request: Request):
    user = await require_auth(request)

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, status FROM query_history WHERE id = ?",
            (history_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="History entry not found")
        if row["user_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Not your query")
        if row["status"] != "running":
            raise HTTPException(status_code=400, detail="Query is not running")

    cancel_query(history_id)

    task = _running_tasks.get(history_id)
    if task and not task.done():
        task.cancel()

    with get_db() as conn:
        conn.execute(
            "UPDATE query_history SET status = 'cancelled', error_message = 'Cancelled by user' WHERE id = ? AND status = 'running'",
            (history_id,),
        )

    logger.info("User %s cancelled query history_id=%d", user["username"], history_id)
    return {"ok": True, "history_id": history_id}


@router.get("/status/{history_id}")
async def query_status(history_id: int, request: Request):
    user = await require_auth(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, status, result_count, error_message FROM query_history WHERE id = ?",
            (history_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="History entry not found")
    result = dict(row)
    if result["status"] == "running":
        progress = get_progress(history_id)
        result["progress_percent"] = progress["percent"]
        result["progress_stage"] = progress["stage"]
    return result
