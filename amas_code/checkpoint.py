"""Git-based checkpoints — save, undo, redo, list, restore."""
from pathlib import Path

from amas_code import ui

# Checkpoint commit message prefix
_PREFIX = "[amas] "


def _repo():
    """Get or init a git repo. Lazy import to keep startup fast."""
    from git import Repo, InvalidGitRepositoryError
    try:
        return Repo(".", search_parent_directories=True)
    except InvalidGitRepositoryError:
        ui.info("Initializing git repo for checkpoints...")
        repo = Repo.init(".")
        # Initial commit — HEAD doesn't exist yet, so don't call index.diff("HEAD")
        if repo.untracked_files:
            repo.index.add(repo.untracked_files)
            repo.index.commit(f"{_PREFIX}Initial checkpoint")
            ui.success("Created initial checkpoint.")
        return repo


def _tracked_files(repo) -> list[str]:
    """Get list of tracked files."""
    try:
        return [item.path for item in repo.head.commit.tree.traverse()]
    except ValueError:
        return []


def save(message: str = "checkpoint") -> bool:
    """Create a checkpoint (git commit) with current changes."""
    try:
        repo = _repo()

        # Stage all changes
        repo.git.add(A=True)

        # Check if there are changes to commit
        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return False  # Nothing to checkpoint

        repo.index.commit(f"{_PREFIX}{message}")
        return True
    except Exception as e:
        ui.error(f"Checkpoint failed: {e}")
        return False


def undo() -> str:
    """Undo to the previous Amas checkpoint."""
    try:
        repo = _repo()
        commits = _amas_commits(repo, limit=2)

        if len(commits) < 2:
            return "Nothing to undo — no previous checkpoints."

        # Reset to previous checkpoint
        target = commits[1]
        repo.head.reset(target, index=True, working_tree=True)
        return f"Undone to: {target.message.replace(_PREFIX, '').strip()}"
    except Exception as e:
        return f"Undo failed: {e}"


def list_checkpoints(limit: int = 10) -> list[dict]:
    """List recent Amas checkpoints."""
    try:
        repo = _repo()
        commits = _amas_commits(repo, limit=limit)
        return [
            {
                "hash": c.hexsha[:8],
                "message": c.message.replace(_PREFIX, "").strip(),
                "time": c.committed_datetime.strftime("%H:%M:%S"),
                "files": len(c.stats.files),
            }
            for c in commits
        ]
    except Exception:
        return []


def restore(hash_prefix: str) -> str:
    """Restore to a specific checkpoint by hash prefix."""
    try:
        repo = _repo()

        # Find matching commit
        for commit in repo.iter_commits():
            if commit.hexsha.startswith(hash_prefix) and commit.message.startswith(_PREFIX):
                # Save current state first
                save("before restore")

                repo.head.reset(commit, index=True, working_tree=True)
                msg = commit.message.replace(_PREFIX, "").strip()
                return f"Restored to: {msg} ({commit.hexsha[:8]})"

        return f"No checkpoint found matching '{hash_prefix}'"
    except Exception as e:
        return f"Restore failed: {e}"


def get_diff_between(start_hash: str, end_hash: str = "HEAD") -> str:
    """Get the diff between two specific commits."""
    try:
        repo = _repo()
        return repo.git.diff(start_hash, end_hash)
    except Exception as e:
        return f"Could not get diff: {e}"


def get_diff(commit_hash: str) -> str:
    """Get the diff for a specific commit compared to its parent."""
    try:
        repo = _repo()
        commit = repo.commit(commit_hash)
        if not commit.parents:
            return "Initial checkpoint (no parent)"
        return repo.git.diff(commit.parents[0].hexsha, commit.hexsha)
    except Exception as e:
        return f"Could not get diff: {e}"


def _amas_commits(repo, limit: int = 20) -> list:
    """Get recent commits made by Amas."""
    result = []
    try:
        for commit in repo.iter_commits(max_count=100):
            if commit.message.startswith(_PREFIX):
                result.append(commit)
                if len(result) >= limit:
                    break
    except Exception:
        pass
    return result
