import json
import logging
from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.auth import require_admin, hash_password, validate_password
from app.models import (
    CreateUserRequest, UpdateUserRequest, ResetPasswordRequest,
    CreateStoredQueryRequest, UpdateStoredQueryRequest, BulkDeleteHistoryRequest,
    CreateFolderRequest, UpdateFolderRequest, ReorderFoldersRequest, MoveQueryToFolderRequest,
)

logger = logging.getLogger("sqh.routes.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── User Management ──────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(request: Request):
    await require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, full_name, role, status, force_password_change, "
            "created_at, last_login FROM users ORDER BY created_at"
        ).fetchall()
    return {"users": [dict(r) for r in rows]}


@router.post("/users")
async def create_user(body: CreateUserRequest, request: Request):
    await require_admin(request)

    err = validate_password(body.password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    pw_hash = hash_password(body.password)
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, full_name, password_hash, role, force_password_change) "
                "VALUES (?, ?, ?, ?, 1)",
                (body.username, body.full_name, pw_hash, body.role),
            )
    except Exception:
        raise HTTPException(status_code=409, detail="Username already exists")

    logger.info("Admin created user: %s (%s)", body.username, body.role)
    return {"ok": True}


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UpdateUserRequest, request: Request):
    await require_admin(request)
    updates, params = [], []
    if body.full_name is not None:
        updates.append("full_name = ?")
        params.append(body.full_name)
    if body.role is not None:
        updates.append("role = ?")
        params.append(body.role)
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.append(user_id)
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)

    logger.info("Admin updated user id=%d: %s", user_id, updates)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, body: ResetPasswordRequest, request: Request):
    await require_admin(request)
    err = validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    pw_hash = hash_password(body.new_password)
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, force_password_change = 1 WHERE id = ?",
            (pw_hash, user_id),
        )
    logger.info("Admin reset password for user id=%d", user_id)
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    admin = await require_admin(request)
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    logger.info("Admin deleted user id=%d", user_id)
    return {"ok": True}


# ── Stored Query Management ──────────────────────────────────────────────────

@router.get("/queries")
async def list_admin_queries(request: Request):
    await require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sq.*, u.username as creator_name FROM stored_queries sq "
            "LEFT JOIN users u ON sq.created_by = u.id ORDER BY sq.name"
        ).fetchall()
        queries = []
        for r in rows:
            params = conn.execute(
                "SELECT name, label, param_type, placeholder, options, sort_order "
                "FROM query_params WHERE query_id = ? ORDER BY sort_order",
                (r["id"],),
            ).fetchall()
            q = dict(r)
            q["params"] = [
                {**dict(p), "options": json.loads(p["options"]) if p["options"] else None}
                for p in params
            ]
            queries.append(q)
    return {"queries": queries}


@router.post("/queries")
async def create_query(body: CreateStoredQueryRequest, request: Request):
    admin = await require_admin(request)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO stored_queries (name, description, category, dv_query, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (body.name, body.description, body.category, body.dv_query, admin["id"]),
        )
        query_id = cursor.lastrowid
        for i, p in enumerate(body.params):
            conn.execute(
                "INSERT INTO query_params (query_id, name, label, param_type, placeholder, options, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (query_id, p.name, p.label, p.param_type, p.placeholder,
                 json.dumps(p.options) if p.options else None, p.sort_order or i),
            )
    logger.info("Admin created stored query: %s (id=%d)", body.name, query_id)
    return {"ok": True, "id": query_id}


@router.put("/queries/{query_id}")
async def update_query(query_id: int, body: UpdateStoredQueryRequest, request: Request):
    await require_admin(request)
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM stored_queries WHERE id = ?", (query_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Query not found")

        updates, params_list = [], []
        if body.name is not None:
            updates.append("name = ?"); params_list.append(body.name)
        if body.description is not None:
            updates.append("description = ?"); params_list.append(body.description)
        if body.category is not None:
            updates.append("category = ?"); params_list.append(body.category)
        if body.dv_query is not None:
            updates.append("dv_query = ?"); params_list.append(body.dv_query)
        if updates:
            updates.append("modified_at = datetime('now')")
            params_list.append(query_id)
            conn.execute(f"UPDATE stored_queries SET {', '.join(updates)} WHERE id = ?", params_list)

        if body.params is not None:
            conn.execute("DELETE FROM query_params WHERE query_id = ?", (query_id,))
            for i, p in enumerate(body.params):
                conn.execute(
                    "INSERT INTO query_params (query_id, name, label, param_type, placeholder, options, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (query_id, p.name, p.label, p.param_type, p.placeholder,
                     json.dumps(p.options) if p.options else None, p.sort_order or i),
                )

    logger.info("Admin updated stored query id=%d", query_id)
    return {"ok": True}


@router.delete("/queries/{query_id}")
async def delete_query(query_id: int, request: Request):
    await require_admin(request)
    with get_db() as conn:
        conn.execute("DELETE FROM stored_queries WHERE id = ?", (query_id,))
    logger.info("Admin deleted stored query id=%d", query_id)
    return {"ok": True}


# ── Query History Management ─────────────────────────────────────────────────

@router.get("/history")
async def list_all_history(request: Request):
    await require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT qh.*, u.username as run_by FROM query_history qh "
            "LEFT JOIN users u ON qh.user_id = u.id ORDER BY qh.executed_at DESC"
        ).fetchall()
    return {"history": [dict(r) for r in rows]}


@router.delete("/history")
async def bulk_delete_history(body: BulkDeleteHistoryRequest, request: Request):
    await require_admin(request)

    with get_db() as conn:
        if body.mode == "all":
            conn.execute("DELETE FROM query_results")
            conn.execute("DELETE FROM query_history")
            logger.info("Admin deleted ALL query history")
        elif body.mode == "30days":
            conn.execute(
                "DELETE FROM query_results WHERE history_id IN "
                "(SELECT id FROM query_history WHERE executed_at >= datetime('now', '-30 days'))"
            )
            conn.execute("DELETE FROM query_history WHERE executed_at >= datetime('now', '-30 days')")
            logger.info("Admin deleted query history from last 30 days")
        elif body.mode == "range" and body.start_date and body.end_date:
            conn.execute(
                "DELETE FROM query_results WHERE history_id IN "
                "(SELECT id FROM query_history WHERE executed_at BETWEEN ? AND ?)",
                (body.start_date, body.end_date + " 23:59:59"),
            )
            conn.execute(
                "DELETE FROM query_history WHERE executed_at BETWEEN ? AND ?",
                (body.start_date, body.end_date + " 23:59:59"),
            )
            logger.info("Admin deleted history from %s to %s", body.start_date, body.end_date)
        else:
            raise HTTPException(status_code=400, detail="Invalid delete mode")

    return {"ok": True}


@router.delete("/history/{history_id}")
async def delete_history_entry(history_id: int, request: Request):
    await require_admin(request)
    with get_db() as conn:
        conn.execute("DELETE FROM query_results WHERE history_id = ?", (history_id,))
        conn.execute("DELETE FROM query_history WHERE id = ?", (history_id,))
    logger.info("Admin deleted history entry id=%d", history_id)
    return {"ok": True}


# ── Folder Management ─────────────────────────────────────────────────────────

@router.get("/folders")
async def list_folders(request: Request):
    await require_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, parent_id, sort_order, created_at "
            "FROM query_folders ORDER BY sort_order, name"
        ).fetchall()
    return {"folders": [dict(r) for r in rows]}


@router.post("/folders")
async def create_folder(body: CreateFolderRequest, request: Request):
    await require_admin(request)
    with get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM query_folders").fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO query_folders (name, parent_id, sort_order) VALUES (?, ?, ?)",
            (body.name, body.parent_id, max_order + 1),
        )
    logger.info("Admin created folder: %s (id=%d)", body.name, cursor.lastrowid)
    return {"ok": True, "id": cursor.lastrowid}


@router.put("/folders/{folder_id}")
async def update_folder(folder_id: int, body: UpdateFolderRequest, request: Request):
    await require_admin(request)
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.sort_order is not None:
        updates.append("sort_order = ?"); params.append(body.sort_order)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.append(folder_id)
    with get_db() as conn:
        conn.execute(f"UPDATE query_folders SET {', '.join(updates)} WHERE id = ?", params)
    logger.info("Admin updated folder id=%d", folder_id)
    return {"ok": True}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, request: Request):
    await require_admin(request)
    with get_db() as conn:
        conn.execute("UPDATE stored_queries SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM query_folders WHERE id = ?", (folder_id,))
    logger.info("Admin deleted folder id=%d", folder_id)
    return {"ok": True}


@router.post("/folders/reorder")
async def reorder_folders(body: ReorderFoldersRequest, request: Request):
    await require_admin(request)
    with get_db() as conn:
        for idx, fid in enumerate(body.order):
            conn.execute("UPDATE query_folders SET sort_order = ? WHERE id = ?", (idx, fid))
    logger.info("Admin reordered folders: %s", body.order)
    return {"ok": True}


@router.put("/queries/{query_id}/folder")
async def move_query_to_folder(query_id: int, body: MoveQueryToFolderRequest, request: Request):
    await require_admin(request)
    with get_db() as conn:
        conn.execute("UPDATE stored_queries SET folder_id = ? WHERE id = ?", (body.folder_id, query_id))
    logger.info("Admin moved query id=%d to folder_id=%s", query_id, body.folder_id)
    return {"ok": True}
