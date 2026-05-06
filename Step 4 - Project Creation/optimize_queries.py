"""Optimize all stored queries by adding ObjectType filter and fixing syntax issues."""
import sys
import os
sys.path.insert(0, "/opt/sqh")

from app.database import init_db, get_db

init_db()

with get_db() as conn:
    rows = conn.execute("SELECT id, name, dv_query FROM stored_queries ORDER BY id").fetchall()
    
    updated = 0
    for row in rows:
        qid = row["id"]
        name = row["name"]
        query = row["dv_query"]
        original = query
        
        if not query or query.strip().startswith("|"):
            # Skip PowerQuery or empty
            print(f"  SKIP [{qid}] {name} (PowerQuery or empty)")
            continue

        # Fix common issues
        # 1. Remove line breaks
        query = " ".join(query.split())
        
        # 2. Fix CONTAINS -> contains
        query = query.replace(" CONTAINS ", " contains ")
        query = query.replace(" REGEXP ", " RegExp ")
        
        # 3. Fix invalid field names
        query = query.replace("TargetProcessName", "TgtProcName")
        query = query.replace("TargetProcessCmd", "TgtProcCmdLine")
        query = query.replace("SourceProcessName", "ProcessName")
        query = query.replace("SourceProcessCmd", "ProcessCmd")
        
        # 4. Add ObjectType = "process" if not already present and query is process-related
        has_object_type = 'ObjectType' in query
        if not has_object_type:
            # Detect if it's a process query based on field names used
            process_fields = [
                "ProcessName", "ProcessCmd", "ProcessImagePath", "ParentProcessName",
                "TgtProcName", "TgtProcCmdLine", "UserName", "SignedStatus",
                "ProcessIntegrityLevel", "SrcProcName", "SrcProcCmdLine",
            ]
            is_process_query = any(f in query for f in process_fields)
            
            if is_process_query:
                query = 'ObjectType = "process" AND ' + query
        
        # 5. Optimize multiple ORs on same field to use In operator
        # (only for simple ProcessName = "x" OR ProcessName = "y" patterns)
        import re
        # Find patterns like: ProcessName = "a" OR ProcessName = "b" OR ProcessName = "c"
        for field in ["ProcessName", "ParentProcessName", "TgtProcName"]:
            pattern = rf'(?:\(?){field}\s*=\s*"([^"]+)"(?:\s+OR\s+{field}\s*=\s*"([^"]+)")+(?:\)?)'
            match = re.search(pattern, query)
            if match:
                # Extract all values for this field
                all_values = re.findall(rf'{field}\s*=\s*"([^"]+)"', query)
                if len(all_values) >= 3:
                    # Build In clause
                    in_clause = f'{field} In (' + ', '.join(f'"{v}"' for v in all_values) + ')'
                    # Replace the OR chain
                    or_chain = re.search(rf'\(?{field}\s*=\s*"[^"]+"(?:\s+OR\s+{field}\s*=\s*"[^"]+")+\)?', query)
                    if or_chain:
                        old_text = or_chain.group()
                        # Remove outer parens if present
                        query = query.replace(old_text, in_clause)
        
        if query != original:
            conn.execute("UPDATE stored_queries SET dv_query = ?, modified_at = datetime('now') WHERE id = ?", (query, qid))
            updated += 1
            print(f"  FIXED [{qid}] {name}")
            if 'ObjectType' in query and 'ObjectType' not in original:
                print(f"         + Added ObjectType filter")
            if query != original:
                print(f"         → {query[:120]}{'...' if len(query) > 120 else ''}")
        else:
            print(f"  OK    [{qid}] {name}")
    
    print(f"\nDone. Updated {updated}/{len(rows)} queries.")
