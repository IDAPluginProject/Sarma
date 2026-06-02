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
pip install -e .
```

这会安装 `sarma` 命令。开发时也可以不安装直接运行：

```bash
python src/main.py
```

## 快速开始

```bash
# 1. 直接启动 shell
sarma

# 2. 在 shell 中交互式配置模型（保存到 ~/.sarma）
sarma [chat]> /config

# 单次非交互执行（需已配置模型）
sarma -c "审计 ./target.bin 固件中的命令注入漏洞"
```

`/config` 会依次询问模型名、API 接口模式、Base URL、API key，然后保存到
`~/.sarma/config.toml`。修改在当前会话的下一轮即生效。（命令行参数
`-m/--api-key/--base-url/--api-mode` 仍作为可选覆盖保留，便于脚本化 `-c`。）

## 工作流

Sarma 运行在多种工作流之一；可随时切换，下一轮生效。

| 工作流 | 进入方式 | 作用 |
|--------|----------|------|
| `chat`（默认） | `sarma` / `/workflow chat` | 与 agent 及其工具直接进行 ReAct 对话 |
| `audit` | `sarma workflow audit` / `/workflow audit` | 完整 harness:recon → hunt → validate（⇄ gapfill）→ dedupe → trace → feedback（↺ hunt）→ report |
| `audit-slim` | `/workflow audit-slim` | 轻量三阶段:recon（负责审计）→ verify（确保结果真实可靠）→ report（验证结果并给用户反馈） |

REPL 提示符会显示当前工作流：`sarma [chat]>`、`sarma [audit]>` 或 `sarma [audit-slim]>`。

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 列出命令 |
| `/status` | 模型、MCP 工具数量、skills 状态 |
| `/graph` | 渲染当前工作流的执行图 |
| `/workflow [name]` | 列出工作流，或切换到某个工作流 |
| `/models` | 显示已配置的模型 |
| `/history` | 列出历史会话 |
| `/resume <id>` | 恢复历史会话 |
| `/config` | 显示当前配置 |
| `/clear` | 清空当前会话 |
| `/exit` | 退出 |

## 配置

配置为分层 TOML。`sarma init` 写入**全局**文件 `~/.sarma/config.toml`
（Windows 上为 `C:\Users\<你>\.sarma\config.toml`）。可选地，`sarma init --local`
在当前工作区写入 `./.sarma/config.toml`，用于按字段覆盖全局配置。

优先级顺序（高者覆盖低者）：

```
命令行参数  >  环境变量  >  ./.sarma/config.toml（本地）  >  ~/.sarma/config.toml（全局）
```

本地文件按字段合并到全局文件之上——只在本地设 `model_name`，其余（API key、MCP
servers）全部继承全局。MCP servers 按 **name 合并**：同名的本地 server 覆盖全局，
新名字则追加。

```toml
[provider]
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
temperature = 0.7

# 每个 MCP server 重复一个 [[mcp_servers]]
[[mcp_servers]]
name = "ida-mcp"
transport = "streamable_http"
url = "http://127.0.0.1:11338/mcp"
enabled = true
```

环境变量覆盖：`SARMA_MODEL`、`SARMA_API_KEY`、`SARMA_BASE_URL`、`SARMA_API_MODE`。
设置 `SARMA_HOME` 可重定向全局配置目录（设置后它即为 sarma 目录本身）。

会话历史按工作区存储在 `./.sarma/db.sqlite`。

## 项目结构

```text
Sarma/
├── pyproject.toml          # 包配置 + `sarma` 入口
├── pytest.ini              # 测试配置
├── README.md / README_CN.md
└── src/
    ├── main.py             # 开发启动器（python src/main.py）
    └── sarma_cli/
        ├── __main__.py     # CLI 入口：init / workflow / install + REPL
        ├── app.py          # 交互式 REPL 循环
        ├── session.py      # 会话生命周期（工作流感知）
        ├── config.py       # 分层全局+本地配置加载
        ├── paths.py        # 跨平台路径解析
        ├── store.py        # SQLite 持久化
        ├── renderer.py     # 实时流式输出
        ├── status.py       # 状态面板
        ├── engine/         # Agent 运行时（LangGraph、MCP 连接池、审计图、prompts）
        ├── workflows/      # chat + audit 工作流定义
        └── commands/       # 斜杠命令处理
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。

