"""Update Script Engines with Network Activity query to filter for network-related commands"""
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db

init_db()

new_query = 'EventType = "Process Creation" AND ProcessName In ("powershell.exe", "wscript.exe", "cscript.exe") AND (ProcessCmd contains "http" OR ProcessCmd contains "download" OR ProcessCmd contains "invoke-webrequest" OR ProcessCmd contains "net.webclient")'

with get_db() as conn:
    conn.execute("UPDATE stored_queries SET dv_query = ? WHERE id = 44", (new_query,))
    print(f"[44] Script Engines with Network Activity - updated")
    print(f"  New query: {new_query}")
