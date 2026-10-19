# FitTrack 项目约定

- 保持 Svelte 5 / TypeScript / FastAPI / SQLite 架构，代码按界面、路由、存储、计算、AI 与任务分层。
- 用户资料、图片、任务与事件都必须校验所属用户；管理员身份不授予读取其他用户健康记录的权限。
- 金额、密码、API 密钥不得写入日志、前端资源、测试、文档或 Git；真实图片与运行数据仅保存在忽略目录。
- 日期使用 Asia/Shanghai；纯计算必须确定性，AI 输出先验证再展示为草稿。
- AI 测试默认离线模拟；真实请求限定次数，不自动重发超时请求。
- 修改后运行相关 pytest、前端 check/build；更新 docs/PROGRESS.md 和相应说明，再按阶段提交。
- Windows 文件操作使用明确的绝对路径和 LiteralPath，移动前后核对文件哈希。
