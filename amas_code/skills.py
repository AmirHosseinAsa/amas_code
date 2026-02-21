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


def generate_amas_md(path: str = ".", config: dict | None = None) -> str:
    """Generate a concise project identity summary using README + config + LLM."""
    from amas_code import providers
    root = Path(path).resolve()

    # Gather raw context from metadata files
    parts = []
    for name in ("README.md", "readme.md", "README.rst"):
        p = root / name
        if p.exists():
            parts.append(f"README:\n{p.read_text(errors='ignore')[:2000]}")
            break
    for name in ("pyproject.toml", "package.json", "setup.py", "Cargo.toml", "go.mod"):
        p = root / name
        if p.exists():
            parts.append(f"{name}:\n{p.read_text(errors='ignore')[:1500]}")
            break

    if not parts:
        return ""

    try:
        resp = providers.complete(
            messages=[
                {"role": "system", "content": "Write a concise project summary (max 200 words). Include: name, purpose, tech stack, key features. No setup instructions. Output only the summary."},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
            tools=None, config=config or {},
        )
        return resp.get("content", "")
    except Exception as e:
        ui.warning(f"Could not generate project summary: {e}")
        return ""


def generate_project_summary(path: str = ".", config: dict | None = None) -> str:
    """Analyze project structure and generate an intelligent summary for AI context.

    Reads key files to understand their purpose and creates a concise map.
    """
    root = Path(path).resolve()
    ignore = set((config or {}).get("ignore", [
        "node_modules", "__pycache__", ".git", "*.pyc", "dist", "build", ".venv", ".amas",
    ]))

    ui.info("Generating intelligent project summary...")

    # Collect source files
    source_files = []
    _collect_files(root, source_files, ignore, root, max_depth=5)

    if not source_files:
        return "Empty project — no source files found."

    # Prioritize files to analyze (config, main entry points, core modules)
    priority_files = _rank_files(source_files)

    # Analyze top files (limit to 20 to avoid too much processing)
    summaries = []
    for rel_path in priority_files[:20]:
        summary = _analyze_file(root / rel_path, rel_path)
        if summary:
            summaries.append(summary)

    # Build final map
    lines = [f"# Project: {root.name}\n"]
    lines.append(f"**{len(source_files)} files** across the codebase.\n")
    lines.append("## Key Files\n")
    lines.extend(summaries)

    result = "\n".join(lines)

    # Keep under 5000 chars to leave room in context
    if len(result) > 5000:
        result = result[:5000] + "\n\n[Summary truncated for context]"

    return result


def _rank_files(files: list[str]) -> list[str]:
    """Rank files by importance (entry points, core modules first)."""
    priority_indicators = {
        "main": 1000, "index": 900, "app": 800, "cli": 800, "entry": 800,
        "core": 700, "agent": 700, "config": 600, "setup": 600,
        "init": 500, "test": -100,  # Lower priority for tests
    }

    def get_priority(f: str) -> int:
        name = Path(f).stem.lower()
        for key, val in priority_indicators.items():
            if key in name:
                return val
        return 0

    return sorted(files, key=get_priority, reverse=True)


def _analyze_file(path: Path, rel_path: str) -> str:
    """Analyze a single file and return a summary."""
    if not path.exists():
        return ""

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    # Extract module/file docstring
    docstring = _extract_docstring(content, path.suffix)

    # Extract top-level functions/classes
    symbols = _extract_file_symbols(content, path.suffix)

    # Build summary line
    symbol_text = ", ".join(symbols[:5])  # First 5 symbols
    if len(symbols) > 5:
        symbol_text += f", +{len(symbols)-5} more"

    summary = f"**{rel_path}**"
    if docstring:
        summary += f" — {docstring}"
    if symbol_text:
        summary += f"\n  - Exports: {symbol_text}\n"
    else:
        summary += "\n"

    return summary


def _extract_docstring(content: str, ext: str) -> str:
    """Extract the first docstring/comment from a file."""
    import re

    # Python docstring ("""...""" or '''...''')
    if ext.lower() == ".py":
        m = re.search(r'^\s*(?:"""|\'\'\'|#)\s*(.+?)(?:\n|""")', content, re.MULTILINE)
        if m:
            text = m.group(1).strip()
            return text[:100]  # First 100 chars

    # JavaScript/TypeScript docstring (/** ... */ or // comment)
    if ext.lower() in {".js", ".ts", ".jsx", ".tsx"}:
        m = re.search(r'^\s*(?:/\*\*|//)\s*(.+?)(?:\n|\*/)', content, re.MULTILINE)
        if m:
            text = m.group(1).strip()
            return text[:100]

    return ""


def _extract_file_symbols(content: str, ext: str) -> list[str]:
    """Extract function and class names from file content."""
    import re

    symbols = []

    if ext.lower() == ".py":
        # Python: def and class
        for m in re.finditer(r"^(?:def|class)\s+(\w+)", content, re.MULTILINE):
            symbols.append(m.group(1))

    elif ext.lower() in {".js", ".ts", ".jsx", ".tsx"}:
        # JavaScript/TypeScript: function, const, class, export
        for m in re.finditer(r"(?:export\s+)?(?:async\s+)?(?:function|const|let|class)\s+(\w+)", content, re.MULTILINE):
            symbols.append(m.group(1))

    elif ext.lower() in {".go", ".rs"}:
        # Go/Rust: func, type
        for m in re.finditer(r"(?:func|type|fn)\s+(\w+)", content, re.MULTILINE):
            symbols.append(m.group(1))

    return symbols[:8]  # Limit to 8 per file
