"""Test Unsigned Binaries query and broader variants"""
import httpx
import time
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db, get_config
from app.secrets_manager import decrypt
from datetime import datetime, timedelta, timezone

init_db()
base = get_config("s1_base_url")
token = decrypt(get_config("s1_api_key"))
headers = {"Authorization": f"ApiToken {token}", "Content-Type": "application/json"}

now = datetime.now(timezone.utc)
to_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
from_date = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

# Show what's stored
with get_db() as conn:
    row = conn.execute("SELECT dv_query FROM stored_queries WHERE id = 41").fetchone()
    print(f"Stored query #41: {row['dv_query']}\n")

test_queries = [
    ("Stored query (needs username param)", 'EventType = "Process Creation" AND (ProcessCmd contains "AppData" OR ProcessCmd contains "Temp" OR ProcessCmd contains "Downloads")'),
    ("Just AppData in cmd", 'EventType = "Process Creation" AND ProcessCmd contains "AppData"'),
    ("Just Temp in cmd", 'EventType = "Process Creation" AND ProcessCmd contains "Temp"'),
    ("Just Downloads in cmd", 'EventType = "Process Creation" AND ProcessCmd contains "Downloads"'),
]

print(f"Time range: {from_date} to {to_date} (last 14 days)\n")

for label, query in test_queries:
    print(f"--- {label} ---")
    print(f"    {query}")

    payload = {"query": query, "fromDate": from_date, "toDate": to_date, "limit": 20000}
    r = httpx.post(f"{base}/web/api/v2.1/dv/init-query", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        print(f"    ERROR: HTTP {r.status_code} - {r.text[:200]}")
        print()
        time.sleep(2)
        continue

    qid = r.json().get("data", {}).get("queryId", "")

    finished = False
    for attempt in range(90):
        time.sleep(1)
        sr = httpx.get(f"{base}/web/api/v2.1/dv/query-status", headers=headers, params={"queryId": qid}, timeout=10)
        sd = sr.json().get("data", {})
        state = sd.get("responseState", "")
        if state == "FINISHED":
            finished = True
            break
        if state == "FAILED":
            print(f"    FAILED: {sd}")
            break

    if not finished:
        print(f"    Did not finish in 90s")
        print()
        continue

    r_events = httpx.get(f"{base}/web/api/v2.1/dv/events", headers=headers, params={"queryId": qid, "limit": 5}, timeout=15)
    events = r_events.json().get("data", [])
    total = r_events.json().get("pagination", {}).get("totalItems", len(events))

    if events:
        print(f"    RESULTS: {total} total events")
        for ev in events[:3]:
            proc = ev.get("processName", "?")
            cmd = (ev.get("processCmd") or "")[:100]
            endpoint = ev.get("agentComputerName", "?")
            user = ev.get("user") or ev.get("userName") or "?"
            print(f"      {proc} | {endpoint} | user={user}")
            print(f"        cmd: {cmd}")
    else:
        print(f"    0 RESULTS")
    print()
    time.sleep(2)
