# Sarma Roadmap Index

Sarma 的根仓库规划只描述父项目边界、子模块协作和发布节奏。IDE 细节进入 `ide/roadmap.md`，IDA-MCP 插件细节进入 `ide/resources/ida_mcp/roadmap.md`。

## 当前仓库形态

- `ide/` 是主项目：PySide6 桌面 IDE、安装器、gateway 管理、配置、chat/workspace 编排。
- `ide/resources/ida_mcp` 是 Git submodule，跟踪 `Captain-AI-Hub/IDA-MCP.git` 的 `main` 分支。
- `ide/resources/diaphora` 是 Git submodule，跟踪上游 Diaphora 的 `master` 分支。
- 根仓库负责锁定这两个资源版本，并提供 IDE 发布所需的父级文档、测试入口和打包上下文。

## 近期重点

### 1. 子模块发布纪律

- 保持 `.gitmodules` 中的分支约定：IDA-MCP -> `main`，Diaphora -> `master`。
- IDA-MCP 插件变更先在子模块内提交、验证、推送，再回到 Sarma 更新 gitlink。
- Sarma 发布说明应记录所绑定的 IDA-MCP 和 Diaphora 子模块提交。

### 2. IDE 安装与资源管理

- 明确 IDE 安装时复制的文件清单，避免把子模块开发文件误装到 IDA plugins 目录。
- 在设置页展示 IDA-MCP 与 Diaphora 当前绑定提交，便于排查用户环境。
- 继续保持 IDE 普通 Python 运行时与 IDA Python 插件运行时隔离。

### 3. Gateway 与插件体验

- IDE 侧继续负责 gateway 启停、健康检查、实例列表、配置编辑和错误提示。
- 插件侧 API、资源、gateway/proxy 行为在 IDA-MCP 子模块内演进。
- Sarma 根文档只链接插件 API，不复制完整工具清单，避免父仓库文档和子模块文档漂移。

### 4. 打包与分发

- 稳定 Nuitka 打包路径，保证桌面 IDE 可携带固定版本的资源子模块。
- 建立发布前检查：子模块提交存在于远程、IDE smoke test 通过、插件 compileall 通过。
- 后续可增加自动化脚本输出发布包中的子模块版本清单。

## 子项目规划入口

| 子项目 | 规划文档 | 当前关注点 |
|--------|----------|------------|
| Sarma IDE | `ide/roadmap.md` | UI、设置、chat/workspace、安装器、打包 |
| IDA-MCP plugin | `ide/resources/ida_mcp/roadmap.md` | MCP tools/resources、gateway/proxy、live-IDA 测试 |
| Diaphora resource | upstream repository | 跟踪上游 `master`，由 Sarma 锁定可用提交 |

## 测试基线

- IDE 单元/集成测试：`pytest ide/tests`
- IDA-MCP 静态烟测：`python -m compileall -q ide/resources/ida_mcp/ida_mcp.py ide/resources/ida_mcp/ida_mcp ide/resources/ida_mcp/test`
- IDA-MCP live 测试：`python ide/resources/ida_mcp/test/test.py`

live 测试需要 gateway 和已注册 IDA 实例；没有该环境时不要把未运行 live 测试解释为通过。

## 阅读顺序

1. `README.md` - Sarma 用户入口和子模块说明。
2. `project.md` - 仓库级项目地图和维护边界。
3. `codemap.md` - 架构 atlas、入口和调用链索引。
4. `ide/project.md` + `ide/roadmap.md` - IDE 子项目结构与规划。
5. `ide/resources/ida_mcp/API.md` - IDA-MCP 工具与响应契约。
