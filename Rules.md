# RULES FOR AI AGENT — Building Amas Code

> You are building **Amas Code**, a CLI AI coding agent in ~760 lines of Python.
> Read PLAN.md and README.md fully before writing any code.

---

## PRIME DIRECTIVES

1. **LESS CODE IS BETTER.** Every line you write is a line that must be maintained. If a package does it, use the package. If stdlib does it, use stdlib. If you can delete a line without losing functionality, delete it.

2. **NEVER reinvent what a package provides.** You are a GLUE CODER. Your job is to wire robust packages together, not reimplement their internals.

3. **Target: ~760 lines total across all files.** If you exceed 900 lines, you are doing it wrong. Stop and refactor.

4. **It MUST run on 1GB RAM Raspberry Pi.** No heavy frameworks. No background daemons. Lazy-load everything expensive (playwright, tree-sitter). Stream, don't buffer.

---

## PROJECT STRUCTURE (STRICT)

```
amas-code/
├── amas_code/
│   ├── __init__.py       # Version only
│   ├── amas.py           # ~40 lines  — CLI entry (click)
│   ├── agent.py          # ~120 lines — Agent loop, messages, compact
│   ├── tools.py          # ~250 lines — All tools + schemas + handlers
│   ├── ui.py             # ~120 lines — Rich UI (diffs, panels, prompts)
│   ├── providers.py      # ~60 lines  — LiteLLM wrapper
│   ├── checkpoint.py     # ~40 lines  — Git-based checkpoints
│   ├── browser.py        # ~60 lines  — Playwright wrapper (lazy-loaded)
│   ├── skills.py         # ~30 lines  — Skills + rules loader
│   └── config.py         # ~40 lines  — YAML config management
├── pyproject.toml
├── README.md
├── PLAN.md
└── LICENSE
```

**Do NOT:**
- Create additional files beyond this structure
- Create a `utils.py`, `helpers.py`, or `constants.py` — inline everything
- Create subdirectories inside `amas_code/`
- Create test files until all features work
- Create any `__main__.py` — use click entry point

---

## DEPENDENCY RULES

### MUST USE — These are non-negotiable

| Package | Use For | Import Style |
|---------|---------|-------------|
| `litellm` | ALL LLM calls — completion, streaming, tool calling | `import litellm` |
| `rich` | ALL terminal output — console, syntax, diff, panel, markdown, table, tree, spinner | `from rich.console import Console` etc. |
| `prompt_toolkit` | User input — multiline, history, keybindings | `from prompt_toolkit import PromptSession` |
| `click` | CLI commands and args | `import click` |
| `pyyaml` | Config read/write | `import yaml` |
| `gitpython` | Checkpoints, undo, redo | `from git import Repo` |
| `googlesearch-python` | Web search tool | `from googlesearch import search` |
| `httpx` | URL fetching | `import httpx` |

### LAZY-LOAD ONLY — Import inside function, never at top of file

| Package | Why Lazy |
|---------|----------|
| `playwright` | 150MB RAM, only needed for browser tools |
| `tree_sitter` + `tree_sitter_languages` | Only needed for `init` command |

**Pattern for lazy loading:**
```python
def navigate(url):
    from playwright.sync_api import sync_playwright  # HERE, not top of file
    ...
```

### STDLIB — Use instead of packages for these

| Need | Use | NOT |
|------|-----|-----|
| File operations | `pathlib.Path` | `os.path` |
| Diffs | `difflib.unified_diff` | Any diff package |
| JSON | `json` | msgpack, orjson |
| Subprocesses | `subprocess.run` | sh, plumbum |
| Time | `time.time()` | arrow, pendulum |
| Temp files | `tempfile` | Any |
| Regex | `re` | regex |
| Copy | `shutil` | Any |

### NEVER INSTALL

- `langchain` — Bloated, we use litellm directly
- `autogen` — We ARE the agent framework
- `transformers` — We call APIs, not run models
- `pandas` — We don't process data
- `numpy` — Same
- `flask/fastapi` — This is CLI only
- `typer` — We use click
- `colorama` — We use rich
- `tqdm` — We use rich
- Any ORM or database — We use JSONL and git

---

## CODING RULES

### Python Style

- **Python 3.10+ minimum** — Use `match/case`, `X | Y` unions, `list` not `List`
- **Type hints on function signatures** — But don't over-annotate internals
- **No classes unless state is needed** — Prefer functions. Only `Checkpoint`, `Browser`, `Agent` deserve classes.
- **No abstract base classes, no protocols, no metaclasses** — This is glue code, not a framework
- **No dataclasses for simple dicts** — Tool schemas are dicts, config is a dict, messages are dicts
- **f-strings everywhere** — Never `.format()` or `%`
- **One file = one concern** — Never put UI code in agent.py or tool code in ui.py

### Function Rules

- **Max 25 lines per function** — If longer, split it
- **Max 4 parameters per function** — Use a config dict if more
- **Every tool handler: input → string output** — Tools always return strings for the LLM
- **No nested functions deeper than 1 level** — No closures-in-closures
- **No decorators except `@click` commands** — Keep it simple

### Error Handling

- **Wrap tool execution in try/except** — Tools must NEVER crash the agent loop
- **Return error strings from tools, don't raise** — `return f"Error: {e}"` not `raise`
- **Let litellm handle API errors** — Don't wrap litellm calls in custom retry logic
- **Show errors to user via `ui.error()`** — Never print() or silent fail

### Import Rules

```python
# TOP OF FILE — stdlib only
import json
import time
from pathlib import Path

# SECOND BLOCK — packages
import click
from rich.console import Console

# NEVER at top — lazy loaded packages
# playwright, tree_sitter — inside functions only
```

---

## ARCHITECTURE RULES

### Agent Loop (agent.py)

```
THE LOOP — This is the heart of everything:

while True:
    user_input = get_input()
    if user_input starts with "/": handle_command(user_input)
    else:
        messages.append({"role": "user", "content": user_input})
        while True:  # Tool loop
            response = call_model(messages, tools)
            messages.append(response)
            if response has tool_calls:
                for tool_call in tool_calls:
                    result = execute_tool(tool_call)
                    messages.append(tool_result)
                # Continue loop — let model see results
            else:
                display_response(response)
                break  # Exit tool loop, wait for user
```

**Rules:**
- The agent loop is a `while True` — never exits except on `/quit`
- Tool calls loop back automatically — the model decides when to stop
- NEVER limit tool call iterations with a hard cap — trust the model (but add a soft warning at 20+ iterations)
- Messages list is the ONLY state — everything flows through it
- Compact when token count exceeds config threshold

### Tool System (tools.py)

**Every tool has exactly 3 things:**

1. **Schema** — A dict matching OpenAI function-calling format
2. **Handler** — A function that takes kwargs and returns a string
3. **Registry entry** — `HANDLERS[name] = function`

```python
# THIS PATTERN, EVERY TIME:
TOOLS = []  # List of schema dicts
HANDLERS = {}  # name → function

def read_file(path: str) -> str:
    """Read a file and return contents with line numbers."""
    try:
        content = Path(path).read_text()
        lines = content.splitlines()
        numbered = "\n".join(f"{i+1:4} | {l}" for i, l in enumerate(lines))
        return numbered
    except Exception as e:
        return f"Error reading {path}: {e}"

TOOLS.append({
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read file contents with line numbers",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"]
        }
    }
})
HANDLERS["read_file"] = read_file
```

**Tool rules:**
- ALL tools return strings — never dicts, lists, or None
- ALL tools catch their own exceptions
- File-modifying tools (write, edit, create) MUST call `ui.show_diff()` and `ui.confirm()` before applying (unless auto-accept is on)
- File-modifying tools MUST call `checkpoint.save()` after applying
- Shell tool MUST have a timeout (default 30s)
- Shell tool MUST capture both stdout and stderr
- Browser tools MUST lazy-load playwright

### Accept/Decline Flow (CRITICAL)

```python
# EVERY file modification tool must do this:
def edit_file(path, old_str, new_str):
    content = Path(path).read_text()
    if old_str not in content:
        return f"Error: string not found in {path}"
    if content.count(old_str) > 1:
        return f"Error: string appears multiple times in {path}, be more specific"
    
    new_content = content.replace(old_str, new_str, 1)
    
    # SHOW DIFF — always
    ui.show_diff(content, new_content, path)
    
    # ASK — unless auto-accept
    if not config.get("auto_accept") and not ui.confirm("Accept edit?"):
        return "Edit declined by user."
    
    # APPLY
    Path(path).write_text(new_content)
    checkpoint.save(f"edit {path}")
    return f"Edited {path} successfully."
```

**NEVER skip the diff + confirm step. This is a core UX promise.**

### Provider Layer (providers.py)

```python
# THIS IS ALMOST THE ENTIRE FILE:
import litellm

def complete(messages, tools, config, on_chunk=None):
    response = litellm.completion(
        model=config["model"],
        messages=messages,
        tools=tools if tools else None,
        stream=True,
        api_key=config.get("api_key"),
        api_base=config.get("api_base"),
    )
    # Handle streaming, accumulate response
    # Call on_chunk for UI updates
    # Return final message dict
```

**Rules:**
- ONE function: `complete()` — that's it
- LiteLLM handles everything: format conversion, retries, auth
- Pass `stream=True` always — never buffer full responses
- Config dict passed in, never read global state
- Support `on_chunk` callback for streaming UI

### Checkpoint System (checkpoint.py)

**Use git, nothing else.**

```python
from git import Repo

class Checkpoint:
    def __init__(self, path="."):
        self.repo = Repo(path) if Path(path, ".git").exists() else None
    
    def save(self, msg): ...      # git add -A && git commit
    def undo(self, n=1): ...      # git reset --hard HEAD~n
    def list(self, n=20): ...     # git log --oneline
    def restore(self, hash): ...  # git reset --hard <hash>
```

**Rules:**
- If no .git exists, checkpoint operations are no-ops (don't crash)
- Commit messages prefixed with `[amas]` to distinguish from user commits
- Never force push, never touch branches — work on current branch only
- `undo` is `git reset --hard` — destructive, that's fine, we have history

### UI (ui.py)

**One global `Console` instance. All output goes through `ui.` functions.**

```python
from rich.console import Console
console = Console()

def info(msg): console.print(f"[blue]ℹ[/] {msg}")
def success(msg): console.print(f"[green]✓[/] {msg}")
def error(msg): console.print(f"[red]✗[/] {msg}")
def warning(msg): console.print(f"[yellow]⚠[/] {msg}")
def show_diff(old, new, filename): ...  # rich Syntax with diff
def show_tool_call(name, args): ...     # rich Panel
def show_response(text): ...            # rich Markdown
def confirm(prompt): ...                # Yes/No prompt
def show_summary(actions): ...          # rich Table
```

**Rules:**
- NEVER use `print()` anywhere in the codebase — always `ui.*` or `console.*`
- NEVER use ANSI escape codes — Rich handles all formatting
- Diffs use `difflib.unified_diff` → rendered with `rich.syntax.Syntax`
- Streaming responses show a spinner, then replace with final markdown

### Config (config.py)

```python
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "model": "gemini/gemini-2.5-flash",
    "auto_accept": False,
    "max_context_tokens": 32000,
    "checkpoint_on_edit": True,
    "stream": True,
    "ignore": ["node_modules", "__pycache__", ".git", "*.pyc", "dist", "build"],
}

def load(path=".amas/config.yaml"):
    if Path(path).exists():
        user = yaml.safe_load(Path(path).read_text()) or {}
        return {**DEFAULT_CONFIG, **user}
    return DEFAULT_CONFIG.copy()

def save(config, path=".amas/config.yaml"):
    Path(path).parent.mkdir(exist_ok=True)
    Path(path).write_text(yaml.dump(config, default_flow_style=False))
```

**Rules:**
- Defaults are sane — works out of the box with Gemini free tier
- User config overrides defaults via dict merge
- API keys can come from config OR environment variables
- LiteLLM reads env vars automatically (ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.)

---

## SYSTEM PROMPT RULES

The system prompt sent to the LLM must follow this template:

```
You are Amas Code, an elite AI coding assistant and principal software engineer.
You execute tasks autonomously and thoroughly.

# Core Mandates
- **Engineering Standards & Completeness:** Never leave "TODO" or placeholder code. Always implement full, robust logic.
- **Idiomatic Code & Visuals:** Write idiomatic code. Ensure UIs are modern, polished, and use consistent spacing.
- **Development Lifecycle:** Research -> Strategy -> Execution -> Validation.
- **Validation:** Always verify your changes through tests or manual checks before declaring success. Fix all console errors.

# Browser Control & Web Interaction
(Include detailed Mandatory Browser Rules and Chatbot Interaction Pattern here)

## Rules
- ALWAYS read a file before editing it.
- Explain your plan before executing multi-step changes.
- Provide FULL file content when using write_file.

## Context & Rules
{project_map from init, if available}
{contents of .amas/rules.md, if exists}
{contents of matched .amas/skills/*.md files}
```

**Rules:**
- System prompt is rebuilt every conversation turn (project context may change)
- Skills are matched by keyword to current conversation topic
- Keep system prompt under 2000 tokens — trim project map if needed
- Rules.md content is included verbatim — user controls it

---

## IMPLEMENTATION ORDER (STRICT)

Build in this EXACT order. Each phase must be fully working before starting the next.

### Phase 1: Skeleton
1. `pyproject.toml` with all dependencies
2. `config.py` — load/save config
3. `ui.py` — basic console output functions (info, error, success)
4. `providers.py` — litellm.completion wrapper with streaming
5. `agent.py` — bare agent loop: input → LLM → display (no tools)
6. `amas.py` — click CLI entry point
7. **TEST:** `amas "hello"` works, gets response from LLM, displays it

### Phase 2: Tools
8. `tools.py` — define TOOLS list and HANDLERS dict
9. Implement: `read_file`, `write_file`, `create_file`, `edit_file`
10. Implement: `shell_command`, `search_files`, `list_files`
11. Update `agent.py` — handle tool_calls in response, execute, loop back
12. Add diff display and confirm to file tools in `ui.py`
13. **TEST:** `amas "create a hello.py that prints hello world"` creates the file

### Phase 3: Checkpoints
14. `checkpoint.py` — Checkpoint class with save/undo/list/restore
15. Wire into file-modifying tools — auto-checkpoint on edit
16. Add `/undo`, `/redo`, `/checkpoint` slash commands to agent
17. **TEST:** Make edits, `/undo` rolls them back

### Phase 4: Intelligence
18. Add `init` command — scan files with tree-sitter (lazy loaded)
19. `skills.py` — load rules.md and skills/*.md
20. Build system prompt from template + project context + rules + skills
21. Add `/compact` — summarize conversation when context is long
22. **TEST:** `amas init` then ask about the codebase, AI knows the structure

### Phase 5: Web + Browser
23. Add `search_google` tool
24. Add `fetch_url` tool with httpx
25. `browser.py` — Browser class with lazy playwright
26. Add browser tools: navigate, click, type, screenshot, get_text
27. **TEST:** `amas "search for python asyncio best practices"` returns results

### Phase 6: Polish
28. Streaming UI — token-by-token display with rich Live
29. Tool call panels — collapsible rich panels showing tool name + args
30. Action summary table after each turn
31. `/help` command listing all commands
32. History — JSONL append in .amas/history.jsonl
33. `/attach` command — inject file contents
34. Error handling pass — ensure no unhandled exceptions
35. **TEST:** Full workflow end-to-end, looks beautiful

---

## TESTING RULES

- **Manual test after every phase** — Run actual CLI commands
- Test with at least 2 different models (e.g., Gemini Flash + Ollama)
- Test on constrained environment if possible (limit to 512MB RAM with `ulimit`)
- Test these critical flows:
  - Create a new file → verify it exists
  - Edit a file → verify diff shown → accept → verify changed
  - Edit a file → decline → verify NOT changed
  - `/undo` after edit → verify reverted
  - Long conversation → `/compact` → verify still works
  - `/init` on a real project → verify function extraction
  - Tool error (read nonexistent file) → verify graceful error message
  - Network error (bad API key) → verify graceful error message

---

## WHAT NOT TO BUILD

- ❌ Web server or REST API
- ❌ GUI or TUI framework (curses, textual) — Rich + prompt_toolkit is enough
- ❌ Plugin system with dynamic loading — skills are just markdown files
- ❌ Database — JSONL for history, git for checkpoints
- ❌ User auth or multi-user support
- ❌ Async/await — Keep it synchronous (simpler, less RAM)
- ❌ Custom streaming protocol — Use litellm's built-in streaming
- ❌ Token counting library — Use litellm's `token_counter()`
- ❌ Custom diff algorithm — Use `difflib`
- ❌ File watcher daemon — Scan on demand only
- ❌ Conversation branching/forking — Linear history only
- ❌ Image generation or vision — Text only (for now)
- ❌ Voice input/output
- ❌ Auto-update mechanism
- ❌ Telemetry or analytics

---

## NAMING CONVENTIONS

- **Files:** `snake_case.py`
- **Functions:** `snake_case`
- **Classes:** `PascalCase` (only Agent, Checkpoint, Browser)
- **Constants:** `UPPER_SNAKE` (only TOOLS, HANDLERS, DEFAULT_CONFIG)
- **Config keys:** `snake_case` in YAML
- **Tool names:** `snake_case` (matches function names exactly)
- **Slash commands:** `/lowercase` with no underscores
- **Commit messages:** `[amas] description` for checkpoint commits

---

## EDGE CASES TO HANDLE

1. **No .git directory** — Checkpoint operations silently no-op
2. **No config file** — Use defaults (Gemini Flash, all features on)
3. **No API key** — Show helpful error with setup instructions
4. **Binary files** — `read_file` detects and returns "Binary file, cannot display"
5. **Very large files** — `read_file` truncates at 50KB with warning
6. **Empty tool response** — Return "Tool executed successfully (no output)"
7. **Model doesn't support tools** — Fall back to prompt-based tool calling
8. **Network timeout** — Retry once, then show error
9. **User Ctrl+C during generation** — Catch KeyboardInterrupt, keep agent loop alive
10. **Concurrent file edit** — Not handled (single user tool, acceptable)
11. **Path traversal** — Warn if tool tries to access files outside project root
12. **Circular tool calls** — Soft warning at 20+ iterations per turn

---

## PERFORMANCE BUDGET

| Metric | Target |
|--------|--------|
| Startup time | < 1 second |
| Memory (idle) | < 80 MB |
| Memory (active, no browser) | < 150 MB |
| Memory (with browser) | < 300 MB |
| Tool execution (file ops) | < 100ms |
| Tool execution (shell) | Timeout at 30s |
| Init scan (1000 files) | < 5 seconds |

**How to hit these targets:**
- Lazy import everything heavy
- Never load full conversation history into RAM (stream from JSONL)
- Stream LLM responses (never buffer full response)
- Use `subprocess.run` not `Popen` for shell (simpler, auto-cleanup)
- Tree-sitter grammars loaded per-language, not all at once

---

## FINAL CHECKLIST BEFORE EACH COMMIT

- [ ] Total line count under 900?
- [ ] No `print()` statements? (use `ui.*`)
- [ ] No top-level playwright/tree-sitter imports?
- [ ] All tools return strings?
- [ ] All file-modifying tools show diff + confirm?
- [ ] All file-modifying tools call checkpoint.save()?
- [ ] No unhandled exceptions in tool handlers?
- [ ] Config defaults work without any setup?
- [ ] Works with `python -m amas_code` and `amas` command?
- [ ] Streaming works for the default model?

---

*Remember: The best code is no code. The second best is someone else's well-tested package. The distant third is code you write yourself.*