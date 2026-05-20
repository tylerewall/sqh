"""Fix Office Applications Spawning Shells - broaden to show all Office child processes"""
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db

init_db()

new_query = 'EventType = "Process Creation" AND ParentProcessName In ("winword.exe", "excel.exe", "outlook.exe", "powerpnt.exe")'

with get_db() as conn:
    conn.execute("UPDATE stored_queries SET dv_query = ?, description = ? WHERE id = 40", (
        new_query,
        "Detects any process spawned by Microsoft Office applications (Word, Excel, Outlook, PowerPoint). Useful for identifying macro execution, plugin activity, or suspicious child processes.",
    ))
    print(f"[40] Office Applications Spawning Shells - updated")
    print(f"  New query: {new_query}")
