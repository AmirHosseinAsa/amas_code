"""Chat history — persistent chat sessions with checkpoints and replay modes.

Each chat session is stored as a JSON file in .amas/chats/ and tracks:
- All conversation messages (user, assistant, tool)
- Checkpoints (git commit hashes) created during the session
- Metadata (start time, model, title)

Replay modes:
- CONVERSATION_ONLY: Show only user/assistant messages (no tool calls/results)
- CONVERSATION_AND_CODE: Show everything including file changes and tool outputs
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from amas_code import ui

# ── Types ────────────────────────────────────────────────────────────────────

ReplayMode = Literal["conversation_only", "conversation_and_code"]

CHATS_DIR = Path(".amas/chats")


# ── ChatSession ──────────────────────────────────────────────────────────────

class ChatSession:
    """A single conversational session with checkpoints."""

    def __init__(self, session_id: str | None = None):
        self.id = session_id or _new_id()
        self.title: str = ""
        self.model: str = ""
        self.started_at: float = time.time()
        self.updated_at: float = time.time()
        self.messages: list[dict] = []
        self.checkpoints: list[dict] = []  # {hash, message, timestamp, message_index}

    @property
    def path(self) -> Path:
        return CHATS_DIR / f"{self.id}.json"

    def add_message(self, role: str, content: str, tool_calls: list | None = None,
                    tool_call_id: str | None = None) -> None:
        """Record a message in the session."""
        msg = {
            "role": role,
            "content": content[:5000],  # Cap to avoid huge files
            "timestamp": time.time(),
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        self.messages.append(msg)
        self.updated_at = time.time()

        # Auto-title from first user message
        if not self.title and role == "user" and content.strip():
            self.title = content.strip()[:80]

    def add_checkpoint(self, git_hash: str, message: str) -> None:
        """Record a checkpoint (git commit) linked to this chat session."""
        cp = {
            "hash": git_hash,
            "message": message,
            "timestamp": time.time(),
            "message_index": len(self.messages),  # What message triggered this
        }
        self.checkpoints.append(cp)
        self.updated_at = time.time()

    def undo_to_checkpoint(self, index: int = -1) -> dict | None:
        """Move a checkpoint and return the target to restore to.

        Args:
            index: Checkpoint index to undo to. -1 means the latest.

        Returns:
            The checkpoint to restore to (the one before the undone one), or None.
        """
        if len(self.checkpoints) < 2:
            return None

        # Pop the latest checkpoint
        self.checkpoints.pop()

        # Return the new latest checkpoint (the one to restore to)
        return self.checkpoints[-1] if self.checkpoints else None

    def get_messages(self, mode: ReplayMode = "conversation_and_code") -> list[dict]:
        """Get messages filtered by replay mode.

        Args:
            mode: 'conversation_only' filters out tool/system messages,
                  'conversation_and_code' returns everything.
        """
        if mode == "conversation_only":
            return [
                m for m in self.messages
                if m["role"] in ("user", "assistant") and m.get("content")
                and not m.get("tool_calls")  # Skip assistant messages that are just tool calls
            ]
        return list(self.messages)

    def save(self) -> None:
        """Persist session to disk."""
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "checkpoints": self.checkpoints,
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    @classmethod
    def load(cls, session_id: str) -> "ChatSession":
        """Load a session from disk."""
        path = CHATS_DIR / f"{session_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Chat session not found: {session_id}")

        data = json.loads(path.read_text())
        session = cls(data["id"])
        session.title = data.get("title", "")
        session.model = data.get("model", "")
        session.started_at = data.get("started_at", 0)
        session.updated_at = data.get("updated_at", 0)
        session.messages = data.get("messages", [])
        session.checkpoints = data.get("checkpoints", [])
        return session

    def summary(self) -> dict:
        """Return a compact summary for listing."""
        user_msgs = sum(1 for m in self.messages if m["role"] == "user")
        return {
            "id": self.id,
            "title": self.title or "(untitled)",
            "model": self.model,
            "started": _format_ts(self.started_at),
            "updated": _format_ts(self.updated_at),
            "messages": len(self.messages),
            "user_messages": user_msgs,
            "checkpoints": len(self.checkpoints),
        }


# ── History Manager ──────────────────────────────────────────────────────────

def list_sessions(limit: int = 20) -> list[dict]:
    """List all saved chat sessions, newest first."""
    if not CHATS_DIR.exists():
        return []

    sessions = []
    for f in sorted(CHATS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            sessions.append({
                "id": data.get("id", f.stem),
                "title": data.get("title", "(untitled)")[:60],
                "model": data.get("model", "?"),
                "started": _format_ts(data.get("started_at", 0)),
                "updated": _format_ts(data.get("updated_at", 0)),
                "messages": len(data.get("messages", [])),
                "checkpoints": len(data.get("checkpoints", [])),
            })
        except (json.JSONDecodeError, KeyError):
            continue

        if len(sessions) >= limit:
            break

    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a chat session file."""
    path = CHATS_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def search_sessions(query: str) -> list[dict]:
    """Search sessions by title or content."""
    query_lower = query.lower()
    results = []
    if not CHATS_DIR.exists():
        return results

    for f in CHATS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            title = data.get("title", "")
            # Search title
            if query_lower in title.lower():
                results.append({
                    "id": data.get("id", f.stem),
                    "title": title[:60],
                    "match": "title",
                })
                continue
            # Search messages
            for msg in data.get("messages", []):
                content = msg.get("content", "")
                if query_lower in content.lower():
                    results.append({
                        "id": data.get("id", f.stem),
                        "title": title[:60],
                        "match": f"message: {content[:50]}...",
                    })
                    break
        except (json.JSONDecodeError, KeyError):
            continue

    return results


# ── UI Display Functions ─────────────────────────────────────────────────────

def show_chat_list(sessions: list[dict]) -> None:
    """Display chat sessions in a beautiful table."""
    from rich.table import Table

    table = Table(
        title="[bold bright_cyan]💬 Chat History[/]",
        border_style="#3b4261",
        padding=(0, 1),
        title_justify="left",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Title", style="bold white", max_width=40)
    table.add_column("Model", style="cyan", max_width=20)
    table.add_column("Messages", justify="right", style="#73daca")
    table.add_column("Checkpoints", justify="right", style="#bb9af7")
    table.add_column("Last Active", style="dim")
    table.add_column("ID", style="dim", max_width=10)

    for i, s in enumerate(sessions, 1):
        table.add_row(
            str(i),
            s["title"],
            s.get("model", "?"),
            str(s["messages"]),
            str(s["checkpoints"]),
            s["updated"],
            s["id"][:8] + "…",
        )

    ui.console.print(table)
    ui.console.print()


def show_chat_detail(session: ChatSession, mode: ReplayMode = "conversation_only") -> None:
    """Display a single chat session's messages."""
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.text import Text

    # Header
    header = Text()
    header.append(f"  Chat: ", style="bold")
    header.append(session.title or "(untitled)", style="bold bright_cyan")
    header.append(f"\n  Model: ", style="bold")
    header.append(session.model, style="cyan")
    header.append(f"\n  Started: ", style="bold")
    header.append(_format_ts(session.started_at), style="dim")
    header.append(f"  |  Messages: ", style="bold")
    header.append(str(len(session.messages)), style="#73daca")
    header.append(f"  |  Checkpoints: ", style="bold")
    header.append(str(len(session.checkpoints)), style="#bb9af7")
    header.append(f"\n  Mode: ", style="bold")
    mode_label = "📝 Conversation Only" if mode == "conversation_only" else "📝💻 Conversation + Code"
    header.append(mode_label, style="#e0af68")

    ui.console.print(Panel(header, border_style="#3b4261", padding=(0, 1)))

    # Messages
    messages = session.get_messages(mode)
    if not messages:
        ui.info("No messages to display.")
        return

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        ts = _format_ts(msg.get("timestamp", 0))

        if role == "user":
            ui.console.print(f"\n  [bold #7aa2f7]❯ You[/] [dim]{ts}[/]")
            ui.console.print(f"  {content}")
        elif role == "assistant":
            ui.console.print(f"\n  [bold #bb9af7]◆ Assistant[/] [dim]{ts}[/]")
            try:
                ui.console.print(Markdown(content))
            except Exception:
                ui.console.print(f"  {content}")
        elif role == "tool" and mode == "conversation_and_code":
            tool_id = msg.get("tool_call_id", "")
            ui.console.print(f"\n  [dim]⚡ Tool result ({tool_id})[/]")
            ui.console.print(f"  [dim]{content[:200]}{'…' if len(content) > 200 else ''}[/]")

    ui.console.print()

    # Show checkpoints for this chat
    if session.checkpoints:
        from rich.table import Table
        cp_table = Table(
            title="[bold #bb9af7]🔖 Chat Checkpoints[/]",
            border_style="#3b4261",
            padding=(0, 1),
            title_justify="left",
        )
        cp_table.add_column("#", style="dim", width=4, justify="right")
        cp_table.add_column("Hash", style="cyan", width=10)
        cp_table.add_column("Message", style="bold white")
        cp_table.add_column("Time", style="dim")
        cp_table.add_column("At Msg#", justify="right", style="#73daca")

        for i, cp in enumerate(session.checkpoints, 1):
            cp_table.add_row(
                str(i),
                cp["hash"][:8],
                cp["message"],
                _format_ts(cp["timestamp"]),
                str(cp["message_index"]),
            )
        ui.console.print(cp_table)
        ui.console.print()


def show_chat_checkpoints(session: ChatSession) -> None:
    """Display only the checkpoints for a chat session."""
    from rich.table import Table

    if not session.checkpoints:
        ui.info("No checkpoints in this chat session.")
        return

    table = Table(
        title=f"[bold #bb9af7]🔖 Checkpoints — {session.title or '(untitled)'}[/]",
        border_style="#3b4261",
        padding=(0, 1),
        title_justify="left",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Hash", style="cyan", width=10)
    table.add_column("Message", style="bold white")
    table.add_column("Time", style="dim")
    table.add_column("At Msg#", justify="right", style="#73daca")

    for i, cp in enumerate(session.checkpoints, 1):
        table.add_row(
            str(i),
            cp["hash"][:8],
            cp["message"],
            _format_ts(cp["timestamp"]),
            str(cp["message_index"]),
        )

    ui.console.print(table)
    ui.console.print()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _new_id() -> str:
    """Generate a short, readable session ID."""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _format_ts(ts: float) -> str:
    """Format a timestamp for display."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(ts)
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M:%S")
        elif (now - dt).days < 7:
            return dt.strftime("%a %H:%M")
        else:
            return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "—"
