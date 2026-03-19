"""
Seed script — populates stored queries for Security Query Hub.
Run on the server:  python3 /opt/sqh/app/seed_queries.py
"""

import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import get_db, init_db

QUERIES = [
    # ─── NETWORK ──────────────────────────────────────────────────────
    {
        "name": "DNS Lookups",
        "description": "All DNS resolution events across endpoints.",
        "category": "Network",
        "dv_query": "EventType = \"DNS\"",
        "params": [],
    },
    {
        "name": "DNS Lookup by Domain",
        "description": "Find DNS lookups matching a specific domain or pattern.",
        "category": "Network",
        "dv_query": "EventType = \"DNS\" AND DNSRequest contains \"{domain}\"",
        "params": [
            {"name": "domain", "label": "Domain (full or partial)", "param_type": "text", "placeholder": "e.g. evil.com"},
        ],
    },
    {
        "name": "Outbound Connections to IP",
        "description": "Find all outbound network connections to a specific destination IP.",
        "category": "Network",
        "dv_query": "EventType = \"IP Connect\" AND DstIP = \"{target_ip}\"",
        "params": [
            {"name": "target_ip", "label": "Destination IP", "param_type": "text", "placeholder": "e.g. 10.0.0.1"},
        ],
    },
    {
        "name": "Outbound Connections to Port",
        "description": "Find outbound connections to a specific destination port.",
        "category": "Network",
        "dv_query": "EventType = \"IP Connect\" AND DstPort = \"{port}\"",
        "params": [
            {"name": "port", "label": "Destination Port", "param_type": "text", "placeholder": "e.g. 443"},
        ],
    },
    {
        "name": "Connections to Non-Standard Ports",
        "description": "Outbound connections to ports outside common ranges (not 80, 443, 53).",
        "category": "Network",
        "dv_query": "EventType = \"IP Connect\" AND DstPort != \"80\" AND DstPort != \"443\" AND DstPort != \"53\"",
        "params": [],
    },
    {
        "name": "DNS Lookups by Endpoint",
        "description": "All DNS activity from a specific endpoint.",
        "category": "Network",
        "dv_query": "EventType = \"DNS\" AND EndpointName = \"{hostname}\"",
        "params": [
            {"name": "hostname", "label": "Endpoint Name", "param_type": "text", "placeholder": "e.g. DESKTOP-ABC123"},
        ],
    },

    # ─── PROCESS / ENDPOINT ───────────────────────────────────────────
    {
        "name": "Process by Name",
        "description": "Find process execution events matching a specific process name.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND ProcessName contains \"{process_name}\"",
        "params": [
            {"name": "process_name", "label": "Process Name", "param_type": "text", "placeholder": "e.g. powershell"},
        ],
    },
    {
        "name": "PowerShell Execution",
        "description": "All PowerShell process executions across endpoints.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND (ProcessName contains \"powershell\" OR ProcessName contains \"pwsh\")",
        "params": [],
    },
    {
        "name": "CMD Execution",
        "description": "All cmd.exe process executions across endpoints.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"cmd.exe\"",
        "params": [],
    },
    {
        "name": "Process with Command Line Keyword",
        "description": "Search for processes whose command-line arguments contain a keyword.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND ProcessCmd contains \"{keyword}\"",
        "params": [
            {"name": "keyword", "label": "Command Line Keyword", "param_type": "text", "placeholder": "e.g. -encodedcommand"},
        ],
    },
    {
        "name": "Processes on Endpoint",
        "description": "All process events on a specific endpoint.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND EndpointName = \"{hostname}\"",
        "params": [
            {"name": "hostname", "label": "Endpoint Name", "param_type": "text", "placeholder": "e.g. DESKTOP-ABC123"},
        ],
    },
    {
        "name": "Scheduled Task Creation",
        "description": "Detect creation of scheduled tasks (common persistence technique).",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND (ProcessName = \"schtasks.exe\" AND ProcessCmd contains \"/create\")",
        "params": [],
    },
    {
        "name": "Service Installation",
        "description": "Detect new service installations via sc.exe.",
        "category": "Endpoint",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"sc.exe\" AND ProcessCmd contains \"create\"",
        "params": [],
    },

    # ─── FILE ACTIVITY ────────────────────────────────────────────────
    {
        "name": "File Creation Events",
        "description": "All file creation events across endpoints.",
        "category": "File Activity",
        "dv_query": "EventType = \"File Creation\"",
        "params": [],
    },
    {
        "name": "File Created by Name",
        "description": "Find file creation events matching a specific filename.",
        "category": "File Activity",
        "dv_query": "EventType = \"File Creation\" AND FilePath contains \"{filename}\"",
        "params": [
            {"name": "filename", "label": "File Name or Path", "param_type": "text", "placeholder": "e.g. mimikatz"},
        ],
    },
    {
        "name": "Executable File Writes",
        "description": "Files with executable extensions (.exe, .dll, .bat, .ps1) written to disk.",
        "category": "File Activity",
        "dv_query": "EventType = \"File Creation\" AND (FilePath endswithanycase \".exe\" OR FilePath endswithanycase \".dll\" OR FilePath endswithanycase \".bat\" OR FilePath endswithanycase \".ps1\")",
        "params": [],
    },
    {
        "name": "Files Written to Temp Directories",
        "description": "File creation events in temp directories (often used by malware).",
        "category": "File Activity",
        "dv_query": "EventType = \"File Creation\" AND (FilePath contains \"\\\\Temp\\\\\" OR FilePath contains \"/tmp/\")",
        "params": [],
    },
    {
        "name": "File Activity on Endpoint",
        "description": "All file creation events on a specific endpoint.",
        "category": "File Activity",
        "dv_query": "EventType = \"File Creation\" AND EndpointName = \"{hostname}\"",
        "params": [
            {"name": "hostname", "label": "Endpoint Name", "param_type": "text", "placeholder": "e.g. DESKTOP-ABC123"},
        ],
    },

    # ─── IDENTITY / LOGIN ────────────────────────────────────────────
    {
        "name": "Login Events",
        "description": "All login events across endpoints.",
        "category": "Identity",
        "dv_query": "EventType = \"Login\"",
        "params": [],
    },
    {
        "name": "Logins by Username",
        "description": "Login events for a specific user account.",
        "category": "Identity",
        "dv_query": "EventType = \"Login\" AND UserName contains \"{username}\"",
        "params": [
            {"name": "username", "label": "Username", "param_type": "text", "placeholder": "e.g. jsmith"},
        ],
    },
    {
        "name": "Failed Logins",
        "description": "Failed login attempts (potential brute force indicator).",
        "category": "Identity",
        "dv_query": "EventType = \"Login\" AND LoginIsSuccessful = \"false\"",
        "params": [],
    },
    {
        "name": "Failed Logins on Endpoint",
        "description": "Failed login attempts on a specific endpoint.",
        "category": "Identity",
        "dv_query": "EventType = \"Login\" AND LoginIsSuccessful = \"false\" AND EndpointName = \"{hostname}\"",
        "params": [
            {"name": "hostname", "label": "Endpoint Name", "param_type": "text", "placeholder": "e.g. DC01"},
        ],
    },

    # ─── REGISTRY ─────────────────────────────────────────────────────
    {
        "name": "Registry Modification",
        "description": "All registry value modification events.",
        "category": "Registry",
        "dv_query": "EventType = \"Registry Value Modified\"",
        "params": [],
    },
    {
        "name": "Registry Key Search",
        "description": "Registry events involving a specific key path.",
        "category": "Registry",
        "dv_query": "(EventType = \"Registry Value Modified\" OR EventType = \"Registry Key Create\") AND RegistryKeyPath contains \"{key_path}\"",
        "params": [
            {"name": "key_path", "label": "Registry Key Path", "param_type": "text", "placeholder": "e.g. Run"},
        ],
    },
    {
        "name": "Autorun Registry Changes",
        "description": "Modifications to common autorun registry locations (persistence detection).",
        "category": "Registry",
        "dv_query": "EventType = \"Registry Value Modified\" AND (RegistryKeyPath contains \"\\\\Run\" OR RegistryKeyPath contains \"\\\\RunOnce\")",
        "params": [],
    },

    # ─── THREAT HUNTING ───────────────────────────────────────────────
    {
        "name": "Encoded PowerShell Commands",
        "description": "PowerShell invocations using encoded commands (common obfuscation technique).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND ProcessName contains \"powershell\" AND (ProcessCmd contains \"-enc\" OR ProcessCmd contains \"-encodedcommand\")",
        "params": [],
    },
    {
        "name": "LOLBIN Execution — certutil",
        "description": "Certutil.exe used for downloading (living-off-the-land technique).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"certutil.exe\" AND (ProcessCmd contains \"urlcache\" OR ProcessCmd contains \"decode\")",
        "params": [],
    },
    {
        "name": "LOLBIN Execution — mshta",
        "description": "Mshta.exe process execution (often abused for code execution).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"mshta.exe\"",
        "params": [],
    },
    {
        "name": "LOLBIN Execution — wmic",
        "description": "Wmic.exe process execution (remote execution and recon).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"wmic.exe\"",
        "params": [],
    },
    {
        "name": "LOLBIN Execution — regsvr32",
        "description": "Regsvr32.exe with remote script loading (squiblydoo technique).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND ProcessName = \"regsvr32.exe\" AND (ProcessCmd contains \"http\" OR ProcessCmd contains \"/i:\")",
        "params": [],
    },
    {
        "name": "Suspicious Parent-Child Process",
        "description": "Detect processes spawned by common phishing vectors (Word, Excel, Outlook).",
        "category": "Threat Hunting",
        "dv_query": "ObjectType = \"process\" AND (ParentProcessName = \"winword.exe\" OR ParentProcessName = \"excel.exe\" OR ParentProcessName = \"outlook.exe\") AND (ProcessName = \"cmd.exe\" OR ProcessName = \"powershell.exe\" OR ProcessName = \"wscript.exe\" OR ProcessName = \"cscript.exe\")",
        "params": [],
    },
    {
        "name": "Activity by SHA1 Hash",
        "description": "Find all events related to a specific file hash.",
        "category": "Threat Hunting",
        "dv_query": "FileSHA1 = \"{sha1}\"",
        "params": [
            {"name": "sha1", "label": "SHA1 Hash", "param_type": "text", "placeholder": "e.g. da39a3ee5e6b4b0d3255bfef95601890afd80709"},
        ],
    },
    {
        "name": "Full Endpoint Timeline",
        "description": "All events from a specific endpoint (broad investigation query).",
        "category": "Threat Hunting",
        "dv_query": "EndpointName = \"{hostname}\"",
        "params": [
            {"name": "hostname", "label": "Endpoint Name", "param_type": "text", "placeholder": "e.g. DESKTOP-ABC123"},
        ],
    },
]


def seed():
    init_db()
    with get_db() as conn:
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM stored_queries").fetchone()["cnt"]
        if existing > 0:
            print(f"Database already has {existing} stored queries. Skipping seed.")
            print("To re-seed, delete existing queries first or drop the stored_queries table.")
            return

        for i, q in enumerate(QUERIES):
            cursor = conn.execute(
                "INSERT INTO stored_queries (name, description, category, dv_query, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (q["name"], q["description"], q["category"], q["dv_query"], 1),
            )
            query_id = cursor.lastrowid
            for j, p in enumerate(q["params"]):
                conn.execute(
                    "INSERT INTO query_params (query_id, name, label, param_type, placeholder, options, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (query_id, p["name"], p["label"], p["param_type"], p.get("placeholder", ""), None, j),
                )
            print(f"  [{q['category']}] {q['name']}")

    print(f"\nSeeded {len(QUERIES)} stored queries.")


if __name__ == "__main__":
    seed()
