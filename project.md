# IDA-MCP Repository Project Map

## 仓库定位

本仓库现在以 `ide/` 为主项目：它提供 PySide6 桌面工作台，并把 IDA 插件源码作为受管资源打包在 `ide/resources/ida_mcp/` 中。根目录只保留仓库级说明、路线图、Agent 指令、技能资料和许可证。

## 仓库结构

```text
IDA-MCP/
├── ide/                          # PySide6 桌面 IDE（主项目）
│   ├── launcher.py               # IDE 启动入口
│   ├── pyproject.toml            # IDE Python/Poetry 项目配置
│   ├── app/                      # UI、presenter、业务服务与 chat runtime
│   ├── supervisor/               # 安装、配置、gateway 生命周期与环境探测
│   ├── shared/                   # 路径、数据库、DTO、配置读写等共享层
│   ├── resources/
│   │   ├── ida_mcp/              # Bundled IDA 插件资源、API 文档、live-IDA 测试
│   │   │   ├── ida_mcp.py        # IDA 插件入口文件，安装到 IDA plugins/
│   │   │   ├── ida_mcp/          # 实际插件包（MCP server、gateway、API、proxy）
│   │   │   ├── test/             # 需要 gateway + IDA 实例的插件集成测试
│   │   │   ├── API.md            # MCP 工具、资源、HTTP/internal 契约参考
│   │   │   └── requirements.txt  # IDA Python 运行依赖
│   │   ├── diaphora/             # Bundled Diaphora 插件资源
│   │   ├── diaphora-cpp/         # C++ Diaphora diff core rewrite
│   │   ├── i18n/                 # IDE 文案资源
│   │   └── icons/                # IDE 图标资源
│   ├── tests/                    # IDE 自身 pytest 测试
│   └── build_helpers/            # Nuitka 打包辅助
├── skills/                       # 面向 Agent/MCP 工作流的技能资料
├── codemap.md                    # 仓库级架构边界与入口索引
├── project.md                    # 本文件，仓库级项目地图
├── roadmap.md                    # 仓库级规划索引
├── README.md / README_CN.md      # 用户文档
├── AGENTS.md                     # Agent 开发约束
└── pytest.ini                    # 插件测试默认入口：ide/resources/ida_mcp/test
```

## 子项目边界

### `ide/` — 产品与编排层

- 负责桌面 UI、设置、状态监控、安装流程、gateway 生命周期和 chat/workspace 等用户工作流。
- 通过 `supervisor/` 和 subprocess 调用 `ide/resources/ida_mcp/ida_mcp/command.py`。
- 不在代码层面 import `ida_mcp` 包；该包依赖 IDA Python/SDK，不能假定普通 Python 环境可用。
- 持久化、技能、聊天会话、工作区数据属于 IDE 边界，放在 `ide/shared/`、`ide/app/` 或 `ide/data/`。

### `ide/resources/ida_mcp/` — Bundled IDA 插件项目

- 是 IDE 安装到 IDA plugins 目录的源资源根。
- 安装时只复制 `ida_mcp.py`、`ida_mcp/` 包和运行所需配置/依赖；`test/` 与 `API.md` 是开发文档和验证资产。
- `test/` 需要运行中的 gateway 与已注册 IDA 实例，默认由根 `pytest.ini` 指向。

### `ide/resources/ida_mcp/ida_mcp/` — 插件核心包

- 运行在 IDA Python 或 gateway/proxy 进程中。
- 提供 FastMCP server、tool/resource 注册、gateway registry、proxy、CLI/control 和 `api_*.py` 能力模块。
- 所有触碰 IDA SDK 的 tool 必须通过 `@idaread` 或 `@idawrite` 进入 IDA 主线程同步边界。
- `py_eval` 和 `dbg_*` 属于 unsafe 能力，受 `config.conf` 中 `enable_unsafe` 控制。

### `ide/resources/diaphora/` — 第三方插件资源

- 作为 IDE 可安装/配置的 bundled resource 存在。
- 不属于 `ida_mcp` 包，也不应被 `ida_mcp` 核心层反向依赖。

### `ide/resources/diaphora-cpp/` — C++ Diaphora 重写

- 作为 Diaphora diff 核心的 C++ 重写路径存在。
- 当前边界是离线 CLI：读取 Diaphora SQLite export 数据库，写出兼容结果数据库。
- 后续 IDA C++ 插件/exporter 集成应遵循 IDA 9 `plugin_t`/`plugmod_t` 与 `execute_sync()` 线程边界。

### `skills/` — Agent 技能资料

- 存放面向 Agent 的本地技能和参考材料。
- 不参与 IDE 或 IDA 插件运行时导入链。

## 关键入口

| 入口 | 职责 |
|------|------|
| `python ide/launcher.py` | 启动 PySide6 IDE |
| `ide/app/main.py` | IDE 应用初始化 |
| `ide/supervisor/manager.py` | IDE 后台控制面聚合入口 |
| `ide/resources/ida_mcp/ida_mcp.py` | IDA 插件 `PLUGIN_ENTRY()` 入口 |
| `ide/resources/ida_mcp/ida_mcp/plugin_runtime.py` | IDA 实例内 MCP server 生命周期 |
| `ide/resources/ida_mcp/ida_mcp/command.py` | gateway、IDA 打开、tool/resource 调用 CLI |
| `ide/resources/ida_mcp/ida_mcp/registry_server.py` | 独立 gateway HTTP/internal + MCP proxy 进程 |
| `ide/resources/ida_mcp/ida_mcp/server_factory.py` | 实例内 FastMCP server 组装 |
| `ide/resources/ida_mcp/API.md` | MCP 工具、资源、内部 HTTP 契约 |

## 测试边界

| 测试目录 | 覆盖范围 | 运行条件 |
|----------|----------|----------|
| `ide/tests/` | IDE 配置、UI presenter、安装器、路径和 chat 支撑逻辑 | 普通 Python/pytest |
| `ide/resources/ida_mcp/test/` | IDA 插件工具、资源、gateway/proxy、lifecycle | 需要 gateway 与 live IDA instance |

根目录旧 `test/` 已不再是测试入口；插件测试已迁移到 `ide/resources/ida_mcp/test/`。

## 文档入口

| 文档 | 说明 |
|------|------|
| `codemap.md` | 仓库级架构 atlas 和目录责任摘要 |
| `project.md` | 仓库级项目地图 |
| `roadmap.md` | 仓库级规划索引 |
| `ide/project.md` | IDE 子项目结构与调用链 |
| `ide/roadmap.md` | IDE/chat 产品与工程规划 |
| `ide/resources/ida_mcp/ida_mcp/project.md` | 插件核心包结构地图 |
| `ide/resources/ida_mcp/ida_mcp/roadmap.md` | 插件核心包规划 |
| `ide/resources/ida_mcp/API.md` | MCP API/资源/内部 HTTP 契约 |
