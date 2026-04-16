# claude-rag-memory

Persistent memory and token optimization system for [Claude Code](https://claude.ai/code).

Every message you send is saved and semantically indexed. Future sessions get relevant history injected automatically — so Claude always has context from past work, even in new projects.

## What it does

| Hook | Trigger | Action |
|------|---------|--------|
| `UserPromptSubmit` | Every message | Saves input to SQLite + ChromaDB, injects similar past inputs as context, shows token metrics |
| `SessionStart` | Session open | Auto-indexes the project with RAG, injects past session summaries |
| `Stop` | Session close | Summarizes the conversation with Claude Haiku and saves it (~150 tokens vs ~1500 raw) |

A local MCP server (`rag-anything`) exposes RAG tools so Claude can query the project index on demand.

## Token metrics

Every Claude response ends with a breakdown like:

```
┌─ Token breakdown ───────────────────────────────┐
│  Tu input                      20 tokens          │
│  Contexto sesión (RAG)   +     50 tokens          │
│  Historia similar (RAG)  +    120 tokens          │
│  ─────────────────────────────────────────────  │
│  Total enviado a Anthropic     190 tokens          │
│  Sin este setup sería           20 tokens          │
│  RAG agregó               +    170 tokens (+850%)  │
└─────────────────────────────────────────────────┘
```

## Requirements

- Python 3.10+
- [Claude Code](https://claude.ai/code) CLI
- An Anthropic API key (`ANTHROPIC_API_KEY` in your environment)

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/claude-rag-memory
cd claude-rag-memory
chmod +x install.sh
./install.sh
```

Then **restart Claude Code**. That's it.

The installer:
1. Creates a virtualenv with all dependencies (PyTorch CPU-only, ~300MB)
2. Downloads the `all-MiniLM-L6-v2` embedding model
3. Patches `~/.claude/mcp.json` to register the RAG server
4. Patches `~/.claude/settings.json` to register the three hooks

## MCP tools (available inside Claude Code sessions)

| Tool | Description |
|------|-------------|
| `rag_index_project(project_path)` | Index a project manually |
| `rag_query(question, project_path)` | Semantic search over project code |
| `rag_find_relevant_files(task, project_path)` | Find files relevant to a task |
| `rag_project_summary(project_path)` | Architecture summary of the project |

## Search your history

```bash
# Last 20 inputs
./venv/bin/python search_history.py

# Full-text search
./venv/bin/python search_history.py "docker"

# Semantic search
./venv/bin/python search_history.py "authentication bug" --semantic

# Stats
./venv/bin/python search_history.py --stats
```

## Storage

| Path | Contents |
|------|----------|
| `~/.claude/rag-mcp/inputs.db` | SQLite: all inputs + session summaries |
| `~/.claude/rag-mcp/inputs_chroma/` | ChromaDB: semantic index of inputs |
| `~/.claude/rag-mcp/storage/` | ChromaDB: per-project code indexes |

## How it optimizes tokens

Instead of injecting raw conversation history (expensive), the `Stop` hook compresses each session into a 2-3 sentence summary using Claude Haiku. The next session gets those summaries (~150 tokens) instead of full transcripts (~1500 tokens).

For within-session context, only semantically similar past inputs are injected — not the entire history.

## Global CLAUDE.md integration

For best results, add this to `~/.claude/CLAUDE.md`:

```markdown
## RAG first

Before using Read, Glob, or Grep:
1. Call rag_query(question, project_path) to get relevant chunks
2. Call rag_find_relevant_files(task, project_path) to identify files to touch
3. Only read full files if RAG results are insufficient
```

## License

MIT
