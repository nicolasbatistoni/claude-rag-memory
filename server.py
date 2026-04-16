#!/home/user87/.claude/rag-mcp/venv/bin/python
"""MCP server RAG para Claude Code."""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Logging a archivo para diagnosticar desconexiones
_log_file = os.environ.get("MCP_LOG_FILE", "/tmp/rag-mcp.log")

def _log(msg: str):
    try:
        with open(_log_file, "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

# Captura excepciones no manejadas
_orig_excepthook = sys.excepthook
def _excepthook(exc_type, exc_val, exc_tb):
    _log(f"UNCAUGHT EXCEPTION: {''.join(traceback.format_exception(exc_type, exc_val, exc_tb))}")
    _orig_excepthook(exc_type, exc_val, exc_tb)
sys.excepthook = _excepthook

_log("server.py starting — importing FastMCP and rag_core")

try:
    from mcp.server.fastmcp import FastMCP
    _log("FastMCP imported OK")
except Exception as e:
    _log(f"FastMCP import FAILED: {e}")
    raise

try:
    import rag_core
    _log("rag_core imported OK")
except Exception as e:
    _log(f"rag_core import FAILED: {e}")
    raise

mcp = FastMCP("rag")
_log("FastMCP instance created")


@mcp.tool()
def rag_index_project(project_path: str) -> str:
    """Indexa un proyecto para búsqueda RAG. Llamar una vez por proyecto nuevo."""
    path = Path(project_path).expanduser().resolve()
    if not path.exists():
        return f"Error: {project_path} no existe"
    n, errors = rag_core.index_project(str(path))
    msg = f"Indexados {n} archivos de '{path.name}'"
    if errors:
        msg += f"\nErrores: {'; '.join(errors[:3])}"
    return msg


@mcp.tool()
def rag_query(question: str, project_path: str) -> str:
    """Busca contexto relevante en el índice RAG. Usar antes de leer archivos."""
    path = Path(project_path).expanduser().resolve()
    return rag_core.query(question, str(path))


@mcp.tool()
def rag_project_summary(project_path: str) -> str:
    """Resumen de arquitectura del proyecto."""
    path = Path(project_path).expanduser().resolve()
    return rag_core.get_summary(str(path))


@mcp.tool()
def rag_find_relevant_files(task_description: str, project_path: str) -> str:
    """Dado el enunciado de una tarea, devuelve qué archivos son relevantes."""
    path = Path(project_path).expanduser().resolve()
    return rag_core.find_relevant_files(task_description, str(path))


if __name__ == "__main__":
    _log("mcp.run() starting")
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        _log(f"mcp.run() crashed: {traceback.format_exc()}")
        raise
