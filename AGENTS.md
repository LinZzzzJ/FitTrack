# FitTrack AI 开发指南

FitTrack · 轻衡是本地优先的身体、饮食和训练日记。已发布基线为 v0.4.0、API 修订号 2；当前 `main` 源码 API 修订号为 5，包含后续训练、饮食功能，但尚无对应的新便携包验收。服务器模式已有部分接口与测试，Linux/WSL 完整运行和公网部署尚未验收。版本、验证范围和下一步以 [当前状态](docs/current_status.md) 为准。

## 接手顺序

1. 阅读 [当前状态](docs/current_status.md)，核对当前分支、工作区差异和任务范围。
2. 阅读 [架构](docs/ARCHITECTURE.md) 与本次相关模块、测试；以实际实现为准。
3. 涉及平台、启动或迁移时先读 [环境](docs/environment.md) 和 [移植清单](docs/migration.md)。
4. 将不确定结论标为待确认，不把讨论、历史测试或平台推断写成当前实测结果。

## 工程入口

- `src/fittrack/__main__.py` → `cli.main`：明确数据根目录、实例锁与服务启动。
- `app.create_app` / `routes` / `management_routes`：生命周期、访问保护、HTTP 合约。
- `paths.RuntimePaths` / `control.WorkspaceHub`：受控根目录、控制库与个人工作区。
- `store` / `calculations` / `nutrition` / `coaching`：记录、确定性汇总、标签换算与周资格。
- `WorkoutTemplate`、`/workout-templates` 和 `/workout-days`：个人训练模板、账号隔离与训练日历记录标记；导入格式见接口文档。
- `credentials.CredentialStore` / `ai.AIClient` / `jobs.JobRunner` / `events.EventBus`：个人凭据、AI 合约、后台线程和 SSE。
- `web/src/pages`、`web/src/components`、`web/src/lib`：Svelte 页面、组件、类型和共用状态。
- `tools`、`scripts`、`release-docs`：Windows 打包、检查和成品指南；不要当作 Linux 启动配方。

## 开发与验证

已验证的源码环境为 Windows、Python 3.12、Node.js 24。在仓库根目录的 PowerShell 运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

`setup.ps1` 会安装依赖、构建页面并生成快捷方式；已有环境仅检查时使用 `check.ps1`。检查脚本包含 pytest、Ruff、Svelte/TypeScript 检查和生产构建。测试与缓存写入明确的 `artifacts` 子目录。Linux 命令及其未验证边界见环境文档，不能直接在 Linux 执行 `.ps1` 后宣称通过。

## 必须保持的约束

- 保持 Svelte 5 / TypeScript / FastAPI / SQLite 分层，先复用现有合约和任务体系。
- 用户资料、图片、任务、备份和事件都校验当前账号归属；管理员不获得读取他人健康记录的权限。
- 所有应用运行文件从 `RuntimePaths` 获取位置；不得回退 AppData、注册表定位文件、当前目录或系统临时目录。程序依赖和构建产物与运行数据的边界见架构文档。
- 不读取、修改或复制用户真实数据库、图片、主密钥及 `.env` 来做测试；使用隔离根目录和模拟账号。
- 密码、API Key、会话令牌、真实图片及私人路径不得进入日志、文档、截图、前端或 Git。当前生产路径使用个人 `CredentialStore`，不得恢复公共 Key 回退。
- 日期使用 `Asia/Shanghai`、接口使用 `YYYY-MM-DD`。统计起点 `2026-10-15` 与历史补录边界不同，不得随意修改。
- 热量和营养汇总由后端确定性计算；AI 输出须校验、预览和人工确认，不能自动改目标或入账。
- 精确餐食录入由后端按蛋白质/碳水/脂肪 4/4/9 计算热量；不信任客户端提交的精确模式 kcal。
- 静息消耗估算必须与设备/手动值区分；营养未知值保持为空，不得补零。当前扩展营养项为膳食纤维、总糖和钠。
- 新增个人模板时同步检查备份白名单与旧 v1 健康 ZIP 恢复；当前健康 ZIP v2 包含模板。
- AI 测试默认离线模拟；真实调用需用户授权，不自动重发超时请求。服务重启后的未完成任务标为中断。
- 保持 API 修订号、请求指纹、幂等确认及备份格式兼容；字段变化先检查前端类型、恢复校验和旧记录。
- 不强杀用户浏览器或不属于本应用的进程。Windows 文件操作用明确绝对路径和 `-LiteralPath`，复制/迁移核验哈希并保留原档。
- 不擅自清理历史、删除数据、强制推送或覆盖用户未提交修改；提交、推送及发布按当前用户授权执行。

## 文档地图与维护

| 问题 | 读取文档 |
|---|---|
| 当前版本、验证范围、下一步 | [current_status](docs/current_status.md)、[ACCEPTANCE](docs/ACCEPTANCE.md) |
| 模块、存储、计算、数据流 | [ARCHITECTURE](docs/ARCHITECTURE.md) |
| 请求字段、任务状态、错误和备份合约 | [interfaces](docs/interfaces.md) |
| 为什么这样设计、哪些方案未采用 | [decisions](docs/decisions.md) |
| 用户需求、实现及验收对应 | [requirements](docs/requirements.md) |
| 故障复现、定位与经验 | [development_notes](docs/development_notes.md) |
| Windows/WSL 环境和移植工作 | [environment](docs/environment.md)、[migration](docs/migration.md) |
| 历史演进及资料访问范围 | [history_summary](docs/history_summary.md) |
| 未解问题和证据缺口 | [open_questions](docs/open_questions.md) |
| 公网路线与本机模式差异 | [WEB_DEPLOYMENT_ASSESSMENT](docs/WEB_DEPLOYMENT_ASSESSMENT.md) |

修改后运行相关检查，更新当前状态、对应专题、用户指南与 [版本进展](docs/PROGRESS.md)。同一功能涉及 API、数据恢复、用户流程或平台边界时，检查 `README.zh-CN.md`、`README.md`、`interfaces.md`、`ARCHITECTURE.md`、`ACCEPTANCE.md`、`migration.md` 和部署评估中的旧描述。文档应区分已确认事实、已验证方案、讨论但未验证、推断和待确认，并给出版本、代码/测试或讨论主题依据。保留 `ARCHITECTURE.md` 等现有大小写，不创建仅大小写不同的重复文件。
