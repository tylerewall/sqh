import json
import csv
import io
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.auth import require_auth

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


@router.get("/{history_id}/results")
async def get_results(history_id: int, request: Request):
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

        data = json.loads(result_row["result_data"]) if result_row else []
        return {
            "history_id": history_id,
            "query_name": hist["query_name"],
            "category": hist["category"],
            "status": hist["status"],
            "count": len(data),
            "data": data,
        }


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
        data = json.loads(result_row["result_data"]) if result_row else []

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
            for row in data[:200]:
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
