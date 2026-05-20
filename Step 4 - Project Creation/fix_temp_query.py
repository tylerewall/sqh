"""Fix the 'Process Spawning from Temp Directories' query that has backslash parsing issues."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.database import get_db

FIXED_QUERY = 'EventType = "Process Creation" AND (ProcessCmd contains "Temp" OR ProcessCmd contains "AppData")'

with get_db() as conn:
    row = conn.execute(
        "SELECT id, dv_query FROM stored_queries WHERE name = ?",
        ("Process Spawning from Temp Directories",)
    ).fetchone()
    if row:
        print(f"Current query #{row['id']}: {row['dv_query']}")
        conn.execute(
            "UPDATE stored_queries SET dv_query = ? WHERE id = ?",
            (FIXED_QUERY, row["id"])
        )
        conn.commit()
        print(f"Updated to: {FIXED_QUERY}")
    else:
        print("Query not found")
