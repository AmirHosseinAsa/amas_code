"""All tool definitions, schemas, and handlers."""
import json
import subprocess
from pathlib import Path

from amas_code import checkpoint, config as config_mod, ui

# ── Module state (set by agent before use) ───────────────────────────────────
_config: dict = {}
_project_root: str = "."


def init(config: dict, project_root: str = ".") -> None:
    """Initialize tools with config (called by agent on startup)."""
    global _config, _project_root
    _config = config
    _project_root = project_root


# ── Tool registry ────────────────────────────────────────────────────────────
TOOLS: list[dict] = []
HANDLERS: dict[str, callable] = {}


def _schema(name: str, desc: str, props: dict, required: list[str]) -> dict:
    """Helper to build a tool schema dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


# ── read_file ────────────────────────────────────────────────────────────────

def read_file(path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read file contents with line numbers, optionally restricted to a range."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"
        if not p.is_file():
            return f"Error: not a file: {path}"

        # Binary file detection
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Binary file, cannot display: {path}"

        lines = content.splitlines()
        total_lines = len(lines)
        
        start = max(1, start_line)
        end = min(total_lines, end_line) if end_line else total_lines
        
        if start > total_lines:
            return f"Error: start_line {start} is beyond end of file ({total_lines} lines)"
            
        requested_lines = lines[start-1:end]
        content_subset = "\n".join(requested_lines)

        # Truncate if still too large
        if len(content_subset) > 50_000:
            content_subset = content_subset[:50_000]
            return _numbered(content_subset, start) + f"\n\n[truncated — block is {len(content_subset):,} bytes]"

        return _numbered(content_subset, start)
    except Exception as e:
        return f"Error reading {path}: {e}"


def _numbered(content: str, start_line: int = 1) -> str:
    """Add line numbers to content starting from start_line."""
    lines = content.splitlines()
    max_line = start_line + len(lines) - 1
    width = len(str(max_line))
    return "\n".join(f"{i+start_line:>{width}} | {l}" for i, l in enumerate(lines))


TOOLS.append(_schema("read_file", "Read a file and return contents with line numbers. Use start_line/end_line for efficiency on large files.", {
    "path": {"type": "string", "description": "Path to the file to read"},
    "start_line": {"type": "integer", "description": "First line to read (default 1)"},
    "end_line": {"type": "integer", "description": "Last line to read (optional)"},
}, ["path"]))
HANDLERS["read_file"] = read_file


# ── write_file ───────────────────────────────────────────────────────────────

def write_file(path: str, content: str) -> str:
    """Write content to a file (full rewrite). Shows diff and asks for confirmation."""
    try:
        p = Path(path)
        old_content = p.read_text(encoding="utf-8") if p.exists() else ""

        ui.show_diff(old_content, content, path)

        if not _config.get("auto_accept", False) and not ui.confirm("Accept this write?"):
            return "Write declined by user."

        checkpoint.save(f"before write {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        checkpoint.save(f"write {path}")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


TOOLS.append(_schema("write_file", "Write content to a file (creates or overwrites). Use for full file rewrites.", {
    "path": {"type": "string", "description": "Path to write to"},
    "content": {"type": "string", "description": "Full file content to write"},
}, ["path", "content"]))
HANDLERS["write_file"] = write_file


# ── create_file ──────────────────────────────────────────────────────────────

def create_file(path: str, content: str = "") -> str:
    """Create a new file. Fails if file already exists."""
    try:
        p = Path(path)
        if p.exists():
            return f"Error: file already exists: {path}. Use write_file to overwrite."

        if content:
            ui.show_diff("", content, path)
            if not _config.get("auto_accept", False) and not ui.confirm("Create this file?"):
                return "File creation declined by user."

        checkpoint.save(f"before create {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        checkpoint.save(f"create {path}")
        return f"Created {path} ({len(content)} bytes)"
    except Exception as e:
        return f"Error creating {path}: {e}"


TOOLS.append(_schema("create_file", "Create a new file with content. Fails if file already exists.", {
    "path": {"type": "string", "description": "Path for the new file"},
    "content": {"type": "string", "description": "Content for the new file (empty string for empty file)"},
}, ["path", "content"]))
HANDLERS["create_file"] = create_file


# ── edit_file ────────────────────────────────────────────────────────────────

def edit_file(path: str, old_str: str, new_str: str, occurrence: int = 1) -> str:
    """Edit a file by replacing an exact string match. occurrence=0 replaces all, >0 replaces Nth match."""
    try:
        if not old_str:
            return "Error: old_str cannot be empty."
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"

        content = p.read_text(encoding="utf-8")
        count = content.count(old_str)
        
        if count == 0:
            snippet = _numbered(content)
            if len(snippet) > 4000:
                snippet = snippet[:4000] + "\n[truncated — file has more content]"
            return f"Error: string not found in {path}. Current file content:\n{snippet}"

        if occurrence == 0:
            # Replace all
            new_content = content.replace(old_str, new_str)
        else:
            if occurrence > count:
                return f"Error: string appears {count} times, but occurrence {occurrence} was requested."
            if count > 1 and occurrence == 1 and _config.get("require_unique_edit", True):
                 # Keep existing safe behavior by default if not specified otherwise
                 return f"Error: string appears {count} times. Be more specific or use 'occurrence' (1-{count}, or 0 for all)."
            
            # Replace Nth occurrence
            parts = content.split(old_str)
            # parts has count+1 elements. We want to join parts[0:occurrence] with old_str, 
            # then add new_str, then join the rest with old_str.
            prefix = old_str.join(parts[:occurrence])
            suffix = old_str.join(parts[occurrence:])
            new_content = prefix + new_str + suffix

        ui.show_diff(content, new_content, path)

        if not _config.get("auto_accept", False) and not ui.confirm("Accept this edit?"):
            return "Edit declined by user."

        checkpoint.save(f"before edit {path}")
        p.write_text(new_content, encoding="utf-8")
        checkpoint.save(f"edit {path}")
        return f"Edited {path} successfully ({'all' if occurrence == 0 else 'occurrence ' + str(occurrence)} replaced)."
    except Exception as e:
        return f"Error editing {path}: {e}"


TOOLS.append(_schema("edit_file", "Edit a file by replacing an exact string match. The old_str should usually be unique.", {
    "path": {"type": "string", "description": "Path to the file to edit"},
    "old_str": {"type": "string", "description": "Exact string to find"},
    "new_str": {"type": "string", "description": "Replacement string"},
    "occurrence": {"type": "integer", "description": "Which match to replace (1-based). Use 0 to replace all. Default 1."},
}, ["path", "old_str", "new_str"]))
HANDLERS["edit_file"] = edit_file


# ── delete_file ──────────────────────────────────────────────────────────────

def delete_file(path: str) -> str:
    """Delete a file after confirmation."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"

        if not _config.get("auto_accept", False) and not ui.confirm(f"Delete {path}?"):
            return "Deletion declined by user."

        checkpoint.save(f"before delete {path}")
        p.unlink()
        checkpoint.save(f"delete {path}")
        return f"Deleted {path}"
    except Exception as e:
        return f"Error deleting {path}: {e}"


TOOLS.append(_schema("delete_file", "Delete a file. Asks for confirmation first.", {
    "path": {"type": "string", "description": "Path to the file to delete"},
}, ["path"]))
HANDLERS["delete_file"] = delete_file


# ── shell_command ────────────────────────────────────────────────────────────

def shell_command(command: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout + stderr."""
    try:
        if not _config.get("auto_accept", False):
            if not ui.confirm("Run this command?"):
                return "Command declined by user."

        # Background commands (ends with & but not &&) must use Popen — subprocess.run
        # hangs because it waits for inherited file descriptors to close.
        cmd_stripped = command.strip()
        is_background = cmd_stripped.endswith("&") and not cmd_stripped.endswith("&&")
        if is_background:
            proc = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=_project_root, start_new_session=True,
            )
            return f"Started background process (PID {proc.pid}). Give it a moment to start before connecting."

        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=_project_root,
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}" if output else result.stderr

        if not output.strip():
            output = "Command executed successfully (no output)."

        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        # Truncate very long output
        if len(output) > 20_000:
            output = output[:20_000] + "\n\n[output truncated]"

        return output
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error running command: {e}"


TOOLS.append(_schema("shell_command", "Run a shell command and return output. Has a 30s timeout by default.", {
    "command": {"type": "string", "description": "Shell command to execute"},
    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
}, ["command"]))
HANDLERS["shell_command"] = shell_command


# ── set_model ────────────────────────────────────────────────────────────────

def set_model(model: str, persist: bool = True) -> str:
    """Switch the AI model for the current session, optionally saving to config."""
    try:
        if model not in config_mod.KNOWN_MODELS and "/" not in model:
            return f"Error: unknown model '{model}'. Use a known model or 'provider/name' format."

        _config["model"] = model
        if persist:
            config_mod.save(_config)

        # Update API key for the new model in the shared config
        key = config_mod.resolve_api_key(_config)
        if key:
            _config["api_key"] = key

        return f"Model switched to {model}" + (" and saved to config" if persist else "")
    except Exception as e:
        return f"Error setting model: {e}"


TOOLS.append(_schema("set_model", "Switch the AI model for the current session, optionally saving to config.", {
    "model": {"type": "string", "description": "Model name (e.g. gemini/gemini-2.5-flash)"},
    "persist": {"type": "boolean", "description": "Whether to save this as the default model in config (default: true)"},
}, ["model"]))
HANDLERS["set_model"] = set_model


# ── get_model ────────────────────────────────────────────────────────────────

def get_model() -> str:
    """Return the currently selected AI model."""
    return f"Current model: {_config.get('model', 'unknown')}"


TOOLS.append(_schema("get_model", "Return the currently selected AI model.", {}, []))
HANDLERS["get_model"] = get_model


# ── search_files ─────────────────────────────────────────────────────────────

def search_files(pattern: str, path: str = ".", include: str = "") -> str:
    """Search for a pattern in files using grep."""
    try:
        cmd = ["grep", "-rnI", "--color=never"]
        if include:
            cmd.extend(["--include", include])
        cmd.extend([pattern, path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=_project_root)
        output = result.stdout.strip()

        if not output:
            return f"No matches found for '{pattern}' in {path}"

        lines = output.splitlines()
        if len(lines) > 50:
            output = "\n".join(lines[:50]) + f"\n\n[{len(lines) - 50} more matches...]"

        return output
    except subprocess.TimeoutExpired:
        return "Error: search timed out"
    except Exception as e:
        return f"Error searching: {e}"


TOOLS.append(_schema("search_files", "Search for a text pattern in files using grep. Returns matching lines with file paths and line numbers.", {
    "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
    "path": {"type": "string", "description": "Directory or file to search in (default: current directory)"},
    "include": {"type": "string", "description": "File glob filter, e.g. '*.py' or '*.js'"},
}, ["pattern"]))
HANDLERS["search_files"] = search_files


# ── save_lesson ──────────────────────────────────────────────────────────────

def save_lesson(problem: str, solution: str) -> str:
    """Save a concise lesson learned from an error or challenge."""
    try:
        lessons_dir = Path(_project_root) / ".amas" / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)

        # Generate a short slug from the problem
        import re
        import time
        slug = re.sub(r'[^a-z0-9]+', '-', problem.lower()).strip('-')[:30]
        filename = f"{int(time.time())}_{slug}.md"
        p = lessons_dir / filename

        content = f"### Problem: {problem}\n\n**Solution:** {solution}"
        p.write_text(content, encoding="utf-8")

        ui.success(f"Lesson saved: [cyan]{problem[:50]}...[/]")
        return f"Lesson saved successfully as {filename}. I will remember this for future tasks."
    except Exception as e:
        return f"Error saving lesson: {e}"


TOOLS.append(_schema("save_lesson", "Save a concise lesson learned from an error or challenge to help you solve similar problems in the future.", {
    "problem": {"type": "string", "description": "Concise description of the error or challenge (e.g., 'Failed to load Three.js in browser')"},
    "solution": {"type": "string", "description": "Concise explanation of the working solution (e.g., 'Use file:// absolute paths and check console for CORS')"},
}, ["problem", "solution"]))
HANDLERS["save_lesson"] = save_lesson


# ── list_files ───────────────────────────────────────────────────────────────

def list_files(path: str = ".", max_depth: int = 3) -> str:
    """List files and directories in a tree-like format."""
    try:
        root = Path(_project_root) / path
        if not root.exists():
            return f"Error: path not found: {path}"

        ignore = set(_config.get("ignore", ["node_modules", "__pycache__", ".git", "*.pyc", "dist", "build", ".venv"]))
        lines = []
        _walk_tree(root, "", lines, ignore, max_depth, 0)

        if not lines:
            return f"Empty directory: {path}"

        return "\n".join(lines)
    except Exception as e:
        return f"Error listing {path}: {e}"


def _walk_tree(p: Path, prefix: str, lines: list, ignore: set, max_depth: int, depth: int) -> None:
    """Recursively build file tree lines."""
    if depth > max_depth:
        lines.append(f"{prefix}...")
        return

    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        return

    entries = [e for e in entries if e.name not in ignore and not any(e.match(ig) for ig in ignore)]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        if entry.is_dir():
            lines.append(f"{prefix}{connector}📁 {entry.name}/")
            ext = "    " if is_last else "│   "
            _walk_tree(entry, prefix + ext, lines, ignore, max_depth, depth + 1)
        else:
            size = entry.stat().st_size
            size_str = _human_size(size)
            lines.append(f"{prefix}{connector}{entry.name} ({size_str})")


def _human_size(size: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


TOOLS.append(_schema("list_files", "List files and directories in a tree format. Respects ignore patterns from config.", {
    "path": {"type": "string", "description": "Directory to list (default: current directory)"},
    "max_depth": {"type": "integer", "description": "Maximum depth to recurse (default: 3)"},
}, []))
HANDLERS["list_files"] = list_files


# ── count_loc ────────────────────────────────────────────────────────────────

def count_loc(path: str = ".", file_extension: str = "") -> str:
    """Counts lines of code in a file or directory, optionally filtered by extension."""
    try:
        p = Path(_project_root) / path
        if not p.exists():
            return f"Error: path not found: {path}"

        total_lines = 0
        file_count = 0

        if p.is_file():
            if file_extension and not p.name.endswith(file_extension):
                return f"File {path} does not match extension {file_extension}"
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                total_lines = len(f.readlines())
            file_count = 1
        elif p.is_dir():
            import os
            ignore = set(_config.get("ignore", ["node_modules", "__pycache__", ".git", ".venv", "dist", "build"]))
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in ignore and not d.startswith(".")]
                for file in files:
                    file_path = Path(root) / file
                    if not file_extension or file_path.name.endswith(file_extension):
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            total_lines += len(f.readlines())
                        file_count += 1
        else:
            return f"Error: path is neither a file nor a directory: {path}"

        if file_count == 0:
            return f"No files found matching criteria in {path}"

        return f"Counted {total_lines:,} lines in {file_count} files in {path}"
    except Exception as e:
        return f"Error counting lines of code in {path}: {e}"


TOOLS.append(_schema("count_loc", "Counts lines of code in a file or directory, optionally filtered by extension.", {
    "path": {"type": "string", "description": "Path to the file or directory (default: current directory)"},
    "file_extension": {"type": "string", "description": "Optional file extension to filter by (e.g., '.py')"},
}, []))
HANDLERS["count_loc"] = count_loc


# ── replace_lines ────────────────────────────────────────────────────────────

def replace_lines(path: str, start_line: int, end_line: int, content: str) -> str:
    """Replace a range of lines in a file (1-based, inclusive)."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"

        lines = p.read_text(encoding="utf-8").splitlines()
        if start_line < 1 or start_line > len(lines):
            return f"Error: start_line {start_line} out of range (1-{len(lines)})"
        if end_line < start_line or end_line > len(lines):
            return f"Error: end_line {end_line} out of range ({start_line}-{len(lines)})"

        new_lines = lines[:start_line-1] + content.splitlines() + lines[end_line:]
        new_content = "\n".join(new_lines)
        if p.read_text(encoding="utf-8").endswith('\n') and not new_content.endswith('\n'):
            new_content += '\n'

        ui.show_diff("\n".join(lines), new_content, path)
        if not _config.get("auto_accept", False) and not ui.confirm("Accept this line replacement?"):
            return "Edit declined by user."

        checkpoint.save(f"before replace_lines {path}")
        p.write_text(new_content, encoding="utf-8")
        checkpoint.save(f"replace_lines {path}")
        return f"Replaced lines {start_line}-{end_line} in {path}."
    except Exception as e:
        return f"Error replacing lines in {path}: {e}"


TOOLS.append(_schema("replace_lines", "Replace a range of lines in a file. Very token-efficient for large files.", {
    "path": {"type": "string", "description": "Path to the file to edit"},
    "start_line": {"type": "integer", "description": "First line to replace (1-based, inclusive)"},
    "end_line": {"type": "integer", "description": "Last line to replace (1-based, inclusive)"},
    "content": {"type": "string", "description": "New content for the specified line range"},
}, ["path", "start_line", "end_line", "content"]))
HANDLERS["replace_lines"] = replace_lines


# ── ask_user ───────────────────────────────────────────────────────────────

def ask_user(question: str) -> str:
    """Ask the user a question and return their response."""
    try:
        response = ui.prompt_input(question)
        if not response:
            return "No response provided by user."
        return response
    except Exception as e:
        return f"Error asking user: {e}"


TOOLS.append(_schema("ask_user", "Ask the user a question when you need more information or clarification.", {
    "question": {"type": "string", "description": "The question to ask the user"},
}, ["question"]))
HANDLERS["ask_user"] = ask_user




# ── Web tools (lazy-loaded) ─────────────────────────────────────────────────

from amas_code import web

TOOLS.append(_schema("web_search", "Search Google and return results with titles, URLs, and descriptions.", {
    "query": {"type": "string", "description": "Search query"},
    "num_results": {"type": "integer", "description": "Number of results (default 5)"},
}, ["query"]))
HANDLERS["web_search"] = web.web_search

TOOLS.append(_schema("fetch_url", "Fetch a URL and return its text content. HTML is converted to plain text.", {
    "url": {"type": "string", "description": "URL to fetch"},
    "max_chars": {"type": "integer", "description": "Max chars to return (default 1000000)"},
}, ["url"]))
HANDLERS["fetch_url"] = web.fetch_url

TOOLS.append(_schema("browser_navigate", "Open a URL in the visible Chromium browser. The browser stays open for the session. Returns page title and text.", {
    "url": {"type": "string", "description": "URL to navigate to"},
}, ["url"]))
HANDLERS["browser_navigate"] = web.browser_navigate

TOOLS.append(_schema("browser_click", "Click an element on the current browser page. Waits for element to be visible first.", {
    "selector": {"type": "string", "description": "CSS selector of element to click"},
}, ["selector"]))
HANDLERS["browser_click"] = web.browser_click

TOOLS.append(_schema("browser_type", "Type text into an input on the current page. Clicks the element first, clears it, then types character by character.", {
    "selector": {"type": "string", "description": "CSS selector of input element"},
    "text": {"type": "string", "description": "Text to type"},
}, ["selector", "text"]))
HANDLERS["browser_type"] = web.browser_type

TOOLS.append(_schema("browser_press", "Press a keyboard key in the browser (Enter, Tab, Escape, ArrowDown, Backspace, etc).", {
    "key": {"type": "string", "description": "Key to press (default: Enter)"},
}, []))
HANDLERS["browser_press"] = web.browser_press

TOOLS.append(_schema("browser_screenshot", "Take a screenshot of the current browser page.", {
    "path": {"type": "string", "description": "File path to save screenshot (default: screenshot.png)"},
}, []))
HANDLERS["browser_screenshot"] = web.browser_screenshot

TOOLS.append(_schema("browser_get_text", "Get text content from an element on the current browser page.", {
    "selector": {"type": "string", "description": "CSS selector (default: body)"},
}, []))
HANDLERS["browser_get_text"] = web.browser_get_text

TOOLS.append(_schema("browser_eval", "Execute arbitrary JavaScript on the current page. Use for complex interactions, DOM queries, or anything not covered by other tools.", {
    "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
}, ["expression"]))
HANDLERS["browser_eval"] = web.browser_eval

TOOLS.append(_schema("browser_wait", "Wait for an element to become visible on the page.", {
    "selector": {"type": "string", "description": "CSS selector to wait for"},
    "timeout": {"type": "integer", "description": "Timeout in ms (default: 15000)"},
}, ["selector"]))
HANDLERS["browser_wait"] = web.browser_wait

TOOLS.append(_schema("browser_wait_idle", "Wait for page content to stop changing (stabilize). ESSENTIAL after sending a message in a chatbot — waits for the AI to finish responding, then returns the page text.", {
    "selector": {"type": "string", "description": "CSS selector to monitor (default: body)"},
    "timeout": {"type": "integer", "description": "Max seconds to wait (default: 30)"},
    "stable": {"type": "integer", "description": "Seconds of no change before considering stable (default: 3)"},
}, []))
HANDLERS["browser_wait_idle"] = web.browser_wait_idle

TOOLS.append(_schema("browser_get_console_errors", "Return all captured JS console errors and warnings since the last browser_navigate. Always call this after opening a local HTML file to catch JS errors.", {}, []))
HANDLERS["browser_get_console_errors"] = web.browser_get_console_errors

TOOLS.append(_schema("browser_url", "Get the current page URL and title.", {}, []))
HANDLERS["browser_url"] = web.browser_url

TOOLS.append(_schema("browser_scroll", "Scroll the page up or down.", {
    "direction": {"type": "string", "description": "Scroll direction: 'up' or 'down' (default: down)"},
    "amount": {"type": "integer", "description": "Pixels to scroll (default: 500)"},
}, []))
HANDLERS["browser_scroll"] = web.browser_scroll

# ── Tab management ───────────────────────────────────────────────────────────

TOOLS.append(_schema("browser_new_tab", "Open a new browser tab, optionally navigating to a URL.", {
    "url": {"type": "string", "description": "URL to open (default: about:blank)"},
}, []))
HANDLERS["browser_new_tab"] = web.browser_new_tab

TOOLS.append(_schema("browser_switch_tab", "Switch to a browser tab by index. Use browser_list_tabs to see available tabs.", {
    "index": {"type": "integer", "description": "Tab index to switch to (0-based)"},
}, ["index"]))
HANDLERS["browser_switch_tab"] = web.browser_switch_tab

TOOLS.append(_schema("browser_close_tab", "Close a browser tab by index. -1 (default) closes the current tab.", {
    "index": {"type": "integer", "description": "Tab index to close (-1 for current tab)"},
}, []))
HANDLERS["browser_close_tab"] = web.browser_close_tab

TOOLS.append(_schema("browser_list_tabs", "List all open browser tabs with their index, title, URL, and which is active.", {}, []))
HANDLERS["browser_list_tabs"] = web.browser_list_tabs

# ── Tool execution ───────────────────────────────────────────────────────────

def execute(name: str, args_json: str) -> str:
    """Execute a tool by name with JSON arguments. Returns result string."""
    handler = HANDLERS.get(name)
    if not handler:
        return f"Error: unknown tool '{name}'"

    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        return f"Error: invalid tool arguments: {e}"

    try:
        result = handler(**args)
        return result if result else "Tool executed successfully (no output)."
    except TypeError as e:
        return f"Error: wrong arguments for {name}: {e}"
    except Exception as e:
        return f"Error executing {name}: {e}"
