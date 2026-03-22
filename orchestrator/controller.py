"""
Central controller for Easycode orchestrator.

Orchestrates the entire system: agents, worktrees, tasks, and state.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from orchestrator.events import (
    EventBus,
    Event,
    EventType,
    create_task_event,
    create_agent_event,
    EVENT_TASK_STARTED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_FAILED,
    EVENT_MERGE_STARTED,
    EVENT_MERGE_COMPLETED,
    EVENT_MERGE_FAILED,
)
from orchestrator.models import (
    AppConfig,
    AppState,
    Task,
    TaskStatus,
    WorktreeSession,
    RunResult,
    Plan,
)
from orchestrator.planner import MentorPlanner
from agents.base import BaseAgentAdapter, AgentContext
from agents.registry import AgentRegistry
from gitops.worktree import WorktreeManager
from gitops.diff import DiffCollector
from gitops.merge import MergeManager
from gitops.verify import VerifyRunner
from storage.repo import StateRepository
from utils.config import Config
from utils.logging import get_logger
from utils.paths import Paths

logger = get_logger("controller")


class Controller:
    """
    Central controller for the Easycode orchestrator.

    Manages:
    - Agent lifecycle and task execution
    - Git worktree creation and cleanup
    - Task state and transitions
    - Merge and verify operations
    - Event emission for TUI updates
    """

    def __init__(self, config: Config, event_bus: EventBus):
        """
        Initialize the controller.

        Args:
            config: Application configuration.
            event_bus: Event bus for system events.
        """
        self.config = config
        self.event_bus = event_bus

        # Initialize paths
        self.paths = Paths(
            workspace_path=config.workspace.path,
            worktree_dir=config.workspace.worktree_dir,
            log_dir=config.workspace.log_dir,
            state_dir=config.workspace.state_dir,
        )

        # Initialize components
        self.state = AppState()
        self.state_repository = StateRepository(self.paths.state_dir)
        self.agent_registry = AgentRegistry(event_bus)
        self.worktree_manager = WorktreeManager(
            self.paths.workspace,
            self.paths.worktree_dir,
        )
        self.merge_manager = MergeManager(self.paths.workspace)
        self.verify_runner = VerifyRunner(
            self.paths.workspace,
            config.verify.commands,
        )
        self.planner = MentorPlanner(config, event_bus)

        # Running tasks tracking
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the controller."""
        logger.info("Initializing controller...")

        # Ensure directories
        self.paths.ensure_directories()

        # Load state
        self.state = await self.state_repository.load_state()

        # Register agent configs
        for agent_id, agent_config in self.config.agents.items():
            if agent_config.enabled:
                self.agent_registry.register_config(agent_id, agent_config)

        # Check if workspace is a git repo
        if not await self.worktree_manager.is_git_repo():
            logger.warning("Workspace is not a git repository")

        # Get current branch
        self.config.workspace.current_branch = await self.worktree_manager.get_current_branch()

        # Emit system start event
        await self.event_bus.emit(
            EventType.SYSTEM_START,
            source="controller",
            branch=self.config.workspace.current_branch,
        )

        self._initialized = True
        logger.info(f"Controller initialized. Branch: {self.config.workspace.current_branch}")

    async def shutdown(self) -> None:
        """Shutdown the controller."""
        logger.info("Shutting down controller...")

        # Cancel running tasks
        for task_id, task in self._running_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Stop all agents
        await self.agent_registry.stop_all()

        # Save state
        await self.state_repository.save_state(self.state)

        # Emit shutdown event
        await self.event_bus.emit(EventType.SYSTEM_SHUTDOWN, source="controller")

        logger.info("Controller shutdown complete")

    async def handle_user_input(self, input_str: str) -> Optional[str]:
        """
        Handle user input (command or natural language).

        Args:
            input_str: User input string.

        Returns:
            Response string, or None.
        """
        input_str = input_str.strip()

        # Check for slash commands
        if input_str.startswith("/"):
            return await self._handle_command(input_str)

        # Treat as natural language goal
        return await self._handle_goal(input_str)

    async def _handle_command(self, command: str) -> str:
        """Handle a slash command."""
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "plan": self._cmd_plan,
            "run": self._cmd_run,
            "merge": self._cmd_merge,
            "retry": self._cmd_retry,
            "status": self._cmd_status,
            "tasks": self._cmd_tasks,
            "agents": self._cmd_agents,
            "help": self._cmd_help,
            "clear": self._cmd_clear,
            "debug": self._cmd_debug,
        }

        handler = handlers.get(cmd)
        if handler:
            return await handler(args)

        return f"Unknown command: {cmd}. Type /help for available commands."

    async def _handle_goal(self, goal: str) -> str:
        """Handle a natural language goal."""
        if not goal:
            return "Please provide a goal or use /help for commands."

        # Generate a plan
        plan = await self.planner.create_plan(goal)

        if not plan.tasks:
            return "Could not generate tasks for the goal. Try being more specific."

        # Store plan
        self.state.current_plan = plan

        # Add tasks to state
        for task in plan.tasks:
            self.state.tasks[task.id] = task

        # Save state
        await self.state_repository.save_state(self.state)

        # Emit plan created event
        await self.event_bus.emit(
            EventType.PLAN_CREATED,
            source="controller",
            plan_id=plan.id,
            task_count=len(plan.tasks),
        )

        return f"Created plan with {len(plan.tasks)} tasks. Use /tasks to view, /run <id> to execute."

    async def _cmd_plan(self, args: str) -> str:
        """Handle /plan command."""
        if not args:
            return "Usage: /plan <goal>"

        return await self._handle_goal(args)

    async def _cmd_run(self, args: str) -> str:
        """Handle /run command."""
        if not args:
            # Run first pending task
            pending = [t for t in self.state.tasks.values() if t.status == TaskStatus.PENDING]
            if not pending:
                return "No pending tasks to run."
            task = pending[0]
        else:
            task = self.state.tasks.get(args)
            if not task:
                return f"Task not found: {args}"

        # Run the task in background
        asyncio.create_task(self.run_task(task.id))

        return f"Started task: {task.id} - {task.title}"

    async def _cmd_merge(self, args: str) -> str:
        """Handle /merge command."""
        if not args:
            return "Usage: /merge <task_id>"

        result = await self.merge_task(args)
        return result

    async def _cmd_retry(self, args: str) -> str:
        """Handle /retry command."""
        if not args:
            return "Usage: /retry <task_id>"

        task = self.state.tasks.get(args)
        if not task:
            return f"Task not found: {args}"

        # Reset task status
        task.status = TaskStatus.PENDING
        task.error_message = None
        task.result_summary = None

        # Run again
        asyncio.create_task(self.run_task(task.id))

        return f"Retrying task: {task.id}"

    async def _cmd_status(self, args: str) -> str:
        """Handle /status command."""
        lines = [
            f"Workspace: {self.paths.workspace}",
            f"Branch: {self.config.workspace.current_branch}",
            f"Mentor: {self.state.mentor_agent}",
            "",
            f"Tasks: {len(self.state.tasks)} total",
            f"  - Pending: {len(self.state.get_pending_tasks())}",
            f"  - Running: {len(self.state.get_running_tasks())}",
            f"  - Completed: {len(self.state.get_completed_tasks())}",
        ]

        if self._running_tasks:
            lines.append(f"\nRunning tasks: {list(self._running_tasks.keys())}")

        return "\n".join(lines)

    async def _cmd_tasks(self, args: str) -> str:
        """Handle /tasks command."""
        if not self.state.tasks:
            return "No tasks. Use /plan <goal> to create tasks."

        lines = ["Tasks:"]

        for task in sorted(self.state.tasks.values(), key=lambda t: t.id):
            status_icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.DONE: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.MERGED: "🔀",
            }.get(task.status, "❓")

            lines.append(f"  {status_icon} [{task.id}] {task.title} ({task.status.value})")

        return "\n".join(lines)

    async def _cmd_agents(self, args: str) -> str:
        """Handle /agents command."""
        lines = ["Available agents:"]

        for agent_id, config in self.config.agents.items():
            status = "enabled" if config.enabled else "disabled"
            running = " (running)" if agent_id in self.agent_registry.get_running_agents() else ""
            lines.append(f"  - {agent_id}: {config.type.value} [{status}]{running}")

        return "\n".join(lines)

    async def _cmd_help(self, args: str) -> str:
        """Handle /help command."""
        return """Available commands:
  /plan <goal>    - Create a plan for a goal
  /run [task_id]  - Run a task (or first pending task)
  /merge <id>     - Merge a completed task
  /retry <id>     - Retry a failed task
  /status         - Show system status
  /tasks          - List all tasks
  /agents         - List available agents
  /clear          - Clear all tasks and state
  /help           - Show this help

You can also just type a goal directly without /plan"""

    async def _cmd_clear(self, args: str) -> str:
        """Handle /clear command."""
        self.state = AppState()
        await self.state_repository.clear_state()
        return "State cleared."

    async def _cmd_debug(self, args: str) -> str:
        """Handle /debug command."""
        task_id = args if args else None

        lines = ["=== DEBUG INFO ==="]

        # Show git worktree list
        lines.append("\n--- Git Worktrees ---")
        try:
            worktrees = await self.worktree_manager.list_worktrees()
            for wt in worktrees:
                lines.append(f"  {wt.path} | {wt.branch} | {wt.commit[:8]}")
        except Exception as e:
            lines.append(f"  Error: {e}")

        # Show git branches
        lines.append("\n--- Git Branches ---")
        try:
            import subprocess
            result = subprocess.run(["git", "branch", "-a"], capture_output=True, text=True, cwd=self.paths.workspace)
            for line in result.stdout.strip().split("\n")[:10]:
                lines.append(f"  {line}")
        except Exception as e:
            lines.append(f"  Error: {e}")

        # Show task details
        if task_id:
            task = self.state.tasks.get(task_id)
            if task:
                lines.append(f"\n--- Task {task_id} ---")
                lines.append(f"  Status: {task.status.value}")
                lines.append(f"  Title: {task.title}")
                lines.append(f"  Error: {task.error_message or 'None'}")
                if task.worktree:
                    lines.append(f"  Worktree: {task.worktree.path}")
                    lines.append(f"  Branch: {task.worktree.branch}")

                result = self.state.results.get(task_id)
                if result:
                    lines.append(f"\n  Result success: {result.success}")
                    lines.append(f"  Result exit_code: {result.exit_code}")
                    lines.append(f"  Result stdout: {result.stdout[:200] if result.stdout else 'None'}...")
                    lines.append(f"  Result stderr: {result.stderr[:200] if result.stderr else 'None'}...")
            else:
                lines.append(f"\n--- Task {task_id} not found ---")

        # Show all tasks status
        lines.append("\n--- All Tasks ---")
        for tid, t in self.state.tasks.items():
            lines.append(f"  {tid}: {t.status.value}")

        return "\n".join(lines)

    async def run_task(self, task_id: str) -> RunResult:
        """
        Run a task with an agent.

        Args:
            task_id: ID of the task to run.

        Returns:
            RunResult with task outcome.
        """
        task = self.state.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if task.status == TaskStatus.RUNNING:
            raise ValueError(f"Task is already running: {task_id}")

        # Check dependencies
        for dep_id in task.depends_on:
            dep_task = self.state.tasks.get(dep_id)
            if dep_task and dep_task.status not in (TaskStatus.DONE, TaskStatus.MERGED):
                raise ValueError(f"Dependency not satisfied: {dep_id}")

        # Update task status
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        # Emit task started event
        await self.event_bus.publish(create_task_event(
            EventType.TASK_STARTED,
            task_id=task_id,
            source="controller",
            title=task.title,
        ))

        logger.info(f"Running task: {task_id}")

        # Initialize result to track progress
        result = None
        worktree_path = None
        branch_name = None

        try:
            # Create worktree
            branch_name, worktree_path = await self.worktree_manager.create_worktree(task_id)
            logger.info(f"Worktree created: {worktree_path} on branch {branch_name}")

            # Create worktree session
            worktree = WorktreeSession(
                id=f"wt-{task_id}",
                path=worktree_path,
                branch=branch_name,
                task_id=task_id,
                agent_id=task.assigned_agent or "mock",
            )
            task.worktree = worktree
            self.state.worktrees[worktree.id] = worktree

            # Get agent
            agent_id = task.assigned_agent or "mock"
            agent = await self.agent_registry.get_agent(agent_id)

            if not agent:
                raise ValueError(f"Agent not available: {agent_id}")

            # Create context
            context = AgentContext(
                task=task,
                worktree_path=worktree_path,
                event_bus=self.event_bus,
                agent_id=agent_id,
                config=self.config.agents.get(agent_id),
            )

            # Run agent
            result = await agent.run_task(
                task_prompt=task.prompt,
                worktree_path=worktree_path,
                context=context,
            )

            logger.info(f"Agent completed: success={result.success}, files={result.changed_files}")

            # Collect diff if successful
            if result.success:
                try:
                    diff_collector = DiffCollector(worktree_path)
                    diff_result = await diff_collector.collect_diff()
                    result.diff = diff_result.raw_diff
                    # Update changed_files from diff result (more accurate)
                    if diff_result.files:
                        result.changed_files = [f.path for f in diff_result.files]
                    logger.info(f"Diff collected: {len(result.changed_files)} files")
                except Exception as e:
                    logger.error(f"Failed to collect diff: {e}")
                    # Don't fail the task just because diff collection failed

            # Update task status based on agent result
            task.status = TaskStatus.DONE if result.success else TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.result_summary = result.summary
            task.error_message = result.stderr if not result.success else None

            # Store result
            self.state.results[task_id] = result

            # Emit completion event
            await self.event_bus.publish(create_task_event(
                EventType.TASK_COMPLETED if result.success else EventType.TASK_FAILED,
                task_id=task_id,
                source="controller",
                success=result.success,
                summary=result.summary,
            ))

            logger.info(f"Task completed: {task_id} (success={result.success})")

        except asyncio.CancelledError:
            task.status = TaskStatus.FAILED
            task.error_message = "Task cancelled"
            task.completed_at = datetime.now()
            logger.info(f"Task cancelled: {task_id}")

            # Create a result for cancelled task
            result = RunResult(
                task_id=task_id,
                agent_id=task.assigned_agent or "mock",
                success=False,
                summary="Task cancelled",
                stderr="Task was cancelled",
                exit_code=-1,
            )
            self.state.results[task_id] = result
            raise

        except Exception as e:
            import traceback
            logger.error(f"Task failed: {task_id} - {e}\n{traceback.format_exc()}")

            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now()

            # Create a result for failed task (preserve what we have)
            result = RunResult(
                task_id=task_id,
                agent_id=task.assigned_agent or "mock",
                success=False,
                summary=f"Task failed: {e}",
                stderr=str(e),
                exit_code=1,
            )
            if worktree_path:
                result.changed_files = []  # Will be empty if agent didn't complete
            self.state.results[task_id] = result

            await self.event_bus.publish(create_task_event(
                EventType.TASK_FAILED,
                task_id=task_id,
                source="controller",
                error=str(e),
            ))

        finally:
            # Always try to save state (even on failure)
            # Use a separate try-except to ensure we don't lose the result
            try:
                save_success = await self.state_repository.save_state(self.state)
                if not save_success:
                    logger.warning(f"Failed to save state for task {task_id}, but task result is preserved in memory")
            except Exception as save_error:
                logger.error(f"Error saving state: {save_error}")

        return result

    async def merge_task(self, task_id: str) -> str:
        """
        Merge a completed task back to the main branch.

        Args:
            task_id: ID of the task to merge.

        Returns:
            Result message.
        """
        task = self.state.tasks.get(task_id)
        if not task:
            return f"Task not found: {task_id}"

        if task.status != TaskStatus.DONE:
            return f"Task must be done before merging. Current status: {task.status.value}"

        if not task.worktree:
            return "Task has no worktree."

        # Emit merge started event
        await self.event_bus.publish(create_task_event(
            EventType.MERGE_STARTED,
            task_id=task_id,
            source="controller",
        ))

        logger.info(f"Merging task: {task_id}")

        try:
            # Perform merge
            result = await self.merge_manager.merge_branch(
                source_branch=task.worktree.branch,
                target_branch=self.config.workspace.current_branch,
                message=f"Merge task {task_id}: {task.title}",
            )

            if not result.success:
                await self.event_bus.publish(create_task_event(
                    EventType.MERGE_FAILED,
                    task_id=task_id,
                    source="controller",
                    conflicts=result.conflicts,
                ))
                return f"Merge failed: {result.message}"

            # Run verification
            if self.config.verify.commands:
                verify_result = await self.verify_runner.run_all()

                if not verify_result.success:
                    # Revert merge on verification failure
                    await self.merge_manager._run_git(
                        ["reset", "--hard", "HEAD~1"], check=False
                    )
                    return f"Verification failed: {verify_result.failed_count} command(s) failed"

            # Cleanup worktree
            await self.worktree_manager.remove_worktree(task.worktree.path)
            del self.state.worktrees[task.worktree.id]

            # Delete feature branch
            await self.merge_manager.delete_branch(task.worktree.branch)

            # Update task status
            task.status = TaskStatus.MERGED
            task.worktree = None

            # Emit merge completed event
            await self.event_bus.publish(create_task_event(
                EventType.MERGE_MERGED,
                task_id=task_id,
                source="controller",
                commit=result.commit_hash,
            ))

            logger.info(f"Task merged: {task_id}")

            await self.state_repository.save_state(self.state)

            return f"Successfully merged task {task_id} ({result.commit_hash[:8]})"

        except Exception as e:
            logger.error(f"Merge failed: {task_id} - {e}")

            await self.event_bus.publish(create_task_event(
                EventType.MERGE_FAILED,
                task_id=task_id,
                source="controller",
                error=str(e),
            ))

            return f"Merge error: {e}"

    async def add_task(
        self,
        title: str,
        description: str,
        prompt: str,
        depends_on: list[str] = None,
    ) -> Task:
        """
        Add a new task manually.

        Args:
            title: Task title.
            description: Task description.
            prompt: Agent prompt.
            depends_on: List of task IDs this depends on.

        Returns:
            Created Task.
        """
        # Generate task ID
        task_id = f"task-{len(self.state.tasks) + 1:03d}"

        task = Task(
            id=task_id,
            title=title,
            description=description,
            prompt=prompt,
            depends_on=depends_on or [],
        )

        self.state.tasks[task_id] = task

        await self.event_bus.publish(create_task_event(
            EventType.TASK_CREATED,
            task_id=task_id,
            source="controller",
            title=title,
        ))

        await self.state_repository.save_state(self.state)

        logger.info(f"Task created: {task_id}")

        return task

    async def get_task_output(self, task_id: str) -> Optional[str]:
        """Get output/logs for a task."""
        result = self.state.results.get(task_id)
        if result:
            return result.stdout
        return None

    async def get_task_diff(self, task_id: str) -> Optional[str]:
        """Get diff for a task."""
        result = self.state.results.get(task_id)
        if result:
            return result.diff
        return None