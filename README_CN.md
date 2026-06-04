# Sarma

**[English](README.md)** | **中文**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma 是一个轻量级终端漏洞审计 agent。它在任意 MCP 工具集
（例如 [IDA-MCP](https://github.com/Captain-AI-Hub/IDA-MCP)）之上驱动
LangGraph ReAct agent，在终端中实时流式输出推理与工具调用，并提供一个可选的
8 阶段审计 pipeline，用于结构化的逆向工程工作流。

## 安装

需要 Python 3.12+。

```bash
git clone https://github.com/Captain-AI-Hub/Sarma.git
cd Sarma
uv sync
```

这会创建本地 `.venv` 并安装 `sarma` 命令。使用下面的命令运行：

```bash
uv run sarma
```

开发时也可以直接运行启动器：

```bash
uv run python src/main.py
```

## 快速开始

```bash
# 1. 直接启动 shell
uv run sarma

# 2. 在 shell 中交互式配置模型（保存到 ~/.sarma）
sarma [ruflo]> /config

# 单次非交互执行（需已配置模型）
uv run sarma -c "审计 ./target.bin 固件中的命令注入漏洞"
```

`/config` 会打开全屏 Textual TUI 来管理模型和工作流 agents。它会保存
`./.sarma/models.toml` 和 `./.sarma/agents.toml`。修改在当前会话的下一轮即生效。
MCP server 定义通过 `/plugin` 管理。

## 工作流

Sarma 运行在多种工作流之一；可随时切换，下一轮生效。

| 工作流 | 进入方式 | 作用 |
|--------|----------|------|
| `ruflo`（默认） | `uv run sarma` / `/workflow ruflo` | 主 agent 可委派 focused subagents 的对话工作流 |
| `audit` | `uv run sarma workflow audit` / `/workflow audit` | 完整 harness:recon → hunt → validate（⇄ gapfill）→ dedupe → trace → feedback（↺ hunt）→ report |
| `audit-slim` | `/workflow audit-slim` | 紧凑 harness：recon → hunter ⇄ verify → report |

REPL 提示符会显示当前工作流：`sarma [ruflo]>`、`sarma [audit]>` 或 `sarma [audit-slim]>`。

### Ruflo

`ruflo` 是默认对话工作流。它运行一个 primary ReAct agent；必要时会把明确、聚焦的
子任务委派给 subagents，然后把紧凑的 subagent 结果综合成面向用户的回答。

```text
user
  ↓
primary agent
  ├─ optional delegate_task → focused subagent
  ├─ optional delegate_task → focused subagent
  └─ synthesize compact results → answer
```

`ruflo` 的 subagents 返回紧凑结果模板，而不是完整隐藏推理轨迹，避免委派任务把共享
上下文撑爆。

### Audit

`audit` 是完整漏洞发现 harness。它包含 8 个 specialist agents，以及 3 个 router
nodes：

| Agent | 职责 |
|-------|------|
| `recon` | 探测二进制/项目架构、metadata、入口点、imports/exports、strings、functions 和 trust boundaries |
| `hunt` | 搜索 dangerous sinks 和漏洞候选 |
| `validate` | 确认候选是否可达、真实、且未被过滤或防护 |
| `gapfill` | 识别覆盖缺口，并要求继续 hunt 或重新 validate |
| `dedupe` | 合并重复 findings，并按 root cause 聚类 |
| `trace` | 构建从外部输入到漏洞 sink 的数据流/控制流路径 |
| `feedback` | 审查证据质量，把弱证据 findings 退回 hunt |
| `report` | 生成最终漏洞报告 |

执行图不是简单单向链路。`gapfill` 是 `validate` 的有界侧支，`feedback` 可以把弱
findings 退回 `hunt`：

```text
START
  ↓
recon
  ↓
hunt
  ↓
validate
  ↓
validate_check
  ├─ gaps / unresolved → gapfill → gapfill_check
  │                         ├─ needs new candidates → hunt
  │                         └─ needs re-check      → validate
  └─ ok → dedupe
          ↓
        trace
          ↓
        feedback
          ↓
        feedback_check
          ├─ weak / insufficient → hunt
          └─ ok → report
                    ↓
                   END
```

循环有上限，保证 harness 一定收敛：`validate`/`gapfill` 最多循环 3 次；
`feedback` 回到 `hunt` 最多 2 次。

每个 audit agent 都会收到原始用户 audit task 和前序 `stage_outputs`。agent 之间
不会传递前一个 agent 的完整 token/tool trace；共享的是结构化阶段结果，避免上下文
失控。

### Audit-Slim

`audit-slim` 是用于快速审计的四阶段紧凑 harness：

| Agent | 职责 |
|-------|------|
| `recon` | 探测整体架构/框架，并识别薄弱区域 |
| `hunter` | 基于 recon 的薄弱区域执行漏洞审计 |
| `verify` | 确认 hunter 的 findings 是否真实可靠 |
| `report` | 只报告 verify 确认可靠的 findings |

```text
START
  ↓
recon
  ↓
hunter
  ↓
verify
  ├─ needs-hunter / weak / unsupported → hunter
  └─ verified → report
                  ↓
                 END
```

`hunter` 和 `verify` 构成反馈循环。`verify` 认为 findings 还不够可靠时，会以
`needs-hunter` 开头并给出 hunter 必须处理的具体反馈；当 findings 可以进入报告时，
以 `verified` 开头。`verify -> hunter` 循环最多 3 次。

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 列出命令 |
| `/status` | 模型、MCP servers 和 skills 状态 |
| `/graph` | 渲染当前工作流的执行图 |
| `/workflow [name]` | 列出工作流，或切换到某个工作流 |
| `/plugin` | 管理 MCP 和 skill plugins |
| `/restart` | 重启当前 workflow runtime |
| `/models` | 显示已配置的模型 |
| `/history` | 列出历史会话 |
| `/resume <id>` | 恢复历史会话 |
| `/config` | 打开全屏工作区配置 TUI |
| `/clear` | 清空当前会话 |
| `/compact` | 把旧上下文整理成结构化 memory |
| `/exit` | 退出 |

## 配置

配置拆分为工作区 TOML 文件。首次在某个工作区运行时，Sarma 会在 `~/.sarma` 下创建
全局默认配置，并复制到 `./.sarma`，这样每个项目都可以独立调整。

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
max_context_tokens = 128000
```

`./.sarma/agents.toml` 用于给工作流 agent 分配模型、MCP servers 和 skills：

```toml
[[agents]]
name = "ruflo"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.recon"
model = "default"
mcp = ["local-http-tools"]
skills = ["*"]
```

`["*"]` 表示允许使用全部已配置 MCP servers 或全部已安装 skills。
`./.sarma/mcp.toml` 保存 MCP server 定义：

```toml
[[mcp_servers]]
name = "local-http-tools"
transport = "http"   # stdio | http | sse
url = "http://127.0.0.1:8000/mcp"
enabled = true
```

设置 `SARMA_HOME` 可重定向全局配置目录（设置后它即为 sarma 目录本身）。

会话历史按工作区存储在 `./.sarma/db.sqlite`。

## 上下文整理

Sarma 只会在估算的 conversation tokens 接近当前模型窗口
（`max_context_tokens`）时自动整理上下文。它会尽量保留预算内最近的原始上下文，
把更早的内容转换为结构化 memory：目标、约束、决策、实体、已验证事实、工具结果、
未完成任务和风险。`/compact` 可以手动触发同一流程。
`/config` 里的最大上下文窗口支持 `200K`、`1M` 这类简写；保存配置时会展开为整数
token 数。

## Plugins

`/plugin` 会打开全屏 Textual plugin 管理界面，用于管理 MCP servers 和 skill
模板。MCP 区域可以快速创建 stdio、http 或 sse MCP 配置并写入
`./.sarma/mcp.toml`；Skills 区域可以安装本地 skill 目录、`skills.zip`、远程 zip
链接，或安装 Skillshub 搜索结果。

Skills 是包含 `SKILL.md` 的目录。工作区 skills 位于
`./.sarma/skills/<name>`，全局 skills 位于 `~/.sarma/skills/<name>`。
plugin 变更会在安装/保存前校验。手动改配置后可以用 `/restart` 重启 runtime；
通过 `/plugin` 保存的变更会自动请求 runtime restart。安装后通过 `/config` 把
skill 分配给工作流或 agent。

## Terminal UI 边界

Sarma 使用三个终端 UI 库，并保持明确边界：

- `prompt_toolkit`：只负责轻量 REPL 输入行（`sarma [ruflo]>`）和输入历史。
- `Rich`：负责非全屏输出，例如表格、状态面板、markdown 风格流式渲染和命令反馈。
- `Textual`：负责全屏配置应用。`/config` 通过 `src/sarma_cli/tui/` 管理模型和
  agents；`/plugin` 管理 MCP servers 和 skills。

## 项目结构

```text
Sarma/
├── pyproject.toml          # 包配置 + `sarma` 入口
├── pytest.ini              # 测试配置
├── README.md / README_CN.md
└── src/
    ├── main.py             # 开发启动器（python src/main.py）
    └── sarma_cli/
        ├── __main__.py     # CLI 入口：init / workflow / plugin + REPL
        ├── app.py          # 交互式 REPL 循环
        ├── session.py      # 会话生命周期（工作流感知）
        ├── config.py       # 分层全局+本地配置加载
        ├── paths.py        # 跨平台路径解析
        ├── store.py        # SQLite 持久化
        ├── renderer.py     # 实时流式输出
        ├── status.py       # 状态面板
        ├── resources/      # 插件目录和 skill 资源加载
        ├── engine/         # Agent 运行时（LangGraph、MCP 连接池、审计图、prompts）
        ├── runtime/        # 配置到运行计划的策略解析
        ├── tui/            # Textual 全屏应用
        ├── workflows/      # ruflo + audit 工作流定义
        └── commands/       # 斜杠命令处理
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。
