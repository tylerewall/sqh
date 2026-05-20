"""
Fix all stored queries based on what we learned:
1. Replace ObjectType = "process" with EventType = "Process Creation"
2. Remove DstIP filters (not valid in scalyr mode)
3. Remove IS NOT EMPTY (not valid)
4. Remove any other fields that silently fail in scalyr mode
"""
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db

init_db()

# Known field replacements for scalyr mode
FIXES = [
    ('ObjectType = "process"', 'EventType = "Process Creation"'),
    ("ObjectType = 'process'", 'EventType = "Process Creation"'),
    (' AND DstIP != ""', ''),
    (' AND DstIP IS NOT EMPTY', ''),
    (' AND DstIP is not empty', ''),
    ('DstIP != "" AND ', ''),
    ('IS NOT EMPTY', '!= ""'),
]

with get_db() as conn:
    rows = conn.execute("SELECT id, name, dv_query FROM stored_queries").fetchall()
    print(f"Total stored queries: {len(rows)}\n")
    
    updated = 0
    for r in rows:
        original = r["dv_query"]
        q = original
        
        for old, new in FIXES:
            if old in q:
                q = q.replace(old, new)
        
        # Clean up any double spaces or trailing AND
        q = q.strip()
        while "  " in q:
            q = q.replace("  ", " ")
        if q.endswith(" AND"):
            q = q[:-4].strip()
        if q.startswith("AND "):
            q = q[4:].strip()
        
        if q != original:
            conn.execute("UPDATE stored_queries SET dv_query = ? WHERE id = ?", (q, r["id"]))
            print(f"[{r['id']}] {r['name']}")
            print(f"  OLD: {original}")
            print(f"  NEW: {q}")
            print()
            updated += 1
        else:
            print(f"[{r['id']}] {r['name']} - OK (no changes needed)")
    
    print(f"\n{'='*50}")
    print(f"Updated {updated} queries, {len(rows) - updated} unchanged")

# Also fix the AI detection query builder in database.py
# The build_ai_s1ql function uses ObjectType = "process" 
print("\n\nNOTE: Also need to update build_ai_s1ql() in database.py")
print('  Change: ObjectType = "process"')
print('  To:     EventType = "Process Creation"')
