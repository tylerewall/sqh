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
POWER_QUERY_ENDPOINTS = [
    "/web/api/v{version}/dv/query-pq",
    "/api/powerQuery",
]

_cancelled: set[int] = set()
_progress: dict[int, dict] = {}  # history_id -> {percent: 0-100, stage: str}


def cancel_query(history_id: int):
    _cancelled.add(history_id)
    logger.info("Query cancellation requested: history_id=%d", history_id)


def is_cancelled(history_id: int) -> bool:
    return history_id in _cancelled


def clear_cancelled(history_id: int):
    _cancelled.discard(history_id)


def set_progress(history_id: int, percent: int, stage: str = ""):
    if history_id:
        _progress[history_id] = {"percent": min(percent, 100), "stage": stage}


def get_progress(history_id: int) -> dict:
    return _progress.get(history_id, {"percent": 0, "stage": ""})


def clear_progress(history_id: int):
    _progress.pop(history_id, None)


def _is_power_query(query_string: str) -> bool:
    stripped = query_string.strip()
    return stripped.startswith("|") or stripped.startswith("filter(") or stripped.startswith("group ")


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


def _build_dates(from_date: str, to_date: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    if not to_date:
        to_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if not from_date:
        from_date = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return from_date, to_date


def _dedup_events(events: list[dict]) -> list[dict]:
    """Collapse duplicate process events into unique rows with an _eventCount field.

    Groups by (endpoint, process name/cmd, user) so the dashboard sees only
    distinct matches instead of thousands of redundant telemetry rows.
    """
    seen: dict[str, dict] = {}
    for ev in events:
        endpoint = ev.get("agentComputerName") or ev.get("endpointName") or ev.get("EndpointName") or ""
        proc = ev.get("processName") or ev.get("ProcessName") or ev.get("SrcProcName") or ""
        cmd = ev.get("processCmd") or ev.get("ProcessCmd") or ev.get("SrcProcCmdLine") or ""
        user = ev.get("user") or ev.get("UserName") or ev.get("userName") or ""
        key = f"{endpoint}|{proc}|{cmd}|{user}"
        if key in seen:
            seen[key]["_eventCount"] = seen[key].get("_eventCount", 1) + 1
        else:
            ev["_eventCount"] = 1
            seen[key] = ev
    deduped = sorted(seen.values(), key=lambda r: r.get("_eventCount", 1), reverse=True)
    return deduped


DV_ACCOUNT_CAP = 20000


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s}")


MAX_CONCURRENT_SLICES = 2
TARGET_SLICES = 4


async def run_dv_query(query_string: str, from_date: str = "", to_date: str = "", timeout: int = 300, history_id: int = 0, deduplicate: bool = False, on_first_page=None) -> dict:
    """
    Auto-detects query type (PowerQuery vs standard DV) and routes accordingly.
    Stops at 20K results and raises an error — too many results is not useful.
    on_first_page: optional async callback(events_list) called after each page arrives.
    """
    if _is_power_query(query_string):
        return await _run_power_query(query_string, from_date, to_date, timeout, history_id)

    from_date, to_date = _build_dates(from_date, to_date)

    result = await _run_dv_query(query_string, from_date, to_date, timeout, history_id, on_first_page=on_first_page)

    if len(result.get("data", [])) >= DV_ACCOUNT_CAP:
        logger.warning("Query hit %d-event cap — stopping (too many results)", DV_ACCOUNT_CAP)
        raise ValueError(
            f"Query returned {DV_ACCOUNT_CAP:,}+ results which is too many to be useful. "
            "Narrow your search by using a shorter time range, adding an EndpointName or UserName filter, "
            "or using more specific search terms."
        )

    if deduplicate and result.get("data"):
        raw_count = len(result["data"])
        result["data"] = _dedup_events(result["data"])
        result["raw_count"] = raw_count
        result["count"] = len(result["data"])
        logger.info("Deduplication: %d raw events → %d unique", raw_count, result["count"])
    return result


async def _run_dv_query_sliced(query_string: str, from_date: str, to_date: str, timeout: int, history_id: int) -> dict:
    """Split the date range into sequential time windows (respects S1 rate limits)."""
    dt_from = _parse_dt(from_date)
    dt_to = _parse_dt(to_date)
    total_hours = (dt_to - dt_from).total_seconds() / 3600

    if total_hours <= 4:
        slice_hours = total_hours or 1
    else:
        slice_hours = max(6, int(total_hours / TARGET_SLICES))

    slices = []
    cursor = dt_from
    while cursor < dt_to:
        slice_end = min(cursor + timedelta(hours=slice_hours), dt_to)
        slices.append((
            cursor.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            slice_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        ))
        cursor = slice_end

    logger.info("Time-slicing: %d slices of %dh across %s → %s (concurrency=%d)",
                len(slices), slice_hours, from_date, to_date, MAX_CONCURRENT_SLICES)

    all_events = []
    seen_ids = set()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SLICES)

    async def _run_slice(idx, s_from, s_to):
        async with semaphore:
            if history_id and is_cancelled(history_id):
                return []
            logger.info("Time-slice %d/%d: %s → %s", idx + 1, len(slices), s_from, s_to)
            res = await _run_dv_query(query_string, s_from, s_to, timeout, history_id)
            events = res.get("data", [])
            logger.info("Time-slice %d/%d: %d events", idx + 1, len(slices), len(events))
            return events

    tasks = [_run_slice(i, sf, st) for i, (sf, st) in enumerate(slices)]
    slice_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, sr in enumerate(slice_results):
        if isinstance(sr, Exception):
            logger.error("Time-slice %d/%d failed: %s", i + 1, len(slices), sr)
            continue
        for ev in sr:
            eid = ev.get("id") or ev.get("eventId") or ev.get("trueContext")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            all_events.append(ev)

    logger.info("Time-slicing complete: %d total events from %d slices", len(all_events), len(slices))
    return {"data": all_events, "count": len(all_events)}


async def _run_power_query(query_string: str, from_date: str, to_date: str, timeout: int, history_id: int) -> dict:
    """Execute a PowerQuery (S1QL 2.0 pipe syntax) against the S1 API."""
    base_url, api_token, version = _get_credentials()
    if not base_url or not api_token:
        raise ValueError("SentinelOne API not configured. Run the Setup Wizard first.")

    from_date, to_date = _build_dates(from_date, to_date)

    headers = {
        "Authorization": f"ApiToken {api_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query_string,
        "fromDate": from_date,
        "toDate": to_date,
    }

    t0 = time.time()

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
        resp = None
        used_url = None

        for pq_template in POWER_QUERY_ENDPOINTS:
            pq_url = pq_template.format(version=version)
            logger.info("S1 PowerQuery trying: %s%s", base_url, pq_url)
            resp = await client.post(pq_url, json=payload)
            if resp.status_code != 404:
                used_url = pq_url
                break
            logger.info("S1 PowerQuery endpoint %s returned 404, trying next", pq_url)

        if resp is None or resp.status_code == 404:
            raise ValueError(
                "PowerQuery endpoint not found on this SentinelOne instance. "
                "Your S1 license may not include PowerQuery / Data Lake. "
                "Try converting the query to standard S1QL (Deep Visibility) syntax."
            )

        logger.info("S1 PowerQuery used endpoint: %s  HTTP %d", used_url, resp.status_code)

        if resp.status_code != 200:
            body = resp.text
            logger.error("S1 PowerQuery failed: HTTP %d — %s", resp.status_code, body)
            raise ValueError(f"SentinelOne PowerQuery returned HTTP {resp.status_code}: {body}")

        result = resp.json()
        logger.info("S1 PowerQuery response keys: %s", list(result.keys()))
        data = result.get("data", [])

        if isinstance(data, dict):
            columns = data.get("columns", [])
            rows = data.get("rows", [])
            if columns and rows:
                events = [dict(zip(columns, row)) for row in rows]
            else:
                events = [data] if data else []
        elif isinstance(data, list):
            events = data
        else:
            events = []

        elapsed = round(time.time() - t0, 2)
        logger.info("S1 PowerQuery complete: %d results in %ss", len(events), elapsed)

        return {"data": events, "count": len(events)}


async def _run_dv_query(query_string: str, from_date: str, to_date: str, timeout: int, history_id: int, on_first_page=None) -> dict:
    """Execute a standard Deep Visibility (S1QL 1.0) query with async polling."""
    base_url, api_token, version = _get_credentials()
    if not base_url or not api_token:
        raise ValueError("SentinelOne API not configured. Run the Setup Wizard first.")

    if not from_date or not to_date:
        from_date, to_date = _build_dates(from_date, to_date)

    headers = {
        "Authorization": f"ApiToken {api_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query_string,
        "fromDate": from_date,
        "toDate": to_date,
        "limit": 20000,
    }

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
        init_url = DEEP_VISIBILITY_INIT.format(version=version)
        t0 = time.time()

        resp = None
        for retry in range(4):
            resp = await client.post(init_url, json=payload)
            if resp.status_code == 429:
                wait = (retry + 1) * 10
                logger.warning("S1 rate-limited (429), retrying in %ds (attempt %d/4)", wait, retry + 1)
                await asyncio.sleep(wait)
                continue
            break

        if resp.status_code != 200:
            body = resp.text
            logger.error("S1 init-query failed: HTTP %d — %s", resp.status_code, body)
            raise ValueError(f"SentinelOne returned HTTP {resp.status_code}: {body}")

        query_id = resp.json().get("data", {}).get("queryId")
        if not query_id:
            raise ValueError(f"S1 init-query did not return a queryId: {resp.text}")

        logger.info("S1 DV query initiated: queryId=%s", query_id)
        set_progress(history_id, 5, "Query submitted to SentinelOne")

        status_url = DEEP_VISIBILITY_STATUS.format(version=version)
        max_polls = 300
        for attempt in range(max_polls):
            await asyncio.sleep(0.3 if attempt < 15 else (0.5 if attempt < 40 else 1))
            if history_id and is_cancelled(history_id):
                clear_cancelled(history_id)
                clear_progress(history_id)
                raise asyncio.CancelledError("Query cancelled by user")
            status_resp = await client.get(status_url, params={"queryId": query_id})
            if status_resp.status_code != 200:
                raise ValueError(f"SentinelOne status check failed: HTTP {status_resp.status_code}")
            status_data = status_resp.json().get("data", {})
            state = status_data.get("responseState", "")
            progress_pct = status_data.get("progressStatus", 0)
            set_progress(history_id, max(5, min(int(progress_pct * 0.8), 80)), f"S1 processing ({int(progress_pct)}%)")
            if state == "FINISHED":
                set_progress(history_id, 80, "Fetching results")
                logger.info("S1 DV query FINISHED after %d polls (%.1fs)", attempt + 1, time.time() - t0)
                break
            if state == "FAILED":
                clear_progress(history_id)
                raise ValueError(f"S1 DV query failed: {status_data}")
        else:
            clear_progress(history_id)
            raise TimeoutError(f"S1 DV query timed out after {max_polls} polls")

        events_url = DEEP_VISIBILITY_EVENTS.format(version=version)
        all_events = []
        cursor = None
        page_num = 0

        while True:
            params = {"queryId": query_id, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            if history_id and is_cancelled(history_id):
                clear_cancelled(history_id)
                clear_progress(history_id)
                raise asyncio.CancelledError("Query cancelled by user")
            events_resp = await client.get(events_url, params=params)
            if events_resp.status_code != 200:
                raise ValueError(f"SentinelOne events fetch failed: HTTP {events_resp.status_code}")
            body = events_resp.json()
            page_events = body.get("data", [])
            all_events.extend(page_events)
            page_num += 1
            fetch_pct = 80 + min(18, page_num)
            set_progress(history_id, fetch_pct, f"Fetching results ({len(all_events)} events)")
            if on_first_page and page_events:
                try:
                    await on_first_page(all_events)
                except Exception:
                    pass
            pagination = body.get("pagination", {})
            cursor = pagination.get("nextCursor") or pagination.get("cursor")
            if not cursor or not page_events:
                break

        set_progress(history_id, 100, "Complete")
        clear_progress(history_id)
        elapsed = round(time.time() - t0, 2)
        logger.info("S1 DV complete: %d events in %ss", len(all_events), elapsed)

        return {"data": all_events, "count": len(all_events)}
