"""
Async subprocess utilities for Easycode.

Provides async wrappers for running external processes with streaming output.
"""

import asyncio
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union


@dataclass
class ProcessResult:
    """Result of a process execution."""

    return_code: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: Optional[Path] = None
    duration: float = 0.0
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Check if process succeeded."""
        return self.return_code == 0


class AsyncSubprocess:
    """
    Async subprocess runner with streaming output support.

    Usage:
        proc = AsyncSubprocess(["echo", "hello"])
        async for line in proc.stream():
            print(line)
        result = await proc.wait()
    """

    def __init__(
        self,
        command: list[str],
        cwd: Optional[Union[Path, str]] = None,
        env: Optional[dict[str, str]] = None,
        timeout: float = 0,  # 0 = no timeout
        merge_stderr: bool = False,
    ):
        """
        Initialize subprocess.

        Args:
            command: Command and arguments to run.
            cwd: Working directory.
            env: Environment variables (merged with current env).
            timeout: Timeout in seconds (0 = no timeout).
            merge_stderr: Whether to merge stderr into stdout stream.
        """
        self.command = command
        self.cwd = Path(cwd) if cwd else None
        self.timeout = timeout
        self.merge_stderr = merge_stderr

        # Merge environment
        self.env = os.environ.copy()
        if env:
            self.env.update(env)

        # Process state
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stdout_buffer: list[str] = []
        self._stderr_buffer: list[str] = []
        self._start_time: float = 0.0
        self._timed_out: bool = False

    async def start(self) -> None:
        """Start the subprocess."""
        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.STDOUT
            if self.merge_stderr
            else asyncio.subprocess.PIPE,
            "env": self.env,
        }

        if self.cwd:
            kwargs["cwd"] = str(self.cwd)

        self._process = await asyncio.create_subprocess_exec(*self.command, **kwargs)
        self._start_time = asyncio.get_event_loop().time()

    async def stream(self) -> AsyncIterator[str]:
        """
        Stream output lines from the process.

        Yields:
            Lines of output (stdout or merged stdout+stderr).
        """
        if not self._process:
            await self.start()

        assert self._process is not None
        assert self._process.stdout is not None

        try:
            while True:
                # Check timeout
                if self.timeout > 0:
                    elapsed = asyncio.get_event_loop().time() - self._start_time
                    if elapsed > self.timeout:
                        self._timed_out = True
                        self._process.terminate()
                        break

                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                self._stdout_buffer.append(decoded)
                yield decoded

        except asyncio.CancelledError:
            self._process.terminate()
            raise

    async def stream_both(self) -> AsyncIterator[tuple[str, bool]]:
        """
        Stream both stdout and stderr with distinction.

        Y:
            Tuple of (line, is_stderr).
        """
        if not self._process:
            await self.start()

        assert self._process is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None

        stdout_queue: asyncio.Queue[Optional[tuple[str, bool]]] = asyncio.Queue()
        stderr_queue: asyncio.Queue[Optional[tuple[str, bool]]] = asyncio.Queue()

        async def read_stdout():
            assert self._process is not None and self._process.stdout is not None
            try:
                async for line in self._process.stdout:
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    self._stdout_buffer.append(decoded)
                    await stdout_queue.put((decoded, False))
            finally:
                await stdout_queue.put(None)

        async def read_stderr():
            assert self._process is not None and self._process.stderr is not None
            try:
                async for line in self._process.stderr:
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    self._stderr_buffer.append(decoded)
                    await stderr_queue.put((decoded, True))
            finally:
                await stderr_queue.put(None)

        # Start readers
        asyncio.create_task(read_stdout())
        asyncio.create_task(read_stderr())

        stdout_done = False
        stderr_done = False

        while not (stdout_done and stderr_done):
            # Check timeout
            if self.timeout > 0:
                elapsed = asyncio.get_event_loop().time() - self._start_time
                if elapsed > self.timeout:
                    self._timed_out = True
                    assert self._process is not None
                    self._process.terminate()
                    break

            # Try to get from either queue
            try:
                item = await asyncio.wait_for(stdout_queue.get(), timeout=0.1)
                if item is None:
                    stdout_done = True
                else:
                    yield item
            except asyncio.TimeoutError:
                pass

            try:
                item = await asyncio.wait_for(stderr_queue.get(), timeout=0.1)
                if item is None:
                    stderr_done = True
                else:
                    yield item
            except asyncio.TimeoutError:
                pass

    async def wait(self) -> ProcessResult:
        """
        Wait for process to complete and return result.

        Returns:
            ProcessResult with exit code and output.
        """
        if not self._process:
            await self.start()

        assert self._process is not None

        # Wait for process to complete
        try:
            if self.timeout > 0:
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    self._timed_out = True
                    self._process.terminate()
                    await self._process.wait()
            else:
                await self._process.wait()
        except asyncio.CancelledError:
            self._process.terminate()
            await self._process.wait()
            raise

        duration = asyncio.get_event_loop().time() - self._start_time

        return ProcessResult(
            return_code=self._process.returncode or -1,
            stdout="\n".join(self._stdout_buffer),
            stderr="\n".join(self._stderr_buffer),
            command=self.command,
            cwd=self.cwd,
            duration=duration,
            timed_out=self._timed_out,
        )

    def terminate(self) -> None:
        """Terminate the process."""
        if self._process and self._process.returncode is None:
            self._process.terminate()

    def kill(self) -> None:
        """Kill the process forcefully."""
        if self._process and self._process.returncode is None:
            self._process.kill()


async def run_command(
    command: list[str],
    cwd: Optional[Union[Path, str]] = None,
    env: Optional[dict[str, str]] = None,
    timeout: float = 0,
    check: bool = False,
) -> ProcessResult:
    """
    Run a command and return the result.

    Args:
        command: Command and arguments.
        cwd: Working directory.
        env: Environment variables.
        timeout: Timeout in seconds.
        check: Raise exception on non-zero exit.

    Returns:
        ProcessResult with exit code and output.
    """
    proc = AsyncSubprocess(command, cwd=cwd, env=env, timeout=timeout)

    # Consume all output
    async for _ in proc.stream():
        pass

    result = await proc.wait()

    if check and not result.success:
        raise RuntimeError(
            f"Command failed with code {result.return_code}: {' '.join(command)}\n"
            f"stderr: {result.stderr}"
        )

    return result


async def run_command_streaming(
    command: list[str],
    cwd: Optional[Union[Path, str]] = None,
    env: Optional[dict[str, str]] = None,
    timeout: float = 0,
    output_callback: Optional[callable] = None,
) -> ProcessResult:
    """
    Run a command with streaming output.

    Args:
        command: Command and arguments.
        cwd: Working directory.
        env: Environment variables.
        timeout: Timeout in seconds.
        output_callback: Async callback for each output line.

    Returns:
        ProcessResult with exit code and output.
    """
    proc = AsyncSubprocess(command, cwd=cwd, env=env, timeout=timeout)

    async for line in proc.stream():
        if output_callback:
            await output_callback(line)

    return await proc.wait()