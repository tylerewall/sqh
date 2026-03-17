import json
import time
import logging
from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.auth import require_auth
from app.s1_client import run_dv_query
from app.disk_monitor import run_fifo_cleanup
from app.models import RunQueryRequest

logger = logging.getLogger("sqh.routes.queries")
router = APIRouter(prefix="/api/queries", tags=["queries"])


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


@router.get("/{query_id}")
async def get_query(query_id: int, request: Request):
    await require_auth(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM stored_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")
        return {"query": _build_query_dict(row, conn)}


@router.post("/{query_id}/run")
async def execute_query(query_id: int, body: RunQueryRequest, request: Request):
    user = await require_auth(request)

    # Check if user already has a running query
    with get_db() as conn:
        running = conn.execute(
            "SELECT id FROM query_history WHERE user_id = ? AND status = 'running'",
            (user["id"],),
        ).fetchone()
        if running:
            raise HTTPException(status_code=409, detail="You already have a query running")

        row = conn.execute("SELECT * FROM stored_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")

        # Substitute parameters into the DV query string
        dv_query = row["dv_query"]
        for key, val in body.param_values.items():
            dv_query = dv_query.replace(f"{{{key}}}", val)

        # Create history entry with 'running' status
        cursor = conn.execute(
            "INSERT INTO query_history (stored_query_id, query_name, category, params_json, user_id, status) "
            "VALUES (?, ?, ?, ?, ?, 'running')",
            (query_id, row["name"], row["category"], json.dumps(body.param_values), user["id"]),
        )
        history_id = cursor.lastrowid

    logger.info("User %s executing query '%s' (history_id=%d)", user["username"], row["name"], history_id)
    t0 = time.time()

    try:
        result = await run_dv_query(dv_query)
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

        logger.info("Query complete: %d results in %ss", result_count, elapsed)
        return {"history_id": history_id, "count": result_count, "data": result.get("data", [])}

    except Exception as exc:
        logger.error("Query execution failed: %s", exc)
        with get_db() as conn:
            conn.execute(
                "UPDATE query_history SET status = 'error', error_message = ? WHERE id = ?",
                (str(exc), history_id),
            )
        raise HTTPException(status_code=502, detail=str(exc))
