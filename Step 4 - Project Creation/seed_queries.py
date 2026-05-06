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
    {
        "name": "OpenClaw / ClawdBot / MoltBot Detection",
        "description": "Detect openclaw, clawdbot, or moltbot process activity across endpoints.",
        "category": "Threat Hunting",
        "dv_query": "ProcessName ContainsCIS \"openclaw\" OR ProcessCmd ContainsCIS \"openclaw\" OR ProcessName ContainsCIS \"clawdbot\" OR ProcessCmd ContainsCIS \"clawdbot\" OR ProcessName ContainsCIS \"moltbot\" OR ProcessCmd ContainsCIS \"moltbot\"",
        "params": [],
    },
    {
        "name": "AI Tool Usage Detection (PowerQuery)",
        "description": "Detect AI/LLM tool process creation across endpoints — Claude, ChatGPT, Copilot, Gemini, Ollama, Cursor, Codeium, Tabnine, Mistral, Perplexity, Hugging Face, Stable Diffusion, LM Studio, Continue.dev, Aider, Cohere. Requires PowerQuery / Data Lake license.",
        "category": "Threat Hunting",
        "dv_query": (
            '| filter( event.type == "Process Creation" AND ('
            ' ( src.process.cmdline contains:anycase( "claude", "anthropic", "claude-cli", "claude-code" )'
            ' OR tgt.process.cmdline contains:anycase( "claude", "anthropic", "claude-cli", "claude-code" )'
            ' OR osSrc.process.cmdline contains:anycase( "claude", "anthropic", "claude-cli", "claude-code" ) )'
            ' OR ( src.process.image.path contains:anycase( ".claude/", "claude-cli", "claude_desktop", "anthropic" )'
            ' OR tgt.process.image.path contains:anycase( ".claude/", "claude-cli", "claude_desktop", "anthropic" )'
            ' OR osSrc.process.image.path contains:anycase( ".claude/", "claude-cli", "claude_desktop", "anthropic" )'
            ' OR src.process.parent.image.path contains:anycase( ".claude/", "claude-cli", "claude_desktop", "anthropic" )'
            ' OR osSrc.process.parent.image.path contains:anycase( ".claude/", "claude-cli", "claude_desktop", "anthropic" ) )'
            ' OR ( src.process.cmdline contains:anycase( "openai", "chatgpt", "gpt-4", "gpt-3", "openai-cli", "sgpt" )'
            ' OR tgt.process.cmdline contains:anycase( "openai", "chatgpt", "gpt-4", "gpt-3", "openai-cli", "sgpt" )'
            ' OR osSrc.process.cmdline contains:anycase( "openai", "chatgpt", "gpt-4", "gpt-3", "openai-cli", "sgpt" ) )'
            ' OR ( src.process.image.path contains:anycase( ".openai/", "chatgpt", "openai" )'
            ' OR tgt.process.image.path contains:anycase( ".openai/", "chatgpt", "openai" )'
            ' OR osSrc.process.image.path contains:anycase( ".openai/", "chatgpt", "openai" )'
            ' OR src.process.parent.image.path contains:anycase( ".openai/", "chatgpt", "openai" )'
            ' OR osSrc.process.parent.image.path contains:anycase( ".openai/", "chatgpt", "openai" ) )'
            ' OR ( src.process.cmdline contains:anycase( "copilot", "github-copilot", "gh copilot" )'
            ' OR tgt.process.cmdline contains:anycase( "copilot", "github-copilot", "gh copilot" )'
            ' OR osSrc.process.cmdline contains:anycase( "copilot", "github-copilot", "gh copilot" ) )'
            ' OR ( src.process.image.path contains:anycase( "copilot", "github-copilot" )'
            ' OR tgt.process.image.path contains:anycase( "copilot", "github-copilot" )'
            ' OR osSrc.process.image.path contains:anycase( "copilot", "github-copilot" )'
            ' OR src.process.parent.image.path contains:anycase( "copilot", "github-copilot" )'
            ' OR osSrc.process.parent.image.path contains:anycase( "copilot", "github-copilot" ) )'
            ' OR ( src.process.cmdline contains:anycase( "gemini", "google-generativeai", "palm2", "bard", "aistudio" )'
            ' OR tgt.process.cmdline contains:anycase( "gemini", "google-generativeai", "palm2", "bard", "aistudio" )'
            ' OR osSrc.process.cmdline contains:anycase( "gemini", "google-generativeai", "palm2", "bard", "aistudio" ) )'
            ' OR ( src.process.image.path contains:anycase( "gemini", "google-generativeai" )'
            ' OR tgt.process.image.path contains:anycase( "gemini", "google-generativeai" )'
            ' OR osSrc.process.image.path contains:anycase( "gemini", "google-generativeai" )'
            ' OR src.process.parent.image.path contains:anycase( "gemini", "google-generativeai" )'
            ' OR osSrc.process.parent.image.path contains:anycase( "gemini", "google-generativeai" ) )'
            ' OR ( src.process.cmdline contains:anycase( "ollama", "llama", "llama-cpp", "llamafile", "llama.cpp" )'
            ' OR tgt.process.cmdline contains:anycase( "ollama", "llama", "llama-cpp", "llamafile", "llama.cpp" )'
            ' OR osSrc.process.cmdline contains:anycase( "ollama", "llama", "llama-cpp", "llamafile", "llama.cpp" ) )'
            ' OR ( src.process.image.path contains:anycase( ".ollama/", "ollama", "llamafile", "llama.cpp" )'
            ' OR tgt.process.image.path contains:anycase( ".ollama/", "ollama", "llamafile", "llama.cpp" )'
            ' OR osSrc.process.image.path contains:anycase( ".ollama/", "ollama", "llamafile", "llama.cpp" )'
            ' OR src.process.parent.image.path contains:anycase( ".ollama/", "ollama", "llamafile", "llama.cpp" )'
            ' OR osSrc.process.parent.image.path contains:anycase( ".ollama/", "ollama", "llamafile", "llama.cpp" ) )'
            ' OR ( tgt.file.path contains:anycase( ".ollama/", "llamafile" )'
            ' OR tgt.file.oldPath contains:anycase( ".ollama/", "llamafile" )'
            ' OR src.process.activeContent.path contains:anycase( ".ollama/", "llamafile" )'
            ' OR tgt.process.activeContent.path contains:anycase( ".ollama/", "llamafile" )'
            ' OR osSrc.process.activeContent.path contains:anycase( ".ollama/", "llamafile" ) )'
            ' OR ( src.process.cmdline contains:anycase( "mscopilot", "m365copilot", "azureopenai", "azure-openai" )'
            ' OR tgt.process.cmdline contains:anycase( "mscopilot", "m365copilot", "azureopenai", "azure-openai" )'
            ' OR osSrc.process.cmdline contains:anycase( "mscopilot", "m365copilot", "azureopenai", "azure-openai" ) )'
            ' OR ( src.process.image.path contains:anycase( "mscopilot", "m365copilot" )'
            ' OR tgt.process.image.path contains:anycase( "mscopilot", "m365copilot" )'
            ' OR osSrc.process.image.path contains:anycase( "mscopilot", "m365copilot" ) )'
            ' OR ( src.process.cmdline contains:anycase( "cursor", "cursor-ai" )'
            ' OR tgt.process.cmdline contains:anycase( "cursor", "cursor-ai" )'
            ' OR osSrc.process.cmdline contains:anycase( "cursor", "cursor-ai" ) )'
            ' OR ( src.process.image.path contains:anycase( "cursor.app", "cursor-ai", "/cursor/" )'
            ' OR tgt.process.image.path contains:anycase( "cursor.app", "cursor-ai", "/cursor/" )'
            ' OR osSrc.process.image.path contains:anycase( "cursor.app", "cursor-ai", "/cursor/" )'
            ' OR src.process.parent.image.path contains:anycase( "cursor.app", "cursor-ai", "/cursor/" )'
            ' OR osSrc.process.parent.image.path contains:anycase( "cursor.app", "cursor-ai", "/cursor/" ) )'
            ' OR ( src.process.cmdline contains:anycase( "codeium", "windsurf" )'
            ' OR tgt.process.cmdline contains:anycase( "codeium", "windsurf" )'
            ' OR osSrc.process.cmdline contains:anycase( "codeium", "windsurf" ) )'
            ' OR ( src.process.image.path contains:anycase( "codeium", "windsurf" )'
            ' OR tgt.process.image.path contains:anycase( "codeium", "windsurf" )'
            ' OR osSrc.process.image.path contains:anycase( "codeium", "windsurf" )'
            ' OR src.process.parent.image.path contains:anycase( "codeium", "windsurf" )'
            ' OR osSrc.process.parent.image.path contains:anycase( "codeium", "windsurf" ) )'
            ' OR ( src.process.cmdline contains:anycase( "tabnine" )'
            ' OR tgt.process.cmdline contains:anycase( "tabnine" )'
            ' OR osSrc.process.cmdline contains:anycase( "tabnine" ) )'
            ' OR ( src.process.image.path contains:anycase( "tabnine" )'
            ' OR tgt.process.image.path contains:anycase( "tabnine" )'
            ' OR osSrc.process.image.path contains:anycase( "tabnine" )'
            ' OR src.process.parent.image.path contains:anycase( "tabnine" )'
            ' OR osSrc.process.parent.image.path contains:anycase( "tabnine" ) )'
            ' OR ( src.process.cmdline contains:anycase( "mistral", "mistralai", "mixtral" )'
            ' OR tgt.process.cmdline contains:anycase( "mistral", "mistralai", "mixtral" )'
            ' OR osSrc.process.cmdline contains:anycase( "mistral", "mistralai", "mixtral" ) )'
            ' OR ( src.process.image.path contains:anycase( "mistral", "mistralai", "mixtral" )'
            ' OR tgt.process.image.path contains:anycase( "mistral", "mistralai", "mixtral" )'
            ' OR osSrc.process.image.path contains:anycase( "mistral", "mistralai", "mixtral" ) )'
            ' OR ( src.process.cmdline contains:anycase( "perplexity", "perplexityai" )'
            ' OR tgt.process.cmdline contains:anycase( "perplexity", "perplexityai" )'
            ' OR osSrc.process.cmdline contains:anycase( "perplexity", "perplexityai" ) )'
            ' OR ( src.process.image.path contains:anycase( "perplexity" )'
            ' OR tgt.process.image.path contains:anycase( "perplexity" )'
            ' OR osSrc.process.image.path contains:anycase( "perplexity" ) )'
            ' OR ( src.process.cmdline contains:anycase( "huggingface", "hugging-face", "transformers", "diffusers", "huggingface-cli" )'
            ' OR tgt.process.cmdline contains:anycase( "huggingface", "hugging-face", "transformers", "diffusers", "huggingface-cli" )'
            ' OR osSrc.process.cmdline contains:anycase( "huggingface", "hugging-face", "transformers", "diffusers", "huggingface-cli" ) )'
            ' OR ( src.process.image.path contains:anycase( ".huggingface/", "huggingface" )'
            ' OR tgt.process.image.path contains:anycase( ".huggingface/", "huggingface" )'
            ' OR osSrc.process.image.path contains:anycase( ".huggingface/", "huggingface" )'
            ' OR tgt.file.path contains:anycase( ".huggingface/" )'
            ' OR tgt.file.oldPath contains:anycase( ".huggingface/" )'
            ' OR src.process.activeContent.path contains:anycase( ".huggingface/" )'
            ' OR tgt.process.activeContent.path contains:anycase( ".huggingface/" )'
            ' OR osSrc.process.activeContent.path contains:anycase( ".huggingface/" ) )'
            ' OR ( src.process.cmdline contains:anycase( "stable-diffusion", "stablediffusion", "automatic1111", "comfyui", "invokeai", "a1111" )'
            ' OR tgt.process.cmdline contains:anycase( "stable-diffusion", "stablediffusion", "automatic1111", "comfyui", "invokeai", "a1111" )'
            ' OR osSrc.process.cmdline contains:anycase( "stable-diffusion", "stablediffusion", "automatic1111", "comfyui", "invokeai", "a1111" ) )'
            ' OR ( src.process.image.path contains:anycase( "stable-diffusion", "comfyui", "invokeai", "automatic1111" )'
            ' OR tgt.process.image.path contains:anycase( "stable-diffusion", "comfyui", "invokeai", "automatic1111" )'
            ' OR osSrc.process.image.path contains:anycase( "stable-diffusion", "comfyui", "invokeai", "automatic1111" ) )'
            ' OR ( src.process.cmdline contains:anycase( "localai", "lm-studio", "lmstudio", "jan-ai", "jan.ai" )'
            ' OR tgt.process.cmdline contains:anycase( "localai", "lm-studio", "lmstudio", "jan-ai", "jan.ai" )'
            ' OR osSrc.process.cmdline contains:anycase( "localai", "lm-studio", "lmstudio", "jan-ai", "jan.ai" ) )'
            ' OR ( src.process.image.path contains:anycase( "lmstudio", "localai", "jan-ai" )'
            ' OR tgt.process.image.path contains:anycase( "lmstudio", "localai", "jan-ai" )'
            ' OR osSrc.process.image.path contains:anycase( "lmstudio", "localai", "jan-ai" )'
            ' OR tgt.file.path contains:anycase( "lmstudio", "jan-ai" )'
            ' OR src.process.activeContent.path contains:anycase( "lmstudio", "jan-ai" )'
            ' OR tgt.process.activeContent.path contains:anycase( "lmstudio", "jan-ai" )'
            ' OR osSrc.process.activeContent.path contains:anycase( "lmstudio", "jan-ai" ) )'
            ' OR ( src.process.cmdline contains:anycase( "continue-dev", "continuedev" )'
            ' OR tgt.process.cmdline contains:anycase( "continue-dev", "continuedev" )'
            ' OR osSrc.process.cmdline contains:anycase( "continue-dev", "continuedev" ) )'
            ' OR ( src.process.image.path contains:anycase( ".continue/", "continuedev" )'
            ' OR tgt.process.image.path contains:anycase( ".continue/", "continuedev" )'
            ' OR osSrc.process.image.path contains:anycase( ".continue/", "continuedev" )'
            ' OR tgt.file.path contains:anycase( ".continue/" )'
            ' OR src.process.activeContent.path contains:anycase( ".continue/" )'
            ' OR tgt.process.activeContent.path contains:anycase( ".continue/" )'
            ' OR osSrc.process.activeContent.path contains:anycase( ".continue/" ) )'
            ' OR ( src.process.cmdline contains:anycase( "aider", "aider-chat" )'
            ' OR tgt.process.cmdline contains:anycase( "aider", "aider-chat" )'
            ' OR osSrc.process.cmdline contains:anycase( "aider", "aider-chat" ) )'
            ' OR ( src.process.image.path contains:anycase( "aider" )'
            ' OR tgt.process.image.path contains:anycase( "aider" )'
            ' OR osSrc.process.image.path contains:anycase( "aider" ) )'
            ' OR ( src.process.cmdline contains:anycase( "cohere", "cohere-cli" )'
            ' OR tgt.process.cmdline contains:anycase( "cohere", "cohere-cli" )'
            ' OR osSrc.process.cmdline contains:anycase( "cohere", "cohere-cli" ) )'
            ' OR ( src.process.image.path contains:anycase( "cohere" )'
            ' OR tgt.process.image.path contains:anycase( "cohere" )'
            ' OR osSrc.process.image.path contains:anycase( "cohere" ) )'
            ' ))'
            ' | columns endpoint.name, event.time, event.id, event.type, site.id, site.name, agent.uuid,'
            ' src.process.storyline.id, src.process.user, src.process.uid, src.process.cmdline, src.process.image.path,'
            ' tgt.process.storyline.id, tgt.process.user, tgt.process.uid, tgt.process.cmdline, tgt.process.image.path,'
            ' src.process.parent.storyline.id, src.process.parent.user, src.process.parent.uid, src.process.parent.cmdline, src.process.parent.image.path,'
            ' osSrc.process.cmdline, osSrc.process.image.path, osSrc.process.parent.image.path, osSrc.process.activeContent.path,'
            ' tgt.file.path, tgt.file.oldPath, src.process.activeContent.path, tgt.process.activeContent.path'
            ' | sort - event.time'
            ' | limit 1000'
        ),
        "params": [],
    },
    {
        "name": "AI Tool Usage Detection (S1QL)",
        "description": "Detect AI/LLM tool process creation via standard Deep Visibility — Claude, ChatGPT, Copilot, Gemini, Ollama, Cursor, Codeium, Tabnine, Mistral, Perplexity, Hugging Face, Stable Diffusion, LM Studio, Aider, Cohere, DeepSeek.",
        "category": "Threat Hunting",
        "dv_query": (
            'EventType = "Process Creation" AND ('
            'ProcessCmd ContainsCIS "claude" OR ProcessCmd ContainsCIS "anthropic" OR ProcessCmd ContainsCIS "claude-cli" OR ProcessCmd ContainsCIS "claude-code"'
            ' OR ProcessCmd ContainsCIS "openai" OR ProcessCmd ContainsCIS "chatgpt" OR ProcessCmd ContainsCIS "gpt-4" OR ProcessCmd ContainsCIS "sgpt"'
            ' OR ProcessCmd ContainsCIS "copilot" OR ProcessCmd ContainsCIS "github-copilot"'
            ' OR ProcessCmd ContainsCIS "gemini" OR ProcessCmd ContainsCIS "google-generativeai" OR ProcessCmd ContainsCIS "bard" OR ProcessCmd ContainsCIS "aistudio"'
            ' OR ProcessCmd ContainsCIS "ollama" OR ProcessCmd ContainsCIS "llama-cpp" OR ProcessCmd ContainsCIS "llamafile"'
            ' OR ProcessCmd ContainsCIS "mscopilot" OR ProcessCmd ContainsCIS "m365copilot" OR ProcessCmd ContainsCIS "azureopenai" OR ProcessCmd ContainsCIS "azure-openai"'
            ' OR ProcessCmd ContainsCIS "cursor-ai"'
            ' OR ProcessCmd ContainsCIS "codeium" OR ProcessCmd ContainsCIS "windsurf"'
            ' OR ProcessCmd ContainsCIS "tabnine"'
            ' OR ProcessCmd ContainsCIS "mistral" OR ProcessCmd ContainsCIS "mistralai" OR ProcessCmd ContainsCIS "mixtral"'
            ' OR ProcessCmd ContainsCIS "perplexity" OR ProcessCmd ContainsCIS "perplexityai"'
            ' OR ProcessCmd ContainsCIS "huggingface" OR ProcessCmd ContainsCIS "hugging-face" OR ProcessCmd ContainsCIS "huggingface-cli"'
            ' OR ProcessCmd ContainsCIS "stable-diffusion" OR ProcessCmd ContainsCIS "automatic1111" OR ProcessCmd ContainsCIS "comfyui" OR ProcessCmd ContainsCIS "invokeai"'
            ' OR ProcessCmd ContainsCIS "localai" OR ProcessCmd ContainsCIS "lm-studio" OR ProcessCmd ContainsCIS "lmstudio" OR ProcessCmd ContainsCIS "jan-ai"'
            ' OR ProcessCmd ContainsCIS "continuedev" OR ProcessCmd ContainsCIS "continue-dev"'
            ' OR ProcessCmd ContainsCIS "aider" OR ProcessCmd ContainsCIS "aider-chat"'
            ' OR ProcessCmd ContainsCIS "cohere" OR ProcessCmd ContainsCIS "cohere-cli"'
            ' OR ProcessCmd ContainsCIS "deepseek"'
            ' OR SrcProcImagePath ContainsCIS "claude" OR SrcProcImagePath ContainsCIS "anthropic"'
            ' OR SrcProcImagePath ContainsCIS "openai" OR SrcProcImagePath ContainsCIS "chatgpt"'
            ' OR SrcProcImagePath ContainsCIS "copilot"'
            ' OR SrcProcImagePath ContainsCIS "gemini"'
            ' OR SrcProcImagePath ContainsCIS "ollama" OR SrcProcImagePath ContainsCIS "llamafile"'
            ' OR SrcProcImagePath ContainsCIS "cursor.app" OR SrcProcImagePath ContainsCIS "cursor-ai"'
            ' OR SrcProcImagePath ContainsCIS "codeium" OR SrcProcImagePath ContainsCIS "windsurf"'
            ' OR SrcProcImagePath ContainsCIS "tabnine"'
            ' OR SrcProcImagePath ContainsCIS "mistral"'
            ' OR SrcProcImagePath ContainsCIS "perplexity"'
            ' OR SrcProcImagePath ContainsCIS "huggingface"'
            ' OR SrcProcImagePath ContainsCIS "stable-diffusion" OR SrcProcImagePath ContainsCIS "comfyui"'
            ' OR SrcProcImagePath ContainsCIS "lmstudio" OR SrcProcImagePath ContainsCIS "localai"'
            ' OR SrcProcImagePath ContainsCIS "aider"'
            ' OR SrcProcImagePath ContainsCIS "cohere"'
            ' OR SrcProcImagePath ContainsCIS "deepseek"'
            ')'
        ),
        "params": [],
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
