#!/home/user87/.claude/rag-mcp/venv/bin/python
"""
Busca en el historial de inputs.
Uso:
  python3 search_history.py                     # últimos 20
  python3 search_history.py "texto"             # búsqueda exacta (SQL LIKE)
  python3 search_history.py "texto" --semantic  # búsqueda semántica (ChromaDB)
  python3 search_history.py --project /ruta     # filtrar por proyecto
  python3 search_history.py --today             # solo hoy
  python3 search_history.py --stats             # estadísticas
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "rag-mcp" / "inputs.db"
CHROMA_PATH = Path.home() / ".claude" / "rag-mcp" / "inputs_chroma"


def sql_search(query=None, project=None, since=None, limit=20):
    if not DB_PATH.exists():
        print("Sin historial todavía.")
        return

    conn = sqlite3.connect(DB_PATH)
    conditions, params = [], []

    if query:
        conditions.append("message LIKE ?")
        params.append(f"%{query}%")
    if project:
        conditions.append("project LIKE ?")
        params.append(f"%{project}%")
    if since:
        conditions.append("ts >= ?")
        params.append(since)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT ts, project, message FROM inputs {where} ORDER BY ts DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()

    if not rows:
        print("Sin resultados.")
        return

    for ts, proj, msg in rows:
        short = Path(proj).name if proj else "?"
        preview = msg[:120].replace("\n", " ")
        print(f"[{ts[:19]}] ({short}) {preview}")


def semantic_search(query: str, limit=10):
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        col = client.get_or_create_collection("user_inputs")

        model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = model.encode([query], normalize_embeddings=True).tolist()

        results = col.query(query_embeddings=vec, n_results=limit)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        if not docs:
            print("Sin resultados semánticos.")
            return

        for doc, meta in zip(docs, metas):
            short = Path(meta.get("project", "?")).name
            ts = meta.get("ts", "")[:19]
            preview = doc[:120].replace("\n", " ")
            print(f"[{ts}] ({short}) {preview}")

    except ImportError:
        print("ChromaDB no instalado. Usar búsqueda SQL (sin --semantic).")
    except Exception as e:
        print(f"Error: {e}")


def stats():
    if not DB_PATH.exists():
        print("Sin historial.")
        return
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM inputs WHERE ts >= date('now')"
    ).fetchone()[0]
    projects = conn.execute(
        "SELECT project, COUNT(*) as c FROM inputs GROUP BY project ORDER BY c DESC LIMIT 5"
    ).fetchall()
    conn.close()

    print(f"Total inputs guardados : {total}")
    print(f"Hoy                    : {today}")
    print("\nProyectos más activos:")
    for proj, count in projects:
        print(f"  {count:5d}  {proj}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="?", help="Texto a buscar")
    p.add_argument("--semantic", action="store_true", help="Búsqueda semántica")
    p.add_argument("--project", help="Filtrar por ruta de proyecto")
    p.add_argument("--today", action="store_true", help="Solo inputs de hoy")
    p.add_argument("--stats", action="store_true", help="Estadísticas")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    if args.stats:
        stats()
    elif args.semantic and args.query:
        semantic_search(args.query, args.limit)
    else:
        since = datetime.now(timezone.utc).date().isoformat() if args.today else None
        sql_search(args.query, args.project, since, args.limit)


if __name__ == "__main__":
    main()
