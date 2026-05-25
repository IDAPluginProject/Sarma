# ida-mcp Package Roadmap

## 子项目定位

`ida_mcp/` 是底层逆向能力层，负责把 IDA 的分析、修改、建模、资源读取、实例生命周期和 gateway/proxy 能力，以稳定的 MCP / HTTP / control 接口暴露出来。

它不是 IDE 产品层，不负责：

- PySide6 UI 状态
- workspace 与 SQLite 产品数据
- chat、thread、message、skill 运行状态
- audit plan、artifact、checkpoint、report 等上层工作流编排

这些能力应位于 Sarma IDE 项目中。

## 核心职责

### 1. IDA 插件接入

- 在 IDA 内启动 per-instance MCP server。
- 注册到 gateway，并维护 heartbeat、shutdown 与资源释放。
- 保持所有 IDA SDK 调用在 `@idaread` / `@idawrite` 同步边界内。

### 2. Gateway / Registry / Proxy

- 管理多实例注册、状态与选择。
- 提供 `/internal/*` HTTP API 与 gateway `/mcp` proxy。
- 支持 `open_in_ida`、关闭实例、关闭 gateway 和 tool 转发。

### 3. 分析与修改能力

- 元数据、函数、字符串、导入导出。
- 反编译、反汇编、xrefs、搜索、CFG。
- 类型、结构体、枚举、栈帧、局部变量。
- 注释、重命名、补丁、代码/数据建模。

### 4. 资源层

- 暴露 `ida://` resources。
- 为 IDE、CLI 和第三方 MCP 客户端提供稳定只读浏览能力。

### 5. CLI、API 文档与测试支撑

- `command.py` 与 `control.py` 提供脚本与手工操作入口。
- `../API.md` 维护 tool/resource/internal HTTP 契约。
- `../test/` 保证多 transport、多模块行为稳定。

## 当前基线

当前已具备：

- IDA 实例内 FastMCP server 组装。
- gateway / registry / proxy 基础能力。
- 常用逆向分析、修改、建模和类型 API。
- lifecycle 与 `open_in_ida`。
- `ida://` resources 与 CLI 包装。
- 插件测试入口位于仓库根目录下的 `test/`。

当前仍需要持续打磨：

- 错误模型统一。
- 多实例状态与异常恢复边界。
- resource/tool 返回契约稳定性。
- 文档、API 参考与测试覆盖深度。
- 与 Sarma IDE 子模块边界的稳定性。
- IDA 9.x-only 收敛：继续用 live IDA 9 样本验证 `ida_ida`、`ida_typeinf`、`ida_frame` 等 API 的返回契约。

## 目标方向

### A. 稳定核心契约

目标：让 `ida_mcp` 成为可长期复用的底层能力层。

工作项：

- 稳定 `/internal`、proxy tool 和 control 层语义。
- 明确 tool/resource 返回结构与错误结构。
- 降低 IDE、CLI 和 Agent 调用方对内部实现细节的感知。

### B. 提高多实例可靠性

目标：在一个 gateway 下更稳定地管理多个 IDA 实例。

工作项：

- 改善实例状态判定与 heartbeat 鲁棒性。
- 完善 unresponsive / quarantined / closed 行为定义。
- 完善并发调用、超时控制和 shutdown 语义。

### C. 强化资源层与只读浏览能力

目标：为上层 IDE 工作台和直接 MCP 客户端提供更稳的浏览入口。

工作项：

- 完善 `ida://` resource 覆盖面。
- 统一分页、过滤、错误与大对象响应约定。
- 区分浏览优先接口与修改优先接口。

### D. 强化 unsafe 边界

目标：让高风险能力更清晰、更可控。

工作项：

- 明确 `py_eval`、`dbg_*`、修改类接口的风险分级。
- 强化 API 文档标注。
- 为上层调用方保留策略控制点。

### E. 提高可测试性

目标：保证核心层迭代不破坏行为契约。

工作项：

- 增补 gateway / proxy / lifecycle / resources 测试。
- 提高分析与修改接口的回归覆盖。
- 明确 stdio、HTTP proxy、direct instance 三类 transport 测试矩阵。

## 阶段规划

## P0：核心层边界与契约收敛

- 固化 `project.md`、`roadmap.md`、`../API.md` 的边界表述。
- 梳理 control、gateway、resource、tool 契约。
- 清理与 IDE 产品层耦合的表述。
- 明确支持范围为 IDA 9.x；旧 `compat.py`、`ida_struct`、`idc` 结构体兼容路径已移除。

## P1：可靠性与错误处理增强

- 统一错误结构。
- 强化实例状态与调用锁语义。
- 提高 lifecycle 与 shutdown 稳定性。

## P2：资源层与只读浏览优化

- 扩展 `ida://` resource 覆盖。
- 改善分页、过滤和大型响应处理。
- 为 IDE 浏览场景提供更稳契约。

## P3：测试与文档完善

- 增补 gateway / proxy / lifecycle / resources 测试。
- 提高 README / API / 子项目文档一致性。
- 为 Sarma 与第三方调用方补齐对接说明。

## 明确不做的方向

- 不在 `ida_mcp/` 中实现 IDE 工作台产品状态。
- 不在核心层直接承载聊天、计划、workspace 持久化。
- 不让 `ida_mcp/` 反向依赖 Sarma。
- 不把 Agent 编排逻辑塞进 IDA 插件或 gateway 内部。

## 近期执行顺序

1. 修复 `get_metadata`，以 IDA 9.x `ida_ida.inf_get_procname()`、`inf_get_app_bitness()`、`inf_is_64bit()`、`inf_is_be()` 为唯一基准。
2. 固化测试 fixture：`complex.exe` 覆盖主体 API/资源/修改/建模/类型/栈测试，`simple.exe` 只覆盖 lifecycle open/close。
3. 从 live IDA MCP 返回值采集 `complex_baseline.json`，让测试断言绑定实际函数、字符串、全局、CFG、调用关系和栈帧数据。
4. 梳理 control / gateway / resource / tool 契约。
5. 增补错误处理与可靠性文档。
6. 为 Sarma 子模块集成预留稳定接口。
