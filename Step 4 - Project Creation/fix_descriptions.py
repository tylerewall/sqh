"""Add descriptions to all stored queries that are missing them."""
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db

init_db()

descriptions = {
    39: "Detects PowerShell execution with suspicious command-line arguments commonly used in attacks: encoded commands (-enc), Invoke-Expression (iex), web downloads (Invoke-WebRequest, DownloadString), and hidden window execution.",
    40: "Detects any child process spawned by Microsoft Office applications (Word, Excel, Outlook, PowerPoint). Useful for identifying macro execution, plugin activity, or suspicious child processes that may indicate exploitation.",
    41: "Detects processes launched from user-writable paths (AppData, Temp, Downloads) for a specific user. These paths are commonly abused by malware droppers and unauthorized executables.",
    42: "Detects scheduled task creation via schtasks.exe with the /create flag. Attackers commonly use scheduled tasks for persistence, privilege escalation, and lateral movement.",
    43: "Identifies unusual or rare processes running on a specific endpoint by excluding common system processes (explorer, svchost, services, lsass). Useful for hunting unknown or anomalous binaries.",
    44: "Detects script engines (PowerShell, wscript, cscript) with command lines containing network-related keywords (HTTP, download, Invoke-WebRequest, Net.WebClient). Indicates potential data exfiltration or payload delivery.",
    45: "Detects credential dumping attempts targeting LSASS — specifically procdump, rundll32, or PowerShell with 'lsass' in the command line. Covers common techniques like procdump -ma lsass and comsvcs MiniDump.",
    46: "Detects explorer.exe spawning command shells (cmd, powershell, mshta) for a specific user. While sometimes legitimate, this pattern can indicate user-initiated suspicious activity or exploitation of explorer.",
    48: "Validates a specific file hash (SHA1) across the environment. Use this to check prevalence of a known-bad or suspicious binary across all monitored endpoints.",
}

with get_db() as conn:
    rows = conn.execute("SELECT id, name, description FROM stored_queries ORDER BY id").fetchall()
    updated = 0
    for r in rows:
        qid = r["id"]
        current_desc = r["description"] or ""
        if current_desc.strip():
            continue  # Already has a description

        if qid in descriptions:
            conn.execute("UPDATE stored_queries SET description = ? WHERE id = ?", (descriptions[qid], qid))
            print(f"  [updated] #{qid} {r['name']}")
            updated += 1
        else:
            print(f"  [missing] #{qid} {r['name']} - no description defined")

    print(f"\nDone: {updated} descriptions added")
    
    # Show final state
    print("\n=== ALL QUERIES ===")
    rows = conn.execute("SELECT id, name, description FROM stored_queries ORDER BY id").fetchall()
    for r in rows:
        desc = (r["description"] or "")[:80]
        status = "OK" if desc else "MISSING"
        print(f"  [{status}] #{r['id']} {r['name']}")
        if desc:
            print(f"         {desc}...")
