import secrets
import re
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Request, HTTPException

from app.database import get_db, get_config

logger = logging.getLogger("sqh.auth")

SESSION_COOKIE = "sqh_session"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_password(plain: str) -> str | None:
    """Return an error message if the password doesn't meet policy, else None."""
    min_len = int(get_config("pw_min_length") or 8)
    if len(plain) < min_len:
        return f"Password must be at least {min_len} characters"
    if get_config("pw_require_upper") == "1" and not re.search(r"[A-Z]", plain):
        return "Password must contain an uppercase letter"
    if get_config("pw_require_lower") == "1" and not re.search(r"[a-z]", plain):
        return "Password must contain a lowercase letter"
    if get_config("pw_require_number") == "1" and not re.search(r"\d", plain):
        return "Password must contain a number"
    if get_config("pw_require_special") == "1" and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", plain):
        return "Password must contain a special character"
    return None


def create_session(user_id: int) -> str:
    session_id = secrets.token_urlsafe(48)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id) VALUES (?, ?)",
            (session_id, user_id),
        )
    logger.info("Session created for user_id=%d", user_id)
    return session_id


def get_session_user(session_id: str) -> dict | None:
    timeout_hours = int(get_config("session_timeout_hours") or 8)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        row = conn.execute(
            "SELECT s.id as session_id, s.last_active, u.id, u.username, u.full_name, "
            "u.role, u.status, u.force_password_change "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.id = ? AND s.last_active >= ?",
            (session_id, cutoff),
        ).fetchone()
        if not row:
            return None
        if row["status"] != "active":
            return None
        conn.execute(
            "UPDATE sessions SET last_active = datetime('now') WHERE id = ?",
            (session_id,),
        )
        return dict(row)


def delete_session(session_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def cleanup_expired_sessions():
    timeout_hours = int(get_config("session_timeout_hours") or 8)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        result = conn.execute("DELETE FROM sessions WHERE last_active < ?", (cutoff,))
        if result.rowcount > 0:
            logger.debug("Cleaned up %d expired sessions", result.rowcount)


async def require_auth(request: Request) -> dict:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = get_session_user(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


async def require_admin(request: Request) -> dict:
    user = await require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
