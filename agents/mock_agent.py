"""
Mock agent adapter for Easycode.

Simulates an agent for testing and development purposes.
This is CRITICAL for validating the system architecture.
"""

import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from orchestrator.events import EventBus, EventType
from orchestrator.models import AgentConfig, AgentType, RunResult
from agents.base import BaseAgentAdapter, AgentContext
from agents.registry import register_agent_type


# Simulated agent outputs for different task types
SIMULATED_THOUGHTS = [
    "Analyzing the task requirements...",
    "Understanding the context and constraints...",
    "Planning the implementation approach...",
    "Reviewing existing code structure...",
    "Identifying necessary changes...",
    "Implementing the solution...",
    "Verifying the implementation...",
    "Running tests to validate changes...",
    "Refining the implementation...",
    "Finalizing the solution...",
]

SIMULATED_FILE_CONTENTS = {
    "feature": '''"""
Generated feature module.
"""

def new_feature():
    """A new feature implementation."""
    # Implementation here
    return {"status": "implemented"}


class FeatureClass:
    """A feature class."""

    def __init__(self):
        self.initialized = True

    def process(self, data):
        """Process data."""
        return data
''',
    "test": '''"""
Generated test file.
"""
import pytest


def test_basic():
    """Test basic functionality."""
    assert True


def test_feature():
    """Test feature implementation."""
    result = new_feature()
    assert result["status"] == "implemented"
''',
    "config": '''# Generated configuration
[settings]
enabled = true
timeout = 30

[features]
feature_a = true
feature_b = false
''',
    "util": '''"""
Utility functions.
"""
from typing import Any


def helper_function(value: Any) -> str:
    """A helper utility function."""
    return str(value)


def format_output(data: dict) -> str:
    """Format data for output."""
    import json
    return json.dumps(data, indent=2)
''',
}


@register_agent_type(AgentType.MOCK)
class MockAgentAdapter(BaseAgentAdapter):
    """
    Mock agent adapter that simulates agent behavior.

    This adapter is used for:
    - Testing the orchestrator without real CLI tools
    - Development and debugging
    - Demonstrating the system flow
    """

    def __init__(
        self,
        agent_id: str,
        config: AgentConfig,
        event_bus: EventBus,
    ):
        super().__init__(agent_id, config, event_bus)
        self._simulate_delay = config.simulate_delay
        self._min_delay = config.min_delay
        self._max_delay = config.max_delay

    async def _simulate_thinking(self, task_id: str, num_thoughts: int = 5) -> None:
        """Simulate thinking process with output events."""
        thoughts = random.sample(SIMULATED_THOUGHTS, min(num_thoughts, len(SIMULATED_THOUGHTS)))

        for thought in thoughts:
            if self._simulate_delay:
                await asyncio.sleep(random.uniform(self._min_delay, self._max_delay))

            await self.emit_output(
                content=f"[THINKING] {thought}",
                task_id=task_id,
            )

    async def _simulate_file_changes(
        self,
        worktree_path: Path,
        task_prompt: str,
    ) -> list[str]:
        """
        Simulate file modifications in the worktree.

        Creates or modifies files based on the task prompt.
        """
        changed_files = []

        # Determine what kind of files to create based on prompt
        prompt_lower = task_prompt.lower()

        # Create a timestamp-based file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Determine file types based on prompt keywords
        if "test" in prompt_lower:
            files_to_create = [("test_generated.py", "test")]
        elif "config" in prompt_lower:
            files_to_create = [("config_generated.toml", "config")]
        elif "util" in prompt_lower or "helper" in prompt_lower:
            files_to_create = [("utils_generated.py", "util")]
        else:
            # Default: create a feature file and a test
            files_to_create = [
                (f"feature_{timestamp}.py", "feature"),
                (f"test_{timestamp}.py", "test"),
            ]

        for filename, content_type in files_to_create:
            file_path = worktree_path / filename

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content
            content = SIMULATED_FILE_CONTENTS.get(content_type, SIMULATED_FILE_CONTENTS["feature"])

            # Customize content based on task
            customized_content = f'"""\nGenerated for task: {task_prompt[:100]}\n"""\n\n{content}'

            file_path.write_text(customized_content)
            changed_files.append(str(filename))

            await asyncio.sleep(0.1)  # Small delay between files

        return changed_files

    async def _generate_diff(self, worktree_path: Path, changed_files: list[str]) -> str:
        """Generate a simulated diff string."""
        diff_lines = []

        for filename in changed_files:
            file_path = worktree_path / filename
            if file_path.exists():
                diff_lines.append(f"diff --git a/{filename} b/{filename}")
                diff_lines.append("new file mode 100644")
                diff_lines.append("index 0000000..1234567")
                diff_lines.append("--- /dev/null")
                diff_lines.append(f"+++ b/{filename}")

                # Read and format as diff
                lines = file_path.read_text().split("\n")
                for line in lines:
                    diff_lines.append(f"+{line}")

                diff_lines.append("")  # Empty line between files

        return "\n".join(diff_lines)

    async def run_task_stream(
        self,
        task_prompt: str,
        worktree_path: Path,
        context: Optional[AgentContext] = None,
    ) -> AsyncIterator[str]:
        """
        Run a task and stream simulated output.

        Args:
            task_prompt: The task description.
            worktree_path: Path to the worktree.
            context: Task context.

        Yields:
            Simulated output lines.
        """
        task_id = context.task.id if context else "unknown"
        self._is_running = True
        start_time = datetime.now()

        # Emit started event
        await self.emit_event(EventType.AGENT_STARTED, task_id=task_id)
        yield f"[MOCK AGENT] Starting task: {task_id}"

        try:
            # Simulate thinking
            yield "[MOCK AGENT] Beginning analysis..."
            async for thought in self._stream_thoughts(task_id):
                yield thought

            # Simulate file changes
            yield "[MOCK AGENT] Implementing changes..."
            changed_files = await self._simulate_file_changes(worktree_path, task_prompt)

            for filename in changed_files:
                yield f"[MOCK AGENT] Created/modified: {filename}"
                await self.emit_output(
                    content=f"Created file: {filename}",
                    task_id=task_id,
                )

            # Simulate verification
            yield "[MOCK AGENT] Verifying implementation..."
            if self._simulate_delay:
                await asyncio.sleep(random.uniform(0.5, 1.5))

            # Generate summary
            yield "[MOCK AGENT] Task completed successfully!"
            yield f"[MOCK AGENT] Changed files: {len(changed_files)}"
            yield f"[MOCK AGENT] Summary: Implemented changes for task '{task_prompt[:50]}...'"

            # Emit completed event
            await self.emit_event(
                EventType.AGENT_COMPLETED,
                task_id=task_id,
                success=True,
                changed_files=changed_files,
            )

        except asyncio.CancelledError:
            yield "[MOCK AGENT] Task cancelled"
            await self.emit_event(EventType.AGENT_ERROR, task_id=task_id, error="cancelled")
            raise

        except Exception as e:
            yield f"[MOCK AGENT] Error: {e}"
            await self.emit_event(EventType.AGENT_ERROR, task_id=task_id, error=str(e))
            raise

        finally:
            self._is_running = False

    async def _stream_thoughts(self, task_id: str, num_thoughts: int = 4) -> AsyncIterator[str]:
        """Stream simulated thoughts."""
        thoughts = random.sample(SIMULATED_THOUGHTS, min(num_thoughts, len(SIMULATED_THOUGHTS)))

        for thought in thoughts:
            if self._simulate_delay:
                await asyncio.sleep(random.uniform(self._min_delay, self._max_delay))

            line = f"[MOCK AGENT] {thought}"
            await self.emit_output(content=thought, task_id=task_id)
            yield line

    async def run_task(
        self,
        task_prompt: str,
        worktree_path: Path,
        context: Optional[AgentContext] = None,
    ) -> RunResult:
        """
        Run a task and return result.

        Args:
            task_prompt: The task description.
            worktree_path: Path to the worktree.
            context: Task context.

        Returns:
            RunResult with task outcome.
        """
        task_id = context.task.id if context else "unknown"
        self._is_running = True
        start_time = datetime.now()

        # Collect all output
        output_lines = []

        # Emit started event
        await self.emit_event(EventType.AGENT_STARTED, task_id=task_id)

        try:
            # Simulate thinking
            await self._simulate_thinking(task_id, num_thoughts=4)

            # Simulate file changes
            changed_files = await self._simulate_file_changes(worktree_path, task_prompt)
            output_lines.append(f"Created/modified {len(changed_files)} file(s)")

            for filename in changed_files:
                await self.emit_output(
                    content=f"Created file: {filename}",
                    task_id=task_id,
                )

            # Generate diff
            diff = await self._generate_diff(worktree_path, changed_files)

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()

            # Create summary
            summary = f"Successfully implemented changes for task '{task_prompt[:50]}...'"
            summary += f"\nChanged files: {', '.join(changed_files)}"

            # Emit completed event
            await self.emit_event(
                EventType.AGENT_COMPLETED,
                task_id=task_id,
                success=True,
                changed_files=changed_files,
            )

            return RunResult(
                task_id=task_id,
                agent_id=self.agent_id,
                success=True,
                summary=summary,
                stdout="\n".join(output_lines),
                stderr="",
                exit_code=0,
                changed_files=changed_files,
                diff=diff,
                duration_seconds=duration,
                started_at=start_time,
                completed_at=datetime.now(),
            )

        except asyncio.CancelledError:
            await self.emit_event(EventType.AGENT_ERROR, task_id=task_id, error="cancelled")
            return RunResult(
                task_id=task_id,
                agent_id=self.agent_id,
                success=False,
                summary="Task was cancelled",
                stdout="\n".join(output_lines),
                stderr="Task cancelled",
                exit_code=-1,
                changed_files=[],
                diff="",
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                started_at=start_time,
                completed_at=datetime.now(),
            )

        except Exception as e:
            await self.emit_event(EventType.AGENT_ERROR, task_id=task_id, error=str(e))
            return RunResult(
                task_id=task_id,
                agent_id=self.agent_id,
                success=False,
                summary=f"Task failed: {e}",
                stdout="\n".join(output_lines),
                stderr=str(e),
                exit_code=1,
                changed_files=[],
                diff="",
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                started_at=start_time,
                completed_at=datetime.now(),
            )

        finally:
            self._is_running = False

    def __repr__(self) -> str:
        return f"MockAgentAdapter(id={self.agent_id}, delay={self._simulate_delay})"