"""
Configuration management for Easycode.

Loads configuration from TOML files and provides validation.
"""

import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from orchestrator.models import AgentConfig, AgentType, Workspace


class WorkspaceConfig(BaseModel):
    """Workspace section configuration."""

    model_config = ConfigDict(extra="forbid")

    path: str = "."
    worktree_dir: str = ".easycode/worktrees"
    log_dir: str = ".easycode/logs"
    state_dir: str = ".easycode/state"


class MentorConfig(BaseModel):
    """Mentor section configuration."""

    model_config = ConfigDict(extra="forbid")

    agent: str = "claude-cli"
    max_concurrent: int = 3


class VerifyConfig(BaseModel):
    """Verify section configuration."""

    model_config = ConfigDict(extra="forbid")

    commands: list[str] = Field(default_factory=list)


class UIConfig(BaseModel):
    """UI section configuration."""

    model_config = ConfigDict(extra="forbid")

    theme: str = "dark"
    refresh_rate: int = 30
    show_timestamps: bool = True


class LoggingConfig(BaseModel):
    """Logging section configuration."""

    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    file_pattern: str = "easycode-{date}.log"


class RawConfig(BaseModel):
    """Raw configuration from TOML file."""

    model_config = ConfigDict(extra="forbid")

    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    mentor: MentorConfig = Field(default_factory=MentorConfig)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class Config(BaseModel):
    """Processed configuration ready for use."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workspace: Workspace
    mentor: MentorConfig
    agents: dict[str, AgentConfig]
    verify: VerifyConfig
    ui: UIConfig
    logging: LoggingConfig
    config_path: Path

    @field_validator("config_path", mode="before")
    @classmethod
    def resolve_path(cls, v: Any) -> Path:
        if isinstance(v, str):
            return Path(v).resolve()
        if isinstance(v, Path):
            return v.resolve()
        return v


def load_config(config_path: Path) -> Config:
    """
    Load configuration from a TOML file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        Processed Config object.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config is invalid.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "rb") as f:
        raw_data = tomllib.load(f)

    raw_config = RawConfig(**raw_data)

    # Resolve workspace path
    workspace_path = Path(raw_config.workspace.path).resolve()

    # Create workspace object
    workspace = Workspace(
        path=workspace_path,
        current_branch="",  # Will be set during initialization
        worktree_dir=workspace_path / raw_config.workspace.worktree_dir,
        log_dir=workspace_path / raw_config.workspace.log_dir,
        state_dir=workspace_path / raw_config.workspace.state_dir,
    )

    # Process agent configs
    agents: dict[str, AgentConfig] = {}
    for name, agent_data in raw_config.agents.items():
        # Determine agent type
        agent_type_str = agent_data.get("type", "mock")
        try:
            agent_type = AgentType(agent_type_str)
        except ValueError:
            agent_type = AgentType.MOCK

        agents[name] = AgentConfig(
            type=agent_type,
            enabled=agent_data.get("enabled", True),
            command=agent_data.get("command", []),
            timeout=agent_data.get("timeout", 600),
            env=agent_data.get("env", {}),
            simulate_delay=agent_data.get("simulate_delay", True),
            min_delay=agent_data.get("min_delay", 0.5),
            max_delay=agent_data.get("max_delay", 2.0),
        )

    # Ensure mock agent is always available
    if "mock" not in agents:
        agents["mock"] = AgentConfig(
            type=AgentType.MOCK,
            enabled=True,
            simulate_delay=True,
            min_delay=0.5,
            max_delay=2.0,
        )

    return Config(
        workspace=workspace,
        mentor=raw_config.mentor,
        agents=agents,
        verify=raw_config.verify,
        ui=raw_config.ui,
        logging=raw_config.logging,
        config_path=config_path,
    )


def get_default_config() -> Config:
    """Get a default configuration for testing."""
    workspace_path = Path.cwd()

    workspace = Workspace(
        path=workspace_path,
        current_branch="main",
        worktree_dir=workspace_path / ".easycode/worktrees",
        log_dir=workspace_path / ".easycode/logs",
        state_dir=workspace_path / ".easycode/state",
    )

    agents = {
        "mock": AgentConfig(
            type=AgentType.MOCK,
            enabled=True,
            simulate_delay=True,
            min_delay=0.5,
            max_delay=2.0,
        ),
    }

    return Config(
        workspace=workspace,
        mentor=MentorConfig(),
        agents=agents,
        verify=VerifyConfig(),
        ui=UIConfig(),
        logging=LoggingConfig(),
        config_path=Path("config.toml"),
    )