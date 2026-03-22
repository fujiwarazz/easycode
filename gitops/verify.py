"""
Verification commands for Easycode.

Runs verification commands after merging task results.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils.logging import get_logger
from utils.proc import AsyncSubprocess, ProcessResult

logger = get_logger("gitops.verify")


@dataclass
class VerifyResult:
    """Result of a verification run."""

    success: bool
    command: str
    output: str = ""
    error: str = ""
    duration: float = 0.0
    exit_code: int = 0


@dataclass
class VerifyReport:
    """Report from running all verification commands."""

    success: bool
    results: list[VerifyResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.success)


class VerifyRunner:
    """
    Runs verification commands after task completion.
    """

    def __init__(self, workspace_path: Path, commands: list[str] = None):
        """
        Initialize verify runner.

        Args:
            workspace_path: Path to run commands in.
            commands: List of commands to run.
        """
        self.workspace = workspace_path
        self.commands = commands or []

    async def run_command(
        self,
        command: str,
        timeout: float = 300,
        env: dict = None,
    ) -> VerifyResult:
        """
        Run a single verification command.

        Args:
            command: Command to run (as string).
            timeout: Timeout in seconds.
            env: Additional environment variables.

        Returns:
            VerifyResult with outcome.
        """
        logger.info(f"Running verification: {command}")

        # Parse command string into list
        import shlex
        cmd_args = shlex.split(command)

        proc = AsyncSubprocess(
            cmd_args,
            cwd=self.workspace,
            env=env,
            timeout=timeout,
            merge_stderr=False,
        )

        output_lines = []
        error_lines = []

        try:
            async for line, is_stderr in proc.stream_both():
                if is_stderr:
                    error_lines.append(line)
                    logger.debug(f"[stderr] {line}")
                else:
                    output_lines.append(line)
                    logger.debug(f"[stdout] {line}")
        except Exception as e:
            logger.error(f"Verification command failed: {e}")
            return VerifyResult(
                success=False,
                command=command,
                error=str(e),
            )

        result = await proc.wait()

        verify_result = VerifyResult(
            success=result.success,
            command=command,
            output="\n".join(output_lines),
            error="\n".join(error_lines),
            duration=result.duration,
            exit_code=result.return_code,
        )

        if verify_result.success:
            logger.info(f"Verification passed: {command}")
        else:
            logger.warning(f"Verification failed: {command} (exit code: {result.return_code})")

        return verify_result

    async def run_all(
        self,
        commands: list[str] = None,
        timeout: float = 300,
        stop_on_failure: bool = True,
        env: dict = None,
    ) -> VerifyReport:
        """
        Run all verification commands.

        Args:
            commands: Commands to run (defaults to configured commands).
            timeout: Timeout per command in seconds.
            stop_on_failure: Stop running if a command fails.
            env: Additional environment variables.

        Returns:
            VerifyReport with all results.
        """
        commands = commands or self.commands

        if not commands:
            logger.info("No verification commands configured")
            return VerifyReport(success=True, results=[])

        logger.info(f"Running {len(commands)} verification command(s)")

        report = VerifyReport(success=True, results=[])

        for command in commands:
            result = await self.run_command(command, timeout=timeout, env=env)
            report.results.append(result)

            if not result.success:
                report.success = False
                if stop_on_failure:
                    logger.warning(f"Stopping verification due to failure: {command}")
                    break

        if report.success:
            logger.info(f"All verifications passed ({report.passed_count}/{len(commands)})")
        else:
            logger.warning(f"Verifications failed: {report.failed_count}/{len(commands)}")

        return report

    async def run_tests(
        self,
        test_command: str = "pytest",
        timeout: float = 600,
    ) -> VerifyResult:
        """
        Run tests as verification.

        Args:
            test_command: Test command to run.
            timeout: Timeout in seconds.

        Returns:
            VerifyResult with test outcome.
        """
        return await self.run_command(test_command, timeout=timeout)

    async def run_lint(
        self,
        lint_command: str = "ruff check .",
        timeout: float = 60,
    ) -> VerifyResult:
        """
        Run linting as verification.

        Args:
            lint_command: Lint command to run.
            timeout: Timeout in seconds.

        Returns:
            VerifyResult with lint outcome.
        """
        return await self.run_command(lint_command, timeout=timeout)

    async def run_type_check(
        self,
        type_command: str = "mypy .",
        timeout: float = 120,
    ) -> VerifyResult:
        """
        Run type checking as verification.

        Args:
            type_command: Type check command to run.
            timeout: Timeout in seconds.

        Returns:
            VerifyResult with type check outcome.
        """
        return await self.run_command(type_command, timeout=timeout)