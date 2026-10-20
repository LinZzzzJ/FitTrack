# 需求、实现与验收映射

对应公开 v0.4.0；整理日期：2026-10-20。来源为当前可访问对话中的用户要求、已批准实施计划、源码和验收记录；没有将 AI 自行建议视作已确认需求。功能“已实现”不表示所有平台均通过验收。

## 已确认且当前已实现

| ID | 需求及来源主题 | 实现位置 | 验收边界 |
|---|---|---|---|
| R01 | 初版：身高、体重、可选体脂、性别、平均静息能量与个人目标 | `models.Profile`、`Store.save_profile`、Settings 页面 | 生效日期、范围、历史参数；未要求用年龄公式替代用户静息值 |
| R02 | 初版：每天身体测量、历史补录与编辑 | `BodyRecord`、`Store.save_body`、Body 页面 | 缺失留空，不补零；历史日期仍可访问 |
| R03 | 初版及图片反馈：上传/拖入照片、补充实际食用描述、营养草稿 | `put_image`、`AIClient.meal`、Meals 页面 | 四种图片、原图保留、完整预览；AI 估算需人工核对 |
| R04 | 包装标签计划：读取标签、人工补齐、按实际克数或袋数换算 | `LabelReadout`、`nutrition.label_food`、标签编辑器 | kJ/4.184；60g/120g/半袋；预览不入账、保存后端重算 |
| R05 | 饮食历史计划：每天累加、按周查看、早于统计起点也可补录 | `Store.save_entry`、`diet_history`、DietHistory | 新建餐食累加；编辑同 ID 更新；原任务重试保留日期 |
| R06 | 运动记录：力量逐组、有氧类型/时长/强度、手动覆盖 | `Workout`、`calculations.workout_energy`、Training | 力量量=总外加重量×次数；整次时长估算消耗；计划不入账 |
| R07 | 10/15 趋势与有氧计划：加入羽毛球、有氧 AI 预览/采用 | `ACTIVITIES`、`CardioInput`、`coaching`、CardioAssistant | 羽毛球 5.5/7/9 MET；仅有氧；输入变化旧估算不可采用 |
| R08 | 初版及统一日期计划：身体、热量、训练趋势与明细表 | `trends`、`tracking.ts`、Dashboard/Body/Trends | 固定 2026-10-15、跨段连续、七日均值边界、空值不补零 |
| R09 | 目标生成请求：填目标体重后生成热量及三大营养素 | `GoalProfile`、`AIClient.goals`、Settings | 草稿可未保存；采用再保存；不自动覆盖目标 |
| R10 | 初版：每日完成后 AI 建议、目标和近七天背景 | `feedback`、`Store.context`、Dashboard | 手动触发、源指纹、过期提示；普通记录编辑不调用 AI |
| R11 | 周分析计划：结束的一整周，饮食/训练/身体分析 | `weekly_status`、`weekly_review`、WeeklyReview | 七天均有确认餐食且完成；休息日有效；失败保留上一份报告 |
| R12 | 多人记录：账号、图片、任务、事件和凭据隔离 | `WorkspaceHub`、路由、`EventBus` | 管理员不读取他人健康数据；越权资源不泄漏 |
| R13 | 受控目录计划：根目录明确选择，所有运行数据位置可查 | `RuntimePaths`、DataManagement | 不隐式落 AppData/其他磁盘；临时目录失败不回退 |
| R14 | 个人 Key：密码式输入、默认无公共 Key、记住或会话保存 | `CredentialStore`、Settings | Fernet、固定状态、不回传片段；退出/过期/重启清理临时 Key |
| R15 | 数据管理计划：个人/整根迁移、备份恢复和旧档保留 | `storage_ops`、`relocation`、`upgrade` | 复制校验切换；健康备份不含账号/密钥；跨 OS 尚未实测 |
| R16 | 本机常驻：无 CMD、不自启、快捷方式启停重启 | `cli`、`desktop`、`distribution` | Windows 验证；端口冲突不另开；关闭网页后台继续 |
| R17 | 删除计划：只删除已结束的餐食照片/标签分析 | `Store.delete_job`、DELETE jobs、DietHistory | 确认不可页面撤销；运行任务拒绝；餐食/原图/备份保留 |
| R18 | 发布计划：完整、小体积 Windows 便携版与非 MD 指南 | `tools`、`release-docs`、构建检查脚本 | 无需 Python/Node，Windows 11 x64；约 20.81 MiB ZIP；Win10 未实测 |
| R19 | 公开计划：Public 源码、精致中文 README、Release | README、公开 `main`、v0.4.0 Release | 干净公开历史、模拟截图、无个人数据；没有部署公网服务 |

测试映射：计算/历史见 `test_core.py`；AI 异常/恢复见 `test_ai_and_recovery.py`；目标见 `test_goal_suggestions.py`；有氧/周复盘见 `test_coaching.py`；目录/凭据见 `test_managed_runtime.py`；标签/版本见 `test_diet_labels_version.py`；原图见 `test_meal_images.py`；删除见 `test_delete_meal_jobs.py`；便携边界见 `test_portable.py`。验证范围见 [ACCEPTANCE](ACCEPTANCE.md)。

## 关键不变量

- 初始静息 1800、活动系数 1.2、75kg、6 MET、60 分钟、摄入 2000 → 净运动 375、日消耗 2535、缺口 **535 kcal**。
- 上传照片、AI 分析成功、采用建议和正式保存是不同动作；仅确认餐食和实际训练影响收支。
- 新增夜宵与已有晚饭累加；编辑原餐食才更新该条。重新选择照片本身不应自动覆盖已入账记录。
- 饮食长期保存，七天只是查询与展示窗口；图表固定起点不删除更早记录。
- 应用运行文件受根目录约束；安装依赖、构建产物、绑定快捷方式、浏览器/OS 自身文件分别说明边界。
- 不自动结束用户浏览器、不设置开机启动、不自动调用/重试付费 AI、不静默恢复共享 Key。

## 本轮知识库需求

用户要求沉淀可通过 Git 迁移的项目知识，供后续 Ubuntu/WSL 开发和新 AI 会话接手。本轮仅整理文档，保留 README 设计与现有目录大小写，记录来源、验证状态和材料缺口；不修改业务代码及正式数据。提交、推送和发布按各次任务明确授权执行。

## 已确认方向、尚未交付

| 方向 | 当前状态 | 下一步条件 |
|---|---|---|
| Ubuntu/WSL 跨平台开发 | 知识与移植清单已整理；应用完整适配未完成 | 确定运行目标、重建 Linux 依赖、按矩阵验证 |
| 公网网址服务 | `server` 能力基础与权限测试已存在，实际部署未完成 | 域名/HTTPS、代理、进程与备份、注册策略及真实公网验收 |
| Windows 10/其他 PC | 兼容目标与便携设计已具备，无完整实机证据 | 单独测试并记录平台/限制，不沿用 Win11 结论 |

## 已替代的历史方案与未确认建议

- 初版单库和管理员公共 Key 已被控制库+个人工作区+个人凭据取代；保留旧导入能力，不恢复为默认生产方式。
- 较早仅当前日期饮食展示、1600px/质量85识图副本、缺少版本检查的常驻流程已被后续实现取代；历史记录只能解释演进。
- 纯浏览器重写、PostgreSQL/外部队列、Linux 原生便携包、自动更新、每人独立统计锚点等是可能方向，尚不能写成用户已批准的交付需求。

需求变更时同步 [决策](decisions.md)、[当前状态](current_status.md) 和相关测试；不要把平台适配扩大为重新设计业务。
