"""Diagnostic: verify stored queries and test them against S1 API"""
import httpx
import time
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db, get_config
from app.secrets_manager import decrypt

init_db()

print("=== STORED QUERIES IN DATABASE ===\n")
with get_db() as conn:
    rows = conn.execute("SELECT id, name, dv_query FROM stored_queries ORDER BY id").fetchall()
    for r in rows:
        print(f"[{r['id']}] {r['name']}")
        print(f"    {r['dv_query']}")
        print()

print("\n=== TESTING QUERY AGAINST S1 API ===\n")

base = get_config("s1_base_url")
token = decrypt(get_config("s1_api_key"))
headers = {"Authorization": f"ApiToken {token}", "Content-Type": "application/json"}

# Test a simple query we know should work
query = 'EventType = "Process Creation" AND ProcessName = "powershell.exe"'
print(f"Test query: {query}")
print(f"Base URL: {base}")

from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
to_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
from_date = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
print(f"Time range: {from_date} to {to_date} (last 24h)")

payload = {"query": query, "fromDate": from_date, "toDate": to_date, "limit": 20000}
r = httpx.post(f"{base}/web/api/v2.1/dv/init-query", headers=headers, json=payload, timeout=30)
print(f"init-query: HTTP {r.status_code}")
if r.status_code != 200:
    print(f"ERROR: {r.text[:500]}")
    sys.exit(1)

qid = r.json().get("data", {}).get("queryId", "")
print(f"queryId: {qid}")

for attempt in range(90):
    time.sleep(1)
    sr = httpx.get(f"{base}/web/api/v2.1/dv/query-status", headers=headers, params={"queryId": qid}, timeout=10)
    sd = sr.json().get("data", {})
    state = sd.get("responseState", "")
    progress = sd.get("progressStatus", 0)
    if attempt % 5 == 0:
        print(f"  [{attempt}s] state={state} progress={progress}%")
    if state == "FINISHED":
        print(f"  FINISHED after {attempt+1}s")
        break
    if state == "FAILED":
        print(f"  FAILED: {sd}")
        sys.exit(1)
else:
    print("  Timed out after 90s")
    sys.exit(1)

r_events = httpx.get(f"{base}/web/api/v2.1/dv/events", headers=headers, params={"queryId": qid, "limit": 10}, timeout=15)
events = r_events.json().get("data", [])
print(f"\nRESULTS: {len(events)} events returned")
if events:
    for ev in events[:5]:
        pname = ev.get("processName", "?")
        endpoint = ev.get("agentComputerName") or ev.get("endpointName", "?")
        os_type = ev.get("agentOs", "?")
        cmd = (ev.get("processCmd") or "")[:80]
        print(f"  {pname} | {endpoint} | OS={os_type}")
        print(f"    cmd: {cmd}")
else:
    print("  NO EVENTS returned.")
    print("  This means either:")
    print("    1. No PowerShell ran in the last 24h (unlikely for a Windows fleet)")
    print("    2. The API token doesn't have Deep Visibility access")
    print("    3. The S1 instance has fully deprecated DV and we need PowerQuery")
    
    # Try a broader query
    print("\n  Trying an even broader query: EventType = \"Process Creation\" (any process)...")
    payload2 = {"query": 'EventType = "Process Creation"', "fromDate": from_date, "toDate": to_date, "limit": 20000}
    r2 = httpx.post(f"{base}/web/api/v2.1/dv/init-query", headers=headers, json=payload2, timeout=30)
    if r2.status_code == 200:
        qid2 = r2.json().get("data", {}).get("queryId", "")
        for a in range(60):
            time.sleep(1)
            sr2 = httpx.get(f"{base}/web/api/v2.1/dv/query-status", headers=headers, params={"queryId": qid2}, timeout=10)
            if sr2.json().get("data", {}).get("responseState") == "FINISHED":
                break
        r_ev2 = httpx.get(f"{base}/web/api/v2.1/dv/events", headers=headers, params={"queryId": qid2, "limit": 5}, timeout=15)
        ev2 = r_ev2.json().get("data", [])
        print(f"  Broad query returned {len(ev2)} events")
        for e in ev2[:3]:
            print(f"    {e.get('processName')} | {e.get('agentComputerName')} | {e.get('agentOs')}")
