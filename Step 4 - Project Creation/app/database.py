import os
import json
import logging
from contextlib import contextmanager
from app.config import DB_PATH, DB_PASSPHRASE, DEFAULTS

logger = logging.getLogger("sqh.db")

try:
    from pysqlcipher3 import dbapi2 as sqlite3
    HAS_SQLCIPHER = True
except ImportError:
    import sqlite3
    HAS_SQLCIPHER = False
    logger.warning("pysqlcipher3 not available — using plain sqlite3 (NOT for production)")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'standard')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive')),
    force_password_change INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_active TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER DEFAULT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES query_folders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stored_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT NOT NULL,
    dv_query TEXT NOT NULL,
    folder_id INTEGER DEFAULT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (folder_id) REFERENCES query_folders(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS query_params (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    param_type TEXT NOT NULL CHECK(param_type IN ('text', 'datetime', 'dropdown')),
    placeholder TEXT DEFAULT '',
    options TEXT DEFAULT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (query_id) REFERENCES stored_queries(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stored_query_id INTEGER,
    query_name TEXT NOT NULL,
    category TEXT DEFAULT '',
    params_json TEXT DEFAULT '{}',
    user_id INTEGER NOT NULL,
    executed_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'success', 'error', 'cancelled')),
    error_message TEXT DEFAULT '',
    result_count INTEGER DEFAULT 0,
    partial_ready INTEGER NOT NULL DEFAULT 0,
    shared INTEGER NOT NULL DEFAULT 0,
    shared_by TEXT DEFAULT '',
    shared_at TEXT DEFAULT '',
    FOREIGN KEY (stored_query_id) REFERENCES stored_queries(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS query_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id INTEGER NOT NULL UNIQUE,
    result_data TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (history_id) REFERENCES query_history(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_AI_TOOLS = [
    ("claude", "Claude"), ("anthropic", "Anthropic"),
    ("chatgpt", "ChatGPT"), ("openai", "OpenAI"),
    ("copilot", "GitHub Copilot"), ("gemini", "Google Gemini"),
    ("ollama", "Ollama"), ("cursor", "Cursor AI"),
    ("codeium", "Codeium"), ("windsurf", "Windsurf"),
    ("tabnine", "Tabnine"), ("mistral", "Mistral"),
    ("perplexity", "Perplexity"), ("deepseek", "DeepSeek"),
    ("aider", "Aider"), ("cohere", "Cohere"),
    ("huggingface", "Hugging Face"),
    ("stable-diffusion", "Stable Diffusion"),
    ("lmstudio", "LM Studio"), ("localai", "LocalAI"),
    ("comfyui", "ComfyUI"), ("invokeai", "InvokeAI"),
    ("continuedev", "Continue.dev"),
]


def _open_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    if HAS_SQLCIPHER and DB_PASSPHRASE:
        conn.execute(f"PRAGMA key='{DB_PASSPHRASE}'")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = _open_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn):
    """Apply lightweight migrations for columns/tables added after initial release."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(stored_queries)").fetchall()}
    if "folder_id" not in existing:
        conn.execute("ALTER TABLE stored_queries ADD COLUMN folder_id INTEGER DEFAULT NULL REFERENCES query_folders(id) ON DELETE SET NULL")
        logger.info("Migration: added folder_id to stored_queries")

    hist_cols = {r[1] for r in conn.execute("PRAGMA table_info(query_history)").fetchall()}
    if "partial_ready" not in hist_cols:
        conn.execute("ALTER TABLE query_history ADD COLUMN partial_ready INTEGER NOT NULL DEFAULT 0")
        logger.info("Migration: added partial_ready to query_history")


def init_db():
    """Create tables and seed the default admin account."""
    logger.info("Initialising database at %s (SQLCipher=%s)", DB_PATH, HAS_SQLCIPHER)
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate(conn)

        # Seed default config values
        for key, val in DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
                (key, val),
            )

        # Seed default AI tools if table is empty
        ai_count = conn.execute("SELECT COUNT(*) AS cnt FROM ai_tools").fetchone()
        if ai_count["cnt"] == 0:
            for kw, display in DEFAULT_AI_TOOLS:
                conn.execute(
                    "INSERT OR IGNORE INTO ai_tools (keyword, display_name) VALUES (?, ?)",
                    (kw, display),
                )
            logger.info("Seeded %d default AI tools", len(DEFAULT_AI_TOOLS))

        # Seed default admin (admin/admin) if no users exist
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        if row["cnt"] == 0:
            import bcrypt
            pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO users (username, full_name, password_hash, role, force_password_change) "
                "VALUES (?, ?, ?, ?, ?)",
                ("admin", "Administrator", pw_hash, "admin", 1),
            )
            logger.info("Default admin account created (admin/admin) — password change required")

        # Re-sync AI detection stored query so it picks up any query-builder changes
        _refresh_ai_stored_query(conn)


def _refresh_ai_stored_query(conn):
    """Update the AI detection stored query with the latest build_ai_s1ql() output."""
    new_query = build_ai_s1ql()
    row = conn.execute(
        "SELECT id FROM stored_queries WHERE name LIKE '%AI Tool Usage Detection%'"
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE stored_queries SET dv_query = ?, modified_at = datetime('now') WHERE id = ?",
            (new_query, row["id"]),
        )
        logger.info("Refreshed AI stored query id=%d on startup", row["id"])


def get_config(key: str) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULTS.get(key, "")


def set_config(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_ai_tools() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, keyword, display_name FROM ai_tools ORDER BY display_name").fetchall()
        return [dict(r) for r in rows]


def build_ai_s1ql(tools: list[dict] | None = None) -> str:
    if tools is None:
        tools = get_ai_tools()
    if not tools:
        return 'EventType = "Process Creation"'
    pattern = "|".join(t["keyword"] for t in tools)
    return f'EventType = "Process Creation" AND (ProcessName RegExp "{pattern}" OR ProcessCmd RegExp "{pattern}")'
