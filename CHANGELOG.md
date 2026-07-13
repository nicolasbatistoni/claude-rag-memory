# Changelog

## 2026-07-13 — CI: allowlist de disparo (el pipeline corre solo si cambió código)

El adaptador de Woodpecker pasa de "cualquier commit dispara todo" a una **allowlist explícita**
(`&code_paths`, 6 filtros): los steps filtrados corren si y solo si el commit tocó código propio
(`*.py` — los módulos sueltos de la raíz son todo el paquete), una dependencia que consume
(`requirements.txt`), el entregable que lo instala (`install.sh`) o la definición de su propio
pipeline (`cicd.yml`, `.woodpecker.yml`, `AGENTS.md`). Un typo en este CHANGELOG ya no levanta un pod.

El step `security` queda **sin filtro** a propósito (Trivy caza un secreto commiteado hasta en un
README) y suma `cicd paths-guard`: cruza `git ls-files` contra los `include:` y **rompe el CI** si
aparece código versionado sin filtro, en vez de saltearse el gate en silencio (la red que hace segura
una allowlist fail-closed).

- **Archivos tocados:** `.woodpecker.yml`, `cicd.yml` (`paths_guard.ignore`: `.github/**`).
- **Verificación:** `cicd paths-guard` local → `✓ Paths guard: 6 filtro(s) cubren todo el código versionado.` (exit 0). **Gap declarado:** el repo no está dado de alta en Woodpecker (0 webhooks), así que no hay e2e contra un pipeline real.

## 1.0.0 (2026-06-05)


### Features

* usar claude CLI para resúmenes ricos sin ANTHROPIC_API_KEY ([a7d2844](https://github.com/nicolasbatistoni/claude-rag-memory/commit/a7d284451af6d8488138be31a64e1e4f8f62f14c))


### Bug Fixes

* garantizar tabla session_summaries y fallback local sin API key ([38a44fa](https://github.com/nicolasbatistoni/claude-rag-memory/commit/38a44fa76c41d9b1d1d466b1496a6ff54030c726))
