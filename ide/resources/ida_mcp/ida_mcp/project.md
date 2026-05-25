# ida-mcp Package Project Map

## 子项目定位

`ida_mcp/` 是独立 IDA-MCP 插件仓库的核心 Python 包。它负责把 IDA 的分析、修改、建模、资源读取、实例生命周期和 gateway/proxy 能力暴露为稳定的 MCP / HTTP / control 接口。

它不负责 Sarma IDE 产品层状态、UI、workspace、chat 会话或安装页面。仓库根目录是插件资源根，包含插件入口 `ida_mcp.py`、本包、`API.md`、`ida-plugin.json` 和 live-IDA 测试。

## 目录树

```text
ida_mcp/
├── __init__.py
├── config.py                   # config.conf 读取与运行配置
├── config.conf                 # 默认配置
├── sync.py                     # @idaread / @idawrite IDA 主线程同步
├── utils.py                    # 地址解析、分页、过滤、序列化工具
├── rpc.py                      # @tool / @resource / @unsafe 注册约定
├── api_loader.py               # 导入 api_* 模块以填充 registry
├── server_factory.py           # IDA 实例内 FastMCP server 组装
├── instance_server.py          # per-instance uvicorn/FastMCP 生命周期
├── plugin_runtime.py           # IDA 插件启动、停止、注册、heartbeat 编排
├── heartbeat.py                # 实例 heartbeat 与主线程响应检测
├── instance_registry.py        # gateway 进程内实例表
├── registry_routes.py          # gateway /internal 路由与转发逻辑
├── registry_server.py          # 独立 gateway 进程入口
├── registry.py                 # gateway 启动、状态探测、注册调用封装
├── runtime.py                  # 运行时辅助
├── control.py                  # CLI/脚本友好控制层
├── command.py                  # 命令行入口
├── errors.py                   # 错误定义
├── analysis_utils.py           # 分析结果共享转换逻辑
├── strings_cache.py            # 字符串缓存辅助
├── api_core.py                 # 元数据、函数、字符串、导入导出等浏览能力
├── api_analysis.py             # 反编译、反汇编、xrefs、搜索、CFG
├── api_memory.py               # 字节、标量、字符串读取
├── api_types.py                # 类型、结构体、枚举、typedef
├── api_modify.py               # 注释、重命名、补丁
├── api_modeling.py             # 创建/删除函数与 code/data/string 建模
├── api_stack.py                # 栈帧与局部变量
├── api_debug.py                # 调试相关 unsafe 能力
├── api_python.py               # Python 执行 unsafe 能力
├── api_lifecycle.py            # IDA 实例关闭等生命周期能力
├── api_resources.py            # ida:// 资源端点
└── proxy/
    ├── register_tools.py       # proxy 侧工具注册与包装
    ├── lifecycle.py            # open_in_ida / close / staging / path bridge
    ├── _http.py                # gateway/internal HTTP 请求辅助
    ├── _state.py               # 实例选择与路由状态
    ├── _server.py              # HTTP/stdio proxy 共享 FastMCP server
    ├── http_server.py          # HTTP proxy transport 入口
    └── ida_mcp_proxy.py        # stdio proxy 入口
```

## 模块边界

### 配置与注册基础设施

- `config.py` 读取 transport、端口、路径、超时和 unsafe 策略。
- `rpc.py` 定义 tool/resource/unsafe 注册约定。
- `api_loader.py` 汇总导入 `api_*`，触发装饰器注册 side effect。
- `sync.py` 是所有 IDA SDK 调用的线程边界。

### 实例内服务层

- `server_factory.py` 将注册后的 tool/resource 放入 FastMCP server。
- `instance_server.py` 管理每个 IDA 实例自己的 `/mcp/` 服务。
- `plugin_runtime.py` 由上一级 `ida_mcp.py` 调用，负责启动、停止、注册、心跳和资源释放。

### Gateway / Registry 层

- `registry_server.py` 是独立 gateway 进程入口，挂载 `/internal/*` 与 `/mcp`。
- `registry_routes.py` 实现 health、register、unregister、call、shutdown 等 internal 路由。
- `instance_registry.py` 维护内存实例表。
- `registry.py` 为 IDA 插件、CLI 和 supervisor 提供 gateway 进程控制与 internal API 调用封装。

### Tool / Resource 能力层

- `api_core.py`、`api_analysis.py`、`api_memory.py` 等模块定义直接面向 IDA 的能力。
- 读操作使用 `@idaread`；修改操作使用 `@idawrite`。
- `api_debug.py` 与 `api_python.py` 属于 unsafe 边界，受 `enable_unsafe` 控制。
- `api_resources.py` 提供只读 `ida://` 资源，主要用于直连单实例 MCP。

### Proxy / CLI 层

- `proxy/_server.py` 与 `proxy/register_tools.py` 组成 gateway MCP proxy 的工具面。
- `proxy/lifecycle.py` 处理 `open_in_ida`、路径桥接和 close/shutdown 相关流程。
- `control.py` 给 `command.py`、脚本和测试提供稳定 Python API，避免调用方直接触碰 proxy 初始化细节。

## 关键调用链

### IDA 插件启动

`../ida_mcp.py` -> `plugin_runtime.py` -> `instance_server.py` -> `server_factory.py` -> `registry.py`

### Gateway 启动

`command.py gateway start` -> `control.py` -> `registry.py` -> `registry_server.py`

### Proxy tool 调用

MCP client -> gateway `/mcp` -> `proxy/register_tools.py` -> gateway `/internal/call` -> selected IDA instance `/mcp/`

### Direct resource 读取

MCP client -> selected IDA instance `/mcp/` -> `api_resources.py`

## 与 IDE 的边界

IDE 可以依赖：

- gateway 健康状态、实例列表和实例选择
- `open_in_ida` / `close_ida` / `shutdown_gateway`
- tool call、resource list/read、API 契约
- `command.py` 与 `control.py` 暴露的脚本入口

IDE 不应把以下内容放回本包：

- PySide6 UI 状态
- workspace / SQLite 产品数据
- chat / thread / message / skill 运行状态
- audit run / plan / checkpoint / report 等工作流编排

## 文档与测试

- API 契约：`../API.md`
- live-IDA pytest：`../test/`
- 仓库级地图：`../project.md`

## 一句话总结

`ida_mcp/` 是稳定、可复用、可测试的底层逆向能力层；面向用户的产品状态与编排逻辑属于 Sarma。
