"""
Base agent adapter for Easycode.

Defines the abstract interface that all agent adapters must implement.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from orchestrator.events import EventBus, Event, EventType, create_output_event
from orchestrator.models import AgentConfig, RunResult, Task


@dataclass
class AgentContext:
    """Context provided to an agent when running a task."""

    task: Task
    worktree_path: Path
    event_bus: EventBus
    agent_id: str
    config: AgentConfig
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgentAdapter(ABC):
    """
    Abstract base class for agent adapters.

    All agent adapters (Claude CLI, Codex, Gemini, Mock) must implement
    this interface to be compatible with the orchestrator.
    """

    def __init__(self, agent_id: str, config: AgentConfig, event_bus: EventBus):
        """
        Initialize the agent adapter.

        Args:
            agent_id: Unique identifier for this agent instance.
            config: Agent configuration.
            event_bus: Event bus for emitting events.
        """
        self.agent_id = agent_id
        self.config = config
        self.event_bus = event_bus
        self._is_running = False
        self._current_task: Optional[Task] = None

    @property
    def name(self) -> str:
        """Get agent name."""
        return self.agent_id

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running a task."""
        return self._is_running

    @abstractmethod
    async def run_task_stream(
        self,
        task_prompt: str,
        worktree_path: Path,
        context: Optional[AgentContext] = None,
    ) -> AsyncIterator[str]:
        """
        Run a task and stream output.

        Args:
            task_prompt: The task description/instructions for the agent.
            worktree_path: Path to the worktree where agent should work.
            context: Additional context for the task.

        Yields:
            Lines of output from the agent.

        Returns:
            RunResult with task outcome.
        """
        pass

    @abstractmethod
    async def run_task(
        self,
        task_prompt: str,
        worktree_path: Path,
        context: Optional[AgentContext] = None,
    ) -> RunResult:
        """
        Run a task and return result.

        Args:
            task_prompt: The task description/instructions for the agent.
            worktree_path: Path to the worktree where agent should work.
            context: Additional context for the task.

        Returns:
            RunResult with task outcome.
        """
        pass

    async def start(self) -> None:
        """Initialize the agent (e.g., start subprocess, warm up model)."""
        pass

    async def stop(self) -> None:
        """Stop the agent and clean up resources."""
        self._is_running = False

    async def emit_event(self, event_type: EventType, **kwargs) -> None:
        """Emit an event to the event bus."""
        event = Event(
            type=event_type,
            source=f"agent.{self.agent_id}",
            data={"agent_id": self.agent_id, **kwargs},
        )
        await self.event_bus.publish(event)

    async def emit_output(self, content: str, task_id: str, is_error: bool = False) -> None:
        """Emit an output event."""
        event = create_output_event(
            agent_id=self.agent_id,
            task_id=task_id,
            content=content,
            is_error=is_error,
            source=f"agent.{self.agent_id}",
        )
        await self.event_bus.publish(event)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.agent_id}, type={self.config.type})"


class AgentError(Exception):
    """Error from an agent operation."""

    def __init__(self, message: str, agent_id: str, task_id: Optional[str] = None):
        super().__init__(message)
        self.agent_id = agent_id
        self.task_id = task_id


class AgentTimeoutError(AgentError):
    """Agent operation timed out."""

    pass


class AgentCancelledError(AgentError):
    """Agent operation was cancelled."""

    pass