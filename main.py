#!/usr/bin/env python3
"""
Easycode CLI - Multi-Agent Coding Orchestrator

A CLI tool that orchestrates multiple coding agents (Claude Code, Gemini, Codex, etc.)
to work together in a git repository using worktree isolation.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from utils.config import load_config
from utils.logging import setup_logging
from utils.paths import Paths


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="easycode",
        description="Multi-Agent Coding Orchestrator",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to configuration file (default: config.toml)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run without TUI (headless mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (can be repeated)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    return parser.parse_args()


async def run_headless(config_path: Path) -> int:
    """Run in headless mode (no TUI)."""
    from orchestrator.controller import Controller
    from orchestrator.events import EventBus

    config = load_config(config_path)
    setup_logging(config)

    event_bus = EventBus()
    controller = Controller(config, event_bus)

    # Initialize controller
    await controller.initialize()

    print("Easycode running in headless mode.")
    print("Type 'help' for available commands.")

    try:
        while True:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit", "q"):
                    break

                result = await controller.handle_user_input(user_input)
                if result:
                    print(result)

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nExiting...")
                break
    finally:
        await controller.shutdown()

    return 0


async def run_tui(config_path: Path) -> int:
    """Run with TUI."""
    from tui.app import EasycodeApp

    config = load_config(config_path)
    # In TUI mode, only log to file, not console
    setup_logging(config, console_output=False)

    app = EasycodeApp(config)
    await app.run_async()

    return 0


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Determine config path
    config_path = args.config
    if not config_path.exists():
        # Try example config
        example_config = Path("config.example.toml")
        if example_config.exists():
            config_path = example_config
        else:
            print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
            print("Please create config.toml or specify a path with --config", file=sys.stderr)
            return 1

    # Run appropriate mode
    if args.no_tui:
        return asyncio.run(run_headless(config_path))
    else:
        return asyncio.run(run_tui(config_path))


if __name__ == "__main__":
    sys.exit(main())