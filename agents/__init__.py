"""
Agent adapters for various coding CLIs.
"""

from .base import BaseAgentAdapter
from .mock_agent import MockAgentAdapter
from .registry import AgentRegistry

__all__ = ["BaseAgentAdapter", "MockAgentAdapter", "AgentRegistry"]