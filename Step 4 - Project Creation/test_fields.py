"""Test which S1QL fields actually return data in this instance"""
import httpx
import time
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_config
from app.secrets_manager import decrypt
from datetime import datetime, timedelta, timezone

init_db()
base = get_config("s1_base_url")
token = decrypt(get_config("s1_api_key"))
headers = {"Authorization": f"ApiToken {token}", "Content-Type": "application/json"}

now = datetime.now(timezone.utc)
to_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
from_date = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

test_queries = [
    ("ParentProcessName (explorer)", 'EventType = "Process Creation" AND ParentProcessName = "explorer.exe"'),
    ("ParentProcessName (svchost)", 'EventType = "Process Creation" AND ParentProcessName = "svchost.exe"'),
    ("ProcessName only (cmd)", 'EventType = "Process Creation" AND ProcessName = "cmd.exe"'),
    ("ProcessCmd contains (powershell)", 'EventType = "Process Creation" AND ProcessCmd contains "powershell"'),
    ("EndpointName exists check", 'EventType = "Process Creation" AND ProcessName = "powershell.exe" AND EndpointName != ""'),
    ("UserName field", 'EventType = "Process Creation" AND ProcessName = "powershell.exe" AND UserName != ""'),
]

print(f"Time range: {from_date} to {to_date} (last 7 days)\n")

for label, query in test_queries:
    print(f"--- {label} ---")
    print(f"    {query}")
    
    payload = {"query": query, "fromDate": from_date, "toDate": to_date, "limit": 20000}
    r = httpx.post(f"{base}/web/api/v2.1/dv/init-query", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        print(f"    ERROR: HTTP {r.status_code} - {r.text[:200]}")
        print()
        continue
    
    qid = r.json().get("data", {}).get("queryId", "")
    
    # Wait for completion
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
        print(f"    WORKS - {total} total events")
        ev = events[0]
        print(f"    Sample: {ev.get('processName')} | parent={ev.get('parentProcessName', 'N/A')} | endpoint={ev.get('agentComputerName', 'N/A')}")
    else:
        print(f"    0 RESULTS - field may not work in scalyr mode")
    print()
