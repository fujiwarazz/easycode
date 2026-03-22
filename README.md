
# Multi-Agent Coding Orchestrator MVP

一个基于 **Python + Textual** 的多 agent coding orchestrator MVP。  
目标是实现一个类似 **Claude Code** 风格的 **TUI 工作台**，可以在同一个 git 仓库内同时调度多个 coding CLI（如 Claude Code CLI、Codex CLI、Gemini CLI），由一个 **mentor** 负责规划、分发、验收，并通过 **git worktree** 为每个 agent/task 提供独立隔离环境。

---

# 1. 项目目标

本项目需要实现一个本地可运行的 MVP，满足以下核心需求：

- 打开一个本地 git 仓库作为 workspace
- 支持配置多个 coding agent CLI
- 支持从多个 agent 中指定一个作为 mentor
- mentor 根据用户目标拆分任务
- 每个子任务在独立 git worktree 中执行
- agent 执行后收集：
  - summary
  - changed files
  - git diff
  - stdout/stderr logs
  - 测试结果
- mentor 对结果进行验收并触发 merge
- 提供一个类似 Claude Code 的 TUI 页面：
  - 顶部状态栏
  - 左侧 agents / tasks
  - 中间会话与日志流
  - 右侧详情 / diff / worktree 状态
  - 底部 prompt 输入栏

---

# 2. MVP 范围

## 必须支持

1. 本地 git repo workspace
2. 多 agent 配置加载
3. mentor agent 配置
4. mentor 任务拆分
5. worktree 创建与管理
6. agent 执行任务
7. diff / changed files / logs 收集
8. 单 task merge
9. TUI 展示：
   - agents
   - tasks
   - logs
   - diff 摘要
   - worktree 状态
10. 基础消息接收与发送机制
11. 基于事件总线的流式 UI 更新

## 暂不支持

- 云同步
- 多人协作
- 权限系统
- 复杂 DAG 调度
- 自动解决复杂 merge conflict
- 长期记忆
- GUI 桌面版
- 复杂成本统计
- 智能自动路由
- 完整 sandbox

---

# 3. 技术选型

- **语言**: Python 3.11+
- **TUI**: Textual
- **终端渲染**: Rich
- **数据模型**: Pydantic
- **异步执行**: asyncio
- **Git 操作**: subprocess 调用 git
- **配置**: TOML
- **状态持久化**: JSON 或 SQLite（优先简单）
- **日志**: 写入本地文件 `data/logs/`

---

# 4. 设计原则

## 4.1 先跑通主链路
优先完成以下主链路：

- 打开 repo
- mentor 生成 plan
- 创建 worktree
- agent 执行 task
- 收集 diff / logs
- merge 单个 task

不要一开始过度抽象，不要提前实现复杂自动化。

## 4.2 mentor 只负责规划与验收
mentor 的职责应聚焦于：

- 接收用户目标
- 输出 task plan
- 分配 agent
- 审查结果
- 决定 merge / retry / reject

mentor 不应成为唯一执行者。

## 4.3 每个 task 必须在独立 worktree 中执行
禁止多个 agent 直接在主工作区同时改动。  
每个 task 都应该拥有：

- 独立 branch
- 独立 worktree path
- 独立日志
- 独立 diff

## 4.4 用统一事件流驱动系统
TUI 不应直接轮询每个 agent 进程。  
系统必须通过统一事件总线传递消息，并由 TUI 订阅更新。

## 4.5 真实 CLI 不稳定时要可降级
若 Claude / Codex / Gemini CLI 自动化调用不稳定，必须提供 `MockAgentAdapter`，保证整体 MVP 可演示。

---

# 5. 总体架构

系统分为五层：

## 5.1 TUI Layer
负责：
- 接收用户输入
- 展示 agents/tasks/logs/diff/worktree 状态
- 展示 recent activity / tips
- 通过事件流更新 UI

## 5.2 Controller Layer
负责：
- 接收用户命令或自然语言目标
- 路由到 planner / orchestrator / merge
- 更新状态
- 向事件总线发布系统事件

## 5.3 Planner / Mentor Layer
负责：
- 将用户目标转换成结构化 task plan
- 指定每个 task 的执行 agent
- 定义 acceptance criteria
- 规划失败时 fallback 到规则拆分

## 5.4 Agent Adapter Layer
负责：
- 统一封装不同 coding CLI
- 在对应 worktree 中执行任务
- 流式输出 stdout/stderr/progress/summary
- 收集 diff 与 changed files

## 5.5 Git / Storage Layer
负责：
- workspace 校验
- worktree 生命周期
- merge
- verify hooks
- 状态与日志持久化

---

# 6. 目录结构

请按以下目录组织代码：

```text
multiagent_orchestrator/
  main.py
  requirements.txt
  README.md
  config.example.toml

  orchestrator/
    __init__.py
    models.py
    events.py
    state.py
    controller.py
    planner.py

  agents/
    __init__.py
    base.py
    claude_cli.py
    codex_cli.py
    gemini_cli.py
    mock_agent.py
    registry.py

  gitops/
    __init__.py
    worktree.py
    diff.py
    merge.py
    verify.py

  storage/
    __init__.py
    repo.py

  tui/
    __init__.py
    app.py
    screens.py
    widgets.py
    command_parser.py

  utils/
    __init__.py
    proc.py
    config.py
    logging.py
    paths.py

  data/
    logs/
    state/
    worktrees/
````

---

# 7. 核心数据模型

请使用 Pydantic 定义核心模型。

## 7.1 Workspace

字段建议：

* `id: str`
* `repo_path: str`
* `base_branch: str`
* `mentor_agent_id: str`
* `created_at: datetime`
* `status: str`

职责：

* 校验路径为 git repo
* 获取 base branch
* 初始化 data 目录
* 加载配置与状态

---

## 7.2 AgentConfig

字段建议：

* `id: str`
* `name: str`
* `kind: str`  # claude / codex / gemini / mock
* `command: str`
* `args: list[str]`
* `enabled: bool`
* `is_mentor_capable: bool`

---

## 7.3 Task

字段建议：

* `id: str`
* `title: str`
* `description: str`
* `status: str`  # pending/running/done/failed/merged/rejected
* `assigned_agent_id: str | None`
* `worktree_id: str | None`
* `parent_task_id: str | None`
* `acceptance_criteria: list[str]`
* `file_scope: list[str]`
* `summary: str | None`
* `created_at: datetime`
* `updated_at: datetime`

---

## 7.4 WorktreeSession

字段建议：

* `id: str`
* `task_id: str`
* `agent_id: str`
* `branch_name: str`
* `worktree_path: str`
* `base_commit: str`
* `status: str`
* `changed_files: list[str]`
* `last_diff_path: str | None`

---

## 7.5 RunResult

字段建议：

* `task_id: str`
* `agent_id: str`
* `exit_code: int`
* `summary: str`
* `stdout_log_path: str`
* `stderr_log_path: str`
* `diff_text: str`
* `changed_files: list[str]`
* `test_output: str`
* `success: bool`

---

# 8. 消息接收与发送机制

这是本项目的关键机制之一。
系统不能只靠函数返回值工作，必须支持**流式消息**，这样 TUI 才能像 Claude Code 一样实时显示状态。

## 8.1 消息来源

系统中至少有 4 类消息：

### UserMessage

来自底部 prompt 输入框，用于：

* 创建目标
* 生成计划
* 运行任务
* merge 任务
* retry 任务
* 切换 mentor
* 查看 diff / logs

### MentorMessage

来自 mentor/planner，用于：

* 创建计划
* 分配任务
* 结果验收
* merge 建议
* retry / reject 建议

### AgentEvent

来自 agent 执行器，用于：

* started
* stdout
* stderr
* progress
* summary
* completed
* failed

### SystemEvent

来自 orchestrator/git/merge/verify，用于：

* task created
* worktree created
* verify started/completed/failed
* merge started/completed/failed
* task status changed

---

## 8.2 统一事件模型

请定义统一事件模型，例如：

```python
from pydantic import BaseModel
from typing import Any
from datetime import datetime

class Event(BaseModel):
    id: str
    ts: datetime
    type: str
    source: str
    task_id: str | None = None
    agent_id: str | None = None
    payload: dict[str, Any] = {}
```

---

## 8.3 推荐事件类型

至少支持以下事件类型：

* `user.message`
* `mentor.plan.created`
* `mentor.review.approved`
* `mentor.review.rejected`
* `task.created`
* `task.assigned`
* `task.started`
* `task.completed`
* `task.failed`
* `agent.stdout`
* `agent.stderr`
* `agent.summary`
* `worktree.created`
* `worktree.cleaned`
* `merge.started`
* `merge.completed`
* `merge.failed`
* `verify.started`
* `verify.completed`
* `verify.failed`

---

## 8.4 事件总线

MVP 阶段不需要复杂消息中间件。
请使用：

* `asyncio.Queue` 作为内存事件总线
* controller 作为消息路由中心
* data/logs 作为日志持久化

要求：

* 所有 agent 流式输出都要写入事件总线
* TUI 订阅事件总线进行刷新
* 关键事件持久化到本地

---

# 9. 输入命令协议

TUI 底部输入框必须支持两种输入：

## 9.1 普通自然语言目标

如果输入不以 `/` 开头，则视为用户目标，交给 mentor/planner 处理。

例如：

```text
实现 billing 模块导出功能，并补测试
```

---

## 9.2 命令输入

如果输入以 `/` 开头，则视为命令。

至少支持以下命令：

* `/plan <goal>`
* `/run <task_id>`
* `/merge <task_id>`
* `/retry <task_id>`
* `/mentor <agent_id>`
* `/agents`
* `/tasks`
* `/logs <task_id>`
* `/diff <task_id>`
* `/help`

示例：

```text
/plan 为 billing 模块增加导出功能
/run task-1
/merge task-1
/retry task-2
/mentor claude
```

---

## 9.3 命令解析器

请实现一个 `command_parser.py`，负责：

* 识别命令与参数
* 区分自然语言目标与命令
* 返回统一的 command model

---

# 10. Planner / Mentor 机制

实现 `MentorPlanner`，将用户目标转换成结构化任务列表。

## 10.1 输入

* 用户目标文本
* 当前 repo 路径
* 可用 agent 列表

## 10.2 输出格式

统一输出以下结构：

```json
{
  "goal": "实现功能X",
  "tasks": [
    {
      "title": "后端实现",
      "description": "完成后端逻辑",
      "acceptance_criteria": ["通过相关测试", "接口可用"],
      "file_scope": ["backend/", "api/"],
      "assigned_agent_id": "claude"
    },
    {
      "title": "测试补充",
      "description": "增加测试覆盖",
      "acceptance_criteria": ["新增测试通过"],
      "file_scope": ["tests/"],
      "assigned_agent_id": "codex"
    }
  ]
}
```

## 10.3 规划策略

### 优先使用 mentor agent

如果 mentor agent 可用，则尝试让其输出 JSON 任务计划。

### 失败时 fallback 到规则拆分

例如：

* 若目标中含 `test` / `测试` -> 增加测试任务
* 若目标中含 `doc` / `文档` -> 增加文档任务
* 否则默认拆成：

  * 实现任务
  * 测试任务

---

# 11. Agent 抽象层

定义统一的 adapter 接口。

## 11.1 BaseAgentAdapter

```python
from abc import ABC, abstractmethod

class BaseAgentAdapter(ABC):
    id: str
    name: str
    kind: str

    @abstractmethod
    async def run_task_stream(
        self,
        task_prompt: str,
        worktree_path: str,
        context_files: list[str] | None = None,
    ):
        """Yield AgentEvent/Event objects during execution."""
        ...
```

## 11.2 要求

每个 adapter 负责：

* 启动对应 CLI
* 将 cwd 切换到 `worktree_path`
* 捕获 stdout/stderr
* 以流式事件形式输出执行过程
* 在结束时生成 `RunResult`

---

## 11.3 MockAgentAdapter

必须实现一个 `MockAgentAdapter`，用于：

* 输出模拟 stdout/stderr
* 模拟文件修改
* 模拟 diff 结果
* 演示完整主链路

如果真实 CLI 自动化有问题，MVP 仍必须可运行。

---

# 12. Git Worktree 管理

在 `gitops/worktree.py` 中实现：

## 12.1 create_worktree(task, agent, workspace)

行为：

* 从 `base_branch` 创建 task branch
* branch 名格式：

```text
task/<task_id>/<agent_id>
```

* worktree 路径格式：

```text
data/worktrees/<task_id>--<agent_id>
```

* 记录 base commit

## 12.2 collect_diff(worktree_path)

返回：

* `git diff --stat`
* `git diff`

## 12.3 changed_files(worktree_path)

返回变更文件列表

## 12.4 cleanup_worktree(worktree_path)

保留接口，本版可不自动删除

要求：

* 所有 git 操作都用 subprocess
* 捕获异常
* 写入日志
* 实现尽量简单可靠

---

# 13. Task 执行流程

单个 task 的执行流程应如下：

1. Controller 接收 `/run <task_id>`
2. 创建 worktree
3. 发布 `worktree.created`
4. 更新 task 状态为 `running`
5. 发布 `task.started`
6. 调用对应 agent adapter
7. agent 持续产出：

   * `agent.stdout`
   * `agent.stderr`
   * `agent.summary`
8. agent 完成后生成 `RunResult`
9. 收集 changed files 与 diff
10. 更新 task 状态为 `done` 或 `failed`
11. 发布 `task.completed` 或 `task.failed`

---

# 14. Merge 流程

当前版本先只支持 **单 task merge**。

## 14.1 merge_task_result(task)

行为：

1. 切回主 repo
2. merge task branch 到 integration branch 或 base branch
3. 执行 verify commands
4. 成功则标记 `merged`
5. 失败则标记 `failed`

## 14.2 Verify 规则

从配置文件读取：

```toml
[verify]
commands = ["pytest -q"]
```

执行规则：

* 逐条执行命令
* 记录 stdout / stderr
* 发布：

  * `verify.started`
  * `verify.completed`
  * `verify.failed`

---

# 15. 配置文件

请支持 TOML 配置，并提供 `config.example.toml`：

```toml
[workspace]
repo_path = "/path/to/repo"
base_branch = "main"
mentor_agent = "claude"

[verify]
commands = ["pytest -q"]

[[agents]]
id = "claude"
kind = "claude"
name = "Claude Code"
command = "claude"
args = []
enabled = true
is_mentor_capable = true

[[agents]]
id = "codex"
kind = "codex"
name = "Codex CLI"
command = "codex"
args = []
enabled = true
is_mentor_capable = true

[[agents]]
id = "gemini"
kind = "gemini"
name = "Gemini CLI"
command = "gemini"
args = []
enabled = true
is_mentor_capable = false

[[agents]]
id = "mock"
kind = "mock"
name = "Mock Agent"
command = "python"
args = []
enabled = true
is_mentor_capable = true
```

要求：

* 配置读取失败时要给出明确错误
* 若真实 CLI 不可用，可退回 mock agent 演示

---

# 16. TUI 需求

使用 **Textual** 实现类似 Claude Code 风格的主界面。

## 16.1 页面布局

### 顶部

显示：

* workspace 路径
* base branch
* mentor
* 当前状态

### 左侧

显示：

* agent 列表
* task 列表

### 中间

显示：

* welcome panel
* 当前会话消息流
* task logs
* system messages

### 右侧

显示：

* 选中 task 详情
* worktree 信息
* changed files
* diff 摘要
* recent activity / tips

### 底部

显示：

* prompt 输入框
* 快捷键提示

---

## 16.2 快捷键

至少支持：

* `n`：新建目标
* `p`：生成计划
* `r`：运行选中任务
* `m`：merge 选中任务
* `d`：查看 diff
* `l`：查看日志
* `q`：退出

---

## 16.3 UI 更新原则

TUI 不直接读进程输出，而应：

* 订阅事件总线
* 收到新事件后更新对应 panel
* task 状态变化时刷新 task 列表
* agent 状态变化时刷新 agent 列表
* diff / summary 到达时刷新详情区域

---

# 17. 开发优先级

请严格按以下阶段开发：

## Phase 1：基础骨架

* 项目目录
* requirements.txt
* 配置加载
* Workspace 校验
* Pydantic models
* Event 模型
* asyncio.Queue 事件总线
* worktree 创建

## Phase 2：Task 执行链路

* BaseAgentAdapter
* MockAgentAdapter
* CLI adapter 骨架
* task 执行
* stdout/stderr 事件流
* diff / changed files 收集

## Phase 3：Planner 与命令协议

* MentorPlanner
* JSON 计划结构
* fallback 规则拆分
* command_parser
* `/plan /run /merge /retry /mentor`

## Phase 4：TUI

* Textual 主界面
* agents/tasks/logs/diff/worktree panels
* prompt bar
* 事件驱动刷新

## Phase 5：Merge 与验证

* merge_task_result
* verify hooks
* merge 结果展示
* 错误处理完善

---

# 18. 最小可运行路径

最终 MVP 至少要跑通以下路径：

## Path A：创建目标 -> mentor 拆任务 -> 展示任务列表

## Path B：运行某个 task -> 在独立 worktree 中执行 -> 返回日志和 diff

## Path C：merge 某个 task -> 执行验证 -> 标记 merged / failed

## Path D：通过事件流实时刷新 TUI 面板

---

# 19. 代码质量要求

* 使用 type hints
* 公共模块添加 docstring
* subprocess 调用统一封装并捕获异常
* 日志写入 `data/logs/`
* 不要过度抽象
* 优先可运行与可读性
* 依赖尽量少
* 先保证 mock path 完整可跑

---

# 20. requirements.txt 建议

至少包含：

```txt
textual
rich
pydantic
tomli; python_version < "3.11"
```

可选：

```txt
typing-extensions
```

不要一开始引入太多额外依赖。

---

# 21. 启动方式

请实现一个最简单的入口，例如：

```bash
python main.py --config config.example.toml
```

要求：

* 可以成功加载配置
* 可以打开 TUI
* mock 模式下可演示完整主链路
* 即使真实 CLI 不可用，系统也可以跑通

---

# 22. 已知限制

请在最终实现版 README 中明确这些限制：

* 某些真实 coding CLI 可能无法稳定非交互运行
* 当前 merge 只支持简单场景
* 当前仅支持本地单机
* 任务规划仍较基础
* 复杂冲突处理尚未实现
* verify 逻辑主要依赖外部配置命令
* 目前不做真正多 agent 自主对话，只做 orchestrator 驱动式协作

---

# 23. 最终交付要求

实现完成后请输出：

1. 完整目录结构
2. 关键模块代码
3. `requirements.txt`
4. `config.example.toml`
5. `README.md`
6. 一个可运行示例
7. 若真实 CLI 接入不稳定，提供 `mock` 完整演示路径

---

# 24. 给实现者的说明

请优先交付一个 **真实可运行的 Python TUI MVP**。
重点不是完美架构，而是把下面这些真实打通：

* workspace
* prompt 输入
* plan 生成
* task 列表
* worktree 创建
* agent 流式输出
* diff/logs 展示
* merge
* verify
* 事件驱动 UI 刷新

若真实 CLI 接入困难，请先保证 `MockAgentAdapter` + TUI + worktree + merge 主链路完全可演示。

````

你可以再配一句一起发给 Claude Code：

```text
请严格按 README.md 实现。优先保证 mock agent 路径完整可运行，再补 claude/codex/gemini adapter 骨架。不要过度设计，先把事件流、TUI、worktree、task run、merge 主链路打通。
````


