"""
Agent registry for Easycode.

Provides a registry for agent adapters and factory functions.
"""

from typing import Callable, Optional, Type

from orchestrator.events import EventBus
from orchestrator.models import AgentConfig, AgentType
from agents.base import BaseAgentAdapter


# Registry of agent types to their adapter classes
_agent_registry: dict[AgentType, Type[BaseAgentAdapter]] = {}


def register_agent_type(agent_type: AgentType) -> Callable:
    """
    Decorator to register an agent adapter class.

    Usage:
        @register_agent_type(AgentType.MOCK)
        class MockAgentAdapter(BaseAgentAdapter):
            ...
    """
    def decorator(cls: Type[BaseAgentAdapter]) -> Type[BaseAgentAdapter]:
        _agent_registry[agent_type] = cls
        return cls
    return decorator


def get_agent_class(agent_type: AgentType) -> Optional[Type[BaseAgentAdapter]]:
    """Get the adapter class for an agent type."""
    return _agent_registry.get(agent_type)


def is_agent_registered(agent_type: AgentType) -> bool:
    """Check if an agent type is registered."""
    return agent_type in _agent_registry


class AgentRegistry:
    """
    Registry and factory for agent adapters.

    Manages agent instances and provides factory methods to create them.
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize the registry.

        Args:
            event_bus: Event bus for agent events.
        """
        self.event_bus = event_bus
        self._agents: dict[str, BaseAgentAdapter] = {}
        self._configs: dict[str, AgentConfig] = {}

    def register_config(self, agent_id: str, config: AgentConfig) -> None:
        """Register an agent configuration."""
        self._configs[agent_id] = config

    def get_config(self, agent_id: str) -> Optional[AgentConfig]:
        """Get an agent configuration."""
        return self._configs.get(agent_id)

    def list_configs(self) -> dict[str, AgentConfig]:
        """List all registered configurations."""
        return self._configs.copy()

    async def get_agent(self, agent_id: str) -> Optional[BaseAgentAdapter]:
        """
        Get or create an agent instance.

        Args:
            agent_id: ID of the agent.

        Returns:
            Agent adapter instance, or None if not found.
        """
        # Return existing instance
        if agent_id in self._agents:
            return self._agents[agent_id]

        # Create new instance
        config = self._configs.get(agent_id)
        if not config:
            return None

        agent = self._create_agent(agent_id, config)
        if agent:
            self._agents[agent_id] = agent
            await agent.start()

        return agent

    def _create_agent(self, agent_id: str, config: AgentConfig) -> Optional[BaseAgentAdapter]:
        """Create an agent adapter instance."""
        agent_class = get_agent_class(config.type)
        if not agent_class:
            return None

        return agent_class(agent_id, config, self.event_bus)

    async def start_agent(self, agent_id: str) -> bool:
        """Start an agent."""
        agent = await self.get_agent(agent_id)
        if agent:
            await agent.start()
            return True
        return False

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop an agent."""
        agent = self._agents.get(agent_id)
        if agent:
            await agent.stop()
            return True
        return False

    async def stop_all(self) -> None:
        """Stop all agents."""
        for agent in self._agents.values():
            await agent.stop()
        self._agents.clear()

    def get_running_agents(self) -> list[str]:
        """Get IDs of running agents."""
        return [aid for aid, agent in self._agents.items() if agent.is_running]

    def __repr__(self) -> str:
        return f"AgentRegistry(agents={list(self._configs.keys())})"


# Import and register built-in adapters
def register_builtin_adapters():
    """Register built-in agent adapters."""
    from agents.mock_agent import MockAgentAdapter
    # Other adapters will be imported when implemented
    # from agents.claude_cli import ClaudeCliAdapter
    # from agents.codex_cli import CodexCliAdapter
    # from agents.gemini_cli import GeminiCliAdapter


# Auto-register on module load
# This will be done after MockAgentAdapter is defined