# Sarma

**[English](README.md)** | **中文**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma 是一个全屏终端漏洞审计 agent。它把 Textual 聊天界面、LangGraph 工作流、
LangChain agents、MCP 工具和工作区级配置组合在一起，用于逆向工程和安全审计。

Sarma 主要面向 IDA-MCP 这类工具密集型二进制审计场景，但运行时可以接入任意已配置
的 MCP server。

## 功能

- 全屏 Textual TUI：聊天区、输入栏、运行状态侧边栏、工作流图。
- `ruflo`：默认对话工作流，主 agent 可委派聚焦子任务。
- `audit`：完整多阶段漏洞发现工作流。
- `audit-slim`：紧凑的 recon / hunter / verify / report 工作流。
- 支持按工作流和子 agent 配置模型、MCP 和 skills。
- 通过 `/plugin` 管理 MCP servers 和安装 skills。
- 按模型上下文窗口自动整理旧上下文。
- 原生安装包：Windows MSI、macOS pkg、Linux deb、Linux Arch 风格
  pkg.tar.zst。

## 从源码安装

需要 Python 3.12+ 和 `uv`。

```bash
git clone https://github.com/Captain-AI-Hub/Sarma.git
cd Sarma
uv sync
uv run sarma
```

配置模型后可以使用单次执行模式：

```bash
uv run sarma -c "审计当前加载目标中的命令注入风险"
```

## 首次使用

启动 Sarma：

```bash
uv run sarma
```

然后在 TUI 输入栏输入：

```text
/config
```

至少配置一个模型。配置界面中：

- Model name：Sarma 本地模型别名，workflow agents 通过它引用模型。
- Model ID：provider 的真实模型 id，例如 `gpt-4o`、`claude-sonnet-4-5`
  或 OpenAI-compatible 模型 id。
- API mode：`openai_compatible`、`openai_responses` 或 `anthropic`。
- Max context window：支持 `128000`、`200K`、`1M` 等写法。

使用 `/plugin` 配置 MCP servers 和安装 skills。

## 工作流

| 工作流 | 作用 |
|--------|------|
| `ruflo` | 默认对话工作流，支持聚焦子任务委派 |
| `audit` | 完整漏洞发现 harness |
| `audit-slim` | 更小的四阶段审计 harness |

切换工作流：

```text
/workflow audit
/workflow audit-slim
/workflow ruflo
```

工作流切换会在下一轮用户输入时生效。

### Ruflo

`ruflo` 运行一个 primary ReAct agent。它可以调用 `delegate_task` 启动聚焦
subagent，然后把紧凑的 subagent 结果综合成最终回答。

```text
user
  -> primary agent
      -> optional delegate_task -> focused subagent
      -> optional delegate_task -> focused subagent
  -> final answer
```

### Audit

`audit` 是完整工作流：

```text
START
  -> recon
  -> hunt
  -> validate
  -> validate_check
       -> gapfill -> gapfill_check -> hunt | validate
       -> dedupe
  -> trace
  -> feedback
  -> feedback_check -> hunt | report
  -> END
```

阶段说明：

- `recon`：目标架构、metadata、入口点、imports/exports、strings、functions
  和 trust boundaries。
- `hunt`：漏洞候选和 dangerous sinks。
- `validate`：对候选做全链路真实性验证。
- `gapfill`：覆盖缺口和针对性补充工作。
- `dedupe`：重复项和 root cause 聚合。
- `trace`：数据流/控制流证据。
- `feedback`：证据质量审查。
- `report`：最终漏洞报告。

分支决策由同模型 structured router call 完成。可见的 subagent 输出仍是普通
Markdown，不需要在聊天内容中输出路由 JSON。

### Audit-Slim

`audit-slim` 是紧凑工作流：

```text
START -> recon -> hunter <-> verify -> report -> END
```

- `recon`：梳理整体架构和薄弱区域。
- `hunter`：围绕薄弱区域审计漏洞候选。
- `verify`：确认 findings 是否真实可靠，并把弱证据退回 `hunter`。
- `report`：只报告已验证的 findings。

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 列出命令 |
| `/status` | 显示模型和 MCP 状态 |
| `/graph` | 显示当前工作流图 |
| `/workflow [name]` | 列出或切换工作流 |
| `/models` | 显示已配置模型 |
| `/history` | 列出历史会话 |
| `/resume <id>` | 恢复历史会话 |
| `/config` | 打开模型和工作流配置 |
| `/plugin` | 管理 MCP servers 和 skills |
| `/restart` | 重启运行时资源 |
| `/compact` | 把旧上下文整理为结构化 memory |
| `/clear` | 清空当前会话 |
| `/exit` | 退出 |

## 配置文件

Sarma 会在 `~/.sarma` 下创建全局默认配置，并把缺失文件复制到当前工作区
`./.sarma`。运行时以工作区配置为准。

```text
./.sarma/
  models.toml
  agents.toml
  mcp.toml
  skills/
  db.sqlite
```

`models.toml`：

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"
max_context_tokens = 128000
enabled = true
```

`agents.toml`：

```toml
[[agents]]
name = "ruflo"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.recon"
model = "default"
mcp = ["ida-mcp"]
skills = ["*"]
```

`mcp.toml`：

```toml
[[mcp_servers]]
name = "ida-mcp"
transport = "http" # stdio | http | sse
url = "http://127.0.0.1:8000/mcp"
enabled = true
```

## 上下文和状态

当估算 token 接近模型上下文窗口时，Sarma 会自动整理旧上下文。旧内容会转成结构化
memory，最近内容尽量保持原文。`/compact` 可以手动触发同一流程。

LangGraph checkpointer/store 是运行时内存辅助服务。持久化历史和 memory artifacts
由 Sarma 自己的 `./.sarma/db.sqlite` 保存。

Cache 当前故意不启用。审计依赖可变外部状态，例如加载的 binary、IDA 数据库变更、
MCP 连接状态和工具结果。错误 cache 命中可能隐藏已经变化的证据。

## 原生安装包

原生安装包必须在对应 OS/架构上本机构建。Sarma 不做 Nuitka 交叉编译。

| 目标 | 安装包 |
|------|--------|
| Windows x86_64 | `.msi` |
| macOS arm64 | `.pkg` |
| Linux x86_64 | `.deb`, `.pkg.tar.zst` |
| Linux arm64 | `.deb`, `.pkg.tar.zst` |

构建依赖：

- 所有平台：`uv` 和 Python 3.12+；
- Windows：MSVC Build Tools、.NET SDK 和 WiX Toolset；
- macOS：带 `pkgbuild` 的 Apple command line tools；
- Linux：`dpkg-deb` 和 `zstd`；
- Linux arm64：Nuitka C 后端/链接阶段使用 `clang` 和 `lld`。

安装 Windows 打包工具：

```powershell
scripts\install_windows_packaging_tools.ps1
```

等价的手动命令：

```powershell
winget install --id Microsoft.DotNet.SDK.8 --exact --source winget
dotnet tool install --global wix
```

Windows 使用 MSVC，并带 `--include-windows-runtime-dlls=yes`。Nuitka 在
Python 3.13+ 下不支持 `--mingw64`。

本地原生构建使用和 CI 相同的脚本：

```bash
# Windows PowerShell
scripts\build_native_windows.ps1 -Arch x86_64 -Formats msi -Jobs 4

# macOS
sh scripts/build_native_macos.sh --arch arm64 --formats pkg --jobs 4

# Linux
sh scripts/build_native_linux.sh --arch x86_64 --formats deb,pkg --jobs 4
sh scripts/build_native_linux.sh --arch arm64 --formats deb,pkg --jobs 4
```

每个 wrapper 都会执行完整 release pipeline：

1. 编译检查 `src`、`tests`、`scripts`；
2. 运行聚焦测试集；
3. 构建 Nuitka 可执行文件；
4. 对构建出的可执行文件运行 `sarma --help` smoke test；
5. 按指定格式打包原生安装包。

输出目录：

- `dist/nuitka/<platform>-<machine>/`：Nuitka 构建输出；
- `dist/packages/`：最终安装包。

本地只想跑部分阶段时，可以把这些参数透传给 wrapper：

```bash
--skip-tests
--skip-build
--skip-smoke
--skip-package
```

GitHub 原生 release workflow 只负责选择 target matrix，然后调用同一套本地
wrapper 脚本。手动触发 workflow 时可以选择 `all`、`windows-x86_64`、
`macos-arm64`、`linux-x86_64` 或 `linux-arm64`。

Linux artifact 可能明显大于 macOS artifact，因为 Linux job 当前会同时上传
`.deb` 和 `.pkg.tar.zst`，两个包里都会包含同一份 Nuitka onefile 可执行 payload。
如果只想比较单个 Linux 包体积，本地可以使用 `--formats deb` 或 `--formats pkg`。

## 开发

- 架构说明：[project.md](project.md)
- 开发指南：[docs/development.md](docs/development.md)

常用检查：

```bash
uv run python -m compileall -q src tests scripts
uv run pytest tests/test_build_nuitka.py tests/test_runtime_boundaries.py -q
uv run sarma --help
```

## 许可证

MIT。见 [LICENSE](LICENSE)。
