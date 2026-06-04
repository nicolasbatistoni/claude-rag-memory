# Claude RAG Memory — portfolio

> **Memoria persistente y optimización de tokens para asistentes de IA (Claude Code).** Cada
> mensaje que mandás se guarda y se indexa semánticamente; las sesiones futuras reciben
> automáticamente el contexto relevante del trabajo pasado — así el asistente siempre tiene la
> historia, incluso en proyectos nuevos.

| | |
|---|---|
| **Qué es** | Una capa de memoria de largo plazo para un agente de IA: hooks que capturan, indexan (RAG) y reinyectan contexto, más un MCP server para consultar el índice on-demand. |
| **Disciplina** | IA · tooling para agentes |
| **Rol** | Diseño e implementación end-to-end (hooks, store vectorial, resúmenes, MCP). |
| **Stack** | Python · SQLite · ChromaDB (vectores) · MCP · Claude Haiku (resúmenes) |

## Cómo funciona

Tres hooks del ciclo de vida de la sesión + un MCP server:

- **Cada mensaje** → guarda el input en SQLite + ChromaDB e **inyecta historia similar** como contexto.
- **Al abrir sesión** → auto-indexa el proyecto con RAG e inyecta resúmenes de sesiones pasadas.
- **Al cerrar** → **resume la conversación** (Claude Haiku) y la guarda (~150 tokens vs ~1500 crudos).
- **MCP `rag-anything`** → expone herramientas para que el asistente consulte el índice del proyecto cuando lo necesita.

## Lo interesante de ingeniería

- **Honestidad sobre el costo:** cada respuesta termina con un desglose **real** de tokens —
  cuántos agregó el RAG y cuánto habría sido sin el setup — para que la optimización sea medible,
  no un acto de fe. Salida real de la herramienta:

```
┌─ Token breakdown ───────────────────────────────┐
│  Tu input                      20 tokens          │
│  Contexto sesión (RAG)   +     50 tokens          │
│  Historia similar (RAG)  +    120 tokens          │
│  Total enviado a Anthropic     190 tokens          │
└─────────────────────────────────────────────────┘
```

- **Recuperación semántica** (no keyword): trae lo relevante aunque lo hayas dicho con otras palabras.
- **Resumen con compresión** al cerrar: la sesión queda como ~150 tokens reutilizables, no como un volcado.

---

> **Sobre las imágenes:** es una herramienta de **línea de comandos / hooks**; su "interfaz" es
> la salida en la terminal (el desglose de tokens de arriba es real, no un mockup). No lleva
> capturas de UI.

*Instalación, hooks y uso: ver el [`README.md`](../../README.md) raíz.*
