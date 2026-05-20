import logging
from fastapi import APIRouter, Request

from app.database import get_db, get_config, set_config
from app.auth import require_auth, require_admin
from app.disk_monitor import get_disk_usage, get_storage_breakdown
from app.secrets_manager import encrypt
from app.models import SaveConfigRequest

logger = logging.getLogger("sqh.routes.system")
router = APIRouter(prefix="/api/system", tags=["system"])

SENSITIVE_KEYS = {"s1_api_key", "s1_api_secret", "openai_api_key", "virustotal_api_key", "apivoid_api_key"}
CONFIG_KEYS = [
    "s1_base_url", "s1_api_key", "s1_api_secret", "s1_api_version",
    "disk_cleanup_threshold", "session_timeout_hours",
    "pw_min_length", "pw_require_upper", "pw_require_lower",
    "pw_require_number", "pw_require_special", "retention_days",
    "openai_api_key", "openai_model", "virustotal_api_key", "apivoid_api_key",
]


@router.get("/disk")
async def disk_usage(request: Request):
    await require_auth(request)
    usage = get_disk_usage()
    return {"disk": usage}


@router.get("/disk/breakdown")
async def disk_breakdown(request: Request):
    await require_admin(request)
    breakdown = get_storage_breakdown()
    usage = get_disk_usage()
    return {"disk": usage, "breakdown": breakdown}


@router.get("/config")
async def get_all_config(request: Request):
    await require_admin(request)
    result = {}
    for key in CONFIG_KEYS:
        val = get_config(key)
        if key in SENSITIVE_KEYS and val:
            result[key] = "********"
        else:
            result[key] = val
    return {"config": result}


@router.post("/config")
async def save_config(body: SaveConfigRequest, request: Request):
    await require_admin(request)

    for key, value in body.settings.items():
        if key not in CONFIG_KEYS:
            continue
        if key in SENSITIVE_KEYS:
            if value == "********":
                continue
            value = encrypt(value)
        set_config(key, value)
        if key not in SENSITIVE_KEYS:
            logger.info("Config updated: %s = %s", key, value)
        else:
            logger.info("Config updated: %s = [encrypted]", key)

    return {"ok": True}
