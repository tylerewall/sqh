import json
import time
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.auth import require_auth
from app.s1_client import run_dv_query, cancel_query, is_cancelled, clear_cancelled
from app.disk_monitor import run_fifo_cleanup
from app.models import RunQueryRequest

logger = logging.getLogger("sqh.routes.queries")
router = APIRouter(prefix="/api/queries", tags=["queries"])

_running_tasks: dict[int, asyncio.Task] = {}


def _build_query_dict(row, conn) -> dict:
    params = conn.execute(
        "SELECT name, label, param_type, placeholder, options, sort_order "
        "FROM query_params WHERE query_id = ? ORDER BY sort_order",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "dv_query": row["dv_query"],
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
            "SELECT sq.*, u.username as creator_name FROM stored_queries sq "
            "LEFT JOIN users u ON sq.created_by = u.id ORDER BY sq.category, sq.name"
        ).fetchall()
        queries = []
        for r in rows:
            q = _build_query_dict(r, conn)
            q["creator_name"] = r["creator_name"]
            queries.append(q)
    return {"queries": queries}


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


async def _execute_in_background(history_id: int, dv_query: str, query_name: str, username: str):
    """Run the S1 DV query and update the history entry when done."""
    logger.info("User %s executing query '%s' (history_id=%d)", username, query_name, history_id)
    t0 = time.time()
    try:
        result = await run_dv_query(dv_query, history_id=history_id)
        elapsed = round(time.time() - t0, 2)
        result_json = json.dumps(result.get("data", []))
        result_count = result.get("count", 0)

        run_fifo_cleanup()

        with get_db() as conn:
            conn.execute(
                "UPDATE query_history SET status = 'success', result_count = ? WHERE id = ?",
                (result_count, history_id),
            )
            conn.execute(
                "INSERT INTO query_results (history_id, result_data, size_bytes) VALUES (?, ?, ?)",
                (history_id, result_json, len(result_json.encode())),
            )
        logger.info("Query complete: %d results in %ss (history_id=%d)", result_count, elapsed, history_id)

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

        cursor = conn.execute(
            "INSERT INTO query_history (stored_query_id, query_name, category, params_json, user_id, status) "
            "VALUES (?, ?, ?, ?, ?, 'running')",
            (query_id, row["name"], row["category"], json.dumps(body.param_values), user["id"]),
        )
        history_id = cursor.lastrowid

    task = asyncio.create_task(
        _execute_in_background(history_id, dv_query, row["name"], user["username"])
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
    return dict(row)
