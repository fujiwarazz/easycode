"""
Planner module for Easycode.

Generates task plans from user goals.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from orchestrator.events import EventBus
from orchestrator.models import (
    Plan,
    Task,
    TaskStatus,
)
from utils.config import Config
from utils.logging import get_logger

logger = get_logger("planner")


class MentorPlanner:
    """
    Generates task plans from user goals.

    In the MVP, this uses simple heuristics to split goals into tasks.
    Future versions will use an LLM (mentor agent) for intelligent planning.
    """

    def __init__(self, config: Config, event_bus: EventBus):
        """
        Initialize planner.

        Args:
            config: Application configuration.
            event_bus: Event bus for events.
        """
        self.config = config
        self.event_bus = event_bus
        self._plan_counter = 0

    def _generate_plan_id(self) -> str:
        """Generate a unique plan ID."""
        self._plan_counter += 1
        return f"plan-{self._plan_counter:03d}"

    def _generate_task_id(self, plan_id: str, index: int) -> str:
        """Generate a task ID."""
        return f"{plan_id}-task-{index + 1:02d}"

    async def create_plan(self, goal: str) -> Plan:
        """
        Create a plan from a user goal.

        Args:
            goal: User's goal description.

        Returns:
            Plan with tasks.
        """
        logger.info(f"Creating plan for goal: {goal[:50]}...")

        plan_id = self._generate_plan_id()

        # Split goal into tasks using heuristics
        tasks = await self._split_into_tasks(goal, plan_id)

        # Create the plan
        plan = Plan(
            id=plan_id,
            goal=goal,
            tasks=tasks,
            mentor_agent=self.config.mentor.agent,
            context=f"Generated from goal: {goal}",
        )

        logger.info(f"Created plan {plan_id} with {len(tasks)} tasks")

        return plan

    async def _split_into_tasks(self, goal: str, plan_id: str) -> list[Task]:
        """
        Split a goal into tasks.

        Uses simple heuristics:
        - Split on "and", "then", "also"
        - Detect common patterns (feature + test, setup + implementation)
        """
        tasks = []

        # Try to detect multiple tasks
        goal_lower = goal.lower()

        # Pattern 1: "X and Y" or "X, Y, and Z"
        and_pattern = r'\s+and\s+|\s*,\s+(?:and\s+)?'
        parts = re.split(and_pattern, goal, flags=re.IGNORECASE)

        if len(parts) > 1:
            # Multiple tasks detected
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue

                task = Task(
                    id=self._generate_task_id(plan_id, i),
                    title=self._generate_title(part),
                    description=f"Part of goal: {goal}",
                    prompt=self._generate_prompt(part, goal),
                    status=TaskStatus.PLANNED,
                )
                tasks.append(task)
        else:
            # Single task - but try to add complementary tasks
            main_task = Task(
                id=self._generate_task_id(plan_id, 0),
                title=self._generate_title(goal),
                description=goal,
                prompt=self._generate_prompt(goal, goal),
                status=TaskStatus.PLANNED,
            )
            tasks.append(main_task)

            # Add test task if it looks like an implementation task
            if self._is_implementation_task(goal):
                test_task = Task(
                    id=self._generate_task_id(plan_id, 1),
                    title=f"Add tests for: {self._generate_title(goal)}",
                    description=f"Write tests for the implementation of: {goal}",
                    prompt=f"Write comprehensive tests for: {goal}",
                    status=TaskStatus.PLANNED,
                    depends_on=[main_task.id],
                )
                tasks.append(test_task)

        return tasks

    def _generate_title(self, part: str) -> str:
        """Generate a task title from a goal part."""
        # Capitalize first letter
        title = part.strip()
        if title:
            title = title[0].upper() + title[1:]

        # Limit length
        if len(title) > 60:
            title = title[:57] + "..."

        return title

    def _generate_prompt(self, part: str, full_goal: str) -> str:
        """Generate an agent prompt from a goal part."""
        # For now, just return the part with some context
        if part == full_goal:
            return f"Please implement the following:\n\n{part}"

        return f"Please implement the following as part of the goal '{full_goal}':\n\n{part}"

    def _is_implementation_task(self, goal: str) -> bool:
        """Check if a goal is an implementation task."""
        impl_keywords = [
            "implement", "create", "build", "add", "write",
            "develop", "make", "feature", "function", "class",
            "module", "component", "api", "endpoint",
        ]

        goal_lower = goal.lower()
        return any(kw in goal_lower for kw in impl_keywords)

    async def refine_plan(self, plan: Plan, feedback: str) -> Plan:
        """
        Refine a plan based on feedback.

        Args:
            plan: Existing plan.
            feedback: Feedback for refinement.

        Returns:
            Refined plan.
        """
        # TODO: Use mentor agent for intelligent refinement
        logger.info(f"Refining plan {plan.id} with feedback: {feedback[:50]}...")

        # For now, just add feedback to context
        plan.context += f"\n\nRefinement feedback: {feedback}"

        return plan

    async def add_task_to_plan(
        self,
        plan: Plan,
        title: str,
        description: str,
        prompt: str,
        depends_on: list[str] = None,
    ) -> Task:
        """
        Add a task to an existing plan.

        Args:
            plan: Plan to add to.
            title: Task title.
            description: Task description.
            prompt: Agent prompt.
            depends_on: Dependencies.

        Returns:
            Created task.
        """
        task_id = self._generate_task_id(plan.id, len(plan.tasks))

        task = Task(
            id=task_id,
            title=title,
            description=description,
            prompt=prompt,
            status=TaskStatus.PLANNED,
            depends_on=depends_on or [],
        )

        plan.tasks.append(task)

        logger.info(f"Added task {task_id} to plan {plan.id}")

        return task

    async def remove_task_from_plan(self, plan: Plan, task_id: str) -> bool:
        """Remove a task from a plan."""
        for i, task in enumerate(plan.tasks):
            if task.id == task_id:
                plan.tasks.pop(i)

                # Remove from dependencies of other tasks
                for other_task in plan.tasks:
                    if task_id in other_task.depends_on:
                        other_task.depends_on.remove(task_id)

                logger.info(f"Removed task {task_id} from plan {plan.id}")
                return True

        return False


# Fallback rules for common patterns
FALLBACK_RULES = [
    {
        "pattern": r"add\s+(?:a\s+)?new\s+feature",
        "tasks": [
            {"title": "Implement the feature", "prompt": "Implement the new feature"},
            {"title": "Add tests", "prompt": "Write tests for the new feature", "depends_on": [0]},
        ],
    },
    {
        "pattern": r"refactor\s+(\w+)",
        "tasks": [
            {"title": "Refactor the code", "prompt": "Refactor the code for better structure"},
            {"title": "Update tests", "prompt": "Update tests for the refactored code", "depends_on": [0]},
        ],
    },
    {
        "pattern": r"fix\s+(?:bug\s+)?(.+)",
        "tasks": [
            {"title": "Fix the bug", "prompt": "Identify and fix the bug"},
            {"title": "Add regression test", "prompt": "Add a test to prevent regression", "depends_on": [0]},
        ],
    },
]