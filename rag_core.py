"""
Núcleo RAG liviano: ChromaDB + sentence-transformers + Anthropic.
Sin raganything ni lightrag — misma funcionalidad, ~600MB en vez de 3GB.
"""

import hashlib
import os
from pathlib import Path
from typing import Optional

STORAGE_BASE = Path.home() / ".claude" / "rag-mcp" / "storage"
STORAGE_BASE.mkdir(parents=True, exist_ok=True)

_model = None


def _chromadb():
    import chromadb as _c
    return _c


def _SentenceTransformer():
    from sentence_transformers import SentenceTransformer as _ST
    return _ST

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", ".gradle",
    ".idea", ".vscode", "coverage", ".pytest_cache",
}

CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".cpp", ".c", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".lua", ".sh", ".bash",
}

DOC_EXTS = {
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".env.example",
}


def _get_model():
    global _model
    if _model is None:
        import io, sys, os
        # Suprimir stdout/stderr durante la carga del modelo (evita corromper JSON)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        old_env = os.environ.get("TOKENIZERS_PARALLELISM")
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            _model = _SentenceTransformer()("all-MiniLM-L6-v2")
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            if old_env is None:
                os.environ.pop("TOKENIZERS_PARALLELISM", None)
            else:
                os.environ["TOKENIZERS_PARALLELISM"] = old_env
    return _model


def _project_collection(project_path: str):
    slug = hashlib.md5(project_path.encode()).hexdigest()[:10]
    name = Path(project_path).name
    db_dir = STORAGE_BASE / f"{name}_{slug}"
    db_dir.mkdir(parents=True, exist_ok=True)
    client = _chromadb().PersistentClient(path=str(db_dir))
    return client.get_or_create_collection("project_chunks")


def _chunk_text(text: str, size: int = 400, overlap: int = 50) -> list[str]:
    """Divide texto en chunks con overlap."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + size])
        if chunk.strip():
            chunks.append(chunk)
        i += size - overlap
    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def is_indexed(project_path: str) -> bool:
    try:
        col = _project_collection(project_path)
        return col.count() > 0
    except Exception:
        return False


def index_project(project_path: str, max_files: int = 200) -> tuple[int, list[str]]:
    """Indexa archivos del proyecto. Retorna (n_indexed, errors)."""
    root = Path(project_path).resolve()
    col  = _project_collection(project_path)

    indexed, errors = 0, []
    for p in root.rglob("*"):
        if indexed >= max_files:
            break
        if p.is_dir() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in CODE_EXTS | DOC_EXTS:
            continue
        try:
            text = p.read_text(errors="replace").strip()
            if not text:
                continue
            rel = str(p.relative_to(root))
            full = f"# {rel}\n\n{text}"
            chunks = _chunk_text(full)
            for j, chunk in enumerate(chunks):
                doc_id = hashlib.md5(f"{rel}:{j}".encode()).hexdigest()
                col.upsert(
                    ids=[doc_id],
                    embeddings=_embed([chunk]),
                    documents=[chunk],
                    metadatas=[{"file": rel, "chunk": j}],
                )
            indexed += 1
        except Exception as e:
            errors.append(f"{p.name}: {e}")

    return indexed, errors


def query(question: str, project_path: str, n_results: int = 5) -> str:
    """Busca chunks relevantes y sintetiza respuesta con Haiku."""
    import anthropic

    col = _project_collection(project_path)
    if col.count() == 0:
        return "Proyecto no indexado. Usar rag_index_project primero."

    results = col.query(
        query_embeddings=_embed([question]),
        n_results=min(n_results, col.count()),
    )
    docs  = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    if not docs:
        return "Sin resultados."

    context = "\n\n---\n\n".join(
        f"[{m.get('file', '?')}]\n{d}" for d, m in zip(docs, metas)
    )

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                f"Based on the following code/docs context, answer concisely:\n\n"
                f"{context}\n\n"
                f"Question: {question}"
            ),
        }],
    )
    return resp.content[0].text


def get_summary(project_path: str) -> str:
    """Resumen de arquitectura del proyecto."""
    return query(
        "Summarize this project: its purpose, main components, key files, and tech stack. Be concise.",
        project_path,
    )


def find_relevant_files(task: str, project_path: str) -> str:
    """Qué archivos son relevantes para una tarea dada."""
    return query(
        f"For the task: '{task}' — which files are most relevant and why? List them briefly.",
        project_path,
    )
