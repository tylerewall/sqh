"""Fix the 'NTDS.dit Access Attempts' query that has OR/AND parsing issues in S1QL."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.database import get_db

FIXED_QUERY = 'EventType = "Process Creation" AND (ProcessCmd contains "ntds.dit" OR ProcessCmd contains "ntdsutil" OR (ProcessCmd contains "vssadmin" AND ProcessCmd contains "shadow"))'

with get_db() as conn:
    row = conn.execute(
        "SELECT id, dv_query FROM stored_queries WHERE name = ?",
        ("NTDS.dit Access Attempts",)
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
