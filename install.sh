#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
CLAUDE_DIR="$HOME/.claude"
MCP_JSON="$CLAUDE_DIR/mcp.json"
SETTINGS_JSON="$CLAUDE_DIR/settings.json"

echo "=== claude-rag-memory: instalador ==="
echo ""

# ── 1. Virtualenv ──────────────────────────────────────────────────────────────
echo "[1/5] Creando virtualenv..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip

# ── 2. PyTorch CPU ────────────────────────────────────────────────────────────
echo "[2/5] Instalando PyTorch CPU-only..."
"$VENV/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu

# ── 3. Dependencias ───────────────────────────────────────────────────────────
echo "[3/5] Instalando dependencias..."
"$VENV/bin/pip" install -q chromadb sentence-transformers anthropic "mcp[cli]"

# ── 4. Pre-descarga modelo ────────────────────────────────────────────────────
echo "[4/5] Descargando modelo de embeddings (all-MiniLM-L6-v2)..."
"$VENV/bin/python" -c "
import sys, io, os
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
old = sys.stdout; sys.stdout = io.StringIO()
from sentence_transformers import SentenceTransformer
SentenceTransformer('all-MiniLM-L6-v2')
sys.stdout = old
print('  Modelo descargado OK')
"

# ── 5. Configurar Claude Code ──────────────────────────────────────────────────
echo "[5/5] Configurando Claude Code..."

PYTHON="$VENV/bin/python"

# mcp.json
if [ ! -f "$MCP_JSON" ]; then
  echo "{}" > "$MCP_JSON"
fi

"$PYTHON" - <<PYEOF
import json, sys
from pathlib import Path

script_dir = Path("$SCRIPT_DIR")
python_bin = str(script_dir / "venv/bin/python")
server_py  = str(script_dir / "server.py")

# mcp.json
mcp_path = Path("$MCP_JSON")
try:
    data = json.loads(mcp_path.read_text())
except Exception:
    data = {}
data.setdefault("mcpServers", {})
data["mcpServers"]["rag-anything"] = {
    "command": python_bin,
    "args": [server_py]
}
mcp_path.write_text(json.dumps(data, indent=2))
print("  mcp.json actualizado")

# settings.json
settings_path = Path("$SETTINGS_JSON")
try:
    settings = json.loads(settings_path.read_text())
except Exception:
    settings = {}

startup_cmd  = f"{python_bin} {script_dir}/startup_hook.py"
loginput_cmd = f"{python_bin} {script_dir}/log_input.py"
stop_cmd     = f"{python_bin} {script_dir}/summarize_session.py"

def has_hook(hooks_list, cmd):
    for entry in hooks_list:
        for h in entry.get("hooks", []):
            if h.get("command") == cmd:
                return True
    return False

hooks = settings.setdefault("hooks", {})

for event, cmd, extra in [
    ("SessionStart",      startup_cmd,  {"timeout": 120, "statusMessage": "Indexando proyecto con RAG..."}),
    ("UserPromptSubmit",  loginput_cmd, {"timeout": 10}),
    ("Stop",              stop_cmd,     {"timeout": 60, "async": True}),
]:
    hooks.setdefault(event, [])
    if not has_hook(hooks[event], cmd):
        entry = {"type": "command", "command": cmd}
        entry.update(extra)
        hooks[event].append({"hooks": [entry]})

settings_path.write_text(json.dumps(settings, indent=2))
print("  settings.json actualizado")
PYEOF

echo ""
echo "=== Instalación completa ==="
echo "Reiniciá Claude Code para activar los hooks y el MCP server."
