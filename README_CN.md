# Sarma

**[English](README.md)** | **中文**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma 是一个全屏终端漏洞审计 agent。它把 Textual 聊天界面、LangGraph 工作流、
LangChain agents、MCP 工具和全局/工作区分层配置组合在一起，用于逆向工程和
安全审计。

Sarma 主要面向 IDA-MCP 这类工具密集型二进制审计场景，但运行时可以接入任意已配置
的 MCP server。

## 功能

- 全屏 Textual TUI：聊天区、输入栏、运行状态侧边栏、工作流图。
- `ruflo`：默认对话工作流，主 agent 可委派聚焦子任务。
- `audit`：完整多阶段漏洞发现工作流。
- `audit-slim`：紧凑的 recon / hunter / verify / report 工作流。
- 支持按工作流和子 agent 配置模型、MCP 和 skills。
- 通过 `/plugin` 管理 MCP servers 和安装 skills。
- 通过 `/rag` 配置全局 RAG embedding model，通过 `sarma rag` 注册和切分
  本地 Chroma 知识库。
- 内置 `web_search`、`http_exchange`、`packet_exchange`，用于公开资料检索
  以及 HTTP/HTTPS 或原始端口收发测试。
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
| `/rag` | 配置全局 RAG embedding model，并查看知识库 |
| `/restart` | 重启运行时资源 |
| `/compact` | 把旧上下文整理为结构化 memory |
| `/clear` | 清空当前会话 |
| `/exit` | 退出 |

## 配置文件

Sarma 会在 `~/.sarma` 下创建全局默认配置。当前工作区的 `./.sarma`
是本地资源的增量配置，不会复制或覆盖全局配置。

全局配置：

```text
~/.sarma/
  models.toml
  agents.toml
  mcp.toml
  rag.toml
  rag/
    models/
  skills/
```

工作区配置和数据：

```text
./.sarma/
  mcp.toml
  rag.toml
  rag/
    docs/
    chroma/
  skills/
  db.sqlite
```

运行时合并规则：

- `models.toml` 和 `agents.toml` 是全局配置，由 `/config` 修改。
- MCP servers 使用 `global + workspace` 合并；workspace 同名项覆盖同名
  global 项，但不会遮掉其他 global MCP。
- Skills 仍然是目录资源：`skills/<name>/SKILL.md`。workspace skill
  优先于同名 global skill。
- RAG embedding model 是全局配置，由 `/rag` 或 `sarma rag --model ...`
  修改。
- RAG 知识库使用 `global + workspace` 合并；默认 Chroma 数据库仍保存在
  当前项目的 `./.sarma/rag/chroma/<knowledge-base>/`。

`/plugin` 中 MCP server 和 skill 安装都可以选择 `workspace` 或 `global`
scope。`sarma rag --global` 会把知识库注册到全局 `rag.toml`；不带
`--global` 时只注册到当前工作区。

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

`rag.toml`：

```toml
embedding_backend = "huggingface" # huggingface | api
embedding_model = "text-embedding-3-large"
embedding_api_base = ""
embedding_api_key = ""
embedding_local_path = ""
chunk_size = 1200
chunk_overlap = 150

[[knowledge_bases]]
name = "project-docs"
docs_path = ""
chroma_path = ""
enabled = true
```

使用 `/rag` 配置全局 embedding backend/model、把 HuggingFace 模型拉取到
全局模型缓存，并查看已注册知识库。知识库注册、导入和切分统一使用
`sarma rag` CLI。

Embedding backend：

- `huggingface`：使用 `langchain-huggingface`，可把模型拉取/缓存到
  `~/.sarma/rag/models/<model>/` 或 `embedding_local_path`。
- `api`：通过 `embedding_api_base` 和 `embedding_api_key` 使用 OpenAI-compatible
  embeddings API。

如果 `docs_path` 或 `chroma_path` 为空，Sarma 使用：

- 源文档：`./.sarma/rag/docs/<knowledge-base>/`；
- Chroma 数据库：`./.sarma/rag/chroma/<knowledge-base>/`。

RAG embedding model 和 `models.toml` 中的聊天主模型是分开的；主 agent 模型不会用于
文档切分或后续向量化。

同样的能力也可以通过 CLI 使用：

```bash
sarma rag --backend huggingface --model BAAI/bge-small-en-v1.5 --pull
sarma rag --backend api --model text-embedding-3-large --api-base https://api.example/v1
sarma rag --name project-docs --split ./docs
sarma rag --name project-docs --split ./docs --chroma-path ./.sarma/rag/chroma/project-docs
sarma rag --name imported-kb --add ./.sarma/rag/chroma/imported-kb
sarma rag --global --name shared-kb --add /absolute/path/to/chroma
```

`--add` 只注册已有 Chroma persistent directory。目录必须包含 Chroma 的
`chroma.sqlite3` 文件，例如：

```text
./.sarma/rag/chroma/project-docs/
  chroma.sqlite3
  <Chroma segment/index files>
```

只要至少启用了一个知识库，Sarma 就会把内置 `rag_search` 工具挂到现有 workflow
agents 上。RAG 不是单独 agent；现有 agent 在需要私有知识时调用 `rag_search`。

## 内置 Agent 工具

Sarma 会把本地内置工具挂到现有 workflow agents 上：

| 工具 | 作用 |
|------|------|
| `rag_search` | 检索已启用的本地 RAG 知识库 |
| `web_search` | 检索公开网页，返回简洁标题、URL 和摘要 |
| `http_exchange` | 向目标 host、port、path、method 发送 HTTP/HTTPS 请求 |
| `packet_exchange` | 发送原始 TCP、UDP 或 TLS payload 并捕获响应 |

HTTP/HTTPS 服务检查优先使用 `http_exchange`。只有在需要更底层 payload、
非 HTTP 协议或畸形请求时，才使用 `packet_exchange`。

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
