# Sarma

**[English](README.md)** | **中文**

Sarma 是面向 IDA Pro 自动化的桌面 IDE。它提供 PySide6 工作台，用于安装和配置逆向工程资源、管理 IDA-MCP gateway，并承载面向分析工作的 assistant/chat/workspace 流程。

本仓库是 IDE 父项目。运行时插件资源以 submodule 形式放在 `ide/resources/`：

| 路径 | 远程 | 分支 | 职责 |
|------|------|------|------|
| `ide/resources/ida_mcp` | `git@github.com:Captain-AI-Hub/IDA-MCP.git` | `main` | IDA-MCP 插件、gateway、MCP tools/resources、live-IDA 测试 |
| `ide/resources/diaphora` | `https://github.com/joxeankoret/diaphora` | `master` | IDE 安装/配置流程使用的 Diaphora 资源 |

## 仓库结构

```text
Sarma/
├── ide/                         # PySide6 桌面 IDE 和 supervisor
│   ├── launcher.py              # 开发入口
│   ├── app/                     # UI、presenter、chat/workspace 服务
│   ├── supervisor/              # 安装器、gateway 生命周期、健康检查
│   ├── shared/                  # 路径、数据库、DTO、配置 helper
│   ├── resources/
│   │   ├── ida_mcp/             # Git submodule：独立 IDA-MCP 插件仓库
│   │   ├── diaphora/            # Git submodule：Diaphora 上游仓库
│   │   ├── i18n/                # IDE 多语言资源
│   │   └── icons/               # IDE 图标
│   └── tests/                   # IDE pytest 测试
├── skills/                      # 本地 Agent 工作流使用的技能材料
├── codemap.md                   # 架构 atlas 和入口索引
├── project.md                   # 仓库项目地图
└── roadmap.md                   # 仓库规划索引
```

## 获取源码

建议带 submodule 克隆：

```bash
git clone --recurse-submodules git@github.com:Captain-AI-Hub/Sarma.git
cd Sarma
```

如果已经克隆但没有初始化 submodule：

```bash
git submodule update --init --recursive
```

按 `.gitmodules` 配置更新资源 submodule：

```bash
git submodule update --remote ide/resources/ida_mcp
git submodule update --remote ide/resources/diaphora
```

## 启动 IDE

```bash
python ide/launcher.py
```

IDE 项目目标 Python 3.12，依赖位于 `ide/requirements.txt` 和 `ide/pyproject.toml`。

## IDA-MCP 边界

`ide/resources/ida_mcp` 是独立 Git submodule，包含：

- `ida_mcp.py`：IDA 插件入口文件，暴露 `PLUGIN_ENTRY()`。
- `ida_mcp/`：插件包，包含 FastMCP instance server、gateway、proxy、CLI 和 API 模块。
- `API.md`：tools/resources/internal HTTP 契约文档。
- `test/`：需要 live IDA 环境的 pytest 套件。

IDE 可以复制这些文件、以 subprocess 启动 `ida_mcp/command.py`、编辑插件配置；但 IDE 代码不能直接 import `ida_mcp` 模块，因为它们依赖 IDA Python 运行时。

## 开发命令

```bash
# IDE 测试
pytest ide/tests

# 插件静态烟测
python -m compileall -q ide/resources/ida_mcp/ida_mcp.py ide/resources/ida_mcp/ida_mcp ide/resources/ida_mcp/test

# 插件 live 测试，需要运行中的 gateway 和已注册 IDA 实例
python ide/resources/ida_mcp/test/test.py
```

## 文档入口

- `codemap.md` - 仓库架构、入口和运行时边界。
- `project.md` - Sarma 父仓库项目地图。
- `roadmap.md` - IDE 与资源 submodule 的规划索引。
- `ide/README.md` 和 `ide/project.md` - IDE 子项目说明。
- `ide/resources/ida_mcp/API.md` - IDA-MCP API 契约。
