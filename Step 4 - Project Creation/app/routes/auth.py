import logging
from fastapi import APIRouter, Request, Response, HTTPException

from app.database import get_db
from app.auth import (
    verify_password, hash_password, validate_password,
    create_session, delete_session, require_auth, SESSION_COOKIE,
)
from app.models import LoginRequest, ChangePasswordRequest

logger = logging.getLogger("sqh.routes.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, full_name, password_hash, role, status, force_password_change "
            "FROM users WHERE username = ?",
            (body.username,),
        ).fetchone()

    if not row or not verify_password(body.password, row["password_hash"]):
        logger.warning("Failed login attempt for username=%s", body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="Account is deactivated")

    session_id = create_session(row["id"])
    with get_db() as conn:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (row["id"],))

    logger.info("User %s logged in", row["username"])
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", max_age=86400)
    return {
        "user": {
            "id": row["id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": row["role"],
            "force_password_change": bool(row["force_password_change"]),
        }
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        delete_session(session_id)
        logger.info("User logged out")
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = await require_auth(request)
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "force_password_change": bool(user["force_password_change"]),
        }
    }


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request):
    user = await require_auth(request)

    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()

    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    err = validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    new_hash = hash_password(body.new_password)
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?",
            (new_hash, user["id"]),
        )

    logger.info("User %s changed password", user["username"])
    return {"ok": True}
