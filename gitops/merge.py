"""
Merge operations for Easycode.

Provides functions to merge agent work from worktrees back to the main branch.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utils.logging import get_logger
from utils.proc import AsyncSubprocess

logger = get_logger("gitops.merge")


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    source_branch: str
    target_branch: str
    commit_hash: Optional[str] = None
    message: str = ""
    conflicts: list[str] = None

    def __post_init__(self):
        if self.conflicts is None:
            self.conflicts = []


class MergeError(Exception):
    """Merge operation error."""

    def __init__(self, message: str, conflicts: list[str] = None):
        super().__init__(message)
        self.conflicts = conflicts or []


class MergeManager:
    """
    Manages merge operations for task results.
    """

    def __init__(self, workspace_path: Path):
        """
        Initialize merge manager.

        Args:
            workspace_path: Path to the main git repository.
        """
        self.workspace = workspace_path

    async def _run_git(self, args: list[str], check: bool = True) -> tuple[int, str, str]:
        """Run a git command."""
        proc = AsyncSubprocess(["git"] + args, cwd=self.workspace)

        async for _ in proc.stream():
            pass

        result = await proc.wait()

        if check and not result.success:
            raise MergeError(f"Git command failed: {result.stderr}")

        return result.return_code, result.stdout, result.stderr

    async def get_current_branch(self) -> str:
        """Get current branch name."""
        _, stdout, _ = await self._run_git(["branch", "--show-current"])
        return stdout.strip()

    async def checkout_branch(self, branch: str) -> bool:
        """Checkout a branch."""
        try:
            await self._run_git(["checkout", branch])
            return True
        except MergeError:
            return False

    async def merge_branch(
        self,
        source_branch: str,
        target_branch: Optional[str] = None,
        message: Optional[str] = None,
        no_ff: bool = True,
    ) -> MergeResult:
        """
        Merge a source branch into target branch.

        Args:
            source_branch: Branch to merge from.
            target_branch: Branch to merge into (defaults to current).
            message: Custom merge commit message.
            no_ff: Create a merge commit even if fast-forward is possible.

        Returns:
            MergeResult indicating success or failure.
        """
        # Checkout target branch if specified
        if target_branch:
            logger.info(f"Checking out {target_branch}")
            await self.checkout_branch(target_branch)

        current_branch = await self.get_current_branch()
        logger.info(f"Merging {source_branch} into {current_branch}")

        # Build merge command
        merge_args = ["merge"]
        if no_ff:
            merge_args.append("--no-ff")
        if message:
            merge_args.extend(["-m", message])
        merge_args.append(source_branch)

        try:
            _, stdout, stderr = await self._run_git(merge_args, check=False)

            # Check for conflicts
            if "CONFLICT" in stderr or "CONFLICT" in stdout:
                # Get list of conflicted files
                _, conflict_stdout, _ = await self._run_git(
                    ["diff", "--name-only", "--diff-filter=U"], check=False
                )
                conflicts = [f.strip() for f in conflict_stdout.strip().split("\n") if f.strip()]

                # Abort the merge
                await self._run_git(["merge", "--abort"], check=False)

                return MergeResult(
                    success=False,
                    source_branch=source_branch,
                    target_branch=current_branch,
                    message="Merge conflicts detected",
                    conflicts=conflicts,
                )

            # Get the merge commit hash
            _, commit_hash, _ = await self._run_git(["rev-parse", "HEAD"])

            logger.info(f"Merge successful: {commit_hash.strip()[:8]}")

            return MergeResult(
                success=True,
                source_branch=source_branch,
                target_branch=current_branch,
                commit_hash=commit_hash.strip(),
                message=f"Successfully merged {source_branch}",
            )

        except Exception as e:
            logger.error(f"Merge failed: {e}")
            return MergeResult(
                success=False,
                source_branch=source_branch,
                target_branch=current_branch,
                message=str(e),
            )

    async def squash_merge(
        self,
        source_branch: str,
        target_branch: Optional[str] = None,
        message: Optional[str] = None,
    ) -> MergeResult:
        """
        Perform a squash merge.

        Args:
            source_branch: Branch to merge from.
            target_branch: Branch to merge into (defaults to current).
            message: Commit message for the squashed changes.

        Returns:
            MergeResult indicating success or failure.
        """
        if target_branch:
            await self.checkout_branch(target_branch)

        current_branch = await self.get_current_branch()

        # Squash merge
        await self._run_git(["merge", "--squash", source_branch])

        # Get default message from branch commits
        if not message:
            _, log_stdout, _ = await self._run_git(
                ["log", "--pretty=format:%s", f"HEAD..{source_branch}"]
            )
            messages = log_stdout.strip().split("\n")
            message = f"Squash merge {source_branch}\n\n" + "\n".join(f"- {m}" for m in messages if m)

        # Commit the squashed changes
        await self._run_git(["commit", "-m", message])

        _, commit_hash, _ = await self._run_git(["rev-parse", "HEAD"])

        return MergeResult(
            success=True,
            source_branch=source_branch,
            target_branch=current_branch,
            commit_hash=commit_hash.strip(),
            message=message,
        )

    async def delete_branch(self, branch: str, force: bool = False) -> bool:
        """Delete a branch."""
        try:
            args = ["branch", "-D" if force else "-d", branch]
            await self._run_git(args, check=False)
            return True
        except Exception:
            return False

    async def branch_exists(self, branch: str) -> bool:
        """Check if a branch exists."""
        _, stdout, _ = await self._run_git(
            ["branch", "--list", branch], check=False
        )
        return branch in stdout

    async def get_branch_commits(self, branch: str, limit: int = 10) -> list[dict]:
        """Get recent commits on a branch."""
        _, stdout, _ = await self._run_git(
            ["log", "--pretty=format:%H|%s|%an|%ar", "-n", str(limit), branch]
        )

        commits = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "subject": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })

        return commits