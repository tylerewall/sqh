"""Add new threat hunting queries organized into folders.
Queries have been converted from PowerQuery/S1QL 2.0 to working S1QL 1.0 Deep Visibility syntax."""
import sys
sys.path.insert(0, "/opt/sqh")
from app.database import init_db, get_db

init_db()

# Define folders
folders = [
    ("Execution & LOLBins", 1),
    ("Persistence", 2),
    ("Lateral Movement", 3),
    ("Discovery & Reconnaissance", 4),
    ("Defense Evasion", 5),
    ("Credential Access", 6),
    ("Command & Control", 7),
]

# Queries: (folder_name, name, description, dv_query, category)
queries = [
    # ── Execution & LOLBins ──
    ("Execution & LOLBins", "Encoded PowerShell Execution",
     "Detects PowerShell running with encoded/obfuscated commands (-enc, -encodedcommand). Common in fileless malware and post-exploitation frameworks.",
     'EventType = "Process Creation" AND ProcessName = "powershell.exe" AND (ProcessCmd contains "-enc" OR ProcessCmd contains "-encodedcommand" OR ProcessCmd contains "-e ")',
     "Execution"),

    ("Execution & LOLBins", "Rundll32/Regsvr32 Running Scripts",
     "Detects rundll32 or regsvr32 executing JavaScript, MSHTML, or RunHTMLApplication — common LOLBin abuse for execution.",
     'EventType = "Process Creation" AND ProcessName In ("rundll32.exe", "regsvr32.exe") AND (ProcessCmd contains "javascript" OR ProcessCmd contains "mshtml" OR ProcessCmd contains "runhtmlapplication")',
     "Execution"),

    ("Execution & LOLBins", "MSHTA Executing Remote Content",
     "Detects mshta.exe fetching and executing remote HTA files via HTTP/HTTPS/FTP. Used to bypass application whitelisting.",
     'EventType = "Process Creation" AND ProcessName = "mshta.exe" AND (ProcessCmd contains "http" OR ProcessCmd contains "ftp")',
     "Execution"),

    ("Execution & LOLBins", "CertUtil Downloading Files",
     "Detects certutil.exe being used to download files (urlcache). A classic LOLBin technique for fetching malicious payloads.",
     'EventType = "Process Creation" AND ProcessName = "certutil.exe" AND ProcessCmd contains "urlcache"',
     "Execution"),

    ("Execution & LOLBins", "BITSAdmin File Transfer",
     "Detects bitsadmin.exe used for downloading files — another common LOLBin for payload delivery.",
     'EventType = "Process Creation" AND ProcessName = "bitsadmin.exe" AND (ProcessCmd contains "/transfer" OR ProcessCmd contains "download")',
     "Execution"),

    # ── Persistence ──
    ("Persistence", "Scheduled Task Creation (schtasks)",
     "Detects creation of scheduled tasks via schtasks.exe. Commonly used for persistence by attackers.",
     'EventType = "Process Creation" AND ProcessName = "schtasks.exe" AND ProcessCmd contains "/create"',
     "Persistence"),

    ("Persistence", "Service Creation via SC.exe",
     "Detects new Windows service creation via sc.exe. Attackers install malicious services for persistence.",
     'EventType = "Process Creation" AND ProcessName = "sc.exe" AND ProcessCmd contains "create"',
     "Persistence"),

    ("Persistence", "Registry Run Key Modification",
     "Detects reg.exe adding entries to Run/RunOnce keys for persistence.",
     'EventType = "Process Creation" AND ProcessName = "reg.exe" AND ProcessCmd contains "add" AND (ProcessCmd contains "\\Run" OR ProcessCmd contains "RunOnce")',
     "Persistence"),

    # ── Lateral Movement ──
    ("Lateral Movement", "PsExec-Style Execution",
     "Detects PsExec usage or processes accessing admin$/C$ shares — indicators of lateral movement.",
     'EventType = "Process Creation" AND (ProcessCmd contains "psexec" OR ProcessCmd contains "\\\\admin$" OR ProcessCmd contains "\\\\c$")',
     "Lateral Movement"),

    ("Lateral Movement", "WMI Remote Execution",
     "Detects wmic.exe used for remote process execution — a common lateral movement technique.",
     'EventType = "Process Creation" AND ProcessName = "wmic.exe" AND (ProcessCmd contains "/node:" OR ProcessCmd contains "process call create")',
     "Lateral Movement"),

    ("Lateral Movement", "Remote Desktop Connection",
     "Detects mstsc.exe (RDP client) being launched, which may indicate lateral movement attempts.",
     'EventType = "Process Creation" AND ProcessName = "mstsc.exe"',
     "Lateral Movement"),

    # ── Discovery & Reconnaissance ──
    ("Discovery & Reconnaissance", "Net User/Group Enumeration",
     "Detects net.exe used to enumerate users, groups, or domain info — common reconnaissance activity.",
     'EventType = "Process Creation" AND ProcessName = "net.exe" AND (ProcessCmd contains "user" OR ProcessCmd contains "localgroup" OR ProcessCmd contains "group" OR ProcessCmd contains "domain")',
     "Discovery"),

    ("Discovery & Reconnaissance", "System Recon Commands",
     "Detects reconnaissance tool chain: whoami, ipconfig, systeminfo, nltest, net.exe. Multiple hits suggest post-compromise enumeration.",
     'EventType = "Process Creation" AND ProcessName In ("whoami.exe", "ipconfig.exe", "systeminfo.exe", "nltest.exe", "net.exe", "net1.exe")',
     "Discovery"),

    ("Discovery & Reconnaissance", "Active Directory Enumeration",
     "Detects tools commonly used for AD enumeration (dsquery, csvde, ldifde, adfind).",
     'EventType = "Process Creation" AND ProcessName In ("dsquery.exe", "csvde.exe", "ldifde.exe", "adfind.exe", "nltest.exe")',
     "Discovery"),

    # ── Defense Evasion ──
    ("Defense Evasion", "Process Spawning from Temp Directories",
     "Detects processes launched from Temp or AppData directories — common for malware droppers.",
     'EventType = "Process Creation" AND (ProcessCmd contains "\\Temp\\" OR ProcessCmd contains "\\AppData\\Local\\Temp")',
     "Defense Evasion"),

    ("Defense Evasion", "Timestomping via PowerShell",
     "Detects PowerShell commands that modify file timestamps (Set-ItemProperty, CreationTime, LastWriteTime).",
     'EventType = "Process Creation" AND ProcessName = "powershell.exe" AND (ProcessCmd contains "CreationTime" OR ProcessCmd contains "LastWriteTime" OR ProcessCmd contains "LastAccessTime")',
     "Defense Evasion"),

    ("Defense Evasion", "Windows Event Log Clearing",
     "Detects wevtutil.exe clearing event logs — a common anti-forensics technique.",
     'EventType = "Process Creation" AND ProcessName = "wevtutil.exe" AND ProcessCmd contains "cl"',
     "Defense Evasion"),

    # ── Credential Access ──
    ("Credential Access", "Mimikatz-Style Commands",
     "Detects command lines containing Mimikatz module keywords (sekurlsa, lsadump, dcsync, etc.).",
     'EventType = "Process Creation" AND (ProcessCmd contains "sekurlsa" OR ProcessCmd contains "lsadump" OR ProcessCmd contains "kerberos::" OR ProcessCmd contains "dcsync" OR ProcessCmd contains "privilege::debug")',
     "Credential Access"),

    ("Credential Access", "Credential Vault Access",
     "Detects vaultcmd.exe or cmdkey.exe used to enumerate or manipulate stored credentials.",
     'EventType = "Process Creation" AND ProcessName In ("vaultcmd.exe", "cmdkey.exe")',
     "Credential Access"),

    ("Credential Access", "NTDS.dit Access Attempts",
     "Detects commands targeting NTDS.dit (Active Directory database) for offline credential extraction.",
     'EventType = "Process Creation" AND (ProcessCmd contains "ntds.dit" OR ProcessCmd contains "ntdsutil" OR ProcessCmd contains "vssadmin" AND ProcessCmd contains "shadow")',
     "Credential Access"),

    # ── Command & Control ──
    ("Command & Control", "PowerShell Web Requests",
     "Detects PowerShell making outbound web requests (Invoke-WebRequest, Net.WebClient, DownloadString, etc.).",
     'EventType = "Process Creation" AND ProcessName = "powershell.exe" AND (ProcessCmd contains "Invoke-WebRequest" OR ProcessCmd contains "Net.WebClient" OR ProcessCmd contains "DownloadString" OR ProcessCmd contains "DownloadFile" OR ProcessCmd contains "Start-BitsTransfer")',
     "Command & Control"),

    ("Command & Control", "Suspicious Process Network Keywords",
     "Detects processes with command lines referencing unusual network/proxy/tunnel keywords.",
     'EventType = "Process Creation" AND (ProcessCmd contains "proxy" OR ProcessCmd contains "tunnel" OR ProcessCmd contains "socks" OR ProcessCmd contains "ngrok" OR ProcessCmd contains "cloudflared")',
     "Command & Control"),
]

with get_db() as conn:
    # Create folders
    folder_ids = {}
    for fname, sort_order in folders:
        existing = conn.execute("SELECT id FROM query_folders WHERE name = ?", (fname,)).fetchone()
        if existing:
            folder_ids[fname] = existing["id"]
            print(f"  Folder '{fname}' already exists (id={existing['id']})")
        else:
            cur = conn.execute(
                "INSERT INTO query_folders (name, sort_order) VALUES (?, ?)",
                (fname, sort_order + 10),  # offset to not conflict with existing
            )
            folder_ids[fname] = cur.lastrowid
            print(f"  Created folder '{fname}' (id={cur.lastrowid})")

    print()

    # Add queries
    added = 0
    for folder_name, name, description, dv_query, category in queries:
        # Check if query already exists by name
        existing = conn.execute("SELECT id FROM stored_queries WHERE name = ?", (name,)).fetchone()
        if existing:
            print(f"  [skip] '{name}' already exists (id={existing['id']})")
            continue

        folder_id = folder_ids.get(folder_name)
        conn.execute(
            "INSERT INTO stored_queries (name, description, category, dv_query, folder_id, created_by) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (name, description, category, dv_query, folder_id),
        )
        added += 1
        print(f"  [added] '{name}' -> {folder_name}")

    print(f"\nDone: {added} queries added across {len(folders)} folders")
