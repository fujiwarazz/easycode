"""
TUI widgets for Easycode.

Provides all the visual components for the interface.
"""

from datetime import datetime
from typing import Optional

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Tree,
)


class AgentItem(ListItem):
    """A single agent in the agents list."""

    def __init__(self, agent_id: str, agent_type: str, enabled: bool = True, running: bool = False):
        super().__init__()
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.enabled = enabled
        self.running = running

    def compose(self) -> ComposeResult:
        status = "🔄" if self.running else ("✓" if self.enabled else "✗")
        yield Label(f"{status} {self.agent_id} ({self.agent_type})")


class AgentsPanel(Container):
    """Panel showing available agents."""

    DEFAULT_CSS = """
    AgentsPanel {
        width: 1fr;
        height: 1fr;
        border: solid green;
        background: $surface;
    }
    AgentsPanel > Label {
        text-style: bold;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("🤖 Agents")
        yield ListView(id="agents-list")

    def update_agents(self, agents: dict) -> None:
        """Update the agents list."""
        list_view = self.query_one("#agents-list", ListView)
        list_view.clear()

        for agent_id, config in agents.items():
            item = AgentItem(
                agent_id=agent_id,
                agent_type=config.get("type", "unknown"),
                enabled=config.get("enabled", True),
                running=False,  # Will be updated by events
            )
            list_view.append(item)


class TaskItem(ListItem):
    """A single task in the tasks list."""

    def __init__(self, task_id: str, title: str, status: str):
        super().__init__()
        self.task_id = task_id
        self.task_title = title
        self.task_status = status

    def compose(self) -> ComposeResult:
        status_icons = {
            "pending": "⏳",
            "planned": "📋",
            "running": "🔄",
            "done": "✅",
            "failed": "❌",
            "merged": "🔀",
            "cancelled": "🚫",
        }
        icon = status_icons.get(self.task_status, "❓")
        yield Label(f"{icon} {self.task_id}: {self.task_title[:30]}")


class TasksPanel(Container):
    """Panel showing tasks."""

    DEFAULT_CSS = """
    TasksPanel {
        width: 1fr;
        height: 1fr;
        border: solid blue;
        background: $surface;
    }
    TasksPanel > Label {
        text-style: bold;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    """

    selected_task_id: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("📋 Tasks")
        yield ListView(id="tasks-list")

    def update_tasks(self, tasks: dict) -> None:
        """Update the tasks list."""
        list_view = self.query_one("#tasks-list", ListView)
        list_view.clear()

        for task_id, task in sorted(tasks.items()):
            item = TaskItem(
                task_id=task_id,
                title=task.get("title", "Untitled"),
                status=task.get("status", "pending"),
            )
            list_view.append(item)


class MessageItem(Static):
    """A single message in the log."""

    DEFAULT_CSS = """
    MessageItem {
        padding: 0 1;
        margin: 0;
        width: 100%;
        text-wrap: anywhere;
    }
    MessageItem.system {
        color: $text-muted;
    }
    MessageItem.error {
        color: $error;
    }
    MessageItem.success {
        color: $success;
    }
    MessageItem.agent {
        color: $accent;
    }
    """

    def __init__(self, content: str, msg_type: str = "system", timestamp: Optional[str] = None):
        super().__init__()
        self.content = content
        self.msg_type = msg_type
        self.timestamp = timestamp or datetime.now().strftime("%H:%M:%S")

    def render(self) -> Text:
        text = Text()

        # Timestamp
        text.append(f"[{self.timestamp}] ", style="dim")

        # Type indicator
        indicators = {
            "system": ("SYS", "cyan"),
            "error": ("ERR", "red"),
            "success": ("OK", "green"),
            "agent": ("AGT", "yellow"),
            "user": ("USR", "blue"),
        }
        indicator, color = indicators.get(self.msg_type, ("???", "white"))
        text.append(f"[{indicator}] ", style=color)

        # Content
        text.append(self.content)

        return text


class MessageLogPanel(Container):
    """Panel showing message log."""

    DEFAULT_CSS = """
    MessageLogPanel {
        width: 100%;
        height: 100%;
        border: solid yellow;
        background: $surface;
        overflow: hidden;
    }
    MessageLogPanel > Label {
        text-style: bold;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    MessageLogPanel > VerticalScroll {
        height: 1fr;
        width: 100%;
        overflow-x: hidden;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📜 Messages")
        yield VerticalScroll(id="messages-scroll")

    def add_message(self, content: str, msg_type: str = "system") -> None:
        """Add a message to the log."""
        scroll = self.query_one("#messages-scroll", VerticalScroll)
        msg = MessageItem(content, msg_type)
        scroll.mount(msg)
        # Scroll to the newly added message
        msg.scroll_visible()

    def clear_messages(self) -> None:
        """Clear all messages."""
        scroll = self.query_one("#messages-scroll", VerticalScroll)
        for child in list(scroll.children):
            child.remove()


class TaskDetailPanel(Container):
    """Panel showing task details."""

    DEFAULT_CSS = """
    TaskDetailPanel {
        height: 100%;
        border: solid magenta;
        background: $surface;
    }
    TaskDetailPanel > Label {
        text-style: bold;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    TaskDetailPanel.collapsed > VerticalScroll {
        display: none;
    }
    """

    collapsed: reactive[bool] = reactive(False)
    current_task_id: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("📄 Task Details [click]")
        with VerticalScroll(id="detail-scroll"):
            yield Static(id="detail-content", expand=True)

    def on_click(self) -> None:
        """Toggle collapsed state on click - notify parent."""
        self.app.action_toggle_detail()

    def _update_collapsed(self) -> None:
        """Update UI for collapsed state."""
        if self.collapsed:
            self.add_class("collapsed")
            self.query_one(Label).update("▶")
        else:
            self.remove_class("collapsed")
            self.query_one(Label).update("📄 Task Details [click]")

    def update_detail(self, task: dict, result: Optional[dict] = None) -> None:
        """Update the task detail view."""
        if self.collapsed:
            return

        content = self.query_one("#detail-content", Static)

        lines = []

        # Task info
        lines.append(f"[bold]Task: {task.get('id', 'N/A')}[/bold]")
        lines.append(f"Title: {task.get('title', 'N/A')}")
        lines.append(f"Status: {task.get('status', 'N/A')}")
        lines.append("")

        if task.get("description"):
            lines.append("[bold]Description:[/bold]")
            lines.append(task["description"])
            lines.append("")

        if result:
            lines.append("[bold]Result:[/bold]")
            lines.append(f"Success: {result.get('success', False)}")
            lines.append(f"Duration: {result.get('duration_seconds', 0):.2f}s")
            lines.append("")

            if result.get("summary"):
                lines.append("[bold]Summary:[/bold]")
                lines.append(result["summary"])
                lines.append("")

            if result.get("changed_files"):
                lines.append("[bold]Changed Files:[/bold]")
                for f in result["changed_files"]:
                    lines.append(f"  • {f}")
                lines.append("")

            if result.get("diff"):
                lines.append("[bold]Diff:[/bold]")
                lines.append(result["diff"][:500])
                if len(result["diff"]) > 500:
                    lines.append("... (truncated)")

        content.update("\n".join(lines))

    def clear(self) -> None:
        """Clear the detail view."""
        content = self.query_one("#detail-content", Static)
        content.update("Select a task to view details")


class InputBar(Container):
    """Input bar for user commands."""

    DEFAULT_CSS = """
    InputBar {
        height: 5;
        padding: 0 1;
        background: $surface-darken-3;
    }
    InputBar Input {
        width: 1fr;
        height: 3;
    }
    InputBar .hints {
        color: $text-muted;
        text-style: dim;
        height: 1;
    }
    """

    class Submitted(Message):
        """Message sent when input is submitted."""

        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a command or goal... (n:New r:Run m:Merge q:Quit)", id="main-input")
        yield Label("[n]New [p]Plan [r]Run [m]Merge [d]Diff [v]View [h]Help [q]Quit", classes="hints")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self.post_message(self.Submitted(event.value))
        event.input.value = ""


class StatusBar(Horizontal):
    """Status bar at the bottom."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
    }
    StatusBar > Label {
        padding: 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Ready", id="status-message")
        yield Label("Branch: main", id="status-branch")
        yield Label("Mentor: claude-cli", id="status-mentor")


class HelpPanel(Container):
    """Panel showing help information."""

    DEFAULT_CSS = """
    HelpPanel {
        width: 1fr;
        height: 1fr;
        border: solid cyan;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("❓ Help")
        yield Static(self._get_help_content())

    def _get_help_content(self) -> str:
        return """
[bold]Easycode - Multi-Agent Coding Orchestrator[/bold]

[yellow]Commands:[/yellow]
  /plan <goal>     Create a task plan
  /run [id]        Run a task
  /merge <id>      Merge a completed task
  /status          Show status
  /tasks           List tasks
  /agents          List agents
  /diff <id>       Show task diff
  /help            Show help
  /exit            Exit

[yellow]Keyboard Shortcuts:[/yellow]
  n     New task
  p     Plan mode
  r     Run selected task
  m     Merge selected task
  d     View diff
  l     View logs
  q     Quit

[yellow]Workflow:[/yellow]
  1. Enter a goal or use /plan
  2. Review generated tasks
  3. Run tasks with /run
  4. Review changes with /diff
  5. Merge completed tasks
"""