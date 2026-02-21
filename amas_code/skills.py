"""Skills + rules loader, and project init scanner."""
from pathlib import Path

from amas_code import ui


def load_rules(path: str = ".amas/rules.md") -> str:
    """Load project rules from .amas/rules.md."""
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def load_skills(path: str = ".amas/skills/") -> dict[str, str]:
    """Load all skill markdown files from .amas/skills/."""
    skills = {}
    p = Path(path)
    if p.exists() and p.is_dir():
        for f in sorted(p.glob("*.md")):
            skills[f.stem] = f.read_text(encoding="utf-8").strip()
    return skills


def load_lessons(path: str = ".amas/lessons/") -> dict[str, str]:
    """Load all lesson markdown files from .amas/lessons/."""
    lessons = {}
    p = Path(path)
    if p.exists() and p.is_dir():
        # Only load the last 20 lessons to keep prompt size manageable
        files = sorted(p.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]
        for f in reversed(files):
            lessons[f.stem] = f.read_text(encoding="utf-8").strip()
    return lessons



def init_project(path: str = ".", config: dict | None = None) -> str:
    """Scan project and build a compact project map.

    Uses tree-sitter if available, falls back to basic file listing.
    """
    root = Path(path).resolve()
    ignore = set((config or {}).get("ignore", [
        "node_modules", "__pycache__", ".git", "*.pyc", "dist", "build", ".venv", ".amas",
    ]))

    ui.info("Scanning project structure...")

    # Collect source files
    source_files = []
    _collect_files(root, source_files, ignore, root, max_depth=5)

    if not source_files:
        return "Empty project — no source files found."

    # Build file tree
    lines = [f"**Project: {root.name}** ({len(source_files)} files)\n"]
    lines.append("```")
    for rel_path in sorted(source_files):
        lines.append(f"  {rel_path}")
    lines.append("```\n")

    # Try tree-sitter extraction for function/class signatures
    extractions = _extract_symbols(root, source_files)
    if extractions:
        lines.append("**Key symbols:**\n```")
        for item in extractions[:100]:  # Cap at 100 symbols
            lines.append(f"  {item}")
        lines.append("```")

    result = "\n".join(lines)

    # Trim if too long (keep system prompt under 2000 tokens ~ 8000 chars)
    if len(result) > 6000:
        result = result[:6000] + "\n\n[project map truncated — too many files]"

    ui.success(f"Scanned {len(source_files)} files, {len(extractions)} symbols extracted.")
    return result


def _collect_files(p: Path, out: list, ignore: set, root: Path, max_depth: int, depth: int = 0) -> None:
    """Recursively collect source file paths."""
    if depth > max_depth:
        return
    try:
        for entry in sorted(p.iterdir()):
            if entry.name in ignore or entry.name.startswith("."):
                continue
            if any(entry.match(ig) for ig in ignore):
                continue
            if entry.is_dir():
                _collect_files(entry, out, ignore, root, max_depth, depth + 1)
            elif entry.is_file() and _is_source_file(entry):
                try:
                    out.append(str(entry.relative_to(root)))
                except ValueError:
                    out.append(str(entry))
    except PermissionError:
        pass


def _is_source_file(p: Path) -> bool:
    """Check if a file is a source code file worth scanning."""
    source_exts = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".c", ".h", ".cpp", ".hpp",
        ".java", ".kt", ".rb", ".php", ".swift", ".m", ".cs", ".lua", ".sh", ".bash",
        ".yaml", ".yml", ".toml", ".json", ".md", ".html", ".css", ".sql", ".r",
        ".scala", ".clj", ".ex", ".exs", ".hs", ".ml", ".vue", ".svelte",
    }
    return p.suffix.lower() in source_exts


# ── Tree-sitter symbol extraction (lazy-loaded) ─────────────────────────────

_LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "javascript", ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp",
    ".java": "java", ".rb": "ruby", ".php": "php", ".cs": "c_sharp",
    ".swift": "swift", ".kt": "kotlin", ".lua": "lua", ".hs": "haskell",
    ".scala": "scala", ".ex": "elixir", ".html": "html", ".css": "css",
}


def _extract_symbols(root: Path, files: list[str]) -> list[str]:
    """Extract function/class names using tree-sitter (if available)."""
    try:
        from tree_sitter_languages import get_parser  # Lazy import!
    except ImportError:
        ui.info("[dim]tree-sitter not installed — skipping symbol extraction. Install with: pip install tree-sitter-languages[/]")
        return _extract_symbols_basic(root, files)

    symbols = []
    for rel_path in files:
        p = root / rel_path
        ext = p.suffix.lower()
        lang = _LANG_MAP.get(ext)
        if not lang:
            continue

        try:
            parser = get_parser(lang)
            code = p.read_bytes()
            tree = parser.parse(code)
            _walk_tree_sitter(tree.root_node, rel_path, symbols)
        except Exception:
            continue  # Skip files that fail to parse

    return symbols


def _walk_tree_sitter(node, file_path: str, symbols: list) -> None:
    """Walk tree-sitter AST and extract function/class declarations."""
    # Node types that indicate function/class declarations across languages
    fn_types = {"function_definition", "function_declaration", "method_definition", "method_declaration"}
    cls_types = {"class_definition", "class_declaration", "struct_item", "impl_item"}

    if node.type in fn_types:
        name = _get_name_child(node)
        if name:
            symbols.append(f"{file_path}: fn {name}()")
    elif node.type in cls_types:
        name = _get_name_child(node)
        if name:
            symbols.append(f"{file_path}: class {name}")

    for child in node.children:
        _walk_tree_sitter(child, file_path, symbols)


def _get_name_child(node) -> str | None:
    """Get the name identifier from a declaration node."""
    for child in node.children:
        if child.type in ("identifier", "name", "type_identifier"):
            return child.text.decode("utf-8")
    return None


def _extract_symbols_basic(root: Path, files: list[str]) -> list[str]:
    """Fallback: extract symbols using simple regex (no tree-sitter)."""
    import re
    symbols = []
    patterns = [
        (re.compile(r"^\s*(?:def|function|fn|func)\s+(\w+)"), "fn"),
        (re.compile(r"^\s*(?:class|struct|impl|interface|enum)\s+(\w+)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("), "fn"),
    ]

    for rel_path in files:
        p = root / rel_path
        if p.suffix.lower() not in {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java", ".rb", ".php"}:
            continue
        try:
            for line in p.read_text(errors="ignore").splitlines()[:200]:  # First 200 lines
                for pattern, kind in patterns:
                    m = pattern.match(line)
                    if m:
                        symbols.append(f"{rel_path}: {kind} {m.group(1)}{'()' if kind == 'fn' else ''}")
        except Exception:
            continue

    return symbols
