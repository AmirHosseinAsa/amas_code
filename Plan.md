# AMAS CODE — Development Plan

> **Philosophy:** Every line of code you write is a line you must maintain. Use packages. Be lazy. Be smart.

---

## 1. Architecture Overview

```
amas-code/
├── amas.py              # Entry point + CLI (~40 lines)
├── agent.py             # Agent loop + conversation (~120 lines)
├── tools.py             # All tool definitions (~250 lines)
├── ui.py                # Rich-based terminal UI (~120 lines)
├── providers.py         # LiteLLM wrapper, multi-model (~60 lines)
├── checkpoint.py        # Git-based checkpoints (~40 lines)
├── browser.py           # Playwright-lite browser control (~60 lines)
├── skills.py            # Skills/rules loader (~30 lines)
├── config.py            # Config + provider setup (~40 lines)
├── .amas/
│   ├── config.yaml      # User config (model, keys, preferences)
│   ├── history.jsonl     # Conversation history (append-only)
│   ├── rules.md          # Project rules
│   └── skills/           # Skill markdown files
├── pyproject.toml
└── README.md

TOTAL: ~760 lines of Python (target)
```

### Why This is 10x Better Than Claude Code

| Feature | Claude Code | Amas Code |
|---------|------------|-----------|
| Models | Claude only | Gemini, GLM, Claude, OpenAI, Ollama, ANY via LiteLLM |
| Hardware | Needs good machine | Runs on Raspberry Pi / 1GB RAM |
| Checkpoints | Limited | Full git-based snapshots with named tags |
| Redo/Undo | No | Instant rollback to any checkpoint |
| Browser | No | Built-in Playwright browser control |
| Skills | Hardcoded | User-extensible `.amas/skills/` |
| Search | No | Google search built-in |
| Compact | No | Auto-summarize when context grows |
| Accept/Decline | Auto-apply | Interactive diff review per edit |
| Price | $20/mo or API | Use free Gemini, local Ollama, or any API |
| Code | Closed source | Open source, hackable, <800 lines |
| Init | Basic | Deep scan: file tree + function/class extraction |

---

## 2. Core Packages (The Secret Sauce)

These packages do 95% of the work. **We write only glue code.**

### Critical Dependencies (MUST HAVE)

| Package | Purpose | Why It Saves 1000+ Lines |
|---------|---------|--------------------------|
| **litellm** | Multi-model API | ONE interface for Claude, Gemini, GLM, OpenAI, Ollama, 100+ models. Handles auth, streaming, tool calling, retries. Without this we'd write 500+ lines per provider. |
| **rich** | Terminal UI | Beautiful tables, syntax highlighting, diffs, markdown, spinners, panels, trees — all with 1-line calls. Replaces building a TUI from scratch. |
| **prompt_toolkit** | Input handling | Multiline input, history, autocomplete, key bindings. Readline on steroids. |
| **click** | CLI framework | Decorators for commands, args, help text. Zero boilerplate. |
| **pyyaml** | Config files | Load/save `.amas/config.yaml` in 2 lines. |
| **tree-sitter** + grammars | Code parsing | Extract functions/classes from ANY language. One API for Python, JS, Rust, Go, C, etc. Powers `init` and context building. |
| **gitpython** | Checkpoints | `repo.index.commit()` — checkpoint in one line. Branch, tag, diff, rollback. |
| **playwright** | Browser control | Headless browser: navigate, click, extract, screenshot. 3 lines to control Chrome. |
| **googlesearch-python** | Web search | `search("query")` returns URLs. That's it. One line. |
| **httpx** | HTTP client | Async-ready, fast, modern replacement for requests. For web fetching. |

### Optional / Lightweight

| Package | Purpose | Size |
|---------|---------|------|
| **watchdog** | File watching for live reload | Tiny |
| **difflib** (stdlib) | Generate unified diffs | Built-in |
| **pathlib** (stdlib) | File operations | Built-in |
| **json** (stdlib) | History storage | Built-in |
| **subprocess** (stdlib) | Shell commands | Built-in |

### RAM Budget (1GB Target)

| Component | Estimated RAM |
|-----------|--------------|
| Python runtime | ~30 MB |
| Rich + prompt_toolkit | ~15 MB |
| LiteLLM (lazy loaded) | ~20 MB |
| Tree-sitter | ~10 MB |
| Playwright (only when used) | ~150 MB |
| GitPython | ~10 MB |
| Conversation buffer | ~5-50 MB |
| **Total (no browser)** | **~140 MB** ✅ |
| **Total (with browser)** | **~290 MB** ✅ |

> **Key trick:** Lazy-load Playwright only when browser tool is called. Tree-sitter grammars loaded on-demand per language.

---

## 3. Feature Implementation Map

### 3.1 Agent Loop (agent.py ~120 lines)

```
User Input → Build Messages → Call LLM → Parse Response
                                              ↓
                                     Has Tool Calls?
                                    /              \
                                  YES               NO
                                  ↓                  ↓
                          Execute Tools        Display Response
                          Append Results            ↓
                               ↓               Wait for Input
                          Loop Back to
                          "Call LLM"
```

**Implementation:**
- Simple `while True` loop
- LiteLLM handles streaming + tool calling format for ALL providers
- Tools defined as Python dicts (JSON schema) — LiteLLM converts per-provider
- Conversation stored as list of message dicts
- Auto-compact: when token count > threshold, summarize older messages

### 3.2 Tool System (tools.py ~250 lines)

Each tool is a function + a JSON schema dict. That's it.

| Tool | Lines | Implementation |
|------|-------|---------------|
| `read_file` | ~8 | `Path(path).read_text()` + line numbers |
| `write_file` | ~10 | `Path(path).write_text()` + show diff + confirm |
| `edit_file` | ~20 | `str.replace()` with unique match check + diff |
| `create_file` | ~8 | `Path(path).write_text()` + create parents |
| `delete_file` | ~5 | `Path(path).unlink()` with confirm |
| `shell_command` | ~15 | `subprocess.run()` with timeout + output capture |
| `search_files` | ~10 | `grep -rn` via subprocess |
| `list_files` | ~8 | `pathlib.glob` + tree display |
| `search_google` | ~8 | `googlesearch.search()` |
| `fetch_url` | ~10 | `httpx.get()` + extract text |
| `browser_navigate` | ~12 | Playwright: goto + screenshot |
| `browser_click` | ~8 | Playwright: click selector |
| `browser_type` | ~8 | Playwright: fill input |
| `browser_screenshot` | ~5 | Playwright: screenshot to base64 |

**Accept/Decline Flow (inside edit/write tools):**
```python
diff = unified_diff(old, new)
ui.show_diff(diff)
if ui.confirm("Accept this edit?"):
    apply_edit()
    checkpoint.save(f"edit: {path}")
else:
    ui.info("Edit declined.")
```

### 3.3 Init / Project Context (inside tools.py)

```python
def init_project(path="."):
    # 1. Walk directory, skip .git, node_modules, __pycache__, etc.
    # 2. For each source file, use tree-sitter to extract:
    #    - Function names + signatures
    #    - Class names
    #    - Export/import statements
    # 3. Build compact project map as markdown
    # 4. Inject as system message context
```

**Tree-sitter query (same for all languages):**
```
(function_declaration name: (identifier) @fn)
(class_declaration name: (identifier) @cls)
```

### 3.4 Multi-Model Support (providers.py ~60 lines)

```python
import litellm

def call_model(messages, tools, config):
    response = litellm.completion(
        model=config["model"],       # "gemini/gemini-2.5-flash", "claude-sonnet-4-20250514", "glm-4", etc.
        messages=messages,
        tools=tools,
        stream=True,
        api_key=config.get("api_key"),
        api_base=config.get("api_base"),  # For self-hosted / Ollama
    )
    for chunk in response:
        yield chunk
```

**That's it.** LiteLLM handles:
- API format conversion (OpenAI ↔ Anthropic ↔ Google ↔ GLM)
- Tool calling format per provider
- Streaming
- Retries + error handling
- Token counting

**Supported models out of the box:**
- `claude-sonnet-4-20250514`, `claude-opus-4-0520` (Anthropic API)
- `gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro` (Google)
- `glm-4`, `glm-4-flash` (ZhipuAI)
- `ollama/llama3`, `ollama/codellama` (Local)
- `gpt-4o`, `gpt-4o-mini` (OpenAI)
- `deepseek/deepseek-chat` (DeepSeek)
- Any OpenAI-compatible endpoint via `api_base`

### 3.5 Checkpoints (checkpoint.py ~40 lines)

**Use git. Don't reinvent version control.**

```python
from git import Repo

class Checkpoint:
    def __init__(self, path="."):
        self.repo = Repo(path)

    def save(self, message):
        self.repo.git.add(A=True)
        self.repo.index.commit(f"[amas] {message}")

    def undo(self, steps=1):
        self.repo.git.reset("--hard", f"HEAD~{steps}")

    def list(self):
        return list(self.repo.iter_commits(max_count=20))

    def restore(self, commit_hash):
        self.repo.git.reset("--hard", commit_hash)
```

**Redo = `restore(commit_hash)` from history list.**

### 3.6 UI Layer (ui.py ~120 lines)

All powered by `rich`:

```python
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

console = Console()

def show_diff(old, new, filename):
    # rich.syntax with diff highlighting
    
def show_tool_call(name, args):
    # Panel with tool name and formatted args
    
def show_response(text):
    # Markdown rendering
    
def show_action_summary(actions):
    # Table of what was done
    
def confirm(prompt):
    # Yes/No with rich formatting
```

**What the UI shows:**
- 🔧 Tool calls with arguments (collapsible panels)
- 📝 File diffs with syntax highlighting  
- ✅/❌ Accept/decline prompts
- 📊 Summary of all changes made
- 🔄 Streaming response with spinner
- 📁 Project tree (from init)
- 💬 Conversation history

### 3.7 History (built into agent.py)

```python
# Append-only JSONL — minimal, survives crashes
def save_turn(role, content, tool_calls=None):
    with open(".amas/history.jsonl", "a") as f:
        json.dump({"ts": time.time(), "role": role, "content": content, 
                    "tools": tool_calls}, f)
        f.write("\n")

# Load for context
def load_history(last_n=50):
    lines = Path(".amas/history.jsonl").read_text().splitlines()
    return [json.loads(l) for l in lines[-last_n:]]
```

### 3.8 Skills System (skills.py ~30 lines)

```python
def load_skills(path=".amas/skills/"):
    skills = {}
    for f in Path(path).glob("*.md"):
        skills[f.stem] = f.read_text()
    return skills

def get_skill_context(skill_name):
    """Inject skill content into system prompt when relevant"""
    return skills.get(skill_name, "")
```

**Users create skills as markdown files:**
```
.amas/skills/
├── react.md        # React best practices
├── python.md       # Python conventions
├── testing.md      # Testing guidelines
└── deployment.md   # Deploy procedures
```

### 3.9 Rules (.amas/rules.md)

Simple: load file, prepend to system prompt.

```python
rules = Path(".amas/rules.md").read_text() if Path(".amas/rules.md").exists() else ""
system_prompt = BASE_PROMPT + "\n\n## Project Rules\n" + rules
```

### 3.10 Browser Control (browser.py ~60 lines)

```python
from playwright.sync_api import sync_playwright

class Browser:
    def __init__(self):
        self._pw = None  # Lazy load!
        
    def _ensure_started(self):
        if not self._pw:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._page = self._browser.new_page()
    
    def navigate(self, url):
        self._ensure_started()
        self._page.goto(url)
        return self._page.content()
    
    def screenshot(self):
        return self._page.screenshot(type="png")
    
    def click(self, selector):
        self._page.click(selector)
    
    def type_text(self, selector, text):
        self._page.fill(selector, text)
    
    def get_text(self):
        return self._page.inner_text("body")
```

### 3.11 Compact Mode (built into agent.py)

When conversation exceeds token limit:

```python
def compact_conversation(messages, model, max_tokens=4000):
    summary_prompt = "Summarize this conversation concisely, preserving key decisions and context:"
    summary = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": summary_prompt + str(messages)}],
        max_tokens=max_tokens
    )
    return [{"role": "system", "content": f"Previous conversation summary:\n{summary}"}]
```

### 3.12 Google Search (inside tools.py)

```python
from googlesearch import search as gsearch

def search_google(query, num_results=5):
    results = list(gsearch(query, num_results=num_results))
    return "\n".join(results)
```

### 3.13 File Attach

```python
def attach_file(path):
    """Read file and add to conversation as user message with file content"""
    content = Path(path).read_text()
    return {"role": "user", "content": f"File: {path}\n```\n{content}\n```"}
```

---

## 4. Development Steps (Ordered)

### Phase 1: Core (Day 1-2) — Get it talking
1. **Set up project** — `pyproject.toml`, dependencies, virtual env
2. **config.py** — YAML config loader, API key management
3. **providers.py** — LiteLLM wrapper with streaming
4. **agent.py** — Basic agent loop (no tools yet), just chat
5. **amas.py** — CLI entry point with `click`
6. **ui.py** — Basic Rich console output + markdown rendering
7. ✅ **Milestone:** Can chat with any LLM model via CLI

### Phase 2: Tools (Day 3-4) — Make it useful
8. **tools.py** — Define tool schemas (JSON)
9. **Implement file tools** — read, write, create, edit, delete
10. **Implement shell tool** — subprocess execution
11. **Implement search_files** — grep wrapper
12. **Agent loop update** — Handle tool calls + results
13. **Accept/Decline UI** — Diff display + confirmation
14. ✅ **Milestone:** Can read/write files, run commands

### Phase 3: Intelligence (Day 5-6) — Make it smart
15. **init command** — Project scanning with tree-sitter
16. **Skills loader** — Load .amas/skills/*.md
17. **Rules loader** — Load .amas/rules.md
18. **System prompt builder** — Combine base + rules + skills + project context
19. **Compact mode** — Auto-summarize long conversations
20. ✅ **Milestone:** Context-aware coding agent

### Phase 4: Safety Net (Day 7) — Make it safe
21. **checkpoint.py** — Git-based save/restore
22. **Undo/redo commands** — Rollback changes
23. **History** — JSONL append-only log
24. **Action summary** — Show what was done after each turn
25. ✅ **Milestone:** Can undo any change, full history

### Phase 5: Extras (Day 8-9) — Make it powerful
26. **browser.py** — Playwright lazy-loaded browser control
27. **Browser tools** — navigate, click, type, screenshot, get_text
28. **Google search tool** — googlesearch-python integration
29. **URL fetch tool** — httpx web page fetching
30. **File attach command** — Inject file content into conversation
31. ✅ **Milestone:** Full-featured agent with web access

### Phase 6: Polish (Day 10) — Make it beautiful
32. **Streaming UI** — Live token display during generation
33. **Tool call panels** — Collapsible rich panels for tool usage
34. **Project tree display** — Rich tree view
35. **Help command** — Show all available commands
36. **Error handling** — Graceful failures everywhere
37. **Config wizard** — First-run setup for API keys
38. ✅ **Milestone:** Production-ready CLI tool

---

## 5. CLI Commands

```bash
amas                    # Start interactive session
amas init               # Scan project, create .amas/
amas config             # Setup wizard (model, keys)
amas "fix the bug"      # One-shot prompt
amas --model gemini     # Override model
amas history            # Show past sessions
amas undo               # Rollback last change
amas undo 3             # Rollback 3 changes
amas checkpoint list    # Show all checkpoints
amas checkpoint restore abc123  # Restore specific
amas compact            # Summarize and compress conversation
amas attach file.py     # Add file to context
amas skills list        # Show loaded skills
```

### In-Session Slash Commands

```
/help                   # Show commands
/init                   # Re-scan project
/model gemini-flash     # Switch model mid-session  
/undo                   # Rollback last change
/redo                   # Redo last undo
/checkpoint save "msg"  # Named checkpoint
/checkpoint list        # Show checkpoints
/compact                # Compress conversation
/attach file.py         # Add file to context
/history                # Show session history
/clear                  # Clear conversation
/cost                   # Show token usage + cost estimate
/browser open url       # Open browser
/search query           # Google search
/rules                  # Show current rules
/skills                 # Show loaded skills
/accept-all             # Auto-accept mode (no confirmations)
/quit                   # Exit
```

---

## 6. System Prompt Strategy

```markdown
You are Amas Code, an expert coding assistant operating in the user's terminal.

## Your Tools
{tool_descriptions}

## Project Context
{init_output — file tree + function map}

## Project Rules  
{.amas/rules.md content}

## Relevant Skills
{matched skill content}

## Guidelines
- Always use tools to read files before editing (don't assume content)
- Use edit_file for small changes, write_file for full rewrites
- Run tests after making changes when test suite exists
- Explain what you're doing before each tool call
- Create checkpoints before risky operations
- If unsure, ask the user
```

---

## 7. Config File (.amas/config.yaml)

```yaml
# Model Configuration
model: gemini/gemini-2.5-flash    # Default model
fallback_model: ollama/llama3     # Fallback if primary fails

# API Keys (or use env vars)
api_keys:
  anthropic: sk-ant-...
  google: AIza...
  openai: sk-...
  zhipuai: ...

# Behavior
auto_accept: false          # true = skip confirmations
max_context_tokens: 32000   # Trigger compact above this
checkpoint_on_edit: true    # Auto-checkpoint every edit
stream: true                # Stream responses

# Ignore patterns (added to .gitignore-style)
ignore:
  - node_modules
  - __pycache__
  - .git
  - "*.pyc"
  - dist
  - build
```

---

## 8. Token/Cost Optimization (Raspberry Pi Strategy)

1. **Use Gemini Flash as default** — Free tier, fast, good at coding
2. **Compact aggressively** — Summarize every 10 turns
3. **Lazy init** — Only scan files when asked or on first tool use
4. **Stream everything** — Don't buffer full responses in RAM
5. **JSONL history** — Append-only, never load full history into RAM
6. **Lazy imports** — `playwright`, `tree-sitter` loaded only when needed
7. **No daemon** — Single process, exits when done

---

## 9. Dependencies (pyproject.toml)

```toml
[project]
name = "amas-code"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "litellm>=1.40",
    "rich>=13.0",
    "prompt-toolkit>=3.0",
    "click>=8.0",
    "pyyaml>=6.0",
    "gitpython>=3.1",
    "googlesearch-python>=1.2",
    "httpx>=0.27",
]

[project.optional-dependencies]
browser = ["playwright>=1.40"]
parsing = ["tree-sitter>=0.21", "tree-sitter-languages>=1.10"]
all = ["amas-code[browser,parsing]"]

[project.scripts]
amas = "amas_code.amas:main"
```

> **Note:** `browser` and `parsing` are optional to keep base install tiny for Raspberry Pi. Install with `pip install amas-code[all]` for everything.

---

## 10. Testing Strategy

- **No test framework needed initially** — Just manual testing
- Later: `pytest` with mock LLM responses
- Test each tool function independently
- Test agent loop with fake tool calls
- Integration test: `amas "create a hello world python file"` → verify file exists

---

## 11. Future: ClawBot / OpenClaw Integration

Amas Code is designed as the **execution engine** for ClawBot/OpenClaw:

```
ClawBot (Orchestrator)
  ├── Amas Code (Coding Agent)     ← this project
  ├── Research Agent (Web/RAG)
  ├── Design Agent (UI/UX)
  └── Deploy Agent (CI/CD)
```

**Integration points:**
- Amas Code accepts tasks via stdin/CLI args
- Returns structured results (JSON) via stdout
- Can be imported as Python module: `from amas_code import Agent`
- Stateless between invocations (state in .amas/ directory)
- Agent-to-agent communication via tool calls

---

## 12. Line Count Budget

| File | Target Lines | Responsibility |
|------|-------------|----------------|
| `amas.py` | 40 | CLI entry, arg parsing |
| `agent.py` | 120 | Agent loop, message management, compact |
| `tools.py` | 250 | All tool implementations + schemas |
| `ui.py` | 120 | Rich console, diffs, panels, prompts |
| `providers.py` | 60 | LiteLLM wrapper, streaming, model switching |
| `checkpoint.py` | 40 | Git operations |
| `browser.py` | 60 | Playwright wrapper |
| `skills.py` | 30 | Skills + rules loading |
| `config.py` | 40 | YAML config management |
| **TOTAL** | **~760** | **Complete coding agent** |

> For comparison, Claude Code is estimated at 10,000+ lines. **Amas Code: 13x less code.**