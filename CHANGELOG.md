# Changelog

## 2026-07-14 — fix(ci): el pipeline corría DOS VECES por commit (y en ramas sin PR)

El `when` del adaptador decía `event: [pull_request, push]`. En Woodpecker, **`push` dispara en CADA push
a CUALQUIER rama** — no solo a `main`. O sea que cada commit de una rama de trabajo corría el pipeline
**dos veces**: una por el push a la rama y otra por el `pull_request`, **sobre el mismo SHA**. Y una rama
pusheada sin PR levantaba pods igual, sin gatear nada.

Medido en `ai-asset-pipeline` (misma forma en los 27 repos): pipelines `#19` (push, rama
`fix-ci-clonar-el-toolkit…`) y `#20` (pull_request), **ambos sobre `60a6393d`**. Idem `#23`/`#24` sobre
`551313de`.

**Fix:** el `when` pasa a dos condiciones — `pull_request` (cualquier rama) **o** `push` **restringido a
`main`**. Es el patrón que `fran-colarusso/riviera.yml` ya usaba bien y nunca se propagó.

**Por qué es seguro (verificado contra la API, no asumido):** el evento `pull_request` **se re-dispara en
cada commit nuevo del PR** — 6 SHAs distintos del PR, cada uno con su pipeline. Así que el PR sigue
verificando **todos** los commits. Y el `push` a `main` (post-merge) se conserva, que es lo que dispara
`release`/`deploy`/`promote`.

**Efecto:** se elimina ~la mitad de los pipelines (uno por commit en vez de dos), sin perder un solo gate.

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
