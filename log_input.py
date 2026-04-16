#!/home/user87/.claude/rag-mcp/venv/bin/python
"""
UserPromptSubmit hook:
1. Cuenta tokens exactos del input (Anthropic SDK)
2. Guarda el input en SQLite
3. Busca historia semánticamente similar en ChromaDB
4. Inyecta esa historia como additionalContext
5. Muestra systemMessage con métricas de tokens (antes vs ahora)
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH     = Path.home() / ".claude" / "rag-mcp" / "inputs.db"
CHROMA_PATH = Path.home() / ".claude" / "rag-mcp" / "inputs_chroma"
SESSION_CTX = Path("/tmp/rag_session_context_tokens")  # escrito por startup_hook

MIN_MESSAGE_LENGTH     = 10
SIMILARITY_RESULTS     = 3
MIN_ENTRIES_FOR_SEARCH = 5
SIMILARITY_THRESHOLD   = 0.35  # solo inyectar si es MUY similar (era 0.60)


# ── Token counting ────────────────────────────────────────────────────────────

def count_tokens(text: str) -> int:
    """
    Cuenta tokens usando el SDK de Anthropic (preciso, sin costo).
    Fallback: aproximación por caracteres.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.count_tokens(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": text}],
        )
        return resp.input_tokens
    except Exception:
        # Fallback: ~4 chars/token (estimación razonable)
        return max(1, len(text) // 4)


def get_session_context_tokens() -> int:
    """Lee cuántos tokens inyectó el SessionStart hook (si los guardó)."""
    try:
        return int(SESSION_CTX.read_text().strip())
    except Exception:
        return 0


# ── SQLite ────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inputs (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            session TEXT,
            project TEXT,
            message TEXT NOT NULL,
            length  INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts      ON inputs(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON inputs(project)")
    conn.commit()
    return conn


def save_to_sqlite(message, session, project, ts) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO inputs (ts, session, project, message, length) VALUES (?,?,?,?,?)",
        (ts, session, project, message, len(message)),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ── ChromaDB ──────────────────────────────────────────────────────────────────

def search_similar(message: str, current_session: str) -> list:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        col = client.get_or_create_collection("user_inputs")

        if col.count() < MIN_ENTRIES_FOR_SEARCH:
            return []

        model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = model.encode([message], normalize_embeddings=True).tolist()

        where = {"session": {"$ne": current_session}} if current_session else None
        results = col.query(
            query_embeddings=vec,
            n_results=min(SIMILARITY_RESULTS + 5, col.count()),
            where=where,
        )

        docs  = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        return [
            (doc, meta, dist)
            for doc, meta, dist in zip(docs, metas, dists)
            if dist < SIMILARITY_THRESHOLD
        ][:SIMILARITY_RESULTS]

    except Exception:
        return []


def index_in_chroma(message, row_id, session, project, ts):
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        col = client.get_or_create_collection("user_inputs")
        model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = model.encode([message], normalize_embeddings=True).tolist()

        col.add(
            ids=[str(row_id)],
            embeddings=vec,
            documents=[message],
            metadatas=[{"session": session or "", "project": project or "", "ts": ts}],
        )
    except Exception:
        pass


def build_additional_context(similar_inputs: list) -> str | None:
    if not similar_inputs:
        return None
    lines = ["[Historial relevante de sesiones anteriores]"]
    for doc, meta, dist in similar_inputs:
        proj    = Path(meta.get("project", "?")).name
        ts      = meta.get("ts", "")[:10]
        preview = doc[:150].replace("\n", " ")
        lines.append(f"• [{ts}] ({proj}) {preview}")
    lines.append("")
    return "\n".join(lines)


# ── Display ───────────────────────────────────────────────────────────────────

def format_metrics(
    input_tokens: int,
    session_ctx_tokens: int,
    rag_context_tokens: int,
) -> str:
    """
    Compara el contexto enviado a Anthropic antes y después del setup RAG.

    Antes (baseline): solo el input del usuario.
    Ahora:            input + contexto SessionStart + contexto RAG inline.
    """
    rag_total   = session_ctx_tokens + rag_context_tokens
    total_now   = input_tokens + rag_total
    overhead_pct = int((rag_total / input_tokens * 100)) if input_tokens else 0

    lines = [
        "┌─ Token breakdown ───────────────────────────────┐",
        f"│  Tu input                  {input_tokens:>6,} tokens          │",
    ]

    if session_ctx_tokens:
        lines.append(
            f"│  Contexto sesión (RAG)   + {session_ctx_tokens:>6,} tokens          │"
        )
    if rag_context_tokens:
        lines.append(
            f"│  Historia similar (RAG)  + {rag_context_tokens:>6,} tokens          │"
        )

    lines += [
        "│  ─────────────────────────────────────────────  │",
        f"│  Total enviado a Anthropic  {total_now:>6,} tokens          │",
        f"│  Sin este setup sería       {input_tokens:>6,} tokens          │",
        f"│  RAG agregó               + {rag_total:>6,} tokens (+{overhead_pct}%)  │",
        "└─────────────────────────────────────────────────┘",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    message = (
        data.get("message")
        or data.get("prompt")
        or data.get("tool_input", {}).get("message")
        or ""
    ).strip()

    if not message or len(message) < MIN_MESSAGE_LENGTH:
        sys.exit(0)

    session = data.get("session_id", "")
    project = os.getcwd()
    ts      = datetime.now(timezone.utc).isoformat()

    # 1. Contar tokens del input
    input_tokens = count_tokens(message)

    # 2. Guardar en SQLite
    row_id = save_to_sqlite(message, session, project, ts)

    # 3. Buscar historia similar
    similar = search_similar(message, session)

    # 4. Indexar input actual
    index_in_chroma(message, row_id, session, project, ts)

    # 5. Construir additionalContext
    additional_context = build_additional_context(similar)
    rag_context_tokens = count_tokens(additional_context) if additional_context else 0

    # 6. Tokens del contexto de sesión (inyectado al inicio)
    session_ctx_tokens = get_session_context_tokens()

    # 7. Construir output final
    metrics = format_metrics(input_tokens, session_ctx_tokens, rag_context_tokens)

    injected_context = metrics + "\nAl final de tu respuesta, mostrá estas métricas exactamente como aparecen arriba (el bloque ┌─ Token breakdown ─┐).\n"
    if additional_context:
        injected_context = additional_context + "\n" + injected_context

    output: dict = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": injected_context,
        }
    }

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
