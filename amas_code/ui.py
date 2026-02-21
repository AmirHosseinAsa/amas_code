"""Premium terminal UI — modern, practical, beautiful."""
import difflib
import subprocess
import shlex
import time
import threading

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape as _escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.live import Live
from rich.rule import Rule
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.align import Align
from rich.padding import Padding
from rich.layout import Layout

console = Console()

# ── Color palette (modern dark terminal aesthetic) ───────────────────────────
ACCENT      = "bright_cyan"
ACCENT2     = "#a9b1d6"
SUCCESS     = "#73daca"
ERROR       = "#f7768e"
WARN        = "#e0af68"
DIM         = "#565f89"
BORDER      = "#3b4261"
TOOL_CLR    = "#bb9af7"
PROMPT_CLR  = "#7aa2f7"
GRADIENT_1  = "#7aa2f7"
GRADIENT_2  = "#bb9af7"
GRADIENT_3  = "#73daca"
MUTED       = "#414868"
BG_PANEL    = "#1a1b26"


# ── Thinking/Spinner animations ──────────────────────────────────────────────

_THINKING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_THINKING_TEXTS = [
    "Thinking",
    "Analyzing",
    "Reasoning",
    "Processing",
    "Generating",
]


class StreamingDisplay:
    """Context manager that shows a thinking animation while waiting for
    the first token, then renders Markdown in real-time using Rich Live.

    Every chunk updates the accumulated text and Rich re-renders the full
    Markdown in-place — so bold, lists, tables, code blocks etc. appear
    properly formatted as they stream in."""

    def __init__(self):
        self._started = False
        self._start_time: float = 0
        self._char_count = 0
        self._accumulated_text: list[str] = []
        self._spinner_thread: threading.Thread | None = None
        self._stop_spinner = threading.Event()
        self._spinner_active = False
        self._live: Live | None = None

    def __enter__(self):
        self._start_time = time.time()
        self._start_spinner()
        return self

    def __exit__(self, *args):
        self._stop_thinking()
        # Stop the Live display
        if self._live is not None:
            self._live.stop()
            self._live = None

        if self._started:
            # Estimate output tokens (~4 chars per token)
            est_tokens = max(1, self._char_count // 4)

            # Print token stats for cost estimation
            console.print()
            stats = Text()
            stats.append("  ◆ ", style=f"bold {ACCENT}")
            stats.append(f"~{est_tokens:,}", style=f"bold {SUCCESS}")
            stats.append(" tokens", style=DIM)
            console.print(stats)
        console.print()

    def _start_spinner(self):
        """Start the animated thinking spinner in a background thread."""
        self._stop_spinner.clear()
        self._spinner_active = True

        def _animate():
            frame_idx = 0
            text_idx = 0
            dots = 0
            last_text_change = time.time()
            while not self._stop_spinner.is_set():
                elapsed = time.time() - self._start_time
                frame = _THINKING_FRAMES[frame_idx % len(_THINKING_FRAMES)]
                if time.time() - last_text_change > 2.0:
                    text_idx = (text_idx + 1) % len(_THINKING_TEXTS)
                    last_text_change = time.time()
                    dots = 0
                thinking_text = _THINKING_TEXTS[text_idx]
                dot_str = "." * (dots % 4)
                line = f"\r  \033[96m{frame}\033[0m \033[37m{thinking_text}{dot_str:<3}\033[0m \033[90m({elapsed:.0f}s)\033[0m  "
                print(line, end="", flush=True)
                frame_idx += 1
                dots += 1
                self._stop_spinner.wait(0.1)
            # Clear the spinner line
            print("\r" + " " * 60 + "\r", end="", flush=True)

        self._spinner_thread = threading.Thread(target=_animate, daemon=True)
        self._spinner_thread.start()

    def _stop_thinking(self):
        """Stop the thinking spinner."""
        if self._spinner_active:
            self._stop_spinner.set()
            if self._spinner_thread:
                self._spinner_thread.join(timeout=1)
            self._spinner_active = False

    def on_chunk(self, text: str):
        """Called for each streaming chunk from the LLM."""
        if not self._started:
            self._started = True
            self._stop_thinking()
            # Start Live display for real-time markdown rendering
            self._live = Live(
                Markdown(""),
                console=console,
                refresh_per_second=8,
                vertical_overflow="visible",
            )
            self._live.start()

        self._char_count += len(text)
        self._accumulated_text.append(text)

        # Re-render the full accumulated text as Markdown in real-time
        if self._live is not None:
            full = "".join(self._accumulated_text)
            self._live.update(Markdown(full))

    @property
    def full_text(self) -> str:
        """Return the complete accumulated response text."""
        return "".join(self._accumulated_text).strip()


# ── Basic output ─────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    console.print(f"  [{ACCENT}]●[/] {msg}")


def success(msg: str) -> None:
    console.print(f"  [{SUCCESS}]✓[/] {msg}")


def error(msg: str) -> None:
    console.print(f"  [{ERROR}]✗[/] {_escape(msg)}")


def warning(msg: str) -> None:
    console.print(f"  [{WARN}]⚠[/] {msg}")


def dim(msg: str) -> None:
    """Print a dimmed message."""
    console.print(f"  [{DIM}]{msg}[/]")


# ── LLM response display ────────────────────────────────────────────────────

def show_response(text: str) -> None:
    """Render LLM response as markdown."""
    console.print()
    console.print(Markdown(text))
    console.print()


def show_streaming_start() -> None:
    """Indicate streaming response is starting."""
    console.print()


def show_streaming_end() -> None:
    """Mark end of streaming response."""
    pass  # Now handled by StreamingDisplay


# ── Tool display ─────────────────────────────────────────────────────────────

_TOOL_ICONS = {
    "read_file": "📖",
    "write_file": "📝",
    "edit_file": "✏️",
    "create_file": "📄",
    "delete_file": "🗑️",
    "run_command": "⚙️",
    "shell_command": "⚙️",
    "list_directory": "📁",
    "search_files": "🔍",
    "web_search": "🌐",
    "fetch_url": "🔗",
    "browser_navigate": "🌍",
    "browser_click": "🖱️",
    "browser_type": "⌨️",
    "browser_screenshot": "📸",
    "browser_eval": "💻",
    "browser_get_text": "📃",
    "browser_press": "⏎",
    "browser_scroll": "📜",
    "browser_wait": "⏳",
    "browser_wait_idle": "⏳",
    "browser_new_tab": "➕",
    "browser_switch_tab": "🔀",
    "browser_close_tab": "✖️",
    "browser_list_tabs": "📋",
    "browser_url": "🔗",
    "ask_user": "❓",
}


def show_tool_call(name: str, args: dict) -> None:
    """Display tool call in a sleek panel."""
    icon = _TOOL_ICONS.get(name, "⚡")

    # Truncate content values for display
    display_args = {}
    for k, v in args.items():
        sv = str(v)
        if k == "content" and len(sv) > 60:
            sv = sv[:57] + "..."
        elif len(sv) > 120:
            sv = sv[:117] + "..."
        display_args[k] = sv

    arg_lines = []
    for k, v in display_args.items():
        arg_lines.append(f"  [{DIM}]{k}:[/] [white]{_escape(v)}[/]")

    arg_str = "\n".join(arg_lines)

    console.print(Panel(
        arg_str or f"[{DIM}]no arguments[/]",
        title=f"[bold {TOOL_CLR}]{icon} {name}[/]",
        title_align="left",
        border_style=TOOL_CLR,
        padding=(0, 1),
        subtitle=f"[{DIM}]tool call[/]",
        subtitle_align="right",
    ))


def show_tool_progress(name: str) -> None:
    """Show a brief spinner for tool execution."""
    pass  # Can be used if needed later


# ── Diff display ─────────────────────────────────────────────────────────────

def show_diff(old: str, new: str, filename: str) -> None:
    """Show unified diff with syntax highlighting."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}")
    diff_text = "".join(diff)
    if diff_text:
        # Count additions and deletions
        additions = sum(1 for line in diff_text.splitlines() if line.startswith('+') and not line.startswith('+++'))
        deletions = sum(1 for line in diff_text.splitlines() if line.startswith('-') and not line.startswith('---'))

        subtitle = f"[{SUCCESS}]+{additions}[/] [{ERROR}]-{deletions}[/]"

        console.print(Panel(
            Syntax(diff_text, "diff", theme="monokai", line_numbers=False),
            title=f"[bold]📝 {filename}[/]",
            title_align="left",
            border_style=ACCENT,
            padding=(0, 1),
            subtitle=subtitle,
            subtitle_align="right",
        ))
    else:
        info("No changes detected.")


def confirm(prompt: str = "Accept?") -> bool:
    """Interactive accept/decline with arrow keys using prompt_toolkit."""
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.formatted_text import HTML

        selected = [0]  # 0=Accept, 1=Decline
        result = [None]

        def get_toolbar():
            if selected[0] == 0:
                return HTML(
                    f'  <b>{prompt}</b>  '
                    '<style bg="#73daca" fg="#1a1b26"> ▸ Accept </style>'
                    '  '
                    '<style fg="#565f89"> Decline </style>'
                    '  <style fg="#565f89">← →  Enter to confirm</style>'
                )
            else:
                return HTML(
                    f'  <b>{prompt}</b>  '
                    '<style fg="#565f89"> Accept </style>'
                    '  '
                    '<style bg="#f7768e" fg="#1a1b26"> ▸ Decline </style>'
                    '  <style fg="#565f89">← →  Enter to confirm</style>'
                )

        kb = KeyBindings()

        @kb.add("left")
        def _left(event):
            selected[0] = 0

        @kb.add("right")
        def _right(event):
            selected[0] = 1

        @kb.add("tab")
        def _tab(event):
            selected[0] = 1 - selected[0]

        @kb.add("enter")
        def _enter(event):
            result[0] = selected[0] == 0
            event.app.exit()

        @kb.add("y")
        def _yes(event):
            result[0] = True
            event.app.exit()

        @kb.add("n")
        def _no(event):
            result[0] = False
            event.app.exit()

        @kb.add("escape")
        @kb.add("c-c")
        def _cancel(event):
            result[0] = False
            event.app.exit()

        app = Application(
            layout=Layout(Window(FormattedTextControl(get_toolbar), height=1)),
            key_bindings=kb,
            full_screen=False,
        )
        app.run()
        return result[0]
    except Exception:
        # Fallback to simple prompt
        try:
            response = console.input(
                f"  [{ACCENT}]❯ {prompt}[/] [{DIM}]([/][{SUCCESS}]y[/][{DIM}]/[/][{ERROR}]n[/][{DIM}])[/] "
            ).strip().lower()
            return response in ("y", "yes", "")
        except EOFError:
            warning(f"Non-interactive mode — auto-declining: {prompt}")
            return False


# ── Summary / tables ─────────────────────────────────────────────────────────

def show_summary(actions: list[dict]) -> None:
    """Show table of actions taken during a turn."""
    if not actions:
        return

    console.print()
    table = Table(
        show_header=True,
        border_style=BORDER,
        padding=(0, 1),
        title=f"[bold {ACCENT}]Actions Summary[/]",
        title_style="bold",
        title_justify="left",
    )
    table.add_column("#", style=f"bold {DIM}", width=3, justify="right")
    table.add_column("Tool", style=f"bold {TOOL_CLR}", no_wrap=True)
    table.add_column("Result", style=SUCCESS)
    for i, action in enumerate(actions, 1):
        icon = _TOOL_ICONS.get(action.get("tool", ""), "⚡")
        result = action.get("result", "")[:80]
        if result.startswith("Error"):
            result = f"[{ERROR}]{_escape(result)}[/]"
        else:
            result = _escape(result)
        table.add_row(str(i), f"{icon} {action.get('tool', '')}", result)
    console.print(table)
    console.print()


# ── Welcome / help ───────────────────────────────────────────────────────────

def show_welcome() -> None:
    """Show a stunning welcome banner."""
    # Gradient-effect logo using multiple colors
    logo_lines = [
        "     █████╗ ███╗   ███╗ █████╗ ███████╗",
        "    ██╔══██╗████╗ ████║██╔══██╗██╔════╝",
        "    ███████║██╔████╔██║███████║███████╗",
        "    ██╔══██║██║╚██╔╝██║██╔══██║╚════██║",
        "    ██║  ██║██║ ╚═╝ ██║██║  ██║███████║",
        "    ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝",
    ]

    gradient_colors = [
        "#7aa2f7", "#7ba8f8", "#89aff5", "#9bb5f3",
        "#b0b8f0", "#bb9af7",
    ]

    logo = Text()
    for i, line in enumerate(logo_lines):
        color = gradient_colors[i % len(gradient_colors)]
        logo.append(line + "\n", style=f"bold {color}")

    tagline = Text()
    tagline.append("    C O D E", style="bold white")
    tagline.append("  —  ", style=DIM)
    tagline.append("AI-powered coding agent", style=f"italic {ACCENT2}")

    hints = Text()
    hints.append("\n    ", style="")
    hints.append("Any model", style=f"bold {GRADIENT_1}")
    hints.append("  •  ", style=DIM)
    hints.append("Any hardware", style=f"bold {GRADIENT_2}")
    hints.append("  •  ", style=DIM)
    hints.append("Full power", style=f"bold {GRADIENT_3}")

    shortcuts = Text()
    shortcuts.append("\n\n    ", style="")

    cmds = [
        ("/help", ACCENT, "commands"),
        ("/yolo", WARN, "auto-accept"),
        ("/init", GRADIENT_3, "scan project"),
        ("/quit", ERROR, "exit"),
    ]
    for i, (cmd, color, desc) in enumerate(cmds):
        if i > 0:
            shortcuts.append("  │  ", style=MUTED)
        shortcuts.append(cmd, style=f"bold {color}")
        shortcuts.append(f" {desc}", style=DIM)

    content = Text()
    content.append_text(logo)
    content.append_text(tagline)
    content.append_text(hints)
    content.append_text(shortcuts)

    console.print()
    console.print(Panel(
        content,
        border_style=GRADIENT_1,
        padding=(0, 1),
        subtitle=f"[{DIM}]v0.1.0[/]",
        subtitle_align="right",
    ))
    console.print()


def show_help(commands: dict[str, str]) -> None:
    """Display available commands in a styled table."""
    table = Table(
        title=f"[bold {ACCENT}]⌘ Commands[/]",
        show_header=True,
        border_style=BORDER,
        padding=(0, 1),
        title_justify="left",
        show_lines=False,
    )
    table.add_column("Command", style=f"bold {ACCENT}", no_wrap=True, min_width=16)
    table.add_column("Description", style="white")

    # Group commands by category
    categories = {
        "Navigation": ["/help", "/quit", "/clear"],
        "AI Control": ["/yolo", "/model", "/config", "/compact", "/cost"],
        "Project": ["/init", "/rules", "/skills", "/attach", "/test"],
        "History": ["/undo", "/rewind", "/checkpoint", "/history", "/resume", "/export"],
        "Setup": ["/key"],
    }

    categorized = set()
    for cat, cmds in categories.items():
        table.add_row(f"[bold {WARN}]── {cat} ──[/]", "", style=DIM)
        for cmd in cmds:
            if cmd in commands:
                table.add_row(cmd, commands[cmd])
                categorized.add(cmd)

    # Any remaining uncategorized commands
    remaining = {k: v for k, v in commands.items() if k not in categorized}
    if remaining:
        table.add_row(f"[bold {WARN}]── Other ──[/]", "", style=DIM)
        for cmd, desc in remaining.items():
            table.add_row(cmd, desc)

    console.print(table)
    console.print()


def show_model_info(model: str, provider: str, has_key: bool) -> None:
    """Display current model configuration."""
    key_status = f"[{SUCCESS}]● Connected[/]" if has_key else f"[{WARN}]○ No key (env var / free tier)[/]"

    # Model info with icon
    model_icon = "🤖"
    provider_icon = "🔌"
    auth_icon = "🔑"

    console.print(Panel(
        f"  {model_icon} [bold]Model[/]     [{ACCENT}]{model}[/]\n"
        f"  {provider_icon} [bold]Provider[/]  [{ACCENT}]{provider}[/]\n"
        f"  {auth_icon} [bold]Auth[/]      {key_status}",
        title=f"[bold {ACCENT}]Configuration[/]",
        title_align="left",
        border_style=BORDER,
        padding=(0, 1),
    ))
    console.print()


def show_config_saved(key: str, value: str) -> None:
    """Confirm a config change was saved."""
    success(f"Saved [{ACCENT}]{key}[/] = [{SUCCESS}]{value}[/]")


def prompt_input(prompt: str, password: bool = False) -> str:
    """Prompt user for text input."""
    if password:
        return console.input(f"  [{ACCENT}]❯ {prompt}[/] [{DIM}](hidden)[/]: ", password=True).strip()
    return console.input(f"  [{ACCENT}]❯ {prompt}[/]: ").strip()


def run_and_stream_command(command: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command and stream its output to the console. Optionally capture stdout/stderr."""
    console.print(f"  [{DIM}]⚙️  Running:[/] [{ACCENT}]{command}[/]")
    args = shlex.split(command)
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        stdout_lines = []
        stderr_lines = []

        while True:
            stdout_line = process.stdout.readline()
            stderr_line = process.stderr.readline()

            if stdout_line:
                if capture: stdout_lines.append(stdout_line)
                console.print(f"  [{DIM}]│[/] {stdout_line.rstrip()}", highlight=False)
            if stderr_line:
                if capture: stderr_lines.append(stderr_line)
                console.print(f"  [{ERROR}]│[/] {stderr_line.rstrip()}", highlight=False)

            if not stdout_line and not stderr_line and process.poll() is not None:
                break

        return subprocess.CompletedProcess(
            args=args,
            returncode=process.returncode,
            stdout="".join(stdout_lines) if capture else None,
            stderr="".join(stderr_lines) if capture else None,
        )
    except FileNotFoundError:
        error(f"Command not found: [cyan]{args[0]}[/]")
        return subprocess.CompletedProcess(args=args, returncode=127)
    except Exception as e:
        error(f"Error executing command: {e}")
        return subprocess.CompletedProcess(args=args, returncode=1, stderr=str(e))


def show_interrupted() -> None:
    """Show a styled interruption message."""
    console.print(f"\n  [{WARN}]⚡ Interrupted[/] [{DIM}]— type [bold]/quit[/] to exit[/]")


def show_error_with_hint(msg: str, hint: str = "") -> None:
    """Show an error with an optional hint for resolution."""
    error(msg)
    if hint:
        console.print(f"  [{DIM}]💡 {hint}[/]")


def show_context_warning(est_tokens: int, threshold: int) -> None:
    """Show a styled context size warning."""
    pct = est_tokens / threshold * 100
    bar_width = 20
    filled = int(bar_width * min(pct, 100) / 100)
    bar = f"[{SUCCESS}]{'█' * filled}[/][{DIM}]{'░' * (bar_width - filled)}[/]"
    warning(f"Context: {bar} [{WARN}]{pct:.0f}%[/] (~{est_tokens:,} tokens) — use [bold cyan]/compact[/]")


def interactive_picker(items: list[dict], title: str = "Select") -> dict | None:
    """fzf-style interactive picker.

    Each item should have at least:
      - "label": display text
      - any other keys you want returned

    Returns the selected item dict, or None if cancelled.
    Uses arrow keys to navigate, type to filter, Enter to select, Esc/Ctrl-C to cancel.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout as PTLayout
    from prompt_toolkit.layout.containers import Window, HSplit
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition

    if not items:
        return None

    # State
    selected_idx = [0]
    search_text = [""]
    result = [None]

    def get_filtered():
        q = search_text[0].lower()
        if not q:
            return list(items)
        return [it for it in items if q in it["label"].lower()]

    def get_header_text():
        filtered = get_filtered()
        total = len(items)
        shown = len(filtered)
        q = search_text[0]
        parts = [("class:title", f"  {title}"), ("", "  ")]
        if q:
            parts.append(("class:search", f"🔍 {q}"))
            parts.append(("class:dim", f"  ({shown}/{total})"))
        else:
            parts.append(("class:dim", f"  ({total} items — type to filter)"))
        parts.append(("", "\n"))
        return parts

    def get_list_text():
        filtered = get_filtered()
        if not filtered:
            return [("class:dim", "  No matches\n")]

        # Clamp selection
        if selected_idx[0] >= len(filtered):
            selected_idx[0] = len(filtered) - 1
        if selected_idx[0] < 0:
            selected_idx[0] = 0

        lines = []
        for i, item in enumerate(filtered):
            if i == selected_idx[0]:
                lines.append(("class:selected", f"  ▸ {item['label']}\n"))
            else:
                lines.append(("class:normal", f"    {item['label']}\n"))
        return lines

    def get_footer_text():
        return [("class:dim", "\n  ↑↓ navigate  •  type to filter  •  Enter select  •  Esc cancel\n")]

    header = FormattedTextControl(get_header_text)
    body = FormattedTextControl(get_list_text)
    footer = FormattedTextControl(get_footer_text)

    layout = PTLayout(HSplit([
        Window(header, height=2),
        Window(body, height=min(len(items), 12) + 1),
        Window(footer, height=2),
    ]))

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        selected_idx[0] = max(0, selected_idx[0] - 1)

    @kb.add("down")
    def _down(event):
        filtered = get_filtered()
        selected_idx[0] = min(len(filtered) - 1, selected_idx[0] + 1)

    @kb.add("enter")
    def _enter(event):
        filtered = get_filtered()
        if filtered and 0 <= selected_idx[0] < len(filtered):
            result[0] = filtered[selected_idx[0]]
        event.app.exit()

    @kb.add("escape")
    def _escape(event):
        event.app.exit()

    @kb.add("c-c")
    def _ctrl_c(event):
        event.app.exit()

    @kb.add("backspace")
    def _backspace(event):
        if search_text[0]:
            search_text[0] = search_text[0][:-1]
            selected_idx[0] = 0

    @kb.add("<any>")
    def _any(event):
        ch = event.data
        if ch.isprintable() and len(ch) == 1:
            search_text[0] += ch
            selected_idx[0] = 0

    style_dict = {
        "title": "bold #7dcfff",
        "search": "bold #bb9af7",
        "selected": "bold #7dcfff",
        "normal": "",
        "dim": "#565f89",
    }

    from prompt_toolkit.styles import Style
    style = Style.from_dict(style_dict)

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=False)
    app.run()

    return result[0]

