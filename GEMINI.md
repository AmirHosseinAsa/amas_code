# Amas Code - Project Context

Amas Code is a terminal-based AI coding agent designed to provide Claude Code-level capabilities using any LLM provider (Gemini, Claude, GPT, Ollama, etc.) via LiteLLM. It is built to be lightweight, readable, and extensible, with a target of ~760 lines of code.

## Project Overview

- **Purpose:** An autonomous agentic loop that can read, write, edit files, run shell commands, research via Google, and control a browser.
- **Core Principle:** "The best code is the code you didn't write." Uses robust packages for complex tasks.
- **Hardware Target:** Runs efficiently on low-end hardware like a Raspberry Pi (1GB RAM).
- **Architecture:**
    - `amas_code/amas.py`: CLI entry point using `click`.
    - `amas_code/agent.py`: The main agent loop (Prompt -> LLM -> Tool Call -> Result -> Repeat).
    - `amas_code/providers.py`: Wrapper for `litellm` for multi-model support and streaming.
    - `amas_code/tools.py`: Implementation of file, shell, and search tools.
    - `amas_code/web.py`: Browser control (Playwright), web search, and URL fetching.
    - `amas_code/checkpoint.py`: Git-based versioning for automatic undo/redo of AI edits.
    - `amas_code/ui.py`: Rich-based terminal UI with syntax highlighting and diff previews.
    - `amas_code/skills.py`: Project initialization (`/init`), rules, and skills loader.
    - `amas_code/config.py`: YAML configuration management.

## Building and Running

### Installation
```bash
# Development mode
pip install -e .

# With optional dependencies
pip install -e ".[all]"  # Includes browser (Playwright) and parsing (tree-sitter)
```

### Key Commands
- `amas`: Start an interactive session.
- `amas "task"`: Execute a one-shot task.
- `amas init`: Scan the project structure and extract symbols for better context.
- `amas config`: Interactive configuration wizard for models and API keys.

### In-Session Slash Commands
- `/help`: Show all commands.
- `/undo` / `/redo`: Revert or re-apply changes using git checkpoints.
- `/yolo`: Toggle auto-accept mode (skips confirmation for file edits).
- `/compact`: Summarize conversation history to save tokens.
- `/attach <path>`: Manually add a file's content to the conversation.
- `@filename`: Inline fuzzy file picker to attach files.

## Development Conventions

- **Minimalist Codebase:** Keep the total line count under 900. Prefer libraries over custom implementations.
- **Lazy Loading:** Heavy dependencies like `playwright` and `tree-sitter` must be imported inside the functions where they are used to keep startup fast and memory low.
- **Safety First:** All file-modifying tools (`edit_file`, `write_file`, etc.) **MUST** show a diff and ask for user confirmation (`ui.confirm`) unless YOLO mode is active.
- **Checkpoints:** Every successful file modification **MUST** trigger a git checkpoint (`checkpoint.save`).
- **Sync Only:** The project avoids `async/await` to keep the logic simple and memory usage predictable.
- **Tool Patterns:** Every tool consists of a schema dict, a handler function (returning `str`), and a registration in the `HANDLERS` dict.
- **Styling:** Follow PEP 8 with 3.10+ features (`match/case`, pipe types). Use `pathlib` for file ops. No `print()` calls—use `ui.py` functions.

## Project Context Files
- `README.md`: High-level overview and features.
- `PLAN.md`: Development roadmap and phases.
- `Rules.md`: Strict technical and architectural constraints for the AI.
- `CLAUDE.md`: Guidance for AI agents working on this project.
- `.amas/rules.md`: Project-specific instructions for the Amas agent.
