import logging
from fastapi import APIRouter, Request, HTTPException

from app.database import get_db, get_ai_tools, build_ai_s1ql
from app.auth import require_auth
from app.models import CreateAIToolRequest

logger = logging.getLogger("sqh.routes.ai_tools")
router = APIRouter(prefix="/api/ai-tools", tags=["ai-tools"])

AI_QUERY_NAME = "AI Tool Usage Detection"


def _sync_stored_query(conn):
    """Regenerate the S1QL query for the AI detection stored query."""
    tools = [dict(r) for r in conn.execute("SELECT id, keyword, display_name FROM ai_tools ORDER BY display_name").fetchall()]
    new_query = build_ai_s1ql(tools)
    row = conn.execute(
        "SELECT id FROM stored_queries WHERE name LIKE ?",
        (f"%{AI_QUERY_NAME}%",),
    ).fetchone()
    if row:
        conn.execute("UPDATE stored_queries SET dv_query = ?, modified_at = datetime('now') WHERE id = ?", (new_query, row["id"]))
        logger.info("Updated stored query id=%d with %d AI tools", row["id"], len(tools))


@router.get("")
async def list_ai_tools(request: Request):
    await require_auth(request)
    return {"tools": get_ai_tools()}


@router.post("")
async def add_ai_tool(body: CreateAIToolRequest, request: Request):
    await require_auth(request)
    keyword = body.keyword.strip().lower()
    display_name = body.display_name.strip()
    if not keyword or not display_name:
        raise HTTPException(status_code=400, detail="Keyword and display name are required")

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM ai_tools WHERE keyword = ?", (keyword,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Tool with keyword '{keyword}' already exists")
        conn.execute("INSERT INTO ai_tools (keyword, display_name) VALUES (?, ?)", (keyword, display_name))
        _sync_stored_query(conn)

    logger.info("Added AI tool: %s (%s)", display_name, keyword)
    return {"ok": True, "tools": get_ai_tools()}


@router.delete("/{tool_id}")
async def remove_ai_tool(tool_id: int, request: Request):
    await require_auth(request)
    with get_db() as conn:
        row = conn.execute("SELECT id, display_name FROM ai_tools WHERE id = ?", (tool_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tool not found")
        conn.execute("DELETE FROM ai_tools WHERE id = ?", (tool_id,))
        _sync_stored_query(conn)

    logger.info("Removed AI tool: %s (id=%d)", row["display_name"], tool_id)
    return {"ok": True, "tools": get_ai_tools()}
