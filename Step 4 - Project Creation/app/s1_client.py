import time
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.database import get_config
from app.secrets_manager import decrypt
from app.config import S1_API_KEY_ENV

logger = logging.getLogger("sqh.s1")

DEEP_VISIBILITY_INIT = "/web/api/v{version}/dv/init-query"
DEEP_VISIBILITY_STATUS = "/web/api/v{version}/dv/query-status"
DEEP_VISIBILITY_EVENTS = "/web/api/v{version}/dv/events"

_cancelled: set[int] = set()


def cancel_query(history_id: int):
    _cancelled.add(history_id)
    logger.info("Query cancellation requested: history_id=%d", history_id)


def is_cancelled(history_id: int) -> bool:
    return history_id in _cancelled


def clear_cancelled(history_id: int):
    _cancelled.discard(history_id)


def _get_credentials() -> tuple[str, str, str]:
    """Return (base_url, api_token, api_version) from DB config or env fallback."""
    base_url = get_config("s1_base_url")
    version = get_config("s1_api_version") or "2.1"

    db_token = get_config("s1_api_key")

    if db_token:
        api_token = decrypt(db_token)
        if not api_token:
            logger.error("s1_api_key decryption returned empty — check SQH_ENCRYPTION_KEY")
    else:
        api_token = S1_API_KEY_ENV

    return base_url, api_token, version


async def run_dv_query(query_string: str, from_date: str = "", to_date: str = "", timeout: int = 300, history_id: int = 0) -> dict:
    """
    Submit a Deep Visibility query and poll for results.
    Returns {"data": [...], "count": N} or raises an exception.
    Dates must be ISO 8601 format. Defaults to the last 14 days if omitted.
    """
    base_url, api_token, version = _get_credentials()

    if not base_url or not api_token:
        raise ValueError("SentinelOne API not configured. Run the Setup Wizard first.")

    now = datetime.now(timezone.utc)
    if not to_date:
        to_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if not from_date:
        from_date = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    headers = {
        "Authorization": f"ApiToken {api_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query_string,
        "fromDate": from_date,
        "toDate": to_date,
    }

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
        init_url = DEEP_VISIBILITY_INIT.format(version=version)
        logger.info("S1 DV init-query: %s%s  payload=%s", base_url, init_url, json.dumps(payload))
        t0 = time.time()

        resp = await client.post(init_url, json=payload)
        if resp.status_code != 200:
            body = resp.text
            logger.error("S1 init-query failed: HTTP %d — %s", resp.status_code, body)
            raise ValueError(f"SentinelOne returned HTTP {resp.status_code}: {body}")

        query_id = resp.json().get("data", {}).get("queryId")
        if not query_id:
            raise ValueError(f"S1 init-query did not return a queryId: {resp.text}")

        logger.info("S1 DV query initiated: queryId=%s", query_id)

        status_url = DEEP_VISIBILITY_STATUS.format(version=version)
        max_polls = 150
        poll_interval = 2
        for attempt in range(max_polls):
            await asyncio.sleep(poll_interval)
            if history_id and is_cancelled(history_id):
                clear_cancelled(history_id)
                logger.info("S1 DV query cancelled by user: history_id=%d", history_id)
                raise asyncio.CancelledError("Query cancelled by user")
            status_resp = await client.get(status_url, params={"queryId": query_id})
            if status_resp.status_code != 200:
                logger.error("S1 query-status failed: HTTP %d — %s", status_resp.status_code, status_resp.text)
                raise ValueError(f"SentinelOne status check failed: HTTP {status_resp.status_code}")
            status_data = status_resp.json().get("data", {})
            state = status_data.get("responseState", "")
            progress = status_data.get("progressStatus", "")
            if attempt % 5 == 0:
                elapsed_poll = round((attempt + 1) * poll_interval, 0)
                logger.info("S1 DV poll #%d (%ds): state=%s progress=%s", attempt + 1, elapsed_poll, state, progress)
            if state == "FINISHED":
                break
            if state == "FAILED":
                raise ValueError(f"S1 DV query failed: {status_data}")
        else:
            raise TimeoutError(f"S1 DV query timed out after {max_polls * poll_interval}s of polling (last state: {state})")

        events_url = DEEP_VISIBILITY_EVENTS.format(version=version)
        events_resp = await client.get(events_url, params={"queryId": query_id, "limit": 1000})
        if events_resp.status_code != 200:
            logger.error("S1 events fetch failed: HTTP %d — %s", events_resp.status_code, events_resp.text)
            raise ValueError(f"SentinelOne events fetch failed: HTTP {events_resp.status_code}")
        events = events_resp.json().get("data", [])

        elapsed = round(time.time() - t0, 2)
        logger.info("S1 DV query complete: %d events in %ss", len(events), elapsed)

        return {"data": events, "count": len(events)}
