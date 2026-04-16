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

def summarize_local(turns: list[dict]) -> tuple[str, str]:
    """
    Resumen local sin API. Extrae los mensajes del usuario más significativos
    y las palabras clave más frecuentes como topics.
    """
    user_msgs = [t["content"] for t in turns if t["role"] == "user"]
    # Tomar el primer y último mensaje del usuario como contexto de inicio y fin
    snippets = []
    if user_msgs:
        snippets.append(user_msgs[0][:200])
    if len(user_msgs) > 1:
        snippets.append(user_msgs[-1][:200])

    # Topics: palabras de 5+ chars más frecuentes en mensajes del usuario
    from collections import Counter
    stopwords = {"sobre", "hacer", "quiero", "tengo", "puedo", "como", "para", "esto", "esta",
                 "porque", "cuando", "donde", "tiene", "puede", "todos", "había", "ahora"}
    words = []
    for msg in user_msgs:
        words.extend(w.strip(".,?!:;()[]'\"").lower() for w in msg.split() if len(w) > 4)
    top = [w for w, _ in Counter(words).most_common(15) if w not in stopwords][:6]
    topics = ", ".join(top)

    assistant_msgs = [t["content"] for t in turns if t["role"] == "assistant"]
    n_assistant = len(assistant_msgs)

    summary = (
        f"Sesión con {len(user_msgs)} mensajes del usuario y {n_assistant} respuestas. "
        f"Inicio: {snippets[0]!r}"
    )
    if len(snippets) > 1:
        summary += f" — Final: {snippets[1]!r}"

    return summary[:500], topics


def summarize_with_claude_cli(turns: list[dict], project: str) -> tuple[str, str]:
    """
    Genera un resumen usando `claude -p` (Claude Code CLI), que usa la auth
    existente sin necesitar ANTHROPIC_API_KEY por separado.
    Retorna (summary, topics_csv) o ("", "") si falla.
    """
    import subprocess
    import shutil

    if not shutil.which("claude"):
        return "", ""

    convo_lines = []
    total_chars = 0
    for t in turns:
        line = f"{t['role'].upper()}: {t['content'][:400]}"
        total_chars += len(line)
        if total_chars > 6000:
            break
        convo_lines.append(line)

    project_name = Path(project).name
    prompt = (
        f"Project: {project_name}\n\n"
        f"Conversation:\n{chr(10).join(convo_lines)}\n\n"
        "In 2-3 sentences, summarize: what the user was trying to do, "
        "what was accomplished, and any key decisions or problems found. "
        "Then on a new line starting with 'TOPICS:', list 3-5 key topics as comma-separated words. "
        "Reply with the summary and topics only, no preamble."
    )

    result = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--no-session-persistence"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return "", ""

    text = result.stdout.strip()
    summary, topics = text, ""
    if "TOPICS:" in text:
        parts = text.split("TOPICS:", 1)
        summary = parts[0].strip()
        topics  = parts[1].strip()
    return summary, topics


def summarize_with_haiku(turns: list[dict], project: str) -> tuple[str, str]:
    """
    Genera un resumen comprimido de la sesión (~100-150 tokens).
    Prioridad:
      1. claude CLI (-p) — usa la auth de Claude Code sin config extra
      2. ANTHROPIC_API_KEY — SDK directo
      3. summarize_local — fallback sin API
    """
    if not turns:
        return "", ""

    # 1. Intentar con claude CLI
    try:
        summary, topics = summarize_with_claude_cli(turns, project)
        if summary:
            return summary, topics
    except Exception:
        pass

    # 2. Intentar con ANTHROPIC_API_KEY
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

            convo_lines = []
            total_chars = 0
            for t in turns:
                line = f"{t['role'].upper()}: {t['content'][:400]}"
                total_chars += len(line)
                if total_chars > 6000:
                    break
                convo_lines.append(line)

            project_name = Path(project).name
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Project: {project_name}\n\n"
                        f"Conversation:\n{chr(10).join(convo_lines)}\n\n"
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
        except Exception:
            pass

    # 3. Fallback local
    return summarize_local(turns)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Garantizar que la tabla existe siempre, independientemente del flujo posterior
    get_db().close()

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
