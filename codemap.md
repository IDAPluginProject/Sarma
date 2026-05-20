# Sarma Codemap — 项目进度追踪

## 项目概览

Sarma 是一个 PySide6 桌面 IDE，用于管理 IDA Pro 自动化资源。通过 gateway 架构将 IDE 运行时与 IDA Python 运行时完全解耦，提供安装配置、MCP 网关生命周期管理、Agent 驱动的分析工作流。

---

## 已完成模块

### 核心架构 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| 分层架构 (UI / Presenter / Service / Shared) | ✅ 完成 | 严格分层，边界清晰 |
| Supervisor API Protocol 抽象 | ✅ 完成 | `supervisor/api.py` 定义 ISupervisorAPI |
| Git Submodule 隔离 (IDA-MCP / Diaphora) | ✅ 完成 | IDE 不 import ida_mcp |
| 路径系统 (开发态 + Nuitka 打包态) | ✅ 完成 | `shared/paths.py` + `shared/runtime.py` |
| SQLite 持久化 + 迁移框架 | ✅ 完成 | schema v10，结构化 Migration |
| 事件总线 (Qt Signal/Slot) | ✅ 完成 | UI ↔ Service 通信 |

### Supervisor 控制面 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| Gateway 启动/停止/健康检查 | ✅ 完成 | `gateway_controller.py` |
| IDA-MCP 插件安装器 | ✅ 完成 | `installer.py` + `install_runner.py` |
| 平台探测 (IDA/Python 路径) | ✅ 完成 | `platform_detector.py` |
| 配置存储 (IDE + IDA-MCP) | ✅ 完成 | `config_store.py` + `shared/ida_mcp_config.py` |
| 进程管理 | ✅ 完成 | `process_manager.py` |

### Chat Runtime ✅ (核心流程)

| 模块 | 状态 | 说明 |
|------|------|------|
| QThread + asyncio 事件循环 | ✅ 完成 | `chat_service.py` |
| LangGraph ReAct Agent 构建 | ✅ 完成 | `agent_factory.py` |
| MCP Client 连接池 | ✅ 完成 | `mcp_pool.py` |
| Streaming 事件标准化 | ✅ 完成 | `streaming.py` (489 行，文档完善) |
| 会话持久化 (SQLite) | ✅ 完成 | `persistence.py` + `message_persister.py` |
| 历史压缩 | ✅ 完成 | `history_compactor.py` |
| 多 Provider 支持 (OpenAI/Anthropic/兼容) | ✅ 完成 | `agent_factory.py` model builders |
| System Prompt 构建 | ✅ 完成 | `prompts.py` |
| Agent Runner 执行层 | ✅ 完成 | `agent_runner.py` |

### UI 组件 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| MainWindow 导航框架 | ✅ 完成 | `ui/main_window.py` |
| Chat 页面 (消息列表/编辑器/会话) | ✅ 完成 | `ui/chat/page.py` 等 |
| Settings 页面 + 对话框 | ✅ 完成 | `ui/settings/page.py` + `widgets.py` |
| 工作区文件树 | ✅ 完成 | `ui/workspace/directory_tree.py` |
| 代码/十六进制/图片预览 | ✅ 完成 | `code_view.py` / `hex_view.py` / `image_view.py` |
| 主题系统 | ✅ 完成 | `ui/theme.py` |
| 图标系统 | ✅ 完成 | `ui/icons.py` |
| Provider 选择器 | ✅ 完成 | `ui/chat/provider_selector.py` |
| Skill 选择器 | ✅ 完成 | `ui/chat/skill_selector.py` |
| Tool Trace 面板 | ✅ 完成 | `ui/chat/tool_trace_panel.py` |
| Role Panel (系统提示) | ✅ 完成 | `ui/chat/role_panel.py` |
| 首次运行安装向导 | ✅ 完成 | `ui/dialogs/first_run_install.py` |
| 工作区选择器 | ✅ 完成 | `ui/dialogs/workspace_selector.py` |

### Presenter 层 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| ChatPresenter (消息 → 视图模型) | ✅ 完成 | `presenters/chat_presenter.py` |
| MainWindowPresenter (状态卡片) | ✅ 完成 | `presenters/main_window_presenter.py` |
| SettingsPresenter (表单映射) | ✅ 完成 | `presenters/settings_presenter.py` |

### IDA-MCP 插件 (子模块) ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| 插件入口 (PLUGIN_ENTRY) | ✅ 完成 | `ida_mcp.py` |
| 实例内 FastMCP Server | ✅ 完成 | `plugin_runtime.py` + `server_factory.py` |
| Gateway Registry + Proxy | ✅ 完成 | `registry_server.py` + `proxy/` |
| CLI (gateway/IDA/tool) | ✅ 完成 | `command.py` |
| API 模块 (core/analysis/types/modify/memory/stack/debug/resources/lifecycle) | ✅ 完成 | `api_*.py` |
| 心跳与实例注册 | ✅ 完成 | `heartbeat.py` + `instance_registry.py` |
| Live IDA 测试套件 | ✅ 完成 | `test/test_*.py` (10+ 模块) |
| API 文档 | ✅ 完成 | `API.md` |

### 测试覆盖 ✅ (基础)

| 测试 | 状态 | 说明 |
|------|------|------|
| IDE 路径测试 | ✅ 完成 | `test_paths.py` |
| Installer 测试 | ✅ 完成 | `test_installer.py` |
| Settings Service/Presenter/UI 测试 | ✅ 完成 | 4 个测试文件 |
| MainWindow Presenter 测试 | ✅ 完成 | `test_main_window_presenter.py` |
| MCP Pool 测试 | ✅ 完成 | `test_mcp_pool.py` |
| Chat 历史持久化测试 | ✅ 完成 | `test_chat_message_history.py` |
| IDA-MCP Config 测试 | ✅ 完成 | `test_ida_mcp_config.py` |
| Agent 执行测试 | ✅ 完成 | `test_agent_execution.py` |
| Nuitka 打包测试 | ✅ 完成 | `test_build_nuitka.py` |
| i18n 测试 | ✅ 完成 | `test_main_window_i18n.py` + `test_settings_page_i18n.py` |

### Skills 体系 ✅

| 模块 | 状态 | 说明 |
|------|------|------|
| Skill 导入/管理服务 | ✅ 完成 | `app/services/skill_service.py` |
| IDAPython Skill 文档 | ✅ 完成 | `ide/resources/skills/idapython/` (50+ 模块) |
| Router Vuln Audit Skill | ✅ 完成 | `ide/resources/skills/router-fs-vuln-audit/` |

### 漏洞审计工作流 ✅ (定义层)

| 模块 | 状态 | 说明 |
|------|------|------|
| 8 阶段子 Agent 规格定义 | ✅ 完成 | `audit_subagents.py` |
| Workflow DAG 可视化组件 | ✅ 完成 | `ui/chat/workflow_view.py` |

---

## 未完成 / 存在问题的模块

### 错误处理 ✅ 已集成

| 模块 | 状态 | 说明 |
|------|------|------|
| `AgentRunError` | ✅ 已集成 | agent_runner.py 捕获执行异常并包装 |
| `ToolExecutionError` | ✅ 可用 | 定义完整，供上层策略性使用 |
| `PersistenceError` | ✅ 已集成 | persistence.py 关键写操作包装异常 |

### ChatService 架构 ✅ 已优化

| 改进 | 状态 | 说明 |
|------|------|------|
| 提取 `_fail_turn` 辅助方法 | ✅ 完成 | 消除 3 处重复的错误处理模式 |
| 集成 `AgentRunError` 捕获 | ✅ 完成 | 显式捕获 agent 执行错误 |
| 取消机制 | ⚠️ 基础可用 | `_cancel_event` 在 streaming 循环中检查 |

### Agent Factory 复杂度 ⚠️ 需优化

| 问题 | 优先级 | 说明 |
|------|--------|------|
| ReasoningChatOpenAIMixin 脆弱 | 中 | Monkey-patch LangChain 内部，难测试 |
| Model Builder 无类型约束 | 低 | `_MODEL_BUILDERS` dict 无 Protocol 签名 |

### 数据库层 ✅ 已添加索引

| 改进 | 状态 | 说明 |
|------|------|------|
| conversation_id 索引 | ✅ 完成 | migration v9 |
| turn_id 索引 | ✅ 完成 | migration v9 |
| created_at 索引 | ✅ 完成 | migration v9 |
| conversations.updated_at 索引 | ✅ 完成 | migration v9 |
| tool_executions.conversation_id 索引 | ✅ 完成 | migration v9 |
| audit_agent_models 表 | ✅ 完成 | migration v10 |
| 无外键约束 | ⚠️ 待定 | 需评估是否影响性能 |

### UI 耦合 ✅ 已改善

| 改进 | 状态 | 说明 |
|------|------|------|
| ChatPage 通过 setter 注入服务 | ✅ 完成 | MainWindow 实例化 ChatService 后注入 ChatPage |

### Workflow View ✅ 已对齐

| 改进 | 状态 | 说明 |
|------|------|------|
| 8 阶段 DAG 布局 | ✅ 完成 | 与 audit_subagents.py 一致 |
| 模块文档字符串 | ✅ 已修正 | 从旧的 5 节点描述更新为 8 阶段 |

### 漏洞审计工作流 ⚠️ 仅定义未集成

| 问题 | 优先级 | 说明 |
|------|--------|------|
| 8 阶段 pipeline 无运行时编排 | 高 | `audit_subagents.py` 仅定义规格，无 LangGraph 图构建 |
| 子 Agent 无独立执行逻辑 | 高 | 缺少 subagent executor / orchestrator |
| Workflow View 事件驱动未接入 | 中 | UI 组件就绪但无真实事件源 |

### 测试覆盖 ⚠️ 不足

| 问题 | 优先级 | 说明 |
|------|--------|------|
| Chat 核心模块无单测 | 高 | `streaming.py`, `agent_runner.py`, `history_compactor.py` 无测试 |
| UI 组件无测试 | 中 | `app/ui/` 下无任何测试文件 |
| 集成测试缺失 | 中 | 无 ChatService 端到端测试 |

### 打包与发布 ⚠️ 未验证

| 问题 | 优先级 | 说明 |
|------|--------|------|
| Nuitka 打包未实际产出可用二进制 | 中 | `build_helpers/build_nuitka.py` 存在但无 CI 验证 |
| 无 CI/CD pipeline | 中 | 无 GitHub Actions / 自动化测试 |
| 无版本发布流程 | 低 | 无 changelog、tag、release 机制 |

### 国际化 ⚠️ 基础完成

| 问题 | 优先级 | 说明 |
|------|--------|------|
| i18n 资源完整性未验证 | 低 | `resources/i18n/` 存在但覆盖率未知 |

---

## 代码质量评估

### 优势

- **架构纪律严格**：分层清晰，Supervisor API Protocol 抽象优秀
- **类型标注一致**：全面使用 `from __future__ import annotations` + type hints
- **Dataclass 使用得当**：模型层干净 (Conversation, ChatMessage, StreamEvent)
- **文档完善**：模块级 docstring 解释设计意图
- **日志规范**：统一使用 `logging` 模块 + named loggers
- **子模块隔离**：IDE 与 IDA-MCP 零代码依赖，仅通过 HTTP/MCP/subprocess 通信

### 需改进

- **God Class**：`ChatServiceWorker` 承担过多职责 (agent 构建 + 执行 + 流处理 + 持久化)
- **Mixin 脆弱性**：`ReasoningChatOpenAIMixin` patch LangChain 内部

---

## 下一步优先事项

1. **实现审计 pipeline 编排**：基于 `audit_subagents.py` 构建 LangGraph 图，连接 orchestrator 与 8 个子 agent
2. **补充核心测试**：streaming / agent_runner / history_compactor 单测
3. **建立 CI pipeline**：GitHub Actions 自动运行 IDE tests + compile check
4. **Nuitka 打包验证**：产出可用二进制并建立发布流程
