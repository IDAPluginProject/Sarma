# Sarma Project Manifest

## 项目信息

- 名称: Sarma (IDA-MCP IDE)
- 类型: PySide6 桌面应用
- 语言: Python 3.12+
- 构建: Poetry + Nuitka
- 许可: MIT
- 仓库: Captain-AI-Hub/Sarma

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    PySide6 Desktop IDE                       │
├─────────────────────────────────────────────────────────────┤
│  UI Layer        │  Presenters      │  Services             │
│  (Qt Widgets)    │  (View Models)   │  (Business Logic)     │
│  app/ui/         │  app/presenters/ │  app/services/        │
├──────────────────┴──────────────────┴───────────────────────┤
│              Chat Runtime (app/chat/)                        │
│  LangGraph ReAct │ MCP Pool │ Streaming │ Persistence       │
├─────────────────────────────────────────────────────────────┤
│              Supervisor (supervisor/)                        │
│  Gateway │ Installer │ Config │ Health │ Platform            │
├─────────────────────────────────────────────────────────────┤
│              Shared (shared/)                                │
│  Paths │ Database │ DTO │ Events │ Config R/W               │
├─────────────────────────────────────────────────────────────┤
│              IDA-MCP Gateway (HTTP/MCP)                      │
│  ← subprocess / HTTP / MCP →                                │
├─────────────────────────────────────────────────────────────┤
│              IDA Plugin Runtime (IDA Python)                 │
│  FastMCP Server │ API Tools │ Heartbeat │ Instance Registry  │
└─────────────────────────────────────────────────────────────┘
```

## 目录树

```
Sarma/
├── ide/                              # 主项目 (PySide6 IDE)
│   ├── launcher.py                   # 开发启动入口
│   ├── pyproject.toml                # Poetry 项目配置
│   ├── requirements.txt              # 依赖清单
│   │
│   ├── app/                          # 应用层
│   │   ├── main.py                   # IDE 初始化
│   │   ├── i18n.py                   # 国际化
│   │   │
│   │   ├── chat/                     # Chat/Agent 运行时
│   │   │   ├── agent_factory.py      #   LangGraph agent 构建
│   │   │   ├── agent_runner.py       #   Agent 执行 + 事件翻译
│   │   │   ├── audit_subagents.py    #   8 阶段漏洞审计 pipeline 定义
│   │   │   ├── chat_service.py       #   QThread + asyncio 编排
│   │   │   ├── errors.py             #   Chat 异常类型
│   │   │   ├── history_compactor.py  #   历史消息压缩
│   │   │   ├── mcp_pool.py           #   MCP 客户端连接池
│   │   │   ├── message_persister.py  #   消息持久化状态机
│   │   │   ├── models.py             #   数据模型 (Conversation, Message)
│   │   │   ├── persistence.py        #   SQLite CRUD
│   │   │   ├── prompts.py            #   System prompt 构建
│   │   │   └── streaming.py          #   Streaming 事件标准化
│   │   │
│   │   ├── presenters/               # Presenter 层 (纯 Python)
│   │   │   ├── chat_presenter.py     #   消息 → 视图模型
│   │   │   ├── main_window_presenter.py  # 状态卡片映射
│   │   │   └── settings_presenter.py #   设置表单映射
│   │   │
│   │   ├── services/                 # 应用服务
│   │   │   ├── file_preview_service.py   # 文件预览路由
│   │   │   ├── gateway_manager.py    #   Gateway 管理封装
│   │   │   ├── settings_service.py   #   设置读写
│   │   │   ├── skill_service.py      #   Skill 导入/管理
│   │   │   └── supervisor_client.py  #   Supervisor API 客户端
│   │   │
│   │   └── ui/                       # PySide6 UI 组件
│   │       ├── main_window.py        #   主窗口框架
│   │       ├── theme.py              #   主题系统
│   │       ├── icons.py              #   图标管理
│   │       ├── chat/                 #   Chat UI
│   │       │   ├── page.py           #     Chat 主页面
│   │       │   ├── composer.py       #     消息编辑器
│   │       │   ├── message_list.py   #     消息列表
│   │       │   ├── provider_selector.py  # Provider 选择
│   │       │   ├── role_panel.py     #     角色/系统提示
│   │       │   ├── session_sidebar.py    # 会话侧边栏
│   │       │   ├── skill_selector.py #     Skill 选择
│   │       │   ├── tool_trace_panel.py   # Tool 调用追踪
│   │       │   └── workflow_view.py  #     审计 DAG 可视化
│   │       ├── workspace/            #   工作区 UI
│   │       │   ├── directory_tree.py #     文件树
│   │       │   ├── code_view.py      #     代码预览
│   │       │   ├── hex_view.py       #     十六进制预览
│   │       │   └── image_view.py     #     图片预览
│   │       ├── settings/             #   设置 UI
│   │       │   ├── page.py           #     设置主页面
│   │       │   ├── widgets.py        #     设置控件
│   │       │   ├── dialogs.py        #     设置对话框
│   │       │   └── workers.py        #     后台任务
│   │       └── dialogs/              #   通用对话框
│   │           ├── first_run_install.py  # 首次运行向导
│   │           └── workspace_selector.py # 工作区选择
│   │
│   ├── supervisor/                   # Supervisor 控制面
│   │   ├── main.py                   #   Supervisor 入口
│   │   ├── manager.py                #   聚合管理器
│   │   ├── api.py                    #   ISupervisorAPI Protocol
│   │   ├── config_store.py           #   配置存储
│   │   ├── gateway_controller.py     #   Gateway 生命周期
│   │   ├── health.py                 #   健康检查
│   │   ├── install_runner.py         #   安装执行器
│   │   ├── installer.py              #   安装逻辑
│   │   ├── models.py                 #   Supervisor 模型
│   │   ├── platform_detector.py      #   平台探测
│   │   └── process_manager.py        #   进程管理
│   │
│   ├── shared/                       # 共享基础设施
│   │   ├── database.py               #   SQLite 封装
│   │   ├── dto.py                    #   数据传输对象
│   │   ├── enums.py                  #   枚举定义
│   │   ├── events.py                 #   事件类型
│   │   ├── ida_mcp_config.py         #   IDA-MCP 配置读写
│   │   ├── migrations.py             #   数据库迁移
│   │   ├── models.py                 #   共享模型
│   │   ├── paths.py                  #   路径解析
│   │   ├── platform.py               #   平台工具
│   │   └── runtime.py                #   运行时根目录
│   │
│   ├── bootstrap/                    # 引导工具
│   ├── build_helpers/                # Nuitka 打包
│   │   └── build_nuitka.py
│   │
│   ├── resources/                    # 捆绑资源
│   │   ├── ida_mcp/                  #   [Git Submodule] IDA-MCP 插件
│   │   ├── diaphora/                 #   [Git Submodule] Diaphora
│   │   ├── i18n/                     #   国际化文案
│   │   ├── icons/                    #   图标资源
│   │   └── logo.png
│   │
│   ├── tests/                        # IDE 测试套件
│   ├── data/                         # 用户数据 (持久化)
│   │   └── skills/
│   └── resources/
│       └── skills/                   # Agent 技能资料
│           ├── idapython/            #   IDAPython API 文档 (50+ 模块)
│           └── router-fs-vuln-audit/ #   路由器漏洞审计技能
│
├── codemap.md                        # 进度追踪
├── project.md                        # 本文件 (项目清单)
├── AGENTS.md                         # Agent 开发约束
├── README.md / README_CN.md          # 用户文档
├── pytest.ini                        # 测试配置
├── LICENSE                           # MIT
└── .gitmodules                       # 子模块配置
```

## 运行时边界

| 运行时 | 环境 | 入口 |
|--------|------|------|
| IDE | Python 3.12 + PySide6 | `ide/launcher.py` |
| Supervisor | Python 3.12 (无 GUI) | `ide/supervisor/main.py` |
| Gateway | Python 3.12 (独立进程) | `ida_mcp/command.py gateway start` |
| IDA Plugin | IDA Python + IDA SDK | `ida_mcp.py` → `plugin_runtime.py` |
| Tests (IDE) | pytest (普通 Python) | `pytest ide/tests` |
| Tests (Plugin) | pytest (需 gateway + IDA) | `python test/test.py` |

## 通信协议

```
IDE ──subprocess──→ Gateway (127.0.0.1:11338)
IDE ──HTTP GET────→ Gateway /internal/status
IDE ──MCP─────────→ Gateway /mcp (proxy)
Gateway ──HTTP────→ IDA Instance /internal/call
IDA Plugin ──HTTP─→ Gateway /internal/register
```

## 依赖关系 (核心)

| 依赖 | 版本 | 用途 |
|------|------|------|
| PySide6 | >=6.11.1 | Qt GUI 框架 |
| deepagents | >=0.6.2 | Agent 框架 |
| langgraph | >=1.2.0 | 图工作流 |
| langchain-openai | latest | OpenAI Provider |
| langchain-anthropic | latest | Anthropic Provider |
| langchain-mcp-adapters | >=0.2.2 | MCP 集成 |
| pydantic | >=2.13.4 | 数据验证 |

## 子模块

| 路径 | 远程 | 分支 | 用途 |
|------|------|------|------|
| `ide/resources/ida_mcp` | Captain-AI-Hub/IDA-MCP.git | main | IDA-MCP 插件 |
| `ide/resources/diaphora` | joxeankoret/diaphora | master | Diaphora 二进制比对 |

## 项目状态摘要

- 核心架构: 完成
- UI 组件: 完成
- Chat Runtime: 完成
- Supervisor: 完成
- IDA-MCP 插件: 完成
- 漏洞审计 Pipeline: 部分完成 (编排层缺失)
- 错误处理: 部分完成
- CI/CD: 未开始
