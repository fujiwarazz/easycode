"""
Diff collection utilities for Easycode.

Provides functions to collect and analyze git diffs from agent work.
"""

import difflib
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils.logging import get_logger
from utils.proc import AsyncSubprocess

logger = get_logger("gitops.diff")


@dataclass
class FileDiff:
    """Represents a diff for a single file."""

    path: str
    old_path: Optional[str] = None  # For renames
    status: str = "modified"  # added, modified, deleted, renamed
    additions: int = 0
    deletions: int = 0
    diff: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
        }


@dataclass
class DiffResult:
    """Result of diff collection."""

    files: list[FileDiff] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0
    raw_diff: str = ""

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_dict(self) -> dict:
        return {
            "files": [f.to_dict() for f in self.files],
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "file_count": self.file_count,
        }


class DiffCollector:
    """
    Collects and analyzes git diffs from worktrees.
    """

    def __init__(self, repo_path: Path):
        """
        Initialize diff collector.

        Args:
            repo_path: Path to the git repository or worktree.
        """
        self.repo_path = repo_path

    async def _run_git(self, args: list[str]) -> tuple[int, str, str]:
        """Run a git command."""
        proc = AsyncSubprocess(["git"] + args, cwd=self.repo_path)

        async for _ in proc.stream():
            pass

        result = await proc.wait()
        return result.return_code, result.stdout, result.stderr

    async def get_changed_files(self, base_ref: str = "HEAD") -> list[str]:
        """
        Get list of changed files (tracked files with modifications).

        Args:
            base_ref: Base reference to compare against.

        Returns:
            List of changed file paths.
        """
        _, stdout, _ = await self._run_git(
            ["diff", "--name-only", base_ref]
        )

        return [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    async def get_staged_files(self) -> list[str]:
        """Get list of staged files."""
        _, stdout, _ = await self._run_git(
            ["diff", "--name-only", "--cached"]
        )

        return [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    async def get_untracked_files(self) -> list[str]:
        """Get list of untracked files."""
        _, stdout, _ = await self._run_git(
            ["ls-files", "--others", "--exclude-standard"]
        )

        return [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    async def collect_diff(self, base_ref: str = "HEAD", include_untracked: bool = True) -> DiffResult:
        """
        Collect comprehensive diff information.

        Args:
            base_ref: Base reference to compare against.
            include_untracked: Whether to include untracked files.

        Returns:
            DiffResult with all changes.
        """
        result = DiffResult()
        all_diffs = []  # Collect all diff output

        # 1. Get tracked file changes (modified/deleted/renamed)
        logger.debug(f"Getting diff for tracked files against {base_ref}")

        _, stats_stdout, _ = await self._run_git(
            ["diff", "--numstat", base_ref]
        )

        # Parse stats
        file_stats = {}
        for line in stats_stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) >= 3:
                additions = int(parts[0]) if parts[0] != "-" else 0
                deletions = int(parts[1]) if parts[1] != "-" else 0
                path = parts[2]

                file_stats[path] = {"additions": additions, "deletions": deletions}

        # Get full diff for tracked files
        _, diff_stdout, _ = await self._run_git(
            ["diff", base_ref]
        )

        if diff_stdout:
            all_diffs.append(diff_stdout)

        # Parse diff into per-file diffs
        current_file = None
        current_diff_lines = []

        for line in diff_stdout.split("\n"):
            if line.startswith("diff --git "):
                # Save previous file's diff
                if current_file and current_file in file_stats:
                    stats = file_stats[current_file]
                    result.files.append(FileDiff(
                        path=current_file,
                        additions=stats["additions"],
                        deletions=stats["deletions"],
                        diff="\n".join(current_diff_lines),
                    ))

                # Start new file
                parts = line.split(" ")
                if len(parts) >= 3:
                    # Extract filename from a/path or b/path
                    current_file = parts[2].split("/", 1)[-1] if "/" in parts[2] else parts[2]
                else:
                    current_file = None

                current_diff_lines = [line]
            elif current_file:
                current_diff_lines.append(line)

        # Don't forget last file
        if current_file and current_file in file_stats:
            stats = file_stats[current_file]
            result.files.append(FileDiff(
                path=current_file,
                additions=stats["additions"],
                deletions=stats["deletions"],
                diff="\n".join(current_diff_lines),
            ))

        # 2. Handle untracked files (new files not yet in git)
        if include_untracked:
            untracked = await self.get_untracked_files()
            logger.debug(f"Found {len(untracked)} untracked files: {untracked}")

            for path in untracked:
                file_path = self.repo_path / path
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        # Count non-empty lines as additions
                        additions = len([l for l in lines if l.strip()])

                        # Create diff for new file (standard unified diff format)
                        diff_lines = [
                            f"diff --git a/{path} b/{path}",
                            "new file mode 100644",
                            "index 0000000..1234567",
                            "--- /dev/null",
                            f"+++ b/{path}",
                        ]
                        for line in lines:
                            diff_lines.append(f"+{line}")

                        diff_content = "\n".join(diff_lines)
                        all_diffs.append(diff_content)

                        result.files.append(FileDiff(
                            path=path,
                            status="added",
                            additions=additions,
                            deletions=0,
                            diff=diff_content,
                        ))
                        logger.debug(f"Added untracked file to diff: {path} ({additions} lines)")

                    except Exception as e:
                        logger.warning(f"Failed to read untracked file {path}: {e}\n{traceback.format_exc()}")

        # Combine all diffs
        result.raw_diff = "\n".join(all_diffs) if all_diffs else ""

        # Calculate totals (don't double count)
        result.total_additions = sum(f.additions for f in result.files)
        result.total_deletions = sum(f.deletions for f in result.files)

        logger.info(f"Diff collected: {result.file_count} files, +{result.total_additions}/-{result.total_deletions} lines")

        return result

    async def get_diff_summary(self, base_ref: str = "HEAD") -> dict:
        """
        Get a summary of changes.

        Returns:
            Dict with summary statistics.
        """
        diff_result = await self.collect_diff(base_ref)

        return {
            "file_count": diff_result.file_count,
            "total_additions": diff_result.total_additions,
            "total_deletions": diff_result.total_deletions,
            "files": [f.path for f in diff_result.files],
        }

    async def has_changes(self, base_ref: str = "HEAD") -> bool:
        """Check if there are any changes."""
        changed = await self.get_changed_files(base_ref)
        if changed:
            return True

        untracked = await self.get_untracked_files()
        return len(untracked) > 0

    def format_diff_for_display(self, diff: str, max_lines: int = 100) -> str:
        """
        Format diff for display in UI.

        Args:
            diff: Raw diff string.
            max_lines: Maximum lines to show.

        Returns:
            Formatted diff string.
        """
        lines = diff.split("\n")

        if len(lines) <= max_lines:
            return diff

        # Truncate and add ellipsis
        half = max_lines // 2
        return "\n".join(
            lines[:half] + ["\n... (truncated) ...\n"] + lines[-half:]
        )