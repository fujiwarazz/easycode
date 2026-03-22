"""
Git worktree management for Easycode.

Provides functions to create, manage, and clean up git worktrees
for isolated agent task execution.
"""

import asyncio
import random
import string
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.logging import get_logger
from utils.proc import AsyncSubprocess, run_command

logger = get_logger("gitops.worktree")


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    path: Path
    branch: str
    commit: str
    is_main: bool = False

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "branch": self.branch,
            "commit": self.commit,
            "is_main": self.is_main,
        }


class GitError(Exception):
    """Git operation error."""

    pass


class WorktreeManager:
    """
    Manages git worktrees for isolated task execution.

    Each worktree is created from the current branch and provides
    an isolated working directory for an agent.
    """

    def __init__(self, workspace_path: Path, worktree_dir: Path):
        """
        Initialize worktree manager.

        Args:
            workspace_path: Path to the main git repository.
            worktree_dir: Directory to store worktrees.
        """
        self.workspace = workspace_path.resolve()
        self.worktree_dir = worktree_dir.resolve()
        self._git_path: Optional[Path] = None

    async def _run_git(
        self,
        args: list[str],
        cwd: Optional[Path] = None,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """
        Run a git command.

        Args:
            args: Git command arguments.
            cwd: Working directory (defaults to workspace).
            check: Raise on non-zero exit.

        Returns:
            Tuple of (return_code, stdout, stderr).
        """
        if cwd is None:
            cwd = self.workspace

        proc = AsyncSubprocess(["git"] + args, cwd=cwd)

        stdout_lines = []
        async for line in proc.stream():
            stdout_lines.append(line)

        result = await proc.wait()

        if check and not result.success:
            raise GitError(f"Git command failed: git {' '.join(args)}\n{result.stderr}")

        return result.return_code, result.stdout, result.stderr

    async def is_git_repo(self) -> bool:
        """Check if workspace is a git repository."""
        try:
            await self._run_git(["rev-parse", "--git-dir"], check=False)
            return True
        except Exception:
            return False

    async def get_current_branch(self) -> str:
        """Get the current branch name."""
        returncode, stdout, stderr = await self._run_git(["branch", "--show-current"], check=False)
        branch = stdout.strip()

        # Handle no commits yet (return code 128 or empty output)
        if returncode != 0 or not branch:
            # Try to get HEAD anyway (might work in some cases)
            _, head_stdout, _ = await self._run_git(["rev-parse", "--short", "HEAD"], check=False)
            if head_stdout.strip():
                # We have commits but no branch (detached HEAD)
                # Try to find which branch points to this commit
                commit_hash = head_stdout.strip()
                _, branch_stdout, _ = await self._run_git(
                    ["branch", "--points-at", commit_hash], check=False
                )
                branches = [b.strip().lstrip("* ") for b in branch_stdout.strip().split("\n") if b.strip()]
                if branches:
                    return branches[0]
                # Return main as default
                return "main"
            # Default to 'main' for new repos
            return "main"

        return branch

    async def get_main_branch(self) -> str:
        """Get the main branch name (main or master)."""
        # Try to get default branch from remote
        _, stdout, _ = await self._run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"], check=False
        )

        if stdout.strip():
            # Extract branch name from refs/remotes/origin/HEAD -> origin/main
            parts = stdout.strip().split()
            if len(parts) >= 2:
                return parts[-1].replace("origin/", "")

        # Fallback: check if main or master exists
        _, branches, _ = await self._run_git(["branch", "--list", "main", "master"])
        if "main" in branches:
            return "main"
        if "master" in branches:
            return "master"

        # Default to main
        return "main"

    async def get_commit_hash(self, ref: str = "HEAD") -> str:
        """Get the commit hash for a reference."""
        _, stdout, _ = await self._run_git(["rev-parse", ref])
        return stdout.strip()

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """List all worktrees."""
        _, stdout, _ = await self._run_git(["worktree", "list", "--porcelain"])

        worktrees = []
        current_info: Optional[dict] = None

        for line in stdout.strip().split("\n"):
            if not line:
                if current_info:
                    worktrees.append(WorktreeInfo(**current_info))
                    current_info = None
                continue

            if line.startswith("worktree "):
                current_info = {"path": Path(line[9:]), "branch": "", "commit": "", "is_main": False}
            elif line.startswith("HEAD ") and current_info:
                current_info["commit"] = line[5:]
            elif line.startswith("branch ") and current_info:
                current_info["branch"] = line[7:]

        if current_info:
            worktrees.append(WorktreeInfo(**current_info))

        # Mark the first worktree as main
        if worktrees:
            worktrees[0].is_main = True

        return worktrees

    def _generate_branch_name(self, task_id: str) -> str:
        """Generate a unique branch name for a task."""
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"easycode/{task_id}-{suffix}"

    def _generate_worktree_id(self, task_id: str) -> str:
        """Generate a unique worktree ID."""
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{task_id}-{suffix}"

    async def create_worktree(
        self,
        task_id: str,
        base_branch: Optional[str] = None,
        branch_prefix: str = "easycode",
    ) -> tuple[str, Path]:
        """
        Create a new worktree for a task.

        Args:
            task_id: ID of the task.
            base_branch: Base branch to create from (defaults to current branch).
            branch_prefix: Prefix for the new branch name.

        Returns:
            Tuple of (branch_name, worktree_path).
        """
        # Ensure worktree directory exists
        self.worktree_dir.mkdir(parents=True, exist_ok=True)

        # Get base branch or commit
        if base_branch is None:
            base_branch = await self.get_current_branch()

        # Generate branch and worktree names
        worktree_id = self._generate_worktree_id(task_id)
        branch_name = f"{branch_prefix}/{task_id}-{worktree_id.split('-')[-1]}"
        worktree_path = self.worktree_dir / worktree_id

        logger.info(f"Creating worktree at {worktree_path} on branch {branch_name}")

        # Create the worktree with a new branch
        # Use HEAD as base if base_branch is 'main' but might not exist yet
        try:
            await self._run_git(
                ["worktree", "add", "-b", branch_name, str(worktree_path), base_branch],
                check=True
            )
        except GitError:
            # Fallback: use HEAD directly
            logger.warning(f"Failed to use {base_branch}, falling back to HEAD")
            await self._run_git(
                ["worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
                check=True
            )

        logger.info(f"Worktree created: {worktree_path}")

        return branch_name, worktree_path

    async def remove_worktree(self, worktree_path: Path) -> bool:
        """
        Remove a worktree.

        Args:
            worktree_path: Path to the worktree.

        Returns:
            True if successful.
        """
        if not worktree_path.exists():
            logger.warning(f"Worktree path does not exist: {worktree_path}")
            return False

        logger.info(f"Removing worktree: {worktree_path}")

        try:
            await self._run_git(["worktree", "remove", str(worktree_path)], check=False)

            # Force removal if normal removal failed
            if worktree_path.exists():
                await self._run_git(
                    ["worktree", "remove", "--force", str(worktree_path)], check=False
                )

            return True

        except Exception as e:
            logger.error(f"Failed to remove worktree: {e}")
            return False

    async def prune_worktrees(self) -> int:
        """
        Prune stale worktree references.

        Returns:
            Number of pruned worktrees.
        """
        _, stdout, _ = await self._run_git(["worktree", "prune", "-v"])

        # Count pruned entries
        lines = [l for l in stdout.strip().split("\n") if l.strip()]
        count = len(lines)

        if count > 0:
            logger.info(f"Pruned {count} stale worktree(s)")

        return count

    async def get_worktree_status(self, worktree_path: Path) -> dict:
        """
        Get the status of a worktree.

        Returns:
            Dict with 'clean', 'modified', 'untracked' keys.
        """
        _, stdout, _ = await self._run_git(
            ["status", "--porcelain"], cwd=worktree_path, check=False
        )

        modified = []
        untracked = []

        for line in stdout.strip().split("\n"):
            if not line:
                continue

            status = line[:2]
            path = line[3:]

            if status in ("??", "!!"):
                untracked.append(path)
            else:
                modified.append(path)

        return {
            "clean": len(modified) == 0 and len(untracked) == 0,
            "modified": modified,
            "untracked": untracked,
        }

    async def cleanup_task_worktrees(self, task_id: str) -> int:
        """
        Clean up all worktrees for a specific task.

        Returns:
            Number of worktrees removed.
        """
        worktrees = await self.list_worktrees()
        removed = 0

        for wt in worktrees:
            if wt.is_main:
                continue

            # Check if worktree belongs to this task
            if f"/{task_id}-" in str(wt.path) or f"\\{task_id}-" in str(wt.path):
                await self.remove_worktree(wt.path)
                removed += 1

        return removed

    async def ensure_clean_workspace(self) -> bool:
        """Check if the main workspace has no uncommitted changes."""
        status = await self.get_worktree_status(self.workspace)
        return status["clean"]