import os
import logging

logger = logging.getLogger("sqh")

DB_PATH = os.environ.get("SQH_DB_PATH", "/opt/sqh/data/sqh.db")
DB_PASSPHRASE = os.environ.get("SQH_DB_PASSPHRASE", "")
ENCRYPTION_KEY = os.environ.get("SQH_ENCRYPTION_KEY", "")
LOG_DIR = os.environ.get("SQH_LOG_DIR", "/opt/sqh/logs")

S1_API_KEY_ENV = os.environ.get("S1_API_KEY", "")
S1_API_SECRET_ENV = os.environ.get("S1_API_SECRET", "")

DEFAULTS = {
    "s1_base_url": "",
    "s1_api_version": "2.1",
    "disk_cleanup_threshold": "70",
    "session_timeout_hours": "8",
    "pw_min_length": "8",
    "pw_require_upper": "1",
    "pw_require_lower": "1",
    "pw_require_number": "1",
    "pw_require_special": "0",
    "retention_days": "0",
}
