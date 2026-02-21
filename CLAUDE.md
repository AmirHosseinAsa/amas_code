# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Amas Code** is a terminal-based AI coding agent that wraps any LLM provider (Claude, Gemini, GPT, Ollama, etc.) via LiteLLM. **Core philosophy:** use packages, write less code, keep everything readable in an afternoon. **Target: ~760 lines total** across all files. If code exceeds 900 lines, something is wrong.

The system is designed to run on minimal hardware (1GB RAM Raspberry Pi), uses synchronous I/O only, and relies on lazy-loading of expensive dependencies (playwright, tree-sitter).

## Quick Start

```bash
# Install in dev mode (from repo root)
pip install -e .

# Install optional deps
pip install -e ".[browser]"   # Playwright browser tools (150MB, lazy-loaded)
pip install -e ".[parsing]"   # tree-sitter for /init symbol extraction (lazy-loaded)
pip install -e ".[all]"       # Everything

# Run the agent
amas                                                    # Interactive session
amas "what files are in this project?"                # One-shot mode
amas --model gemini/gemini-2.5-flash "prompt"        # Override model
```

No automated test suite. Manual testing is the primary method. **Python 3.10+ required** (uses `match/case`, `X | Y` unions).

## Architecture Overview

The core loop is simple: input → slash command OR chat turn → LLM → tool calls (loop) → display response.

```
amas_code/
├── amas.py         → CLI entry (click), /config /init commands, dispatches to Agent
├── agent.py        → Agent loop: get_input() → handle command/chat → messages list → repeat
├── providers.py    → litellm.completion() wrapper + streaming + tool_calls assembly
├── tools.py        → TOOLS list (schemas) + HANDLERS dict (functions), all tool implementations
├── web.py          → web_search, fetch_url, browser tools (playwright lazy-loaded)
├── skills.py       → load_rules(), load_skills(), init_project() with tree-sitter
├── checkpoint.py   → Git-based checkpoints: save/undo/redo/list/restore
├── config.py       → YAML config loader, KNOWN_MODELS, resolve_api_key()
├── history.py      → Chat session management (JSONL append, search, restore)
└── ui.py           → Rich console output (single Console instance, all formatting)
```

## Key Architectural Decisions

### The Agent Loop (agent.py)
```
while True:
    user_input = get_input()
    if input.startswith("/"): handle_slash_command(input)
    else:
        messages.append({"role": "user", "content": input})
        while True:  # Tool loop
            response = providers.complete(messages, tools)
            messages.append(response)
            if response has tool_calls:
                for call in tool_calls:
                    result = HANDLERS[call.name](**call.args)
                    messages.append({"role": "tool", "content": result})
            else: break  # Exit tool loop
```
**Rules:** Messages list is the only state. Tools loop until the model stops calling them. NEVER cap iterations with a hard limit—trust the model (but warn at 20+).

### Tool System (tools.py)
Every tool has exactly 3 parts:
1. **Schema** — OpenAI function-calling format dict (name, description, parameters)
2. **Handler** — Function with kwargs → str (always return string)
3. **Registry** — `HANDLERS["tool_name"] = function`

File-modifying tools **MUST:**
- Call `ui.show_diff(old, new, path)` before writing
- Call `ui.confirm()` to check auto_accept flag
- Call `checkpoint.save(f"action {path}")` after writing

### Config System (config.py)
Lives at `.amas/config.yaml` (auto-created first run). Default model is Gemini Flash (free tier friendly). API keys come from:
1. Config `api_keys` dict
2. Environment variables (ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.)
3. LiteLLM's fallback env var lookup

Key settings: `model`, `stream`, `auto_accept`, `max_context_tokens`, `checkpoint_on_edit`, `ignore` (glob patterns).

### Git-Based Checkpoints (checkpoint.py)
All changes auto-checkpoint (if enabled). Uses git commits prefixed `[amas]` to distinguish from user commits. `/undo` is `git reset --hard`, so it's destructive—that's intentional and safe because we have history. Auto-initializes .git if absent.

### Lazy Loading
**Heavy imports go INSIDE functions, never at top of file:**
- `playwright` (150MB) — imported only in browser_* tool handlers
- `tree_sitter` / `tree_sitter_languages` — imported only in `/init` command

This keeps startup time < 1 second and memory footprint tiny.

## Dependency Rules

**MUST USE (non-negotiable):**
- `litellm` — ALL LLM calls (handles all providers, streaming, tool calling)
- `rich` — ALL terminal output (Console, Syntax, Panel, Markdown, Table, Tree)
- `prompt-toolkit` — User input (multiline, history, completions)
- `click` — CLI entry point and commands
- `pyyaml` — Config read/write
- `gitpython` — Checkpoints (Repo, Index, Commit)
- `googlesearch-python` — Web search
- `httpx` — URL fetching
- `beautifulsoup4` — HTML parsing in web tools

**NEVER install:**
langchain, autogen, pandas, numpy, flask, fastapi, typer, colorama, tqdm, transformers, any ORM/database, async/await frameworks.

**STDLIB preferred over packages:**
- `pathlib.Path` over os.path
- `difflib.unified_diff` over diff packages
- `json` over msgpack/orjson
- `subprocess.run` over sh/plumbum
- `tempfile` over any wrapper
- `re` over regex

## Code Style Rules

**Critical:**
- Max 25 lines per function (split if longer)
- Max 4 parameters per function (use dict if more)
- No top-level imports of playwright, tree_sitter
- All tools return strings (never None, dicts, lists)
- All file-modifying tools show diff + confirm + checkpoint
- f-strings everywhere (never .format() or %)
- No print() — use `ui.*` or `console.*`
- No ANSI codes — Rich handles formatting
- One file = one concern (no tools in agent.py, no UI in tools.py)

**Type hints on function signatures** (but not obsessive on internals).
**No classes except Agent, Checkpoint, Browser** (prefer functions).
**No dataclasses for simple dicts** (config/tools/messages are plain dicts).

## File Structure Rules

**DO NOT:**
- Create additional files beyond the 11 listed in Architecture
- Create `utils.py`, `helpers.py`, `constants.py` — inline everything
- Create subdirectories inside `amas_code/`
- Create test files before core features work
- Use `__main__.py` — use click entry point

**Project root files allowed:**
`CLAUDE.md`, `Rules.md`, `README.md`, `pyproject.toml`, `.gitignore`, `.amas/` (config dir)

## Common Development Tasks

### Adding a New Tool
1. Write handler function in `tools.py` (returns string)
2. Build schema dict using `_schema()` helper
3. Append to TOOLS list
4. Register in HANDLERS dict
5. If file-modifying: add diff/confirm/checkpoint
6. Test with `amas "do something that uses the tool"`

### Adding a Slash Command
1. Add handler function in `agent.py` (in `_handle_command()`)
2. Add help text in `/help` output
3. Test with `amas` then `/your_command`

### Adding a Config Option
1. Add default to `DEFAULT_CONFIG` in `config.py`
2. Read with `config.get("key", default)`
3. Document in config.py docstring

## Testing Checklist

No automated tests. Manually verify these flows:
- `amas "create a hello.py"` → file created, checkpoint saved
- Edit file → diff shown → accept/decline works → checkpoints correct
- `/init` on a real project → extracts functions/classes
- `/undo` after edit → reverted correctly
- Long conversation → `/compact` summarizes → still works
- Different models: `--model gpt-4o`, `--model ollama/llama3`
- Tool error (read nonexistent file) → graceful error message shown
- Network error (bad API key) → helpful error, doesn't crash loop

## Slash Commands Reference

Full list in `agent.py`:
- `/help` — Show all commands
- `/init` — **Intelligent project scan:** Analyzes key files (reading their content), generates a smart summary of what each file does + its exported functions/classes, saves to `.amas/project_map.md`, and injects into system prompt. Auto-loaded on subsequent sessions. This is how the AI agent understands your entire project without context bloat.
- `/model [name|list]` — Show/change default model
- `/key <provider> [key]` — Set API key
- `/config` — Interactive config wizard
- `/yolo` — Toggle auto-accept mode
- `/attach <path>` — Inject file contents
- `/checkpoint [msg]` — Create manual checkpoint
- `/undo [n]` — Undo last n changes
- `/redo [n]` — Redo last n undone changes
- `/history [search]` — List/search chat sessions
- `/compact` — Summarize long conversation
- `/cost` — Show approximate token costs
- `/rules` — Show current rules
- `/skills` — Show loaded skills
- `/clear` — Clear current chat
- `/quit` — Exit agent

## User Customization

Users can customize behavior via `.amas/` directory:
- `.amas/config.yaml` — Model, API keys, auto-accept, context limit, file ignore patterns
- `.amas/rules.md` — Project-specific rules injected into system prompt every turn
- `.amas/skills/*.md` — Skill files (e.g., `python-expert.md`, `frontend-dev.md`) loaded at startup

These are included in the system prompt, so the LLM sees them.

## Important Performance Constraints

- **Startup:** < 1 second (lazy-load expensive deps)
- **Memory idle:** < 80 MB
- **Memory active (no browser):** < 150 MB
- **Memory with browser:** < 300 MB
- **File operations:** < 100ms
- **Shell timeout:** 30s
- **Init scan (1000 files):** < 5s

Hit these by: lazy importing, streaming responses, subprocess.run not Popen, loading grammars per-language.

## What NOT to Build

- Web server or REST API
- TUI framework (curses, textual) — Rich + prompt_toolkit is enough
- Plugin system with dynamic loading — skills are just markdown
- Database — use JSONL for history, git for checkpoints
- User auth or multi-user
- Async/await — stay synchronous
- Custom streaming protocol — use litellm's built-in
- Token counter library — use litellm's
- Custom diff — use difflib
- File watcher daemon
- Conversation branching
- Image generation or vision — text only
- Voice I/O
- Auto-update
- Telemetry

## System Prompt Structure

Rebuilt every turn and sent to LLM:
```
You are Amas Code, an elite AI coding assistant...

# Core Mandates
- Technical Integrity & Completeness
- Idiomatic Code & Visuals
- Development Lifecycle: Research → Strategy → Execution → Validation

# Tool Rules
[All tool rules...]

# Browser Control & Web Interaction
[All browser rules...]

---

{project_map from /init, if available}
{contents of .amas/rules.md, if exists}
{matched .amas/skills/*.md files}
```

Keep under 2000 tokens total.

## See Also

- **Rules.md** — Exhaustive implementation rules, architecture patterns, and testing checklist
- **README.md** — User-facing overview and quick start
- **pyproject.toml** — Dependencies and entry point
