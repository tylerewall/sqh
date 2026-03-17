import time
import json
import logging

import httpx

from app.database import get_config
from app.secrets_manager import decrypt
from app.config import S1_API_KEY_ENV, S1_API_SECRET_ENV

logger = logging.getLogger("sqh.s1")

DEEP_VISIBILITY_INIT = "/web/api/v{version}/dv/init-query"
DEEP_VISIBILITY_STATUS = "/web/api/v{version}/dv/query-status"
DEEP_VISIBILITY_EVENTS = "/web/api/v{version}/dv/events"


def _get_credentials() -> tuple[str, str, str, str]:
    """Return (base_url, api_token, api_version) from DB config or env fallback."""
    base_url = get_config("s1_base_url")
    version = get_config("s1_api_version") or "2.1"

    db_key = get_config("s1_api_key")
    db_secret = get_config("s1_api_secret")

    if db_key and db_secret:
        api_key = decrypt(db_key)
        api_secret = decrypt(db_secret)
    else:
        api_key = S1_API_KEY_ENV
        api_secret = S1_API_SECRET_ENV

    return base_url, api_key, api_secret, version


def _get_api_token(client: httpx.Client, base_url: str, api_key: str, api_secret: str) -> str:
    """Obtain an API token using key + secret. Adjust based on actual S1 auth flow."""
    return api_key


async def run_dv_query(query_string: str, timeout: int = 120) -> dict:
    """
    Submit a Deep Visibility query and poll for results.
    Returns {"data": [...], "count": N} or raises an exception.
    """
    base_url, api_key, api_secret, version = _get_credentials()

    if not base_url or not api_key:
        raise ValueError("SentinelOne API not configured. Run the Setup Wizard first.")

    headers = {
        "Authorization": f"ApiToken {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
        init_url = DEEP_VISIBILITY_INIT.format(version=version)
        logger.info("S1 DV init-query: %s%s", base_url, init_url)
        t0 = time.time()

        resp = await client.post(init_url, json={"query": query_string, "fromDate": "", "toDate": ""})
        resp.raise_for_status()
        query_id = resp.json().get("data", {}).get("queryId")
        if not query_id:
            raise ValueError(f"S1 init-query did not return a queryId: {resp.text}")

        logger.info("S1 DV query initiated: queryId=%s", query_id)

        status_url = DEEP_VISIBILITY_STATUS.format(version=version)
        import asyncio
        for _ in range(60):
            await asyncio.sleep(2)
            status_resp = await client.get(status_url, params={"queryId": query_id})
            status_resp.raise_for_status()
            status_data = status_resp.json().get("data", {})
            state = status_data.get("responseState", "")
            if state == "FINISHED":
                break
            if state == "FAILED":
                raise ValueError(f"S1 DV query failed: {status_data}")
        else:
            raise TimeoutError("S1 DV query timed out after 120s of polling")

        events_url = DEEP_VISIBILITY_EVENTS.format(version=version)
        events_resp = await client.get(events_url, params={"queryId": query_id, "limit": 1000})
        events_resp.raise_for_status()
        events = events_resp.json().get("data", [])

        elapsed = round(time.time() - t0, 2)
        logger.info("S1 DV query complete: %d events in %ss", len(events), elapsed)

        return {"data": events, "count": len(events)}
