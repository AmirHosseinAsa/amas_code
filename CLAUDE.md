# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Amas Code** is a terminal-based AI coding agent that wraps any LLM provider (Claude, Gemini, GPT, Ollama, etc.) via LiteLLM. Core philosophy: use packages, write less code, keep everything readable in an afternoon. Target: ~760 lines total across all files.

## Development Commands

```bash
# Install in dev mode (from repo root)
pip install -e .

# Install optional deps
pip install -e ".[browser]"   # Playwright browser tools (150MB)
pip install -e ".[parsing]"   # tree-sitter for /init symbol extraction
pip install -e ".[all]"       # Everything

# Run the agent
amas                              # Interactive session
amas "prompt"                     # One-shot mode
amas --model gemini/gemini-3-flash-preview  # Override model
```

No automated test suite. Manual testing is the primary method. Python 3.10+ required (uses `match/case`, `X | Y` unions).

## Architecture

```
amas_code/
├── amas.py        → CLI entry (click), --model/--yolo flags, dispatches to Agent
├── agent.py       → Agent class: input → slash commands or chat_turn()
├── providers.py   → litellm.completion wrapper, streaming, tool_calls assembly
├── tools.py       → All tool schemas (TOOLS list) + handlers (HANDLERS dict)
├── web.py         → web_search, fetch_url, and all browser_* tools (playwright lazy-loaded)
├── skills.py      → load_rules(), load_skills(), init_project() with tree-sitter
├── checkpoint.py  → Git-based undo/redo (auto-inits .git if absent)
├── config.py      → Load/save .amas/config.yaml, KNOWN_MODELS, resolve_api_key()
└── ui.py          → All Rich terminal output (single Console instance)
```

**Agent loop:** `get_input()` → slash command handler OR `chat_turn()` → `providers.complete()` → stream tokens → handle tool_calls in a loop → append to message history → repeat.

**Tool system:** Tools follow a strict 3-part pattern: schema dict (OpenAI function-calling format) + handler function (always returns `str`) + `HANDLERS[name] = fn`. All file-modifying tools must call `ui.show_diff()` + `ui.confirm()` before writing, and `checkpoint.save()` after.

**Config** lives at `.amas/config.yaml` (auto-created on first run). Default model: `gemini/gemini-3-flash-preview`. Config keys: `model`, `stream`, `auto_accept`, `max_context_tokens`, `checkpoint_on_edit`, `ignore`. API keys also read from env vars via litellm (e.g. `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).

**User customization** via `.amas/` directory:
- `.amas/rules.md` — project-specific rules injected into every system prompt
- `.amas/skills/*.md` — skill markdown files loaded at startup and included in system prompt

## Slash Commands & @ References

`/help`, `/yolo` (toggle auto-accept), `/init` (scan project + symbols), `/model [name|list]`, `/key <provider> [key]`, `/config`, `/undo`, `/redo`, `/checkpoint`, `/history`, `/compact`, `/rules`, `/skills`, `/clear`, `/cost`, `/attach <path>`, `/quit`

**`@file` references:** Type `@` anywhere in the prompt to trigger a fuzzy file picker — the dropdown shows project files filtered as you type, arrow keys to navigate, Enter to select. Submitting a message with `@path/to/file` automatically reads the file and prepends its contents. Implemented in `InputCompleter` (handles both `/` commands and `@` files) and `Agent._expand_at_refs()`.

## Coding Rules (from Rules.md)

**Packages to use:** `litellm` (all LLM), `rich` (all UI), `prompt-toolkit` (input), `click` (CLI), `pyyaml` (config), `gitpython` (checkpoints), `googlesearch-python` (web search), `httpx` (URL fetch).

**Never use:** `langchain`, `autogen`, `pandas`, `numpy`, `flask`, `fastapi`, `typer`, any ORM/database, async/await.

**Lazy-load only:** `playwright` (browser tools) and `tree_sitter`/`tree_sitter_languages` (`/init` command) — import inside functions, never at top of file.

**Stdlib preferred:** `pathlib`, `json`, `subprocess`, `difflib`, `tempfile`, `re` over third-party equivalents.

**Style:** Max 25 lines/function, max 4 parameters/function, f-strings everywhere, no `print()` (use `ui.*`), no ANSI codes (Rich handles formatting), one file = one concern.

## Development Phases

1. **Core** (done) — Chat loop, multi-model, streaming
2. **Tools** (done) — File ops, shell exec, search
3. **Intelligence** (done) — `/init` scan with tree-sitter/regex fallback, skills, rules, `/compact`
4. **Safety** (done) — Git checkpoints, `/undo`, `/redo`, `/history`
5. **Extras** (done) — web_search, fetch_url, full browser control via playwright
6. **Polish** (in progress) — Streaming UI panels, config wizard, CI/CD
