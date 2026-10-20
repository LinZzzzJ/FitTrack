# 技术决策与边界

功能基线：v0.4.0；整理日期：2026-10-20。已确认表示实现或明确需求支持；已验证仅限所列环境。原始材料范围见 [历史摘要](history_summary.md)。

## D01：Svelte 单页前端与 FastAPI 同源后端

- **状态**：已采用，Windows 源码及便携版验证。
- **背景/约束**：需要美观图表、集中账号、目录管理、后台 AI 和可复用的服务器路线；初版参考 BrushGraft 的本地工程组织。
- **选择**：Svelte 5/TypeScript/Vite，FastAPI 提供 `/api` 和构建后的静态页面。保留原项目相关 MIT 声明。
- **考虑的替代**：纯浏览器、IndexedDB、浏览器直连 AI，适合静态网站，但与当前后台任务和受控文件目录需求有差异，未作为本项目实现路线。
- **代价/边界**：本机仍需后端进程；公网访问还需托管后端、HTTPS 和运维，上传 GitHub 不会运行应用。
- **证据**：[app.py](../src/fittrack/app.py)、[Vite 配置](../web/vite.config.ts)、[部署评估](WEB_DEPLOYMENT_ASSESSMENT.md)。

## D02：明确根目录、控制库与个人健康库分离

- **状态**：v0.2 起已采用，Windows 迁移与隔离测试通过。
- **背景/约束**：用户要求掌控账号、密钥、日志、临时文件、图片与备份的位置；无隐式 AppData/注册表定位文件。
- **选择**：先指定根目录，再初始化服务；控制库保存账号/会话/工作区映射/凭据，个人库保存健康业务。个人工作区使用根目录内的独立子目录。
- **未采用**：恢复单一公共数据库加全局 Key，或目录不可用时静默回退其他磁盘，均与已确认边界冲突。
- **代价/边界**：迁移和备份需要两种合约；浏览器缓存、Cookie 和操作系统记录不受应用根目录保证覆盖。
- **证据**：[paths.py](../src/fittrack/paths.py)、[control.py](../src/fittrack/control.py)、[受控运行测试](../tests/test_managed_runtime.py)。

## D03：SQLite WAL、单进程与有限并发

- **状态**：已采用；本机并发写入、恢复与任务测试通过。
- **选择**：控制库和个人库使用 SQLite，外键/WAL/写锁；AI 线程池上限 2，存储操作池上限 1，SSE 按账号通知。
- **原因**：适合本地部署，依赖少、数据可控，可使用 SQLite backup API 得到一致副本。
- **未来替代**：共享数据库、外部队列及对象存储属于规模扩大后的评估，尚未实现；没有证据说明曾完整试验并否定 PostgreSQL。
- **代价/边界**：不能简单增加 Uvicorn worker 来扩容；数据库/WAL 不应由 Windows 和 WSL 两个进程同时打开，也不能只复制运行中的主数据库文件。
- **证据**：[store.py](../src/fittrack/store.py)、[jobs.py](../src/fittrack/jobs.py)、[storage_ops.py](../src/fittrack/storage_ops.py)、[SQLite WAL 官方说明](https://www.sqlite.org/wal.html)。

## D04：个人 Key 加密保存或会话内存保存

- **状态**：已采用；账号隔离、退出及重启行为有测试。
- **选择**：密码 Argon2 哈希；API Key 为可解密凭据，使用 Fernet，主密钥单独存放；不记住时只在有效会话的后端内存保留。界面密码框、固定配置状态，不回传 Key 或片段。
- **原因**：AI 调用需要原凭据，不能像密码一样只保存不可逆哈希；其他账号不得使用维护者默认 Key。
- **未采用**：当前生产流程不使用全局 `.env` Key；浏览器直连不是本项目的凭据模式。`config.Settings` 仍供旧版导入与回归，不能误当作生产入口。
- **代价/边界**：主密钥丢失则旧 Key 密文不可恢复；服务器版需要用户信任服务器保管凭据。
- **证据**：[credentials.py](../src/fittrack/credentials.py)、[app.py](../src/fittrack/app.py)、[账号控制库](../src/fittrack/control.py)。

## D05：AI 草稿与确定性计算分离

- **状态**：已采用；模拟接口覆盖，部分历史真实调用成功不构成准确率承诺。
- **选择**：模型输出结构化 JSON，经 Pydantic 校验；普通餐食细项加总，标签能量和份量由后端换算。有氧 AI 提议整段平均 MET，保存训练才入账；目标建议采用并保存才生效。
- **原因**：照片份量、包装反光和模型结构均可能出错，需要人工修正与明确入账步骤。
- **未采用**：未知营养填零、直接信任模型整餐总量、预览即入账、失败自动重试，均未采用。
- **代价/边界**：原图完整也可能识别失败；模型支持与价格须按提供方当前信息确认。`/models` 连接测试只验证鉴权/模型列表，不能证明识图质量。
- **证据**：[ai.py](../src/fittrack/ai.py)、[nutrition.py](../src/fittrack/nutrition.py)、[标签测试](../tests/test_diet_labels_version.py)。

## D06：固定统计起点与严格周资格

- **状态**：用户明确要求，已实现并测试。
- **选择**：统计与周周期锚定 `2026-10-15`；历史补录不受此下限约束。周复盘需完整周期结束，七天均有确认餐食且完成记录，休息日无需训练或称重。
- **原因**：保持各页面一致，避免对不完整一周做误导性的完整周分析。
- **代价/边界**：公开新用户仍沿用该锚点；改成每人起点是未来产品决策，不能在移植时顺手改变。
- **证据**：[tracking.ts](../web/src/lib/tracking.ts)、[coaching.py](../src/fittrack/coaching.py)、[周资格测试](../tests/test_coaching.py)。

## D07：版本身份与表单兼容保护

- **状态**：v0.3 起已采用；旧后端搭配新前端的保护有测试。
- **背景**：历史常驻服务未重启，静态页面已经更新，造成羽毛球缺失和 `ai_estimate_job_id` 被旧后端拒绝。
- **选择**：`/api/version` 返回 API 修订号、能力和加载指纹；不兼容时保留表单并阻止提交。正常重启等待旧实例退出，不强杀、不静默另占端口。
- **代价/边界**：推送源码、构建前端和运行实例更新是不同动作；便携版按构建清单识别身份。
- **证据**：[version.py](../src/fittrack/version.py)、[前端兼容层](../web/src/lib/compatibility.svelte.ts)、[cli.py](../src/fittrack/cli.py)。

## D08：复制、核验、切换并保留旧档

- **状态**：个人迁移、根迁移和恢复已实现，Windows 验收；跨操作系统恢复未实测。
- **选择**：暂停对应写入、等待任务、取得一致副本，校验数据库及图片，再切换映射；恢复到新工作区，保留旧工作区。
- **原因**：避免失败时只剩半成品，满足可控数据要求。
- **代价/边界**：占用额外磁盘；健康 ZIP 不带登录和凭据，完整根目录才包含主密钥。保留旧档不是自动定期备份。
- **证据**：[storage_ops.py](../src/fittrack/storage_ops.py)、[relocation.py](../src/fittrack/relocation.py)、[移植说明](migration.md)。

## D09：Windows onedir 便携包与原生目录选择

- **状态**：v0.4.0 已交付，Windows 11 x64 验收；Windows 10 尚未实机验证。
- **选择**：固定 CPython 3.13.16、PyInstaller 6.22.3，目录打包后 ZIP 分发；Windows 原生目录对话框替代额外 GUI 运行库。浏览器/系统工具启动前处理冻结程序 DLL 环境。
- **原因**：免安装开发工具、缩小体积，同时保留完整业务及受控临时目录。
- **未采用**：单文件自解压未作为本次发布形式，以避免每次运行时解包到额外临时目录。
- **代价/边界**：必须完整解压；EXE 未签名；Windows 包不能变成 Linux 本机包。PyInstaller 构建目标依赖平台，Linux 移植仍需独立验证。
- **证据**：[portable.spec](../tools/portable.spec)、[distribution.py](../src/fittrack/distribution.py)、[公开验收](ACCEPTANCE.md)、[PyInstaller 官方说明](https://pyinstaller.org/en/stable/operating-mode.html)。

## D10：公开副本与源码/成品分别发布

- **状态**：已采用；此次知识整理仍在公开副本维护。
- **选择**：保留本机研发历史，导出经脱敏的 v0.4.0 建立干净公开仓库；`main` 持续开发，标签记录定版，Release 承载便携 ZIP 和说明。
- **原因**：公开分享源码和软件下载，同时不公开账号、Key、正式记录和私人开发历史。
- **代价/边界**：多个本机工作区容易混淆，公开仓库没有早期开发提交；历史文档必须解释范围。知识库提供可移植上下文，不能声称恢复全部原始聊天。
- **证据**：[仓库](https://github.com/LinZzzzJ/FitTrack)、[v0.4.0](https://github.com/LinZzzzJ/FitTrack/releases/tag/v0.4.0)、[当前状态](current_status.md)。
