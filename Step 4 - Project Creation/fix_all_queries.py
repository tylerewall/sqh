"""Quick test: run a query we KNOW works and check results"""
import httpx
import time
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_config
from app.secrets_manager import decrypt

init_db()
base = get_config("s1_base_url")
token = decrypt(get_config("s1_api_key"))
headers = {"Authorization": f"ApiToken {token}", "Content-Type": "application/json"}

# Test the exact query that's now stored for id=44
query = 'EventType = "Process Creation" AND ProcessName In ("powershell.exe", "wscript.exe", "cscript.exe")'
print(f"Query: {query}")
print(f"Time range: last 1 hour")

p = {"query": query, "fromDate": "2026-05-06T13:50:00.000Z", "toDate": "2026-05-06T14:55:00.000Z", "limit": 20000}
r = httpx.post(f"{base}/web/api/v2.1/dv/init-query", headers=headers, json=p, timeout=30)
print(f"init-query: {r.status_code}")
if r.status_code != 200:
    print(r.text[:300])
    sys.exit(1)

qid = r.json().get("data", {}).get("queryId", "")
print(f"queryId: {qid}")

for attempt in range(60):
    time.sleep(1)
    sr = httpx.get(f"{base}/web/api/v2.1/dv/query-status", headers=headers, params={"queryId": qid}, timeout=10)
    sd = sr.json().get("data", {})
    state = sd.get("responseState", "")
    progress = sd.get("progressStatus", 0)
    if attempt % 5 == 0:
        print(f"  {attempt}s: state={state} progress={progress}")
    if state == "FINISHED":
        print(f"FINISHED after {attempt+1}s")
        break
    if state == "FAILED":
        print(f"FAILED: {sd}")
        sys.exit(1)
else:
    print("Timed out after 60s")
    sys.exit(1)

# Get events
r_events = httpx.get(f"{base}/web/api/v2.1/dv/events", headers=headers, params={"queryId": qid, "limit": 5}, timeout=15)
events = r_events.json().get("data", [])
print(f"\nRESULTS: {len(events)} events returned")
if events:
    for ev in events[:3]:
        print(f"  {ev.get('processName')} | {ev.get('endpointName')} | {ev.get('agentOs')}")
else:
    print("  NO EVENTS - the query returned nothing for this time window")
    print("  Try extending to 24h or check if powershell runs in your environment")
