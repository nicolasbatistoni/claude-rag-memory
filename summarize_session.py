#!/home/user87/.claude/rag-mcp/venv/bin/python
"""
Stop hook: al terminar cada sesión, lee el transcript real de Claude Code,
genera un resumen comprimido con Haiku, y lo guarda en SQLite.
Así la próxima sesión puede inyectar resúmenes (~150 tokens) en vez de
historia cruda (~1500 tokens).
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH      = Path.home() / ".claude" / "rag-mcp" / "inputs.db"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


# ── SQLite ────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            project    TEXT,
            ts         TEXT,
            summary    TEXT,
            topics     TEXT,
            msg_count  INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_project ON session_summaries(project)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_ts      ON session_summaries(ts)")
    conn.commit()
    return conn


def already_summarized(session_id: str) -> bool:
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(
        "SELECT 1 FROM session_summaries WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return r is not None


# ── Transcript reader ─────────────────────────────────────────────────────────

def find_transcript(session_id: str) -> Path | None:
    """Busca el archivo .jsonl de la sesión en ~/.claude/projects/."""
    for f in PROJECTS_DIR.rglob("*.jsonl"):
        if session_id in f.name:
            return f
    return None


def extract_conversation(transcript_path: Path) -> list[dict]:
    """Extrae pares user/assistant del transcript."""
    turns = []
    try:
        for line in transcript_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue

            role = d.get("type")
            if role not in ("user", "assistant"):
                continue

            msg = d.get("message", {})
            content = msg.get("content", "")

            # content puede ser string o lista de bloques
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        # ignorar thinking, tool_use, tool_result
                content = " ".join(text_parts)

            content = content.strip()
            if content:
                turns.append({"role": role, "content": content[:800]})  # cap por turno
    except Exception:
        pass

    return turns


# ── Summarizer ────────────────────────────────────────────────────────────────

def summarize_with_haiku(turns: list[dict], project: str) -> tuple[str, str]:
    """
    Genera un resumen comprimido de la sesión (~100-150 tokens).
    Retorna (summary, topics_csv).
    """
    import anthropic

    if not turns:
        return "", ""

    # Armar texto de conversación truncado
    convo_lines = []
    total_chars = 0
    for t in turns:
        line = f"{t['role'].upper()}: {t['content'][:400]}"
        total_chars += len(line)
        if total_chars > 6000:
            break
        convo_lines.append(line)

    convo_text = "\n".join(convo_lines)
    project_name = Path(project).name

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Project: {project_name}\n\n"
                f"Conversation:\n{convo_text}\n\n"
                "In 2-3 sentences, summarize: what the user was trying to do, "
                "what was accomplished, and any key decisions or problems found. "
                "Then on a new line starting with 'TOPICS:', list 3-5 key topics as comma-separated words."
            ),
        }],
    )

    text = resp.content[0].text.strip()
    summary, topics = text, ""

    if "TOPICS:" in text:
        parts = text.split("TOPICS:", 1)
        summary = parts[0].strip()
        topics  = parts[1].strip()

    return summary, topics


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    session_id = data.get("session_id", "")
    project    = os.getcwd()
    ts         = datetime.now(timezone.utc).isoformat()

    if not session_id or already_summarized(session_id):
        sys.exit(0)

    transcript = find_transcript(session_id)
    if not transcript:
        sys.exit(0)

    turns = extract_conversation(transcript)
    if len(turns) < 2:
        sys.exit(0)  # sesión demasiado corta para resumir

    try:
        summary, topics = summarize_with_haiku(turns, project)
    except Exception:
        sys.exit(0)

    if not summary:
        sys.exit(0)

    conn = get_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO session_summaries
            (session_id, project, ts, summary, topics, msg_count)
        VALUES (?,?,?,?,?,?)
        """,
        (session_id, project, ts, summary, topics, len(turns)),
    )
    conn.commit()
    conn.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
