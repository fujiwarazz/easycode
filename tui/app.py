"""
Main TUI application for Easycode.

Built with Textual for a modern terminal interface.
"""

import asyncio
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, Static

from orchestrator.controller import Controller
from orchestrator.events import EventBus, Event, EventType
from tui.command_parser import CommandParser, CommandType, ParsedCommand
from tui.widgets import (
    AgentsPanel,
    TasksPanel,
    MessageLogPanel,
    TaskDetailPanel,
    InputBar,
    StatusBar,
    HelpPanel,
)
from utils.config import Config
from utils.logging import get_logger, setup_logging

logger = get_logger("tui.app")


class EasycodeApp(App):
    """
    Main TUI application for Easycode.

    Layout:
    ┌─────────────────────────────────────────────────┐
    │ Header (workspace, branch, mentor)             │
    ├───────────┬─────────────────────┬───────────────┤
    │ Agents    │  Message Log        │  Task Detail  │
    │ Panel     │  Panel              │  Panel        │
    │           │                     │               │
    │ Tasks     │  - User messages    │  - Summary    │
    │ Panel     │  - Agent events     │  - Diff       │
    │           │  - System events    │  - Files      │
    ├───────────┴─────────────────────┴───────────────┤
    │ Input Bar [> ] + Help hints                     │
    └─────────────────────────────────────────────────┘
    """

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 2;
        grid-rows: 1fr 5;
        grid-columns: 1fr 2fr 1fr;
    }

    #left-panel {
        column-span: 1;
        row-span: 1;
    }

    #center-panel {
        column-span: 1;
        row-span: 1;
    }

    #right-panel {
        column-span: 1;
        row-span: 1;
    }

    #input-area {
        column-span: 3;
        row-span: 1;
    }

    AgentsPanel, TasksPanel, MessageLogPanel, TaskDetailPanel {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("n", "new_task", "New"),
        Binding("p", "plan", "Plan"),
        Binding("r", "run", "Run"),
        Binding("m", "merge", "Merge"),
        Binding("d", "diff", "Diff"),
        Binding("v", "toggle_detail", "View"),
        Binding("h", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    # Reactive state
    current_task_id: reactive[str] = reactive("")
    workspace_branch: reactive[str] = reactive("main")
    mentor_agent: reactive[str] = reactive("claude-cli")

    def __init__(self, config: Config):
        """
        Initialize the app.

        Args:
            config: Application configuration.
        """
        super().__init__()
        self.config = config
        self.event_bus = EventBus()
        self.controller: Optional[Controller] = None
        self.command_parser = CommandParser()
        self._event_queue: Optional[asyncio.Queue] = None
        self._event_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Container(id="left-panel"):
            yield AgentsPanel()
            yield TasksPanel()

        with Container(id="center-panel"):
            yield MessageLogPanel()

        with Container(id="right-panel"):
            yield TaskDetailPanel()

        with Container(id="input-area"):
            yield InputBar()

    async def on_mount(self) -> None:
        """Handle app mount - initialize controller and start event listener."""
        logger.info("Easycode TUI starting...")

        # Initialize controller
        self.controller = Controller(self.config, self.event_bus)
        await self.controller.initialize()

        # Update UI with initial state
        self._update_workspace_info()
        self._update_agents()
        self._update_tasks()

        # Subscribe to events
        self._event_queue = await self.event_bus.subscribe()

        # Start event listener
        self._event_task = asyncio.create_task(self._event_listener())

        # Add welcome message
        self._add_message("Easycode initialized. Type a goal or use /help for commands.", "system")

        logger.info("Easycode TUI ready")

    async def on_unmount(self) -> None:
        """Handle app unmount - cleanup."""
        logger.info("Easycode TUI shutting down...")

        # Stop event listener
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass

        # Shutdown controller
        if self.controller:
            await self.controller.shutdown()

        logger.info("Easycode TUI shutdown complete")

    async def _event_listener(self) -> None:
        """Listen for events and update UI."""
        if not self._event_queue:
            return

        while True:
            try:
                event: Event = await self._event_queue.get()

                # Handle different event types
                await self._handle_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Event listener error: {e}")

    async def _handle_event(self, event: Event) -> None:
        """Handle a single event."""
        event_type = event.type if isinstance(event.type, EventType) else event.type
        data = event.data

        # Task events
        if event_type == EventType.TASK_CREATED.value:
            self._add_message(f"Task created: {data.get('task_id', '')}", "system")
            self._update_tasks()

        elif event_type == EventType.TASK_STARTED.value:
            self._add_message(f"Task started: {data.get('task_id', '')}", "system")
            self._update_tasks()

        elif event_type == EventType.TASK_COMPLETED.value:
            self._add_message(f"Task completed: {data.get('task_id', '')}", "success")
            self._update_tasks()

        elif event_type == EventType.TASK_FAILED.value:
            self._add_message(f"Task failed: {data.get('task_id', '')} - {data.get('error', '')}", "error")
            self._update_tasks()

        elif event_type == EventType.TASK_MERGED.value:
            self._add_message(f"Task merged: {data.get('task_id', '')}", "success")
            self._update_tasks()

        # Agent events
        elif event_type == EventType.AGENT_STARTED.value:
            self._add_message(f"Agent started: {data.get('agent_id', '')}", "agent")

        elif event_type == EventType.AGENT_OUTPUT.value:
            content = data.get("content", "")
            is_error = data.get("is_error", False)
            self._add_message(content, "error" if is_error else "agent")

        elif event_type == EventType.AGENT_COMPLETED.value:
            self._add_message(f"Agent completed: {data.get('agent_id', '')}", "system")

        # Merge events
        elif event_type == EventType.MERGE_STARTED.value:
            self._add_message(f"Merge started: {data.get('task_id', '')}", "system")

        elif event_type == EventType.MERGE_COMPLETED.value:
            self._add_message(f"Merge completed: {data.get('task_id', '')}", "success")

        elif event_type == EventType.MERGE_FAILED.value:
            self._add_message(f"Merge failed: {data.get('task_id', '')}", "error")

        # Plan events
        elif event_type == EventType.PLAN_CREATED.value:
            self._add_message(f"Plan created with {data.get('task_count', 0)} tasks", "success")
            self._update_tasks()

    def _add_message(self, content: str, msg_type: str = "system") -> None:
        """Add a message to the log panel."""
        try:
            panel = self.query_one(MessageLogPanel)
            panel.add_message(content, msg_type)
        except NoMatches:
            pass

    def _update_workspace_info(self) -> None:
        """Update workspace info in header."""
        if self.controller:
            self.workspace_branch = self.config.workspace.current_branch
            self.mentor_agent = self.controller.state.mentor_agent

    def _update_agents(self) -> None:
        """Update agents panel."""
        try:
            panel = self.query_one(AgentsPanel)
            agents_dict = {
                aid: {"type": cfg.type.value, "enabled": cfg.enabled}
                for aid, cfg in self.config.agents.items()
            }
            panel.update_agents(agents_dict)
        except NoMatches:
            pass

    def _update_tasks(self) -> None:
        """Update tasks panel."""
        if not self.controller:
            return

        try:
            panel = self.query_one(TasksPanel)
            tasks_dict = {
                tid: {
                    "title": t.title,
                    "status": t.status.value,
                }
                for tid, t in self.controller.state.tasks.items()
            }
            panel.update_tasks(tasks_dict)
        except NoMatches:
            pass

    def _update_task_detail(self, task_id: str) -> None:
        """Update task detail panel."""
        if not self.controller:
            return

        task = self.controller.state.tasks.get(task_id)
        if not task:
            return

        result = self.controller.state.results.get(task_id)

        try:
            panel = self.query_one(TaskDetailPanel)
            panel.update_detail(task.model_dump(), result.model_dump() if result else None)
        except NoMatches:
            pass

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        """Handle input submission."""
        asyncio.create_task(self._handle_input(event.value))

    async def _handle_input(self, value: str) -> None:
        """Handle user input."""
        if not value.strip():
            return

        # Echo input
        self._add_message(f"> {value}", "user")

        # Parse command
        parsed = self.command_parser.parse(value)

        # Handle command
        response = await self._execute_command(parsed)

        if response:
            self._add_message(response, "system")

    async def _execute_command(self, parsed: ParsedCommand) -> Optional[str]:
        """Execute a parsed command."""
        if not self.controller:
            return "Controller not initialized"

        cmd_type = parsed.type
        args = parsed.args

        try:
            if cmd_type == CommandType.GOAL:
                return await self.controller._handle_goal(args.get("goal", ""))

            elif cmd_type == CommandType.PLAN:
                return await self.controller._cmd_plan(args.get("goal", ""))

            elif cmd_type == CommandType.RUN:
                return await self.controller._cmd_run(args.get("task_id", ""))

            elif cmd_type == CommandType.RUN_ALL:
                # Run all pending tasks
                pending = self.controller.state.get_pending_tasks()
                for task in pending:
                    asyncio.create_task(self.controller.run_task(task.id))
                return f"Running {len(pending)} task(s)"

            elif cmd_type == CommandType.MERGE:
                return await self.controller._cmd_merge(args.get("task_id", ""))

            elif cmd_type == CommandType.RETRY:
                return await self.controller._cmd_retry(args.get("task_id", ""))

            elif cmd_type == CommandType.STATUS:
                return await self.controller._cmd_status("")

            elif cmd_type == CommandType.TASKS:
                return await self.controller._cmd_tasks("")

            elif cmd_type == CommandType.AGENTS:
                return await self.controller._cmd_agents("")

            elif cmd_type == CommandType.LOGS:
                task_id = args.get("task_id", self.current_task_id)
                output = await self.controller.get_task_output(task_id)
                return output or f"No logs for task: {task_id}"

            elif cmd_type == CommandType.DIFF:
                task_id = args.get("task_id", self.current_task_id)
                diff = await self.controller.get_task_diff(task_id)
                return diff or f"No diff for task: {task_id}"

            elif cmd_type == CommandType.HELP:
                return self.command_parser.get_help_text()

            elif cmd_type == CommandType.CLEAR:
                return await self.controller._cmd_clear("")

            elif cmd_type in (CommandType.EXIT, CommandType.QUIT):
                self.exit()
                return None

            else:
                return f"Unknown command. Type /help for available commands."

        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return f"Error: {e}"

    # Keyboard action handlers
    def action_new_task(self) -> None:
        """Handle 'n' key - new task."""
        self._add_message("Enter a goal to create tasks", "system")

    def action_plan(self) -> None:
        """Handle 'p' key - plan mode."""
        self._add_message("Enter /plan <goal> to create a plan", "system")

    def action_run(self) -> None:
        """Handle 'r' key - run task."""
        if self.current_task_id:
            asyncio.create_task(self.controller.run_task(self.current_task_id))

    def action_merge(self) -> None:
        """Handle 'm' key - merge task."""
        if self.current_task_id:
            asyncio.create_task(self.controller.merge_task(self.current_task_id))

    def action_diff(self) -> None:
        """Handle 'd' key - view diff."""
        if self.current_task_id:
            self._update_task_detail(self.current_task_id)

    def action_toggle_detail(self) -> None:
        """Handle 'v' key - toggle detail panel."""
        try:
            panel = self.query_one(TaskDetailPanel)
            panel.toggle()
        except NoMatches:
            pass

    def action_logs(self) -> None:
        """Handle 'l' key - view logs."""
        pass  # Logs are always visible in message panel

    def action_help(self) -> None:
        """Handle 'h' key - show help."""
        self._add_message(self.command_parser.get_help_text(), "system")


def run_app(config: Config) -> None:
    """Run the TUI application."""
    app = EasycodeApp(config)
    app.run()