"""
Command parser for Easycode TUI.

Parses user commands and returns structured command objects.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CommandType(Enum):
    """Types of commands."""

    PLAN = "plan"
    RUN = "run"
    RUN_ALL = "run_all"
    MERGE = "merge"
    RETRY = "retry"
    STATUS = "status"
    TASKS = "tasks"
    AGENTS = "agents"
    LOGS = "logs"
    DIFF = "diff"
    WORKTREE = "worktree"
    MENTOR = "mentor"
    CLEAR = "clear"
    HELP = "help"
    DEBUG = "debug"
    EXIT = "exit"
    QUIT = "quit"

    # Natural language
    GOAL = "goal"

    # Unknown
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    """Result of parsing a command."""

    type: CommandType
    raw: str
    args: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class CommandParser:
    """
    Parses user input into structured commands.

    Supports:
    - Slash commands (/plan, /run, etc.)
    - Natural language goals
    """

    def __init__(self):
        """Initialize the parser."""
        self._command_aliases = {
            "plan": CommandType.PLAN,
            "p": CommandType.PLAN,
            "run": CommandType.RUN,
            "r": CommandType.RUN,
            "run-all": CommandType.RUN_ALL,
            "merge": CommandType.MERGE,
            "m": CommandType.MERGE,
            "retry": CommandType.RETRY,
            "status": CommandType.STATUS,
            "s": CommandType.STATUS,
            "tasks": CommandType.TASKS,
            "t": CommandType.TASKS,
            "agents": CommandType.AGENTS,
            "a": CommandType.AGENTS,
            "logs": CommandType.LOGS,
            "l": CommandType.LOGS,
            "diff": CommandType.DIFF,
            "d": CommandType.DIFF,
            "debug": CommandType.DEBUG,
            "worktree": CommandType.WORKTREE,
            "w": CommandType.WORKTREE,
            "mentor": CommandType.MENTOR,
            "clear": CommandType.CLEAR,
            "c": CommandType.CLEAR,
            "help": CommandType.HELP,
            "h": CommandType.HELP,
            "?": CommandType.HELP,
            "exit": CommandType.EXIT,
            "quit": CommandType.QUIT,
            "q": CommandType.QUIT,
        }

    def parse(self, input_str: str) -> ParsedCommand:
        """
        Parse user input.

        Args:
            input_str: Raw user input.

        Returns:
            ParsedCommand with type and arguments.
        """
        input_str = input_str.strip()

        if not input_str:
            return ParsedCommand(type=CommandType.UNKNOWN, raw=input_str, error="Empty input")

        # Check for slash command
        if input_str.startswith("/"):
            return self._parse_slash_command(input_str)

        # Treat as natural language goal
        return ParsedCommand(
            type=CommandType.GOAL,
            raw=input_str,
            args={"goal": input_str},
        )

    def _parse_slash_command(self, input_str: str) -> ParsedCommand:
        """Parse a slash command."""
        # Remove leading slash
        content = input_str[1:].strip()

        # Split into command and arguments
        parts = content.split(maxsplit=1)
        cmd_str = parts[0].lower() if parts else ""
        arg_str = parts[1] if len(parts) > 1 else ""

        # Look up command
        cmd_type = self._command_aliases.get(cmd_str)

        if not cmd_type:
            return ParsedCommand(
                type=CommandType.UNKNOWN,
                raw=input_str,
                error=f"Unknown command: {cmd_str}",
            )

        # Parse arguments based on command type
        args = self._parse_args(cmd_type, arg_str)

        return ParsedCommand(
            type=cmd_type,
            raw=input_str,
            args=args,
        )

    def _parse_args(self, cmd_type: CommandType, arg_str: str) -> dict[str, Any]:
        """Parse arguments for a specific command type."""
        args: dict[str, Any] = {}

        if cmd_type == CommandType.PLAN:
            args["goal"] = arg_str

        elif cmd_type == CommandType.RUN:
            args["task_id"] = arg_str if arg_str else None

        elif cmd_type == CommandType.MERGE:
            args["task_id"] = arg_str

        elif cmd_type == CommandType.RETRY:
            args["task_id"] = arg_str

        elif cmd_type == CommandType.DIFF:
            args["task_id"] = arg_str

        elif cmd_type == CommandType.LOGS:
            args["task_id"] = arg_str

        elif cmd_type == CommandType.WORKTREE:
            args["task_id"] = arg_str

        elif cmd_type == CommandType.MENTOR:
            args["agent_id"] = arg_str

        elif cmd_type == CommandType.DEBUG:
            args["task_id"] = arg_str if arg_str else None

        elif cmd_type in (CommandType.EXIT, CommandType.QUIT):
            pass  # No arguments

        elif cmd_type == CommandType.HELP:
            args["topic"] = arg_str if arg_str else None

        return args

    def get_help_text(self) -> str:
        """Get help text for all commands."""
        return """
Commands:
  /plan <goal>     - Create a task plan from a goal
  /run [task_id]   - Run a specific task or next pending task
  /run-all         - Run all pending tasks
  /merge <task_id> - Merge a completed task
  /retry <task_id> - Retry a failed task
  /status          - Show workspace status
  /tasks           - List all tasks
  /agents          - List available agents
  /logs [task_id]  - Show logs for a task
  /diff <task_id>  - Show diff for a task
  /debug [task_id] - Show debug info for a task
  /mentor <agent>  - Set mentor agent
  /clear           - Clear all state
  /help            - Show this help
  /exit            - Exit the application

Shortcuts:
  /p = /plan, /r = /run, /m = /merge, /s = /status
  /t = /tasks, /a = /agents, /l = /logs, /d = /diff
  /h = /help, /q = /exit

You can also type a goal directly without /plan.
"""


def parse_command(input_str: str) -> ParsedCommand:
    """Convenience function to parse a command."""
    parser = CommandParser()
    return parser.parse(input_str)