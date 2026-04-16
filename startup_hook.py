#!/home/user87/.claude/rag-mcp/venv/bin/python
"""
SessionStart hook: auto-indexa el proyecto e inyecta contexto RAG + historial.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = Path.home() / ".claude" / "rag-mcp" / "inputs.db"

PROJECT_MARKERS = {
    "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "Makefile", "CLAUDE.md", ".git",
}


def is_real_project(root: Path) -> bool:
    return any((root / m).exists() for m in PROJECT_MARKERS)


def get_session_summaries(project: str, limit: int = 5) -> str:
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT ts, summary, topics, msg_count
            FROM session_summaries
            WHERE project = ?
            ORDER BY ts DESC LIMIT ?
            """,
            (project, limit),
        ).fetchall()
        conn.close()
        if not rows:
            return ""
        lines = ["[Resúmenes de sesiones anteriores]"]
        for ts, summary, topics, msg_count in reversed(rows):
            lines.append(f"\n  {ts[:10]} ({msg_count} mensajes): {summary}")
            if topics:
                lines.append(f"  Temas: {topics}")
        return "\n".join(lines)
    except Exception:
        return ""


def main():
    cwd  = os.getcwd()
    root = Path(cwd)

    context = ""

    if is_real_project(root):
        import rag_core

        # Auto-indexar si no fue indexado
        if not rag_core.is_indexed(cwd):
            n, _ = rag_core.index_project(cwd)
            context += f"[RAG] Proyecto '{root.name}' indexado ({n} archivos).\n\n"
        else:
            context += f"[RAG] Proyecto '{root.name}' — índice disponible.\n\n"

        # Resumen del proyecto
        try:
            summary = rag_core.get_summary(cwd)
            if summary:
                context += f"Resumen:\n{summary}\n\n"
        except Exception:
            pass

    # Resúmenes de sesiones pasadas (siempre, incluso en directorios vacíos)
    hist = get_session_summaries(cwd)
    if hist:
        context += f"{hist}\n\n"

    context += (
        "Herramientas RAG (usar antes de Read/Glob/Grep):\n"
        "- rag_query(question, project_path)\n"
        "- rag_find_relevant_files(task, project_path)\n"
        "- rag_project_summary(project_path)\n"
        "- rag_index_project(project_path)\n"
    )

    # Guardar tamaño para métricas
    try:
        Path("/tmp/rag_session_context_tokens").write_text(str(max(1, len(context) // 4)))
    except Exception:
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"[RAG] Error en startup: {e}",
            }
        }))
