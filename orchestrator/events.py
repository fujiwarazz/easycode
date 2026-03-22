"""
Event system for Easycode orchestrator.

Provides an event bus for decoupled communication between components.
Uses asyncio.Queue for async event handling.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel


class EventType(str, Enum):
    """All event types in the system."""

    # System events
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Task events
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_MERGED = "task.merged"

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_OUTPUT = "agent.output"
    AGENT_ERROR = "agent.error"
    AGENT_COMPLETED = "agent.completed"

    # Worktree events
    WORKTREE_CREATED = "worktree.created"
    WORKTREE_REMOVED = "worktree.removed"

    # Plan events
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"

    # Merge events
    MERGE_STARTED = "merge.started"
    MERGE_COMPLETED = "merge.completed"
    MERGE_FAILED = "merge.failed"

    # Verify events
    VERIFY_STARTED = "verify.started"
    VERIFY_PASSED = "verify.passed"
    VERIFY_FAILED = "verify.failed"

    # UI events
    USER_INPUT = "user.input"
    USER_COMMAND = "user.command"
    UI_REFRESH = "ui.refresh"


class Event(BaseModel):
    """Base event class."""

    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "system"  # Component that emitted the event
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    class Config:
        use_enum_values = True


# Specific event data classes for type safety
@dataclass
class TaskEventData:
    """Event data for task events."""

    task_id: str
    task_title: str = ""
    status: str = ""
    agent_id: str = ""
    message: str = ""
    progress: float = 0.0


@dataclass
class AgentOutputData:
    """Event data for agent output events."""

    agent_id: str
    task_id: str
    content: str
    is_error: bool = False
    timestamp: str = ""


@dataclass
class WorktreeEventData:
    """Event data for worktree events."""

    worktree_id: str
    path: str
    branch: str
    task_id: str = ""


@dataclass
class MergeEventData:
    """Event data for merge events."""

    task_id: str
    source_branch: str
    target_branch: str
    success: bool = False
    message: str = ""


# Event name constants for convenience
EVENT_TASK_CREATED = EventType.TASK_CREATED.value
EVENT_TASK_STARTED = EventType.TASK_STARTED.value
EVENT_TASK_PROGRESS = EventType.TASK_PROGRESS.value
EVENT_TASK_COMPLETED = EventType.TASK_COMPLETED.value
EVENT_TASK_FAILED = EventType.TASK_FAILED.value
EVENT_TASK_MERGED = EventType.TASK_MERGED.value

EVENT_AGENT_STARTED = EventType.AGENT_STARTED.value
EVENT_AGENT_OUTPUT = EventType.AGENT_OUTPUT.value
EVENT_AGENT_ERROR = EventType.AGENT_ERROR.value
EVENT_AGENT_COMPLETED = EventType.AGENT_COMPLETED.value

EVENT_WORKTREE_CREATED = EventType.WORKTREE_CREATED.value
EVENT_WORKTREE_REMOVED = EventType.WORKTREE_REMOVED.value

EVENT_PLAN_CREATED = EventType.PLAN_CREATED.value
EVENT_PLAN_UPDATED = EventType.PLAN_UPDATED.value

EVENT_MERGE_STARTED = EventType.MERGE_STARTED.value
EVENT_MERGE_COMPLETED = EventType.MERGE_COMPLETED.value
EVENT_MERGE_FAILED = EventType.MERGE_FAILED.value

EVENT_VERIFY_STARTED = EventType.VERIFY_STARTED.value
EVENT_VERIFY_PASSED = EventType.VERIFY_PASSED.value
EVENT_VERIFY_FAILED = EventType.VERIFY_FAILED.value

EVENT_USER_INPUT = EventType.USER_INPUT.value
EVENT_USER_COMMAND = EventType.USER_COMMAND.value
EVENT_UI_REFRESH = EventType.UI_REFRESH.value

EVENT_SYSTEM_START = EventType.SYSTEM_START.value
EVENT_SYSTEM_SHUTDOWN = EventType.SYSTEM_SHUTDOWN.value
EVENT_SYSTEM_ERROR = EventType.SYSTEM_ERROR.value


class EventBus:
    """
    Async event bus for publishing and subscribing to events.

    Uses asyncio.Queue for thread-safe event passing between coroutines.
    """

    def __init__(self, maxsize: int = 1000):
        """Initialize event bus."""
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._all_subscribers: list[asyncio.Queue] = []
        self._maxsize = maxsize
        self._lock = asyncio.Lock()

    async def subscribe(
        self, event_type: Optional[str] = None
    ) -> asyncio.Queue:
        """
        Subscribe to events.

        Args:
            event_type: Specific event type to subscribe to, or None for all events.

        Returns:
            Queue that will receive events.
        """
        queue = asyncio.Queue(maxsize=self._maxsize)

        async with self._lock:
            if event_type is None:
                self._all_subscribers.append(queue)
            else:
                if event_type not in self._subscribers:
                    self._subscribers[event_type] = []
                self._subscribers[event_type].append(queue)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue, event_type: Optional[str] = None):
        """Unsubscribe a queue from events."""
        async with self._lock:
            if event_type is None:
                if queue in self._all_subscribers:
                    self._all_subscribers.remove(queue)
            else:
                if event_type in self._subscribers:
                    if queue in self._subscribers[event_type]:
                        self._subscribers[event_type].remove(queue)

    async def publish(self, event: Event):
        """
        Publish an event to all subscribers.

        Args:
            event: The event to publish.
        """
        event_type = event.type.value if isinstance(event.type, EventType) else event.type

        async with self._lock:
            # Send to specific subscribers
            if event_type in self._subscribers:
                for queue in self._subscribers[event_type]:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        pass  # Drop event if queue is full

            # Send to all-event subscribers
            for queue in self._all_subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # Drop event if queue is full

    def publish_sync(self, event: Event):
        """
        Publish event synchronously (for use in sync contexts).

        Creates a new event loop if needed.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            asyncio.run(self.publish(event))

    async def emit(self, event_type: EventType, source: str = "system", **kwargs):
        """Convenience method to create and emit an event."""
        event = Event(type=event_type, source=source, data=kwargs)
        await self.publish(event)

    def emit_sync(self, event_type: EventType, source: str = "system", **kwargs):
        """Synchronous emit convenience method."""
        event = Event(type=event_type, source=source, data=kwargs)
        self.publish_sync(event)


# Helper functions for creating common events
def create_task_event(
    event_type: EventType,
    task_id: str,
    source: str = "controller",
    **kwargs,
) -> Event:
    """Create a task-related event."""
    return Event(type=event_type, source=source, data={"task_id": task_id, **kwargs})


def create_agent_event(
    event_type: EventType,
    agent_id: str,
    task_id: str,
    source: str = "agent",
    **kwargs,
) -> Event:
    """Create an agent-related event."""
    return Event(
        type=event_type,
        source=source,
        data={"agent_id": agent_id, "task_id": task_id, **kwargs},
    )


def create_output_event(
    agent_id: str,
    task_id: str,
    content: str,
    is_error: bool = False,
    source: str = "agent",
) -> Event:
    """Create an agent output event."""
    return Event(
        type=EventType.AGENT_OUTPUT,
        source=source,
        data={
            "agent_id": agent_id,
            "task_id": task_id,
            "content": content,
            "is_error": is_error,
        },
    )