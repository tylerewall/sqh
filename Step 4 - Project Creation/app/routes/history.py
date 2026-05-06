import json
import csv
import gzip
import io
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.database import get_db
from app.auth import require_auth
from app.fast_json import dumps as fj_dumps, loads as fj_loads

logger = logging.getLogger("sqh.routes.history")
router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
async def list_history(request: Request, scope: str = "all", status: str = "all", search: str = ""):
    user = await require_auth(request)
    is_admin = user["role"] == "admin"

    with get_db() as conn:
        if is_admin:
            rows = conn.execute(
                "SELECT qh.*, u.username as run_by FROM query_history qh "
                "LEFT JOIN users u ON qh.user_id = u.id ORDER BY qh.executed_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT qh.*, u.username as run_by FROM query_history qh "
                "LEFT JOIN users u ON qh.user_id = u.id "
                "WHERE qh.user_id = ? OR qh.shared = 1 ORDER BY qh.executed_at DESC",
                (user["id"],),
            ).fetchall()

    history = []
    for r in rows:
        if scope == "mine" and r["user_id"] != user["id"]:
            continue
        if scope == "shared" and not r["shared"]:
            continue
        if status != "all" and r["status"] != status:
            continue
        entry = dict(r)
        entry["params_json"] = json.loads(r["params_json"]) if r["params_json"] else {}
        if search:
            searchable = f"{r['query_name']} {r['category']} {r['params_json']}".lower()
            if search.lower() not in searchable:
                continue
        history.append(entry)

    return {"history": history}


def _load_result_data(result_row) -> list:
    """Decompress (if gzipped) and parse stored result data."""
    if not result_row:
        return []
    raw = result_row["result_data"]
    if isinstance(raw, (bytes, memoryview)):
        raw_bytes = bytes(raw)
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except (gzip.BadGzipFile, OSError):
            pass
        return fj_loads(raw_bytes)
    if isinstance(raw, str):
        return fj_loads(raw)
    return []


@router.get("/{history_id}/results")
async def get_results(history_id: int, request: Request, offset: int = 0, limit: int = 200):
    user = await require_auth(request)
    with get_db() as conn:
        hist = conn.execute("SELECT * FROM query_history WHERE id = ?", (history_id,)).fetchone()
        if not hist:
            raise HTTPException(status_code=404, detail="History entry not found")

        is_admin = user["role"] == "admin"
        is_owner = hist["user_id"] == user["id"]
        is_shared = bool(hist["shared"])
        if not (is_admin or is_owner or is_shared):
            raise HTTPException(status_code=403, detail="Access denied")

        result_row = conn.execute(
            "SELECT result_data FROM query_results WHERE history_id = ?", (history_id,)
        ).fetchone()

        total = hist["result_count"] or 0

    all_data = _load_result_data(result_row)
    page = all_data[offset:offset + limit]
    has_more = (offset + limit) < len(all_data)

    resp = {
        "history_id": history_id,
        "stored_query_id": hist["stored_query_id"],
        "query_name": hist["query_name"],
        "category": hist["category"],
        "status": hist["status"],
        "count": total,
        "offset": offset,
        "has_more": has_more,
        "data": page,
    }

    body = fj_dumps(resp)
    accept_enc = request.headers.get("accept-encoding", "")
    if "gzip" in accept_enc:
        compressed = gzip.compress(body, compresslevel=1)
        return Response(
            content=compressed,
            media_type="application/json",
            headers={"Content-Encoding": "gzip"},
        )
    return Response(content=body, media_type="application/json")


@router.post("/{history_id}/share")
async def share_results(history_id: int, request: Request):
    user = await require_auth(request)
    with get_db() as conn:
        hist = conn.execute("SELECT * FROM query_history WHERE id = ?", (history_id,)).fetchone()
        if not hist:
            raise HTTPException(status_code=404, detail="History entry not found")
        if hist["user_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Can only share your own queries")

        conn.execute(
            "UPDATE query_history SET shared = 1, shared_by = ?, shared_at = datetime('now') WHERE id = ?",
            (user["username"], history_id),
        )

    logger.info("User %s shared history_id=%d", user["username"], history_id)
    return {"ok": True}


@router.get("/{history_id}/export/{fmt}")
async def export_results(history_id: int, fmt: str, request: Request):
    user = await require_auth(request)

    with get_db() as conn:
        hist = conn.execute("SELECT * FROM query_history WHERE id = ?", (history_id,)).fetchone()
        if not hist:
            raise HTTPException(status_code=404, detail="History entry not found")

        is_admin = user["role"] == "admin"
        is_owner = hist["user_id"] == user["id"]
        is_shared = bool(hist["shared"])
        if not (is_admin or is_owner or is_shared):
            raise HTTPException(status_code=403, detail="Access denied")

        result_row = conn.execute(
            "SELECT result_data FROM query_results WHERE history_id = ?", (history_id,)
        ).fetchone()
        data = _load_result_data(result_row)

    if fmt == "json":
        return StreamingResponse(
            io.BytesIO(json.dumps(data, indent=2).encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sqh_export_{history_id}.json"},
        )

    if fmt == "csv":
        if not data:
            content = ""
        else:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
            content = buf.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sqh_export_{history_id}.csv"},
        )

    if fmt == "pdf":
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = [Paragraph(f"Query: {hist['query_name']}", styles["Heading1"])]

        if data:
            headers = list(data[0].keys())
            table_data = [headers]
            for row in data:
                table_data.append([str(row.get(h, ""))[:50] for h in headers])
            t = Table(table_data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTSIZE", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(t)
        else:
            elements.append(Paragraph("No results", styles["Normal"]))

        doc.build(elements)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=sqh_export_{history_id}.pdf"},
        )

    raise HTTPException(status_code=400, detail="Unsupported format. Use json, csv, or pdf.")
