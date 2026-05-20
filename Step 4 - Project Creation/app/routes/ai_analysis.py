import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.database import get_config
from app.auth import require_auth
from app.secrets_manager import decrypt

logger = logging.getLogger("sqh.routes.ai_analysis")
router = APIRouter(prefix="/api/ai", tags=["ai-analysis"])


class AnalyzeRowRequest(BaseModel):
    row_data: dict
    query_name: str = ""
    query_text: str = ""


class VTCheckRequest(BaseModel):
    row_data: dict




SYSTEM_PROMPT = """You are a senior cybersecurity threat analyst assisting with SentinelOne Deep Visibility event triage. 
When given event data from an endpoint detection query, you must:

1. ASSESSMENT: Clearly state if this event is Suspicious, Benign, or Requires Investigation.
2. EXPLANATION: Explain why in 2-3 sentences, referencing specific fields from the data.
3. CONTEXT: Provide relevant context about the process, technique, or behavior observed.
4. RECOMMENDATION: Give a clear next step - investigate further, escalate, or safe to ignore.

Be concise, actionable, and specific. Reference MITRE ATT&CK techniques when relevant.
Format your response with clear section headers."""


@router.post("/analyze")
async def analyze_row(body: AnalyzeRowRequest, request: Request):
    await require_auth(request)

    api_key_enc = get_config("openai_api_key")
    if not api_key_enc:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured. Add it in Administration > Setup Wizard.")

    api_key = decrypt(api_key_enc)
    if not api_key:
        raise HTTPException(status_code=400, detail="Failed to decrypt OpenAI API key. Check encryption settings.")

    model = get_config("openai_model") or "gpt-4o"

    user_msg = f"Query: {body.query_name}\n"
    if body.query_text:
        user_msg += f"S1QL: {body.query_text}\n"
    user_msg += f"\nEvent data:\n"
    for key, val in body.row_data.items():
        if val is not None and val != "" and key != "_eventCount":
            user_msg += f"  {key}: {val}\n"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

        if resp.status_code != 200:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
            logger.error("OpenAI API error: HTTP %d - %s", resp.status_code, err)
            raise HTTPException(status_code=502, detail=f"OpenAI API error: {err}")

        result = resp.json()
        analysis = result["choices"][0]["message"]["content"]
        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        logger.info("AI analysis complete: %d tokens used", tokens_used)

        return {"analysis": analysis, "model": model, "tokens_used": tokens_used}

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="OpenAI API request timed out. Try again.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("AI analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(exc)}")


SUMMARIZE_PROMPT = """You are a senior cybersecurity threat analyst reviewing SentinelOne Deep Visibility query results for an enterprise security team.

You are given a sample of events from a security query along with statistical summaries of the full dataset. Analyze everything and provide:

1. **OVERVIEW**: What does this data show? Summarize the activity in 2-3 sentences.
2. **STANDOUT FINDINGS**: Are there any events that truly stick out as suspicious, anomalous, or require immediate attention? Be specific — reference endpoint names, process names, command lines, or users. If nothing stands out, say so clearly.
3. **RISK ASSESSMENT**: Rate the overall risk level (Low / Medium / High / Critical) and explain why.
4. **NEXT STEPS**: What should the security analyst do next? Be specific and actionable. Should they investigate certain endpoints? Create follow-up queries? Escalate? Or is this safe to close?
5. **SAFE TO IGNORE?**: Clearly state whether this can be closed as benign or if action is needed.

Be direct, concise, and actionable. Reference MITRE ATT&CK techniques when relevant. Don't pad with generic advice.

IMPORTANT: At the very end of your response, you MUST include a section called ACTION_FILTERS with search terms that identify the events requiring attention. Use this exact format:

---ACTION_FILTERS---
term1
term2
term3
---END_FILTERS---

Each term should be a string that appears in the suspicious events (endpoint name, process name, username, or a unique part of a command line). Include only terms for events that genuinely need investigation. If nothing requires action, leave the section empty:

---ACTION_FILTERS---
---END_FILTERS---"""


def _build_dataset_summary(events: list[dict], query_name: str, query_text: str) -> str:
    """Build a comprehensive summary of the full dataset for the AI prompt."""
    total = len(events)
    msg = f"Query: {query_name}\n"
    if query_text:
        msg += f"S1QL: {query_text}\n"
    msg += f"Total events in dataset: {total}\n\n"

    # Statistical summary of key fields
    from collections import Counter
    process_counts = Counter()
    endpoint_counts = Counter()
    user_counts = Counter()
    parent_counts = Counter()
    cmd_samples = []

    for ev in events:
        proc = ev.get("processName") or ev.get("ProcessName") or ""
        if proc:
            process_counts[proc] += 1
        endpoint = ev.get("agentComputerName") or ev.get("endpointName") or ev.get("EndpointName") or ""
        if endpoint:
            endpoint_counts[endpoint] += 1
        user = ev.get("user") or ev.get("UserName") or ev.get("userName") or ""
        if user:
            user_counts[user] += 1
        parent = ev.get("parentProcessName") or ev.get("ParentProcessName") or ""
        if parent:
            parent_counts[parent] += 1
        cmd = ev.get("processCmd") or ev.get("ProcessCmd") or ""
        if cmd and len(cmd_samples) < 30:
            cmd_samples.append(cmd[:200])

    msg += "--- STATISTICAL SUMMARY (full dataset) ---\n"
    msg += f"Unique processes: {len(process_counts)}\n"
    msg += f"Top processes: {', '.join(f'{p} ({c})' for p, c in process_counts.most_common(10))}\n\n"
    msg += f"Unique endpoints: {len(endpoint_counts)}\n"
    msg += f"Top endpoints: {', '.join(f'{e} ({c})' for e, c in endpoint_counts.most_common(10))}\n\n"
    if user_counts:
        msg += f"Unique users: {len(user_counts)}\n"
        msg += f"Top users: {', '.join(f'{u} ({c})' for u, c in user_counts.most_common(10))}\n\n"
    if parent_counts:
        msg += f"Top parent processes: {', '.join(f'{p} ({c})' for p, c in parent_counts.most_common(10))}\n\n"

    msg += "--- SAMPLE COMMAND LINES (for context) ---\n"
    for i, cmd in enumerate(cmd_samples, 1):
        msg += f"  {i}. {cmd}\n"

    # Include a few full event rows for detailed context
    msg += "\n--- DETAILED SAMPLE EVENTS (first 20) ---\n"
    for i, row in enumerate(events[:20], 1):
        msg += f"\nEvent {i}:\n"
        for key, val in row.items():
            if val is not None and val != "" and key != "_eventCount":
                msg += f"  {key}: {val}\n"

    return msg


@router.post("/summarize/{history_id}")
async def summarize_results(history_id: int, request: Request):
    import gzip
    import json as json_stdlib
    await require_auth(request)

    api_key_enc = get_config("openai_api_key")
    if not api_key_enc:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured. Add it in Administration > Setup Wizard.")

    api_key = decrypt(api_key_enc)
    if not api_key:
        raise HTTPException(status_code=400, detail="Failed to decrypt OpenAI API key.")

    model = get_config("openai_model") or "gpt-4o"

    # Load full results from database
    from app.database import get_db
    with get_db() as conn:
        hist = conn.execute(
            "SELECT query_name, result_count FROM query_history WHERE id = ?", (history_id,)
        ).fetchone()
        if not hist:
            raise HTTPException(status_code=404, detail="Query history not found")

        sq_row = conn.execute(
            "SELECT sq.dv_query FROM stored_queries sq "
            "JOIN query_history qh ON qh.stored_query_id = sq.id "
            "WHERE qh.id = ?", (history_id,)
        ).fetchone()
        query_text = sq_row["dv_query"] if sq_row else ""

        res_row = conn.execute(
            "SELECT result_data FROM query_results WHERE history_id = ?", (history_id,)
        ).fetchone()
        if not res_row or not res_row["result_data"]:
            raise HTTPException(status_code=404, detail="No results found for this query")

    # Decompress and parse
    try:
        raw = gzip.decompress(res_row["result_data"])
        events = json_stdlib.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decompress result data")

    if not events:
        raise HTTPException(status_code=400, detail="Result set is empty")

    query_name = hist["query_name"]
    user_msg = _build_dataset_summary(events, query_name, query_text)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARIZE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

        if resp.status_code != 200:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
            logger.error("OpenAI summarize error: HTTP %d - %s", resp.status_code, err)
            raise HTTPException(status_code=502, detail=f"OpenAI API error: {err}")

        result = resp.json()
        raw_analysis = result["choices"][0]["message"]["content"]
        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        logger.info("AI summarize complete: %d tokens, %d events analyzed for '%s'",
                    tokens_used, len(events), query_name)

        # Parse action filters from the response
        action_filters = []
        analysis = raw_analysis
        if "---ACTION_FILTERS---" in raw_analysis:
            parts = raw_analysis.split("---ACTION_FILTERS---")
            analysis = parts[0].strip()
            if len(parts) > 1:
                filter_block = parts[1].split("---END_FILTERS---")[0].strip()
                action_filters = [f.strip() for f in filter_block.split("\n") if f.strip()]

        return {
            "analysis": analysis,
            "model": model,
            "tokens_used": tokens_used,
            "total_count": len(events),
            "action_filters": action_filters,
        }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="OpenAI API request timed out. Try again.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("AI summarize failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI summarize failed: {str(exc)}")


# ── Indicator Extraction & Deep Analysis ─────────────────────────────────────

import re
import asyncio
import base64
from urllib.parse import unquote, urlparse

VT_HASH_FIELDS = [
    "processImageSha1Hash", "ProcessImageSha1Hash", "sha1",
    "processImageSha256Hash", "ProcessImageSha256Hash", "sha256",
    "fileSha1", "fileSha256", "md5", "fileMd5",
]
VT_IP_FIELDS = [
    "dstIp", "DstIP", "srcIp", "SrcIP", "networkUrl",
    "connectionDstIp", "connectionSrcIp",
]
VT_DOMAIN_FIELDS = [
    "dnsRequest", "DNSRequest", "networkUrl", "url", "URL",
]

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_RE = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")
_HASH_RE = re.compile(r"\b[a-fA-F0-9]{40,64}\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")

INTERNAL_DOMAINS = {
    "localhost", "local", "internal", "corp", "intranet",
    "microsoft.com", "windows.com", "windowsupdate.com",
    "digicert.com", "verisign.com", "symantec.com",
}


def _is_internal_domain(domain: str) -> bool:
    d = domain.lower()
    if d.endswith(".local") or d.endswith(".internal"):
        return True
    for internal in INTERNAL_DOMAINS:
        if d == internal or d.endswith("." + internal):
            return True
    return False


def _recursive_url_decode(text: str, depth: int = 3) -> str:
    """Recursively URL-decode and base64-decode to extract embedded URLs."""
    if depth <= 0:
        return text
    decoded = unquote(text)
    if decoded != text:
        return _recursive_url_decode(decoded, depth - 1)
    return decoded


def _extract_urls_deep(text: str) -> set:
    """Extract all URLs including those embedded inside encoded strings."""
    urls = set()
    decoded = _recursive_url_decode(text)
    for url in _URL_RE.findall(decoded):
        urls.add(url.rstrip(".,;)]}\"'"))

    for b64_match in _BASE64_RE.findall(text):
        try:
            raw = base64.b64decode(b64_match, validate=True).decode("utf-8", errors="ignore")
            for url in _URL_RE.findall(raw):
                urls.add(url.rstrip(".,;)]}\"'"))
        except Exception:
            pass

    return urls


def _refang(value: str) -> str:
    """Remove defang brackets and restore original indicator format."""
    return value.replace("[.]", ".").replace("hxxp", "http").replace("[://]", "://").replace("[:]", ":")


def _extract_indicators(row: dict) -> dict:
    """Extract hashes, IPs, domains, and full URLs from an event row."""
    hashes = set()
    ips = set()
    domains = set()
    urls = set()

    for field in VT_HASH_FIELDS:
        val = row.get(field)
        if val and isinstance(val, str) and len(val) >= 32:
            hashes.add(val.strip())

    for field in VT_IP_FIELDS:
        val = row.get(field)
        if val and isinstance(val, str):
            for ip in _IP_RE.findall(val):
                if not ip.startswith("127.") and not ip.startswith("0.") and ip != "255.255.255.255":
                    ips.add(ip)

    for field in VT_DOMAIN_FIELDS:
        val = row.get(field)
        if val and isinstance(val, str):
            for d in _DOMAIN_RE.findall(val):
                if "." in d and not _is_internal_domain(d):
                    domains.add(d.lower())

    all_text = " ".join(str(v) for v in row.values() if v and isinstance(v, str))

    for url in _extract_urls_deep(all_text):
        urls.add(url)
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host:
                if _IP_RE.match(host):
                    if not host.startswith("127.") and not host.startswith("0."):
                        ips.add(host)
                elif not _is_internal_domain(host):
                    domains.add(host.lower())
        except Exception:
            pass

    for val in row.values():
        if not val or not isinstance(val, str):
            continue
        for h in _HASH_RE.findall(val):
            if len(h) in (32, 40, 64):
                hashes.add(h)
        for ip in _IP_RE.findall(val):
            if not ip.startswith("127.") and not ip.startswith("0.") and ip != "255.255.255.255":
                ips.add(ip)

    hashes = {h for h in hashes if not all(c == "0" for c in h)}

    return {
        "hashes": list(hashes)[:10],
        "ips": list(ips)[:10],
        "domains": list(domains)[:10],
        "urls": list(urls)[:15],
    }


# ── VirusTotal ───────────────────────────────────────────────────────────────

async def _check_vt_indicator(client, api_key: str, ioc_type: str, value: str) -> dict:
    """Check a single indicator against VirusTotal."""
    headers = {"x-apikey": api_key}

    if ioc_type == "hash":
        url = f"https://www.virustotal.com/api/v3/files/{value}"
    elif ioc_type == "ip":
        url = f"https://www.virustotal.com/api/v3/ip_addresses/{value}"
    elif ioc_type == "domain":
        url = f"https://www.virustotal.com/api/v3/domains/{value}"
    else:
        return {"value": value, "type": ioc_type, "error": "Unknown type"}

    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return {"value": value, "type": ioc_type, "verdict": "not_found", "detail": "Not in VirusTotal database"}
        if resp.status_code == 429:
            return {"value": value, "type": ioc_type, "verdict": "rate_limited", "detail": "VT rate limit hit"}
        if resp.status_code != 200:
            return {"value": value, "type": ioc_type, "verdict": "error", "detail": f"HTTP {resp.status_code}"}

        data = resp.json().get("data", {}).get("attributes", {})
        stats = data.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        undetected = stats.get("undetected", 0)
        harmless = stats.get("harmless", 0)
        total = malicious + suspicious + undetected + harmless

        if malicious > 0:
            verdict = "malicious"
        elif suspicious > 0:
            verdict = "suspicious"
        else:
            verdict = "clean"

        result = {
            "value": value,
            "type": ioc_type,
            "verdict": verdict,
            "malicious": malicious,
            "suspicious": suspicious,
            "clean": harmless + undetected,
            "total": total,
            "detail": f"{malicious}/{total} engines flagged as malicious",
        }

        if ioc_type == "hash":
            result["name"] = data.get("meaningful_name") or (data.get("names", [""])[0] if data.get("names") else "")
            result["file_type"] = data.get("type_description", "")
            result["size"] = data.get("size", 0)
            result["first_seen"] = data.get("first_submission_date", "")
            result["last_seen"] = data.get("last_analysis_date", "")
            result["tags"] = data.get("tags", [])[:5]
            result["signature"] = data.get("signature_info", {}).get("product", "") if data.get("signature_info") else ""
            result["sha256"] = data.get("sha256", "")
        elif ioc_type == "domain":
            result["reputation"] = data.get("reputation", 0)
            result["creation_date"] = data.get("creation_date", "")
            result["registrar"] = data.get("registrar", "")
            result["last_analysis_date"] = data.get("last_analysis_date", "")
            result["categories"] = data.get("categories", {})
            whois_val = data.get("whois", "")
            result["whois_snippet"] = whois_val[:300] if whois_val else ""
        elif ioc_type == "ip":
            result["country"] = data.get("country", "")
            result["as_owner"] = data.get("as_owner", "")
            result["asn"] = data.get("asn", "")
            result["network"] = data.get("network", "")
            result["continent"] = data.get("continent", "")
            result["last_analysis_date"] = data.get("last_analysis_date", "")
            whois_val = data.get("whois", "")
            result["whois_snippet"] = whois_val[:300] if whois_val else ""

        return result

    except Exception as exc:
        return {"value": value, "type": ioc_type, "verdict": "error", "detail": str(exc)}


# ── APIVoid (IPVoid + URLVoid) ───────────────────────────────────────────────

async def _check_apivoid_ip(client, api_key: str, ip: str) -> dict:
    """Check IP reputation via APIVoid (covers IPVoid functionality)."""
    try:
        resp = await client.get(
            f"https://endpoint.apivoid.com/iprep/v1/pay-as-you-go/?key={api_key}&ip={ip}",
            timeout=12,
        )
        if resp.status_code != 200:
            return {"value": ip, "type": "ip", "source": "apivoid", "error": f"HTTP {resp.status_code}"}

        data = resp.json().get("data", {})
        report = data.get("report", {})
        blacklists = report.get("blacklists", {})
        detection_rate = blacklists.get("detection_rate", "0%")
        detections = blacklists.get("detections", 0)
        engines_count = blacklists.get("engines_count", 0)
        info = report.get("information", {})

        return {
            "value": ip,
            "type": "ip",
            "source": "apivoid",
            "detections": detections,
            "engines": engines_count,
            "detection_rate": detection_rate,
            "country": info.get("country_name", ""),
            "isp": info.get("isp", ""),
            "is_proxy": info.get("is_proxy", False),
            "is_vpn": info.get("is_vpn", False),
            "is_tor": info.get("is_tor", False),
            "reverse_dns": info.get("reverse_dns", ""),
        }
    except Exception as exc:
        return {"value": ip, "type": "ip", "source": "apivoid", "error": str(exc)}


async def _check_apivoid_domain(client, api_key: str, domain: str) -> dict:
    """Check domain reputation via APIVoid (covers URLVoid functionality)."""
    try:
        resp = await client.get(
            f"https://endpoint.apivoid.com/domainbl/v1/pay-as-you-go/?key={api_key}&host={domain}",
            timeout=12,
        )
        if resp.status_code != 200:
            return {"value": domain, "type": "domain", "source": "apivoid", "error": f"HTTP {resp.status_code}"}

        data = resp.json().get("data", {})
        report = data.get("report", {})
        blacklists = report.get("blacklists", {})
        detection_rate = blacklists.get("detection_rate", "0%")
        detections = blacklists.get("detections", 0)
        engines_count = blacklists.get("engines_count", 0)
        server = report.get("server", {})

        return {
            "value": domain,
            "type": "domain",
            "source": "apivoid",
            "detections": detections,
            "engines": engines_count,
            "detection_rate": detection_rate,
            "ip": server.get("ip", ""),
            "country": server.get("country_name", ""),
            "risk_score": report.get("risk_score", {}).get("result", 0),
        }
    except Exception as exc:
        return {"value": domain, "type": "domain", "source": "apivoid", "error": str(exc)}


# ── Wayback Machine (Internet Archive) ──────────────────────────────────────

async def _check_wayback(client, domain: str) -> dict:
    """Get up to 3 historical snapshots from Internet Archive."""
    snapshots = []
    timestamps = ["19990101", "20150101", "20230101"]

    for ts in timestamps:
        try:
            resp = await client.get(
                f"https://archive.org/wayback/available?url={domain}&timestamp={ts}",
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                snap = data.get("archived_snapshots", {}).get("closest")
                if snap and snap.get("available"):
                    snapshots.append({
                        "timestamp": snap.get("timestamp", ""),
                        "url": snap.get("url", ""),
                    })
        except Exception:
            pass

    seen_urls = set()
    unique_snapshots = []
    for s in snapshots:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            unique_snapshots.append(s)

    return {"value": domain, "snapshots": unique_snapshots[:3]}


# ── WHOIS Lookup ─────────────────────────────────────────────────────────────

def _whois_lookup(domain: str) -> dict:
    """Perform WHOIS lookup for domain registration info."""
    try:
        import whois
        w = whois.whois(domain)
        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        expiration = w.expiration_date
        if isinstance(expiration, list):
            expiration = expiration[0]

        return {
            "value": domain,
            "registrar": w.registrar or "",
            "creation_date": str(creation) if creation else "",
            "expiration_date": str(expiration) if expiration else "",
            "name_servers": list(w.name_servers)[:4] if w.name_servers else [],
            "registrant_country": w.country or "",
            "org": w.org or "",
        }
    except Exception as exc:
        return {"value": domain, "error": str(exc)}


# ── Screenshot ───────────────────────────────────────────────────────────────

def _get_screenshot_url(url: str) -> str:
    """Generate a screenshot URL using a free screenshot API."""
    from urllib.parse import quote
    return f"https://image.thum.io/get/width/1280/crop/720/noanimate/{quote(url, safe='')}"


# ── SentinelOne Alerts/Threats Lookup ─────────────────────────────────────────

async def _get_s1_alerts(client, base_url: str, api_token: str, endpoint_name: str, username: str) -> list:
    """Query SentinelOne threats API for recent alerts on a given endpoint or user (last 90 days)."""
    from datetime import datetime, timedelta, timezone
    headers = {"Authorization": f"APIToken {api_token}", "Content-Type": "application/json"}
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    alerts = []
    params = {"createdAt__gte": since, "limit": 20, "sortBy": "createdAt", "sortOrder": "desc"}

    if endpoint_name:
        params["computerName__contains"] = endpoint_name

    try:
        resp = await client.get(f"{base_url}/web/api/v2.1/threats", headers=headers, params=params)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for threat in data[:10]:
                ti = threat.get("threatInfo", {})
                ai = threat.get("agentRealtimeInfo", {}) or threat.get("agentDetectionInfo", {})
                alerts.append({
                    "threat_id": threat.get("id", ""),
                    "threat_name": ti.get("threatName", ""),
                    "classification": ti.get("classification", ""),
                    "confidence": ti.get("confidenceLevel", ""),
                    "status": ti.get("incidentStatus", "") or ti.get("analystVerdict", ""),
                    "created_at": threat.get("createdAt", ""),
                    "endpoint": ai.get("agentComputerName", "") or threat.get("agentComputerName", ""),
                    "agent_id": ai.get("agentId", "") or threat.get("agentId", ""),
                    "file_path": ti.get("filePath", ""),
                    "mitre": ti.get("mitreTechniques", []),
                })
    except Exception as exc:
        logger.warning("S1 alerts lookup failed: %s", exc)

    return alerts


# ── Legacy VirusTotal Endpoint (kept for backward compat) ────────────────────

@router.post("/virustotal")
async def check_virustotal(body: VTCheckRequest, request: Request):
    await require_auth(request)

    vt_key_enc = get_config("virustotal_api_key")
    if not vt_key_enc:
        raise HTTPException(status_code=400, detail="VirusTotal API key not configured. Add it in Administration > Setup Wizard.")

    vt_key = decrypt(vt_key_enc)
    if not vt_key:
        raise HTTPException(status_code=400, detail="Failed to decrypt VirusTotal API key.")

    indicators = _extract_indicators(body.row_data)
    if not any([indicators["hashes"], indicators["ips"], indicators["domains"]]):
        return {"results": [], "message": "No indicators (hashes, IPs, or domains) found in this event."}

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = []
        for h in indicators["hashes"]:
            tasks.append(_check_vt_indicator(client, vt_key, "hash", h))
        for ip in indicators["ips"]:
            tasks.append(_check_vt_indicator(client, vt_key, "ip", ip))
        for d in indicators["domains"]:
            tasks.append(_check_vt_indicator(client, vt_key, "domain", d))

        results = await asyncio.gather(*tasks)

    results = list(results)
    has_malicious = any(r.get("verdict") == "malicious" for r in results)
    has_suspicious = any(r.get("verdict") == "suspicious" for r in results)

    if has_malicious:
        overall = "MALICIOUS"
    elif has_suspicious:
        overall = "SUSPICIOUS"
    else:
        overall = "CLEAN"

    logger.info("VT check: %d indicators checked, verdict=%s", len(results), overall)
    return {"results": results, "overall_verdict": overall, "indicators_checked": len(results)}


# ── Deep Analyze Endpoint (SOC Analyst Method) ───────────────────────────────

class DeepAnalyzeRequest(BaseModel):
    row_data: dict
    query_name: str = ""
    query_text: str = ""


@router.post("/deep-analyze")
async def deep_analyze(body: DeepAnalyzeRequest, request: Request):
    """Comprehensive IOC analysis following SOC Analyst Method."""
    await require_auth(request)

    indicators = _extract_indicators(body.row_data)
    if not any(indicators.values()):
        return {
            "reason": f"Event from query '{body.query_name}' was analyzed but no extractable indicators (URLs, IPs, hashes, domains) were found.",
            "evidence": indicators,
            "analysis": {"virustotal": [], "ip_reputation": [], "url_reputation": [], "whois": [], "s1_alerts": []},
            "conclusion": {"verdict": "NO_INDICATORS", "summary": "No actionable indicators found in this event to perform external lookups."},
            "next_steps": "Review the event manually. Consider expanding the query or checking related events for network indicators.",
        }

    vt_key_enc = get_config("virustotal_api_key")
    vt_key = decrypt(vt_key_enc) if vt_key_enc else None

    apivoid_key_enc = get_config("apivoid_api_key")
    apivoid_key = decrypt(apivoid_key_enc) if apivoid_key_enc else None

    vt_results = []
    apivoid_ip_results = []
    apivoid_domain_results = []
    whois_results = []

    async with httpx.AsyncClient(timeout=20) as client:
        tasks = []

        # VirusTotal checks
        if vt_key:
            for h in indicators["hashes"]:
                tasks.append(("vt", _check_vt_indicator(client, vt_key, "hash", _refang(h))))
            for ip in indicators["ips"]:
                tasks.append(("vt", _check_vt_indicator(client, vt_key, "ip", _refang(ip))))
            for d in indicators["domains"]:
                tasks.append(("vt", _check_vt_indicator(client, vt_key, "domain", _refang(d))))

        # APIVoid checks
        if apivoid_key:
            for ip in indicators["ips"]:
                tasks.append(("apivoid_ip", _check_apivoid_ip(client, apivoid_key, _refang(ip))))
            for d in indicators["domains"]:
                tasks.append(("apivoid_domain", _check_apivoid_domain(client, apivoid_key, _refang(d))))


        # Execute all async tasks in parallel
        if tasks:
            coros = [t[1] for t in tasks]
            results = await asyncio.gather(*coros, return_exceptions=True)
            for i, (task_type, _) in enumerate(tasks):
                result = results[i]
                if isinstance(result, Exception):
                    continue
                if task_type == "vt":
                    vt_results.append(result)
                elif task_type == "apivoid_ip":
                    apivoid_ip_results.append(result)
                elif task_type == "apivoid_domain":
                    apivoid_domain_results.append(result)

    # WHOIS lookups (synchronous library, run in thread pool)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        loop = asyncio.get_event_loop()
        whois_futures = [
            loop.run_in_executor(pool, _whois_lookup, _refang(d))
            for d in indicators["domains"][:5]
        ]
        if whois_futures:
            whois_results = await asyncio.gather(*whois_futures, return_exceptions=True)
            whois_results = [r for r in whois_results if not isinstance(r, Exception)]

    # S1 Alerts/Threats lookup for the endpoint
    s1_alerts = []
    endpoint_name = (body.row_data.get("agentComputerName") or body.row_data.get("endpointName")
                     or body.row_data.get("EndpointName") or "")
    username = body.row_data.get("user") or body.row_data.get("UserName") or body.row_data.get("userName") or ""

    s1_base = get_config("s1_base_url")
    s1_token_enc = get_config("s1_api_key")
    s1_token = decrypt(s1_token_enc) if s1_token_enc else None

    if s1_base and s1_token and endpoint_name:
        async with httpx.AsyncClient(timeout=15) as s1_client:
            s1_alerts = await _get_s1_alerts(s1_client, s1_base, s1_token, endpoint_name, username)

    # Build conclusion
    all_vt_verdicts = [r.get("verdict") for r in vt_results if r.get("verdict")]
    all_apivoid_detections = sum(
        r.get("detections", 0) for r in apivoid_ip_results + apivoid_domain_results
        if isinstance(r, dict)
    )
    has_malicious = "malicious" in all_vt_verdicts or all_apivoid_detections > 3
    has_suspicious = "suspicious" in all_vt_verdicts or all_apivoid_detections > 0

    if has_malicious:
        verdict = "MALICIOUS"
        summary = "One or more indicators are flagged as malicious by threat intelligence sources."
    elif has_suspicious:
        verdict = "SUSPICIOUS"
        summary = "Indicators show suspicious activity that warrants further investigation."
    else:
        verdict = "CLEAN"
        summary = "No indicators were flagged as malicious by any checked sources."

    # Build reason
    reason = f"Analysis triggered on event from query '{body.query_name}'."
    proc = body.row_data.get("processName") or body.row_data.get("ProcessName") or ""
    cmd = body.row_data.get("processCmd") or body.row_data.get("ProcessCmd") or ""
    if proc:
        reason += f" Process: {proc}."
    if cmd:
        reason += f" Command: {cmd[:150]}."

    # Build next steps based on findings
    next_steps_parts = []
    if has_malicious:
        next_steps_parts.append("IMMEDIATE: Isolate the affected endpoint and preserve evidence.")
        next_steps_parts.append("Escalate to Incident Response team for containment.")
    elif has_suspicious:
        next_steps_parts.append("Investigate the flagged indicators further using sandbox analysis.")
        next_steps_parts.append("Check for lateral movement from the affected endpoint.")
    else:
        next_steps_parts.append("No immediate action required. Document and close if no other context suggests risk.")

    if any(w.get("creation_date") for w in whois_results if isinstance(w, dict)):
        young_domains = [
            w["value"] for w in whois_results
            if isinstance(w, dict) and w.get("creation_date") and _is_young_domain(w["creation_date"])
        ]
        if young_domains:
            next_steps_parts.append(f"NOTE: Recently registered domain(s) detected: {', '.join(young_domains)}. Young domains are higher risk.")

    return {
        "reason": reason,
        "evidence": indicators,
        "analysis": {
            "virustotal": vt_results,
            "ip_reputation": apivoid_ip_results,
            "url_reputation": apivoid_domain_results,
            "whois": list(whois_results),
            "s1_alerts": s1_alerts,
        },
        "s1_base_url": s1_base or "",
        "conclusion": {"verdict": verdict, "summary": summary},
        "next_steps": " ".join(next_steps_parts),
    }


def _is_young_domain(creation_date_str: str) -> bool:
    """Check if domain was registered less than 1 year ago."""
    try:
        from datetime import datetime, timedelta
        dt = datetime.fromisoformat(creation_date_str.replace("Z", "+00:00").split("+")[0])
        return (datetime.now() - dt) < timedelta(days=365)
    except Exception:
        return False
