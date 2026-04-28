# IDA-MCP

**[English](README.md)** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%">
</p>

[![MCP Badge](https://lobehub.com/badge/mcp/captain-ai-hub-ida-mcp)](https://lobehub.com/mcp/captain-ai-hub-ida-mcp)

[wiki](https://github.com/jelasin/IDA-MCP/wiki) · [deepwiki](https://deepwiki.com/jelasin/IDA-MCP)

## IDA-MCP (FastMCP + 多实例网关)

* 每个 IDA 实例都会暴露自己的 **FastMCP Streamable HTTP** 端点 `/mcp`
* 独立网关守护进程负责维护内存中的实例注册表并转发工具调用
* 同一个网关进程默认在 `127.0.0.1:11338` 上同时提供 `/internal` 内部 API 和 `/mcp` 客户端 MCP 入口
* stdio 代理是独立子进程入口，但复用同一套 proxy 工具定义
* MCP Resources 由各个 IDA 实例直接暴露，不走 gateway/proxy
* 提供 PySide6 桌面 IDE，支持一键安装、配置、网关管理和状态监控

## 架构

### 仓库结构

```text
IDA-MCP/
├── ide/                        # PySide6 桌面 IDE（主项目）
│   ├── app/                    # UI 层
│   ├── supervisor/             # 网关生命周期与安装管理
│   ├── resources/ida_mcp/      # 打包的 ida_mcp 源码（安装到 IDA plugins/）
│   └── tests/
├── skills/                     # MCP skill 文档
├── test/                       # 测试套件
├── API.md                      # 工具与响应契约参考
├── README.md / README_CN.md
└── project.md / roadmap.md
```

### 核心基础设施（`ida_mcp/` 内）

* `rpc.py` - `@tool` / `@resource` / `@unsafe` 装饰器与注册机制
* `sync.py` - `@idaread` / `@idawrite` IDA 线程同步装饰器
* `utils.py` - 地址解析、分页、模式过滤等工具函数
* `compat.py` - IDA 8.x/9.x 兼容层

### API 模块

* `api_core.py` - IDB 元数据、函数/字符串/全局变量列表
* `api_analysis.py` - 反编译、反汇编、交叉引用
* `api_memory.py` - 内存读取操作
* `api_modeling.py` - 数据库塑形（函数、code/data/string 创建）
* `api_types.py` - 类型操作（原型、本地类型）
* `api_modify.py` - 注释、重命名
* `api_stack.py` - 栈帧操作
* `api_debug.py` - 调试器控制（标记为不安全）
* `api_python.py` - Python 代码执行（标记为不安全）
* `api_resources.py` - MCP 资源（`ida://` URI 模式）

### 核心特性

* **装饰器链模式**：`@tool` + `@idaread`/`@idawrite` 实现简洁的 API 定义
* **批量操作**：大多数工具支持列表参数进行批量处理
* **MCP 资源**：REST 风格的 `ida://` URI 模式，提供面向单实例直连的只读数据访问
* **多实例支持**：默认监听在 11338 的独立网关管理多个 IDA 实例
* **默认偏向 HTTP**：仓库内默认配置为 `enable_http=true`、`enable_stdio=false`、`enable_unsafe=true`
* **IDA 8.x/9.x 兼容**：兼容层处理 API 差异
* **桌面 IDE**：PySide6 GUI 提供一键安装、配置、网关控制和状态监控

## 安装

### 通过桌面 IDE（推荐）

1. 启动 IDE：`python ide/launcher.py`
2. 在 设置 → 配置 页填写 **IDA Python** 路径（如 `D:\IDA\ida-python\python.exe`）
3. 插件目录默认为 `%APPDATA%\Hex-Rays\IDA Pro\plugins`
4. 点击 **安装** — IDE 自动复制插件文件并安装 Python 依赖
5. 在状态页或工具栏点击 **启动 Gateway**

### 通过命令行

```bash
python ide/resources/ida_mcp/ida_mcp/command.py gateway start --json
```

### 手动安装

1. 将 `ide/resources/ida_mcp/` 下的 `ida_mcp.py` 和 `ida_mcp/` 目录复制到 IDA 的 `plugins/` 目录
2. 使用 IDA 的 Python 安装依赖：
   ```bash
   <ida_python> -m pip install -r ide/resources/ida_mcp/requirements.txt
   ```
3. 在 IDA 中打开目标二进制并等待初始分析完成

## 启动步骤

1. 安装插件（通过 IDE 或手动）
2. 启动网关（通过 IDE 或 `command.py gateway start`）
3. 在 IDA 中手动触发插件，或者通过 proxy 调用 `open_in_ida`
4. 启动后，当前实例会：
   * 从 `10000` 开始选择一个空闲实例端口
   * 在 `http://127.0.0.1:<instance_port>/mcp/` 上提供 MCP 服务
   * 通过 `http://127.0.0.1:11338/internal` 向网关注册自己

关闭某个 IDA 实例只会注销该实例；独立网关会继续运行。

## 当前工具

### 核心工具 (`api_core.py`)

* `check_connection` – 网关/注册表健康检查（ok/count）
* `list_instances` – 列出共享网关中已注册的 IDA 实例
* `get_metadata` – IDB 元数据（hash/arch/bits/endian）
* `list_functions` – 分页函数列表，支持可选模式过滤
* `list_globals` – 全局符号（非函数）
* `list_strings` – 提取的字符串
* `list_local_types` – 本地类型定义
* `get_entry_points` – 程序入口点
* `convert_number` – 数字格式转换
* `list_imports` – 列出导入函数及模块名
* `list_exports` – 列出导出函数/符号
* `list_segments` – 列出内存段及权限
* `get_cursor` – 获取当前光标位置和上下文

### 分析工具 (`api_analysis.py`)

* `decompile` – 批量反编译函数（Hex-Rays）
* `disasm` – 批量反汇编函数
* `linear_disasm` – 从任意地址线性反汇编
* `get_callers` – 按函数和调用点聚合的调用者摘要
* `get_callees` – 按函数和调用点聚合的被调函数摘要
* `get_function_signature` – 获取当前最可靠的函数签名字符串
* `xrefs_to` / `xrefs_from` – 批量交叉引用
* `xrefs_to_field` – 启发式结构体字段引用
* `find_bytes` – 搜索带通配符的字节模式
* `get_basic_blocks` – 获取基本块及控制流

### 内存工具 (`api_memory.py`)

* `get_bytes` – 读取原始字节
* `read_scalar` – 按显式宽度读取整数
* `get_string` – 读取空终止字符串

### 建模工具 (`api_modeling.py`)

* `create_function` – 在地址处创建函数
* `delete_function` – 删除已有函数
* `make_code` – 把地址处字节转换为代码
* `undefine_items` – 取消定义一段字节范围
* `make_data` – 创建带类型的数据项
* `make_string` – 创建字符串字面量

### 类型工具 (`api_types.py`)

* `declare_struct` / `declare_enum` / `declare_typedef` – 创建/更新本地类型
* `set_function_prototype` – 设置函数签名
* `set_local_variable_type` – 设置局部变量类型（Hex-Rays）
* `set_global_variable_type` – 设置全局变量类型
* `list_structs` / `get_struct_info` – 结构体列表与详情

### 修改工具 (`api_modify.py`)

* `set_comment` – 批量设置注释
* `rename_function` / `rename_local_variable` / `rename_global_variable` – 重命名
* `patch_bytes` – 在地址处修补字节

### 栈帧工具 (`api_stack.py`)

* `stack_frame` – 获取栈帧变量
* `declare_stack` / `delete_stack` – 创建/删除栈变量

### Python 工具 (`api_python.py`) - 不安全

* `py_eval` – 在 IDA 上下文中执行任意 Python 代码

### 调试工具 (`api_debug.py`) - 不安全

* `dbg_regs` – 获取所有寄存器
* `dbg_callstack` – 获取调用栈
* `dbg_list_bps` – 列出断点
* `dbg_start` / `dbg_exit` / `dbg_continue` – 启动/停止/继续调试
* `dbg_run_to` – 运行到地址
* `dbg_add_bp` / `dbg_delete_bp` / `dbg_enable_bp` – 断点管理
* `dbg_step_into` / `dbg_step_over` – 单步执行
* `dbg_read_mem` / `dbg_write_mem` – 调试器内存访问

### MCP 资源 (`api_resources.py`)

* `ida://idb/metadata` – IDB 元数据
* `ida://functions` / `ida://function/{addr}` – 函数列表与详情
* `ida://function/{addr}/decompile` – 函数反编译快照
* `ida://function/{addr}/disasm` – 函数反汇编快照
* `ida://function/{addr}/basic_blocks` – 函数基本块 / CFG 视图
* `ida://function/{addr}/stack` – 函数栈帧 / 局部变量视图
* `ida://strings` / `ida://globals` / `ida://types` / `ida://segments`
* `ida://imports` / `ida://imports/{module}` / `ida://exports` / `ida://entry_points`
* `ida://structs` / `ida://struct/{name}` – 结构体列表与详情
* `ida://xrefs/to/{addr}` / `ida://xrefs/from/{addr}`（含 `/summary` 变体）
* `ida://memory/{addr}?size=N` – 读取内存

## 传输概览

| 模式 | 说明 | 配置 |
|------|------|------|
| **HTTP proxy**（推荐） | 连接到独立网关暴露的 `11338` proxy | 只需配置 `url` |
| **stdio proxy** | MCP 客户端以子进程方式启动 `ida_mcp/proxy/ida_mcp_proxy.py` | 需要配置 `command` 和 `args` |
| **实例直连 HTTP** | 直接连到单个 IDA 实例，主要用于 `ida://` resources | 需要目标实例端口 |

**代理工具：**

| 类别 | 工具 |
|------|------|
| 管理 | `check_connection`, `list_instances`, `select_instance` |
| 生命周期 | `open_in_ida`, `close_ida`, `shutdown_gateway` |
| 核心 | `list_functions`, `get_metadata`, `list_strings`, `list_globals`, `list_local_types`, `get_entry_points`, `convert_number`, `list_imports`, `list_exports`, `list_segments`, `get_cursor` |
| 分析 | `decompile`, `disasm`, `linear_disasm`, `get_callers`, `get_callees`, `get_function_signature`, `xrefs_to`, `xrefs_from`, `xrefs_to_field`, `find_bytes`, `get_basic_blocks` |
| 建模 | `create_function`, `delete_function`, `make_code`, `undefine_items`, `make_data`, `make_string` |
| 修改 | `set_comment`, `rename_function`, `rename_global_variable`, `rename_local_variable`, `patch_bytes` |
| 内存 | `get_bytes`, `read_scalar`, `get_string` |
| 类型 | `set_function_prototype`, `set_local_variable_type`, `set_global_variable_type`, `declare_struct`, `declare_enum`, `declare_typedef`, `list_structs`, `get_struct_info` |
| 栈帧 | `stack_frame`, `declare_stack`, `delete_stack` |
| Python | `py_eval` |
| 调试 | `dbg_start`, `dbg_continue`, `dbg_step_into`, `dbg_step_over`, `dbg_regs`, `dbg_add_bp`, `dbg_delete_bp`, ... |

可在 Claude Code、Codex、Cursor、VSCode、LangChain、Cherry Studio 等任何 MCP 客户端上使用。

### 方式一：HTTP Proxy 模式（推荐）

```json
{
  "mcpServers": {
    "ida-mcp": {
      "url": "http://127.0.0.1:11338/mcp"
    }
  }
}
```

### 方式二：stdio Proxy 模式

```json
{
  "mcpServers": {
    "ida-mcp-proxy": {
      "command": "IDA的python路径",
      "args": ["ida_mcp/proxy/ida_mcp_proxy.py的路径"]
    }
  }
}
```

## 配置文件

编辑安装后 `plugins/ida_mcp/` 中的 `config.conf`：

```ini
enable_stdio = false
enable_http = true
enable_unsafe = true
wsl_path_bridge = false

http_host = "0.0.0.0"
http_port = 11338
http_path = "/mcp"

ida_default_port = 10000
ida_host = "127.0.0.1"
# ida_path = "C:\\Path\\To\\ida.exe"
# ida_python = "C:\\Path\\To\\ida-python\\python.exe"
open_in_ida_bundle_dir = ""
open_in_ida_autonomous = true
auto_start = false
server_name = "IDA-MCP"

request_timeout = 30
debug = false
```

## 命令行入口

安装后可使用 `command.py` 做本地控制和脚本化调用：

```bash
python <plugins>/ida_mcp/command.py gateway start
python <plugins>/ida_mcp/command.py gateway status
python <plugins>/ida_mcp/command.py gateway stop
python <plugins>/ida_mcp/command.py ida list
python <plugins>/ida_mcp/command.py ida open ./target.exe
python <plugins>/ida_mcp/command.py tool call get_metadata --port 10000
```

加 `--json` 获取机器可读输出。

## 开发理念

工具不在多，而在精准；API 的能力才是真正重要的。此外，工具应该全面，工具越多，模型调用的障碍越多。如果某些工具可以通过现有工具实现，那这些工具就是多余的。我需要的是缺失的工具——现有工具无法完成的那些。

## 许可证

参见 [LICENSE](LICENSE)。
