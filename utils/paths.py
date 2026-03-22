"""
Path management utilities for Easycode.

Provides centralized path handling for workspaces, worktrees, logs, and state.
"""

from pathlib import Path
from typing import Optional


class Paths:
    """Centralized path management for Easycode."""

    def __init__(self, workspace_path: Path, worktree_dir: Path, log_dir: Path, state_dir: Path):
        """
        Initialize paths.

        Args:
            workspace_path: Path to the main git repository.
            worktree_dir: Directory for worktrees.
            log_dir: Directory for logs.
            state_dir: Directory for state files.
        """
        self.workspace = workspace_path.resolve()
        self.worktree_dir = worktree_dir.resolve()
        self.log_dir = log_dir.resolve()
        self.state_dir = state_dir.resolve()

    @classmethod
    def from_workspace(cls, workspace_path: Path, base_dir: str = ".easycode") -> "Paths":
        """
        Create Paths from a workspace path with default subdirectories.

        Args:
            workspace_path: Path to the main git repository.
            base_dir: Base directory name for easycode files.

        Returns:
            Paths instance.
        """
        workspace = workspace_path.resolve()
        base = workspace / base_dir
        return cls(
            workspace_path=workspace,
            worktree_dir=base / "worktrees",
            log_dir=base / "logs",
            state_dir=base / "state",
        )

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        self.worktree_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def worktree_path(self, worktree_id: str) -> Path:
        """Get the path for a specific worktree."""
        return self.worktree_dir / worktree_id

    def log_file(self, name: str) -> Path:
        """Get the path for a log file."""
        return self.log_dir / name

    def state_file(self, name: str) -> Path:
        """Get the path for a state file."""
        return self.state_dir / name

    def git_dir(self) -> Path:
        """Get the .git directory path."""
        return self.workspace / ".git"

    def gitignore_path(self) -> Path:
        """Get the .gitignore path."""
        return self.workspace / ".gitignore"

    def config_path(self) -> Path:
        """Get the easycode config path."""
        return self.workspace / "config.toml"

    def is_inside_workspace(self, path: Path) -> bool:
        """Check if a path is inside the workspace."""
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False

    def relative_path(self, path: Path) -> Path:
        """Get path relative to workspace."""
        return path.resolve().relative_to(self.workspace)

    def __repr__(self) -> str:
        return (
            f"Paths(workspace={self.workspace}, "
            f"worktree_dir={self.worktree_dir}, "
            f"log_dir={self.log_dir}, "
            f"state_dir={self.state_dir})"
        )