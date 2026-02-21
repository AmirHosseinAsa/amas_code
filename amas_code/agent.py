"""Agent loop — the heart of Amas Code."""
import json
import re
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML

from amas_code import checkpoint, config as config_mod, providers, skills, tools, ui
from amas_code.history import (
    ChatSession, list_sessions, show_chat_list, show_chat_detail,
    show_chat_checkpoints, delete_session, search_sessions,
)

BASE_SYSTEM_PROMPT = """You are Amas Code, an elite AI coding assistant and principal software engineer running in the user's terminal. Your singular goal is to deliver high-quality, fully functional, maintainable, and architecturally sound solutions. You execute tasks autonomously and thoroughly.

# Core Mandates

## Engineering Standards & Output Quality
- **Technical Integrity & Completeness:** You are responsible for the entire lifecycle: architecture, implementation, and validation. NEVER leave "TODO" or placeholder code (e.g., `// Add logic here`). Always implement the full, robust logic required to make the feature work completely.
- **Idiomatic Code:** Adhere strictly to the best practices and conventions of the language/framework you are using. Consolidate logic into clean abstractions.
- **Visual & UX Excellence:** When building applications or UI components, ensure they feel modern, polished, and "alive." Use consistent spacing, interactive feedback (hover states, transitions), platform-appropriate design, and robust error handling. Do not deliver ugly or bare-bones UIs unless explicitly requested.

## Development Lifecycle
Operate using a rigorous **Research -> Strategy -> Execution -> Validation** loop.
1. **Research:** Systematically understand the requirements. If modifying existing code, map the codebase using tools and read files thoroughly before acting.
2. **Strategy:** Formulate a grounded plan. Present a concise summary of your strategy before writing code.
3. **Execution:** Apply targeted, surgical changes or write comprehensive new files. Use tools effectively (e.g., `replace_lines` for efficiency, `write_file` for large changes).
4. **Validation:** Validation is the only path to finality. Always verify your changes through tests, browser inspection (for web apps), or manual execution checks before declaring success. Fix any console errors or bugs immediately.

## Application Development (Zero-to-One)
When creating new applications (e.g., games, web apps, tools):
1. **Plan & Scaffold:** Choose the appropriate stack and structure.
2. **Implement Fully:** Write the complete code autonomously. Do not expect the user to fill in the gaps. If building a single-file app (like an index.html game), structure your HTML, CSS, and JS cleanly within the file.
3. **Visual Assets:** Utilize native primitives (e.g., CSS shapes, Canvas API, procedural generation) to ensure a complete, coherent experience without relying on external local assets that don't exist.
4. **Self-Correction:** Run the code/app (e.g., using browser tools or shell execution), check for errors, and self-correct until it is flawless.

## Creative & Design Tasks
- **Ultra Think for Design:** When the user requests a creative task (e.g., make a web page, design a website, or build a creative UI), take time to "ultra think" about creating the most beautiful, modern, and smoothest design possible.
- **Do Not Be Lazy:** Implement fully realized, stunning aesthetics with rich CSS, animations, and proper spacing.
- **Skill Usage:** Proactively rely on or create specific skills (e.g., a "UI/UX Designer" skill, "Python Expert" skill) to guide your implementation. Read and follow these related skills rigorously.

# Tool Rules

## File Operations
- **MANDATORY:** ALWAYS read a file before editing it.
- **Prefer edit_file or replace_lines** for targeted changes.
- **Do NOT be lazy:** When using write_file, provide the FULL, complete file content.
- If a task is critically ambiguous, use ask_user. Otherwise, use your best engineering judgment to proceed autonomously.

# Browser Control & Web Interaction
The browser is a **real visible Chromium window** that stays open during the session.
You have full control: navigate, click, type, press keys, scroll, run JavaScript, wait for elements, manage tabs.

## Mandatory Browser Rules
1. **ALWAYS use browser_wait_idle after sending a message in a chatbot.** NEVER use browser_wait or a manual sleep instead. browser_wait_idle polls the page until content stabilizes — this is the ONLY reliable way to know when an AI has finished responding.
2. **ALWAYS check browser_url after pressing Enter or clicking** if you suspect the page may have changed.
3. **NEVER give up after a single failure.** If a selector fails, try at least 3 different approaches (inspect `body` text, check URL, try alternative selectors, or use `browser_eval` to inspect the DOM) before reporting failure.
4. **ALWAYS read the response** after browser_wait_idle returns.
5. **NEVER assume login is required** just because you see "Sign in" or "Log in" text. If interactive elements are found, USE THEM.
6. **Local File Preview:** To open a local HTML file, use browser_navigate with `file://./file.html` (auto-resolved to absolute path). Do NOT start a Python HTTP server just to view a local file.
7. **Checking for JS errors — MANDATORY:** After opening any local HTML/JS file, ALWAYS call browser_get_console_errors. Fix EVERY error before declaring success. Uncaught errors mean the app is broken.

## Chatbot Interaction Pattern (Grok, ChatGPT, etc)
1. browser_navigate to the chat URL.
2. If navigate reports "Interactive elements found" -> Proceed to type. IGNORE any "Sign in" buttons.
3. browser_type selector='textarea' text='your message' (auto-falls back to contenteditable, ProseMirror, input).
4. browser_press key="Enter" to send the message.
5. browser_url — check if URL changed.
6. **browser_wait_idle** — CRITICAL! Wait for the AI response to finish. Do NOT skip this!
7. browser_get_text selector='body' — read the full page including the AI's response.
8. Parse the response and tell the user what the AI said.

# Tool Rules

## Web & Search
- Use web_search once per topic. If results are found, use them. Do not retry with rephrased queries.
- Use fetch_url for lightweight pages, browser_navigate for JS-heavy pages.

## Self-Improvement
- **save_lesson:** If you solve a tricky problem or learn a project quirk, call save_lesson to store the solution for future turns."""


# Slash commands with descriptions
COMMANDS = {
    "/help": "Show available commands",
    "/yolo": "Toggle auto-accept mode ⚡",
    "/init": "Scan project structure + extract symbols",
    "/model": "Interactive model picker 🤖",
    "/key": "Set API key — /key <provider> <key>",
    "/config": "Show current configuration",
    "/undo": "Undo last file change (per-chat or git)",
    "/rewind": "Interactive rewind to previous state ⏪",
    "/checkpoint": "Save a manual checkpoint",
    "/history": "Show checkpoint history",
    "/resume": "Resume a chat — /resume (interactive) | /resume <id> | /resume search <q> | /resume delete <id>",
    "/export": "Export current chat — /export [conv|full]",
    "/compact": "Summarize conversation to save context",
    "/rules": "Show loaded project rules",
    "/skills": "List loaded skills",
    "/lessons": "List learned lessons",
    "/clear": "Clear conversation history",
    "/cost": "Show context size + token estimate",
    "/attach": "Inject a file into the conversation — /attach <path>",
    "/quit": "Exit Amas Code",
}

# Model sub-completions
_MODEL_COMPLETIONS = {f"/model {m}": "Switch to this model" for m in config_mod.KNOWN_MODELS}

MAX_TOOL_ITERATIONS = 25  # Soft warning threshold


# ── File cache for @ completions ──────────────────────────────────────────────
_FILE_CACHE: list[tuple[str, str]] = []
_FILE_CACHE_TS: float = 0.0
_FILE_CACHE_TTL = 5.0  # Refresh every 5 seconds


class InputCompleter(Completer):
    """Handles both /command and @file completions in the prompt."""

    def __init__(self, config: dict):
        self._ignore = set(config.get("ignore", [
            "node_modules", "__pycache__", ".git", "*.pyc", "dist", "build", ".venv", ".amas",
        ]))

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # @ file reference — find the last @ before cursor (can be mid-line)
        at_idx = text.rfind("@")
        if at_idx >= 0:
            partial = text[at_idx + 1:]
            if " " not in partial:  # Only complete until next space
                for relpath, size in self._file_completions(partial):
                    yield Completion(
                        relpath,
                        start_position=-len(partial),
                        display=f"@{relpath}",
                        display_meta=size,
                    )
                return

        # /command completions
        stripped = text.lstrip()
        if not stripped.startswith("/"):
            return

        if stripped.startswith("/model "):
            sub = stripped[len("/model "):]
            for cmd, desc in _MODEL_COMPLETIONS.items():
                model_name = cmd[len("/model "):]
                if model_name.lower().startswith(sub.lower()):
                    yield Completion(model_name, start_position=-len(sub), display=model_name, display_meta=desc)
            return

        for cmd, desc in COMMANDS.items():
            if cmd.startswith(stripped.lower()):
                yield Completion(cmd, start_position=-len(stripped), display=cmd, display_meta=desc)

    def _file_completions(self, partial: str) -> list[tuple[str, str]]:
        """Return (relpath, size) pairs matching the partial path."""
        global _FILE_CACHE, _FILE_CACHE_TS
        if time.time() - _FILE_CACHE_TS > _FILE_CACHE_TTL:
            _FILE_CACHE = _scan_project_files(Path("."), self._ignore)
            _FILE_CACHE_TS = time.time()
        partial_lower = partial.lower()
        return [(p, s) for p, s in _FILE_CACHE if partial_lower in p.lower()]


class Agent:
    """Main agent loop — input → LLM → tools → display → repeat."""

    def __init__(self, cfg: dict | None = None):
        self.config = cfg or config_mod.load()
        self.messages: list[dict] = []
        self.actions: list[dict] = []
        self.project_context: str = ""  # From /init
        self._rules: str = ""
        self._skills: dict[str, str] = {}
        self._lessons: dict[str, str] = {}
        self._apply_api_key()
        self._load_intelligence()
        self._rebuild_system_prompt()
        self.session: PromptSession | None = None  # Lazy — created on first interactive use
        tools.init(self.config)
        # Chat history — every session gets its own ChatSession
        self.chat_session = ChatSession()
        self.chat_session.model = self.config.get("model", "unknown")

    def _apply_api_key(self) -> None:
        """Resolve and apply API key to config for the current model."""
        key = config_mod.resolve_api_key(self.config)
        if key:
            self.config["api_key"] = key

    def _load_intelligence(self) -> None:
        """Load rules, skills, and lessons from .amas/ directory."""
        self._rules = skills.load_rules()
        self._skills = skills.load_skills()
        self._lessons = skills.load_lessons()
        if self._rules:
            ui.success(f"Loaded project rules ({len(self._rules)} chars)")
        if self._skills:
            ui.success(f"Loaded {len(self._skills)} skill(s): {', '.join(self._skills.keys())}")
        if self._lessons:
            ui.success(f"Loaded {len(self._lessons)} learned lesson(s)")

    def _rebuild_system_prompt(self, extra_context: str = "") -> None:
        """Build system prompt from base + project context + rules + skills."""
        import datetime
        parts = [BASE_SYSTEM_PROMPT]

        # Current state
        model = self.config.get("model", "unknown")
        date_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
        parts.append(f"\n## Current Session\n- Date: {date_str}\n- Model: {model}\n- Auto-accept: {self.config.get('auto_accept', False)}")

        if self.project_context:
            parts.append(f"\n## Project Context\n{self.project_context}")

        if self._rules:
            parts.append(f"\n## Project Rules\n{self._rules}")

        if self._skills:
            # Include all skills (they're explicitly loaded by the user)
            skill_text = "\n\n".join(f"### {name}\n{content}" for name, content in self._skills.items())
            parts.append(f"\n## Active Skills\n{skill_text}")

        if self._lessons:
            lesson_text = "\n\n".join(f"### Lesson Learned: {name}\n{content}" for name, content in self._lessons.items())
            parts.append(f"\n## Lessons from Past Turns\n{lesson_text}")

        if extra_context:
            parts.append(f"\n## Additional Context\n{extra_context}")

        system_prompt = "\n".join(parts)

        # Trim if too long (~2000 tokens ≈ 8000 chars)
        if len(system_prompt) > 8000:
            system_prompt = system_prompt[:8000] + "\n\n[system prompt trimmed for context]"

        # Update or set system message
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": system_prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": system_prompt})

    def _make_session(self) -> PromptSession:
        """Create prompt session with history and styled autocomplete dropdown."""
        history_dir = Path(".amas")
        history_dir.mkdir(exist_ok=True)
        return PromptSession(
            history=FileHistory(str(history_dir / "input_history")),
            completer=InputCompleter(self.config),
            complete_while_typing=True,
        )

    def _get_prompt(self) -> HTML:
        """Build styled prompt with optional YOLO indicator."""
        if self.config.get("auto_accept"):
            return HTML('\n<style fg="#e0af68">⚡</style> <style fg="#7aa2f7" bold="true">❯</style> ')
        return HTML('\n<style fg="#7aa2f7" bold="true">❯</style> ')

    def get_input(self) -> str | None:
        """Get user input with autocomplete. Returns None on empty input, raises SystemExit on EOF."""
        if self.session is None:
            self.session = self._make_session()
        try:
            text = self.session.prompt(self._get_prompt()).strip()
            return text if text else None
        except EOFError:
            raise SystemExit(0)  # Ctrl+D → clean exit instead of infinite loop
        except KeyboardInterrupt:
            return None

    def handle_command(self, command: str) -> bool:
        """Handle slash commands. Returns True if should quit."""
        parts = command.split()
        raw_cmd = parts[0].lower()
        args = parts[1:]

        # Auto-resolve partial commands (e.g. /mode -> /model)
        matches = [c for c in COMMANDS.keys() if c.startswith(raw_cmd)]
        if not matches:
            ui.warning(f"Unknown command: [cyan]{raw_cmd}[/] — type [bold]/help[/]")
            return False
        
        # If multiple matches, prefer exact match, then shortest
        if raw_cmd in matches:
            cmd = raw_cmd
        else:
            cmd = sorted(matches, key=len)[0]
            if len(matches) > 1:
                ui.dim(f"  Resolving [cyan]{raw_cmd}[/] to [bold]{cmd}[/]")

        match cmd:
            case "/quit" | "/exit":
                from amas_code import web
                web.close_browser()
                self._save_chat_session()
                ui.info("Goodbye! 👋")
                return True
            case "/clear":
                self._save_chat_session()
                self.messages = []
                self._rebuild_system_prompt()
                self.chat_session = ChatSession()
                self.chat_session.model = self.config.get("model", "unknown")
                # Clear terminal and re-show startup
                import os
                os.system("clear" if os.name != "nt" else "cls")
                ui.show_welcome()
                model = self.config["model"]
                provider = model.split("/")[0] if "/" in model else "auto"
                has_key = bool(config_mod.resolve_api_key(self.config))
                ui.show_model_info(model, provider, has_key)
            case "/init":
                self._handle_init()
            case "/compact":
                self._handle_compact()
            case "/model":
                self._handle_model_command(args)
            case "/key":
                self._handle_key_command(args)
            case "/config":
                self._show_config()
            case "/yolo":
                current = self.config.get("auto_accept", False)
                self.config["auto_accept"] = not current
                tools.init(self.config)
                if not current:
                    ui.console.print("  [bold #e0af68]⚡ YOLO MODE ON[/] [dim]— all actions auto-accepted[/]")
                else:
                    ui.console.print("  [bold #73daca]🛡  YOLO MODE OFF[/] [dim]— confirmations enabled[/]")
            case "/rules":
                self._show_rules()
            case "/skills":
                self._show_skills()
            case "/lessons":
                self._show_lessons()
            case "/undo":
                self._handle_undo()
            case "/rewind":
                self._handle_rewind()
            case "/checkpoint":
                self._handle_checkpoint(args)
            case "/history":
                self._show_history()
            case "/help":
                ui.show_help(COMMANDS)
            case "/cost":
                self._show_cost()
            case "/attach":
                self._handle_attach(args)
            case "/resume":
                self._handle_resume(args)
            case "/export":
                self._handle_export(args)
            case _:
                ui.warning(f"Unknown command: [cyan]{cmd}[/] — type [bold]/help[/]")
        return False

    def _handle_init(self) -> None:
        """Scan project and inject context into system prompt."""
        self.project_context = skills.init_project(".", self.config)
        self._rebuild_system_prompt()
        ui.success("Project context injected into system prompt.")

    def _handle_compact(self) -> None:
        """Summarize conversation to reduce context size."""
        # Count non-system messages
        convo_msgs = [m for m in self.messages if m.get("role") != "system"]
        if len(convo_msgs) < 4:
            ui.warning("Conversation too short to compact.")
            return

        ui.info(f"Compacting {len(convo_msgs)} messages...")

        # Build summary request
        summary_prompt = (
            "Summarize this conversation concisely, preserving:\n"
            "- Key decisions made\n"
            "- Files created, edited, or deleted\n"
            "- Important context and user preferences\n"
            "- Current state of the task\n\n"
            "Conversation:\n"
        )
        for msg in convo_msgs:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if role == "tool":
                content = content[:200] + "..." if len(content) > 200 else content
            summary_prompt += f"\n[{role}]: {content[:500]}"

        # Call LLM to summarize
        summary_response = providers.complete(
            messages=[
                {"role": "system", "content": "You are a concise summarizer. Provide a clear summary."},
                {"role": "user", "content": summary_prompt},
            ],
            tools=None,
            config=self.config,
        )

        summary = summary_response.get("content", "")
        if not summary:
            ui.error("Failed to generate summary.")
            return

        # Replace conversation with summary
        self.messages = []
        self._rebuild_system_prompt(extra_context=f"Previous conversation summary:\n{summary}")
        ui.success(f"Compacted {len(convo_msgs)} messages into summary.")
        ui.console.print(f"\n[dim]{summary[:300]}{'...' if len(summary) > 300 else ''}[/]\n")

    def _handle_model_command(self, args: list[str]) -> None:
        """Handle /model and /models commands."""
        # Default to interactive picker if no arguments or /model list
        if not args or args[0] == "list":
            current = self.config["model"]
            items = []
            for m in config_mod.KNOWN_MODELS:
                # Group by provider for "searchable by type"
                provider = m.split("/")[0] if "/" in m else config_mod._guess_provider(m)
                marker = " ◀ current" if m == current else ""
                # Use a label that includes the type (provider) for easy searching
                label = f"[{provider}] {m}{marker}"
                items.append({"label": label, "model": m})

            selected = ui.interactive_picker(items, title="🤖 Switch Model")
            if selected:
                import os
                os.system("clear" if os.name != "nt" else "cls")
                
                self.config["model"] = selected["model"]
                config_mod.save(self.config)
                self._apply_api_key()
                
                # Refresh UI
                ui.show_welcome()
                model = self.config["model"]
                provider = model.split("/")[0] if "/" in model else "auto"
                has_key = bool(config_mod.resolve_api_key(self.config))
                ui.show_model_info(model, provider, has_key)
                
                ui.success(f"Model switched to: [cyan]{selected['model']}[/]")
            return

        if args[0] == "load":
            self.config = config_mod.load()
            self._apply_api_key()
            ui.success(f"Model reloaded from config: [cyan]{self.config['model']}[/]")
            return

        # Handle /model <name> direct switch
        self.config["model"] = args[0]
        config_mod.save(self.config)
        self._apply_api_key()
        ui.success(f"Model switched to: [cyan]{args[0]}[/] (saved to config)")

    def _handle_key_command(self, args: list[str]) -> None:
        """Handle /key command."""
        if len(args) >= 2:
            provider, key = args[0].lower(), args[1]
            config_mod.set_api_key(provider, key)
            self._apply_api_key()
            ui.show_config_saved(f"api_keys.{provider}", f"{key[:8]}...{'*' * 8}")
            return
        if len(args) == 1:
            provider = args[0].lower()
            key = ui.prompt_input(f"Enter API key for {provider}", password=True)
            if key:
                config_mod.set_api_key(provider, key)
                self._apply_api_key()
                ui.show_config_saved(f"api_keys.{provider}", f"{key[:8]}...{'*' * 8}")
            return
        ui.info("Usage: [cyan]/key <provider> <key>[/] or [cyan]/key <provider>[/]")

    def _show_config(self) -> None:
        """Display current config."""
        model = self.config["model"]
        provider = model.split("/")[0] if "/" in model else "auto"
        has_key = bool(config_mod.resolve_api_key(self.config))
        ui.show_model_info(model, provider, has_key)
        auto = "[green]ON[/]" if self.config.get("auto_accept") else "[red]OFF[/]"
        ui.info(f"Auto-accept: {auto}")
        ui.info(f"Streaming: [cyan]{self.config.get('stream', True)}[/]")
        ui.info(f"Project context: [cyan]{'loaded' if self.project_context else 'not loaded (/init)'}[/]")
        ui.info(f"Rules: [cyan]{'loaded' if self._rules else 'none'}[/]")
        ui.info(f"Skills: [cyan]{len(self._skills)}[/]")

    def _show_rules(self) -> None:
        """Display loaded rules."""
        if self._rules:
            ui.console.print(f"\n[bold]📋 Project Rules[/]\n{self._rules}\n")
        else:
            ui.info("No rules loaded. Create [cyan].amas/rules.md[/] to add project rules.")

    def _show_skills(self) -> None:
        """Display loaded skills."""
        if self._skills:
            ui.info(f"[bold]🧠 Loaded Skills ({len(self._skills)}):[/]")
            for name, content in self._skills.items():
                ui.console.print(f"  [cyan]{name}[/] — {len(content)} chars")
        else:
            ui.info("No skills loaded. Add markdown files to [cyan].amas/skills/[/]")

    def _show_lessons(self) -> None:
        """Display learned lessons."""
        if self._lessons:
            ui.info(f"[bold]🎓 Learned Lessons ({len(self._lessons)}):[/]")
            for name, content in self._lessons.items():
                ui.console.print(f"  [cyan]{name}[/]")
        else:
            ui.info("No lessons learned yet. The agent will save lessons using [cyan]save_lesson[/].")

    def _show_cost(self) -> None:
        """Show context size information."""
        msg_count = len(self.messages)
        tool_msgs = sum(1 for m in self.messages if m.get("role") == "tool")
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        est_tokens = total_chars // 4  # Rough estimate
        ui.info(f"Messages: [cyan]{msg_count}[/] (tool results: [cyan]{tool_msgs}[/])")
        ui.info(f"Context size: ~[cyan]{est_tokens:,}[/] tokens ({total_chars:,} chars)")
        threshold = self.config.get("max_context_tokens", 32000)
        if est_tokens > threshold * 0.8:
            ui.warning(f"Context is [bold]{est_tokens/threshold*100:.0f}%[/] of limit. Consider [cyan]/compact[/].")

    def _handle_attach(self, args: list[str]) -> None:
        """Inject a file's contents into the conversation as a user message."""
        if not args:
            ui.info("Usage: [cyan]/attach <path>[/]")
            return
        path = " ".join(args)
        p = Path(path)
        if not p.exists():
            ui.error(f"File not found: {path}")
            return
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            ui.error(f"Cannot read binary file: {path}")
            return
        self.messages.append({
            "role": "user",
            "content": f"File attached: `{path}`\n```\n{content}\n```",
        })
        ui.success(f"Attached [cyan]{path}[/] ({len(content):,} chars) to conversation.")

    def _expand_at_refs(self, text: str) -> str:
        """Expand @filepath references: prepend file contents and replace @path with `path`."""
        refs = list(re.finditer(r"@([^\s,;:)(!\?\"']+)", text))
        if not refs:
            return text
        attachments = []
        for m in refs:
            path = m.group(1)
            p = Path(path)
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8")
                    attachments.append(f"File `{path}`:\n```\n{content}\n```")
                    text = text.replace(m.group(0), f"`{path}`", 1)
                    ui.success(f"Attached [cyan]{path}[/] ({len(content):,} chars)")
                except UnicodeDecodeError:
                    ui.warning(f"Cannot read binary file: {path}")
                except Exception as e:
                    ui.warning(f"Could not read {path}: {e}")
            else:
                ui.warning(f"@{path}: file not found")
        if attachments:
            return "\n\n".join(attachments) + "\n\n" + text
        return text

    def _show_history(self) -> None:
        """Display checkpoint history — per-chat first, then global."""
        # Show per-chat checkpoints first
        if self.chat_session.checkpoints:
            show_chat_checkpoints(self.chat_session)
        else:
            ui.info("No checkpoints in current chat.")

        # Also show global git checkpoints
        from rich.table import Table
        history = checkpoint.list_checkpoints()
        if history:
            table = Table(title="📜 All Git Checkpoints", border_style="bright_blue")
            table.add_column("Hash", style="cyan", width=10)
            table.add_column("Time", style="dim")
            table.add_column("Message", style="bold")
            table.add_column("Files", justify="right")
            for cp in history:
                table.add_row(cp["hash"], cp["time"], cp["message"], str(cp["files"]))
            ui.console.print(table)

    def _handle_undo(self) -> None:
        """Undo — per-chat checkpoint first, fallback to global git."""
        target = self.chat_session.undo_to_checkpoint()
        if target:
            result = checkpoint.restore(target["hash"])
            self._save_chat_session()
            ui.success(f"Undone to: [cyan]{target['message']}[/] ({target['hash'][:8]})")
        else:
            result = checkpoint.undo()
            ui.success(result) if "Undone" in result else ui.warning(result)

    def _handle_rewind(self) -> None:
        """Interactive rewind to a previous state based on user prompts."""
        if not self.messages:
            ui.info("No messages in current chat.")
            return

        # 1. Group checkpoints by user prompt
        items = []
        user_indices = [i for i, m in enumerate(self.messages) if m["role"] == "user"]

        if not user_indices:
            ui.info("No user prompts found to rewind to.")
            return

        for idx, u_idx in enumerate(user_indices):
            msg = self.messages[u_idx]
            next_u_idx = user_indices[idx + 1] if idx + 1 < len(user_indices) else 999999
            
            # Find checkpoints for this prompt: message_index > u_idx AND message_index <= next_u_idx
            cps = [cp for cp in self.chat_session.checkpoints if u_idx < cp.get("message_index", 0) <= next_u_idx]
            
            # Summary of changes for this prompt
            total_added = 0
            total_removed = 0
            combined_diff = ""
            for cp in cps:
                try:
                    d = checkpoint.get_diff(cp["hash"])
                    combined_diff += d + "\n"
                    total_added += sum(1 for line in d.splitlines() if line.startswith("+") and not line.startswith("+++"))
                    total_removed += sum(1 for line in d.splitlines() if line.startswith("-") and not line.startswith("---"))
                except Exception:
                    pass
            
            diff_summary = f" [green]+{total_added}[/] [red]-{total_removed}[/]" if total_added or total_removed else ""
            
            # Find the state BEFORE this prompt (latest checkpoint with index <= u_idx)
            target_cp = None
            for cp in reversed(self.chat_session.checkpoints):
                if cp.get("message_index", 0) <= u_idx:
                    target_cp = cp
                    break
            
            label = f"❯ {msg['content'][:60].strip()}"
            if len(msg['content']) > 60: label += "..."
            
            items.append({
                "label": f"{label}{diff_summary}",
                "target_cp": target_cp,
                "diff": combined_diff,
                "message_index": u_idx,
            })

        # Reverse to show newest first
        items.reverse()

        selected = ui.interactive_picker(items, title="⏪ Select Rewind Point (User Prompts)")
        if not selected:
            return

        # Execute rewind
        target_hash = selected["target_cp"]["hash"] if selected["target_cp"] else None
        
        # If no target_cp, try to find the very first checkpoint's parent (beginning of time)
        if not target_hash and self.chat_session.checkpoints:
            try:
                from git import Repo
                repo = Repo(".", search_parent_directories=True)
                first_cp = self.chat_session.checkpoints[0]
                commit = repo.commit(first_cp["hash"])
                if commit.parents:
                    target_hash = commit.parents[0].hexsha
            except Exception:
                pass

        # Show combined changes that will be undone
        if target_hash:
            full_diff = checkpoint.get_diff_between(target_hash, "HEAD")
            if full_diff:
                ui.console.print(f"\n[bold]Changes that will be UNDONE (from this prompt onwards):[/]")
                from rich.syntax import Syntax
                ui.console.print(Syntax(full_diff, "diff", theme="monokai"))
            else:
                ui.info("No code changes recorded for this prompt or after.")
        else:
            ui.info("No code changes to undo (initial state).")

        # Mode selection
        modes = [
            {"label": "1. Rewind code ONLY (keeps chat history)", "mode": "code_only"},
            {"label": "2. Rewind chat and code (truncates history)", "mode": "chat_and_code"},
        ]
        mode_choice = ui.interactive_picker(modes, title="Select Rewind Mode")
        if not mode_choice:
            return

        # Execute restore
        if target_hash:
            res = checkpoint.restore(target_hash)
            ui.success(res)
        else:
            ui.warning("No code checkpoint found to restore to.")

        if mode_choice["mode"] == "chat_and_code":
            # Truncate chat messages
            target_idx = selected["message_index"]
            self.messages = self.messages[:target_idx]
            self.chat_session.messages = self.chat_session.messages[:target_idx]
            
            # Truncate checkpoints list
            new_cps = []
            if target_hash:
                for cp in self.chat_session.checkpoints:
                    new_cps.append(cp)
                    if cp["hash"] == target_hash:
                        break
                else:
                    # If target_hash not found in list, it's before the session started
                    new_cps = []
            self.chat_session.checkpoints = new_cps
            
            self._save_chat_session()
            ui.success("Rewound chat and code to before the selected prompt.")
        else:
            ui.success("Rewound code ONLY.")

    def _handle_checkpoint(self, args: list[str]) -> None:
        """Save a manual checkpoint and link it to the current chat."""
        msg = " ".join(args) if args else "manual checkpoint"
        if checkpoint.save(msg):
            ui.success(f"Checkpoint saved: [cyan]{msg}[/]")
            try:
                from git import Repo
                repo = Repo(".", search_parent_directories=True)
                git_hash = repo.head.commit.hexsha
                self.chat_session.add_checkpoint(git_hash, msg)
                self._save_chat_session()
            except Exception:
                pass
        else:
            ui.info("Nothing to checkpoint (no changes).")

    def _handle_resume(self, args: list[str]) -> None:
        """Handle /resume — interactive picker to browse/resume/delete."""
        # Handle /resume delete <id>
        if args and args[0] == "delete" and len(args) > 1:
            sid = args[1]
            if delete_session(sid):
                ui.success(f"Deleted chat [cyan]{sid}[/].")
            else:
                ui.warning(f"Chat [cyan]{sid}[/] not found.")
            return

        # Handle /resume search <q>
        if args and args[0] == "search" and len(args) > 1:
            query = " ".join(args[1:])
            sessions = search_sessions(query)
            if not sessions:
                ui.info(f"No chats matching '[cyan]{query}[/]'.")
                return
            title = f"💬 Chats matching '{query}'"
        # Handle /resume <id> directly
        elif args and not args[0] in ("search", "delete"):
            self._do_resume(args[0])
            return
        else:
            sessions = list_sessions()
            if not sessions:
                ui.info("No saved chats yet. Start chatting!")
                return
            title = "💬 Resume Chat"

        # Build picker for interactive selection
        items = []
        for s in sessions:
            t = (s["title"] or "(untitled)")[:50]
            msgs = s.get("messages", 0)
            updated = s.get("updated", "")
            items.append({"label": f"{t}  ({msgs} msgs · {updated})", "id": s["id"]})

        selected = ui.interactive_picker(items, title=title)
        if selected:
            self._do_resume(selected["id"])
        else:
            ui.dim("  Cancelled.")

    def _do_resume(self, sid: str) -> None:
        """Actually resume a chat session by ID."""
        try:
            # Save current session first
            self._save_chat_session()
            # Load the target session
            session = ChatSession.load(sid)
            self.chat_session = session
            # Rebuild messages from session history
            self.messages = []
            self._rebuild_system_prompt()
            for msg in session.get_messages("conversation_and_code"):
                self.messages.append(msg)
            # Clean up any orphaned tool messages
            self._sanitize_messages()

            # Clear terminal and show history
            import os
            os.system("clear" if os.name != "nt" else "cls")
            show_chat_detail(session)
            ui.success(f"Resumed chat: [cyan]{session.title or session.id}[/] ({len(session.messages)} msgs)")
        except FileNotFoundError:
            ui.warning(f"Chat [cyan]{sid}[/] not found.")

    def _sanitize_messages(self) -> None:
        """Remove orphaned tool messages that lack matching tool_calls.

        Gemini / Vertex API requires every role='tool' message to have a
        corresponding tool_call entry in a preceding assistant message.
        Orphaned tool results (e.g. from corrupted history) cause a hard crash.
        """
        # Collect all valid tool_call_ids from assistant messages
        valid_ids: set[str] = set()
        for msg in self.messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id:
                        valid_ids.add(tc_id)

        # Filter out tool messages whose tool_call_id isn't in valid_ids
        cleaned = []
        removed = 0
        for msg in self.messages:
            if msg.get("role") == "tool":
                tcid = msg.get("tool_call_id", "")
                if tcid not in valid_ids:
                    removed += 1
                    continue
            cleaned.append(msg)

        if removed:
            self.messages = cleaned
            ui.dim(f"  Cleaned {removed} orphaned tool message(s) from history.")

    def _handle_export(self, args: list[str]) -> None:
        """Handle /export [conv|full] — export current chat to markdown."""
        mode = "conversation_and_code" if args and args[0] == "full" else "conversation_only"
        messages = self.chat_session.get_messages(mode)
        if not messages:
            ui.info("Nothing to export — current chat is empty.")
            return
        lines = [f"# Chat: {self.chat_session.title or 'Untitled'}\n"]
        lines.append(f"Model: {self.chat_session.model}\n")
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"---\n\n**{role}:**\n\n{content}\n")
        export_path = Path(f".amas/exports/{self.chat_session.id}.md")
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("\n".join(lines))
        ui.success(f"Exported to [cyan]{export_path}[/]")

    def _save_chat_session(self) -> None:
        """Persist the current chat session to disk."""
        if self.chat_session.messages:
            self.chat_session.save()

    def chat_turn(self, user_input: str) -> None:
        """Process one user message through the LLM, executing tools as needed."""
        user_input = self._expand_at_refs(user_input)
        self.messages.append({"role": "user", "content": user_input})
        _append_history("user", user_input)
        self.chat_session.add_message("user", user_input)
        self.actions = []
        iterations = 0

        # Auto-compact if context is getting large
        self._check_auto_compact()

        # Sanitize before first API call to avoid orphaned tool messages
        self._sanitize_messages()

        while True:
            iterations += 1
            if iterations > 0 and iterations % MAX_TOOL_ITERATIONS == 0:
                ui.warning(f"[bold]{iterations} tool iterations[/] — the model may be stuck, but continuing...")

            ui.show_streaming_start()

            # Use StreamingDisplay for animated thinking + streaming with
            # real-time Markdown rendering (bold, tables, lists, code blocks)
            streaming = ui.StreamingDisplay()
            with streaming:
                response = providers.complete(
                    messages=self.messages,
                    tools=tools.TOOLS,
                    config=self.config,
                    on_chunk=streaming.on_chunk,
                )
            self.messages.append(response)
            if response.get("content"):
                _append_history("assistant", response["content"])
                self.chat_session.add_message(
                    "assistant", response["content"],
                    tool_calls=response.get("tool_calls"),
                )

            tool_calls = response.get("tool_calls")
            if not tool_calls:
                break

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                tool_id = tc.get("id", "")

                ui.show_tool_call(func_name, _parse_args_for_display(func_args))
                result = tools.execute(func_name, func_args)
                self.actions.append({"tool": func_name, "result": result[:100]})
                _show_tool_result(func_name, result)

                self.chat_session.add_message("tool", result, tool_call_id=tool_id)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result,
                })

                # Auto-checkpoint file operations
                if func_name in ("write_file", "edit_file", "create_file", "delete_file"):
                    if not result.startswith("Error") and "declined" not in result.lower():
                        try:
                            from git import Repo
                            repo = Repo(".", search_parent_directories=True)
                            git_hash = repo.head.commit.hexsha
                            self.chat_session.add_checkpoint(git_hash, f"{func_name}: {result[:60]}")
                        except Exception:
                            pass

        if self.actions:
            ui.show_summary(self.actions)

        # Auto-save chat session after each turn
        self._save_chat_session()

    def _check_auto_compact(self) -> None:
        """Warn if context is getting too large."""
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        est_tokens = total_chars // 4
        threshold = self.config.get("max_context_tokens", 32000)
        if est_tokens > threshold * 0.8:
            ui.warning(f"Context (~{est_tokens:,} tokens) is {est_tokens/threshold*100:.0f}% of limit. Use [cyan]/compact[/] to summarize.")

    def run(self) -> None:
        """Main agent loop."""
        ui.show_welcome()
        model = self.config["model"]
        has_key = bool(self.config.get("api_key"))
        provider = model.split("/")[0] if "/" in model else "auto"
        ui.show_model_info(model, provider, has_key)

        # Show hint about recent chats
        recent = list_sessions(limit=3)
        if recent:
            ui.dim(f"{len(recent)} recent chat(s) — /resume to browse, /resume <id> to continue")

        while True:
            user_input = self.get_input()
            if user_input is None:
                continue

            if user_input.startswith("/"):
                should_quit = self.handle_command(user_input)
                if should_quit:
                    break
                continue

            try:
                self.chat_turn(user_input)
            except KeyboardInterrupt:
                ui.warning("Interrupted. Type [bold]/quit[/] to exit.")
            except SystemExit:
                raise
            except Exception as e:
                ui.error(f"Error: {e}")

        # Save session on exit
        self._save_chat_session()


def _parse_args_for_display(args_json: str) -> dict:
    """Parse tool args JSON for display, truncating long values."""
    try:
        args = json.loads(args_json) if args_json else {}
        return {k: (str(v)[:100] + "..." if len(str(v)) > 100 else v) for k, v in args.items()}
    except (json.JSONDecodeError, AttributeError):
        return {"raw": args_json[:200] if args_json else ""}


def _show_tool_result(name: str, result: str) -> None:
    """Display concise tool result feedback."""
    if result.startswith("Error"):
        ui.error(result[:200])
    elif "declined" in result.lower():
        ui.warning(result)
    else:
        first_line = result.splitlines()[0] if result else ""
        ui.success(first_line[:150])


def _append_history(role: str, content: str) -> None:
    """Append a turn to .amas/history.jsonl (append-only log)."""
    try:
        p = Path(".amas/history.jsonl")
        p.parent.mkdir(exist_ok=True)
        with p.open("a") as f:
            json.dump({"ts": time.time(), "role": role, "content": content[:2000]}, f)
            f.write("\n")
    except Exception:
        pass  # Never crash the agent for logging


def _scan_project_files(root: Path, ignore: set, max_depth: int = 5) -> list[tuple[str, str]]:
    """Walk project files and return (relpath, human_size) pairs for @ completions."""
    result: list[tuple[str, str]] = []
    _walk_for_files(root, root, ignore, max_depth, 0, result)
    return result


def _walk_for_files(p: Path, root: Path, ignore: set, max_depth: int, depth: int, out: list) -> None:
    """Recursively collect file paths for the @ completer."""
    if depth > max_depth:
        return
    try:
        for entry in sorted(p.iterdir()):
            if entry.name in ignore or entry.name.startswith(".") or any(entry.match(ig) for ig in ignore):
                continue
            if entry.is_dir():
                _walk_for_files(entry, root, ignore, max_depth, depth + 1, out)
            elif entry.is_file():
                try:
                    rel = str(entry.relative_to(root))
                    sz = entry.stat().st_size
                    for unit in ("B", "KB", "MB", "GB"):
                        if sz < 1024:
                            size_str = f"{sz:.0f}{unit}" if unit == "B" else f"{sz:.1f}{unit}"
                            break
                        sz /= 1024
                    else:
                        size_str = f"{sz:.1f}TB"
                    out.append((rel, size_str))
                except (ValueError, OSError):
                    pass
    except PermissionError:
        pass
