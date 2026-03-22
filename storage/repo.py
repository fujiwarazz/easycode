"""
State persistence for Easycode.

Provides JSON-based storage for application state.
"""

import json
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from orchestrator.models import (
    AppState,
    Task,
    TaskStatus,
    WorktreeSession,
    RunResult,
    Plan,
)
from utils.logging import get_logger

logger = get_logger("storage.repo")


class StateRepository:
    """
    Manages persistent state storage.

    State is stored as JSON files for simplicity and human-readability.
    """

    def __init__(self, state_dir: Path):
        """
        Initialize state repository.

        Args:
            state_dir: Directory for state files.
        """
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._state_file = state_dir / "state.json"
        self._tasks_dir = state_dir / "tasks"
        self._results_dir = state_dir / "results"

        # Ensure directories exist
        self._tasks_dir.mkdir(exist_ok=True)
        self._results_dir.mkdir(exist_ok=True)

    def _serialize_datetime(self, obj: Any) -> Any:
        """Serialize datetime objects to ISO format."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        return obj

    def _deserialize_datetime(self, data: dict) -> dict:
        """Deserialize ISO datetime strings back to datetime objects."""
        datetime_fields = [
            "created_at", "started_at", "completed_at",
        ]

        for field in datetime_fields:
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = datetime.fromisoformat(data[field])
                except ValueError:
                    pass

        return data

    async def save_state(self, state: AppState) -> bool:
        """
        Save the entire application state with atomic write.

        Args:
            state: Application state to save.

        Returns:
            True if save was successful, False otherwise.
        """
        try:
            # Prepare data - use mode='json' to avoid circular reference issues
            data = state.model_dump(mode='json')

            # Atomic write: write to temp file, then rename
            fd, tmp_path = tempfile.mkstemp(
                dir=self.state_dir,
                prefix="state_tmp_",
                suffix=".json"
            )

            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, default=self._serialize_datetime, indent=2)

                # Atomic rename
                os.replace(tmp_path, self._state_file)
                logger.debug(f"State saved to {self._state_file}")
                return True

            except Exception as e:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

        except Exception as e:
            logger.error(f"Failed to save state: {e}\n{traceback.format_exc()}")
            return False

    async def load_state(self) -> AppState:
        """
        Load the application state.

        Returns:
            Loaded AppState, or empty state if no saved state exists.
        """
        if not self._state_file.exists():
            logger.debug("No saved state found, creating new state")
            return AppState()

        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Deserialize nested objects
            tasks = {}
            for task_id, task_data in data.get("tasks", {}).items():
                task_data = self._deserialize_datetime(task_data)
                if "worktree" in task_data and task_data["worktree"]:
                    task_data["worktree"] = self._deserialize_datetime(task_data["worktree"])
                tasks[task_id] = Task(**task_data)

            worktrees = {}
            for wt_id, wt_data in data.get("worktrees", {}).items():
                wt_data = self._deserialize_datetime(wt_data)
                worktrees[wt_id] = WorktreeSession(**wt_data)

            results = {}
            for res_id, res_data in data.get("results", {}).items():
                res_data = self._deserialize_datetime(res_data)
                results[res_id] = RunResult(**res_data)

            current_plan = None
            if data.get("current_plan"):
                plan_data = data["current_plan"]
                plan_data = self._deserialize_datetime(plan_data)
                plan_tasks = [Task(**self._deserialize_datetime(t))
                             for t in plan_data.get("tasks", [])]
                current_plan = Plan(
                    id=plan_data["id"],
                    goal=plan_data["goal"],
                    tasks=plan_tasks,
                    created_at=plan_data.get("created_at", datetime.now()),
                    mentor_agent=plan_data.get("mentor_agent", "claude-cli"),
                    context=plan_data.get("context", ""),
                )

            return AppState(
                current_plan=current_plan,
                tasks=tasks,
                worktrees=worktrees,
                results=results,
                active_agents=data.get("active_agents", {}),
                mentor_agent=data.get("mentor_agent", "claude-cli"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse state.json (corrupted?): {e}")
            # Backup corrupted file
            backup_path = self._state_file.with_suffix(".json.corrupted")
            self._state_file.rename(backup_path)
            logger.info(f"Corrupted state backed up to {backup_path}")
            return AppState()

        except Exception as e:
            logger.error(f"Failed to load state: {e}\n{traceback.format_exc()}")
            return AppState()

    async def save_task(self, task: Task) -> bool:
        """Save a single task with atomic write."""
        try:
            task_file = self._tasks_dir / f"{task.id}.json"

            fd, tmp_path = tempfile.mkstemp(
                dir=self._tasks_dir,
                prefix=f"task_{task.id}_tmp_",
                suffix=".json"
            )

            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(task.model_dump(mode='json'), f, default=self._serialize_datetime, indent=2)

                os.replace(tmp_path, task_file)
                logger.debug(f"Task saved: {task.id}")
                return True

            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

        except Exception as e:
            logger.error(f"Failed to save task {task.id}: {e}")
            return False

    async def load_task(self, task_id: str) -> Optional[Task]:
        """Load a single task."""
        task_file = self._tasks_dir / f"{task_id}.json"

        if not task_file.exists():
            return None

        try:
            with open(task_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            data = self._deserialize_datetime(data)
            return Task(**data)
        except Exception as e:
            logger.error(f"Failed to load task {task_id}: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task file."""
        task_file = self._tasks_dir / f"{task_id}.json"

        if task_file.exists():
            task_file.unlink()
            return True
        return False

    async def save_result(self, result: RunResult) -> bool:
        """Save a run result with atomic write."""
        try:
            result_file = self._results_dir / f"{result.task_id}.json"

            fd, tmp_path = tempfile.mkstemp(
                dir=self._results_dir,
                prefix=f"result_{result.task_id}_tmp_",
                suffix=".json"
            )

            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(result.model_dump(mode='json'), f, default=self._serialize_datetime, indent=2)

                os.replace(tmp_path, result_file)
                logger.debug(f"Result saved: {result.task_id}")
                return True

            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise

        except Exception as e:
            logger.error(f"Failed to save result {result.task_id}: {e}")
            return False

    async def load_result(self, task_id: str) -> Optional[RunResult]:
        """Load a run result."""
        result_file = self._results_dir / f"{task_id}.json"

        if not result_file.exists():
            return None

        try:
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            data = self._deserialize_datetime(data)
            return RunResult(**data)
        except Exception as e:
            logger.error(f"Failed to load result {task_id}: {e}")
            return None

    async def clear_state(self) -> None:
        """Clear all saved state."""
        if self._state_file.exists():
            self._state_file.unlink()

        # Clear tasks
        for task_file in self._tasks_dir.glob("*.json"):
            task_file.unlink()

        # Clear results
        for result_file in self._results_dir.glob("*.json"):
            result_file.unlink()

        logger.info("State cleared")

    async def export_state(self) -> str:
        """Export state as JSON string."""
        state = await self.load_state()
        return json.dumps(state.model_dump(mode='json'), default=self._serialize_datetime, indent=2)

    async def import_state(self, json_str: str) -> AppState:
        """Import state from JSON string."""
        data = json.loads(json_str)

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(
            dir=self.state_dir,
            prefix="state_import_tmp_",
            suffix=".json"
        )

        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, default=self._serialize_datetime, indent=2)

            os.replace(tmp_path, self._state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

        return await self.load_state()