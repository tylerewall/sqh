"""Add or update the AI Tool Usage Detection (S1QL) query in the database."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import get_db, init_db

# Simplified version — fewer OR conditions to test if S1 accepts the syntax
DV_QUERY = (
    'ObjectType = "process" AND '
    '(ProcessName contains "claude" OR ProcessCmd contains "claude"'
    ' OR ProcessName contains "openai" OR ProcessCmd contains "openai"'
    ' OR ProcessName contains "chatgpt" OR ProcessCmd contains "chatgpt"'
    ' OR ProcessName contains "copilot" OR ProcessCmd contains "copilot"'
    ' OR ProcessName contains "gemini" OR ProcessCmd contains "gemini"'
    ' OR ProcessName contains "ollama" OR ProcessCmd contains "ollama"'
    ' OR ProcessName contains "cursor" OR ProcessCmd contains "codeium"'
    ' OR ProcessName contains "tabnine" OR ProcessCmd contains "mistral"'
    ' OR ProcessName contains "perplexity" OR ProcessCmd contains "deepseek"'
    ' OR ProcessName contains "windsurf" OR ProcessCmd contains "aider")'
)

print("Query to store:")
print(DV_QUERY)
print(f"\nLength: {len(DV_QUERY)} chars")

init_db()
with get_db() as conn:
    existing = conn.execute(
        "SELECT id FROM stored_queries WHERE name = ?",
        ("AI Tool Usage Detection (S1QL)",),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE stored_queries SET dv_query = ? WHERE id = ?",
            (DV_QUERY, existing["id"]),
        )
        print(f"Updated existing query (id={existing['id']}).")
    else:
        conn.execute(
            "INSERT INTO stored_queries (name, description, category, dv_query, created_by) VALUES (?, ?, ?, ?, ?)",
            (
                "AI Tool Usage Detection (S1QL)",
                "Detect AI/LLM tool process creation via standard Deep Visibility.",
                "Threat Hunting",
                DV_QUERY,
                1,
            ),
        )
        print("AI Tool Usage Detection (S1QL) added successfully.")
