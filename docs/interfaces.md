# 接口、任务与数据格式合约

当前开发工作区 API 修订号 3，尚未作为新功能版本发布。以下根据 `models.py`、`routes.py`、`management_routes.py`、`store.py`、`coaching.py` 和 `storage_ops.py` 整理；修改接口时同步前端 `web/src/lib/types.ts`、任务与恢复校验。

## 通用规则

- 同源 `/api`；日期 `YYYY-MM-DD`，业务“今天”使用上海时区；kg、cm、g、分钟和 kcal 见字段后缀。
- JSON 输入继承 `Model`，`extra=forbid`、不接受 NaN/Infinity。前端请求通过 `x-fittrack-api: 3` 表明接口修订号；编辑时不要把响应中的 `totals`、`created_at` 等只读字段原样回传。
- 账号凭 `fittrack_session` Cookie 验证，HttpOnly、SameSite=strict、14 天；`server` 模式另加 Secure。退出使服务端会话失效。
- 登录、注册及版本接口不要求已有会话；其余 `/api` 按当前用户检查归属。Host/Origin 检查仍适用于免登录接口。
- 返回 `detail` 错误信息；401 未登录、403 权限/访问保护、404 不存在或越权资源、409 冲突/运行任务不可删除、422 模型字段校验失败。业务 `ValueError` 为 400；不要假设全部不兼容错误均为 422。
- 后端磁盘源码变化会触发重启保护，部分写入返回 409；前端兼容层也会预检版本。允许的认证与管理路径以 `app.Guard` 为准。

## 主要 HTTP 接口

| 方法与路径 | 输入/输出与关键行为 |
|---|---|
| `GET /api/version` | `version`、`api_revision`、`capabilities`、`backend_build`、`restart_required`、`distribution`、`build_id`；不返回物理路径 |
| `POST /api/auth/register`、`/login` | `username`、`password`；注册 201 并建立会话，登录返回用户 |
| `POST /api/auth/logout` | 204；撤销当前会话并清理对应临时凭据 |
| `GET /api/me` | `user`、`today`、`profile`、`ai`、`runtime`、`activities`、`activity_levels` |
| `GET /api/profile?day=`、`PUT /api/profile` | 指定日期有效资料；保存完整参数版本，含 `effective_date` |
| `GET /api/body?start=&end=`、`PUT /api/body` | 区间测量；按日期保存，可空体重/体脂/静息覆盖 |
| `DELETE /api/body/{day}` | 204；删除当天测量，非删除资料版本 |
| `POST /api/uploads` | multipart 字段 `file`，201 返回图片索引；实际内容验证，12 MiB/4000 万像素限制 |
| `GET /api/images/{iid}?thumb=true` | 当前用户的原图或缩略图；不公开文件路径 |
| `POST /api/meals`、`/workouts`、`/plans` | 创建 201；相应请求模型见下文 |
| `PUT /api/meals/{id}`、`/workouts/{id}`、`/plans/{id}` | 更新指定条目；保留明确的记录日期 |
| `DELETE /api/meals/{id}`、`/workouts/{id}`、`/plans/{id}` | 删除条目 204；与“删除分析”语义不同 |
| `GET /api/plans?start=&end=` | 计划及由实际训练关联推导的完成状态 |
| `GET /api/workout-days?start=&end=` | 当前用户该日期范围内有实际训练的日期数组，用于训练日历标记 |
| `GET/POST /api/workout-templates` | 列出或创建当前用户的个人训练模板 |
| `PUT/DELETE /api/workout-templates/{id}` | 更新/删除当前用户模板；越权资源返回 404 |
| `POST /api/plans/{id}/complete` | 201；转实际训练，`plan_id` 唯一，重复调用不重复训练 |
| `GET /api/days/{day}` | 资料、测量、餐食、实际训练、汇总、完成状态、反馈、任务与计划 |
| `POST /api/days/{day}/complete` | `{completed:true}`；不要求生成每日反馈 |
| `GET /api/diet-history?start=&end=` | 最多 7 个日期，含端点；`{start,end,days:[{date,meals,totals,jobs}]}`，只包含餐食分析任务 |
| `GET /api/trends?start=&end=&measurement_start=` | 最多 366 个日期；`days` 和 `plans`；均值下界使用相同 `measurement_start`，跨段不要重置 |
| `POST /api/nutrition-label/preview` | `NutritionLabel` → `{item:FoodItem}`；只计算，不入账 |
| `GET /api/weekly-review?week_start=` | 周资格、缺失日期、运行任务及最新成功报告；省略日期选择最近结束一期或首期等待状态 |
| `POST /api/jobs` | 202；提交任务或返回幂等/同周期运行任务 |
| `GET /api/jobs/{jid}` | 当前账号任务，可能含按最新记录计算的 `stale` |
| `DELETE /api/jobs/{jid}` | 仅已结束的 `meal`；204。排队/运行中 409，越权/不存在/非餐食 404 |
| `GET /api/events` | SSE；不是业务数据的唯一来源，刷新后仍从查询接口恢复状态 |
| `PUT /api/settings` | 当前账号的 AI 设置；不返回明文 Key |
| `DELETE /api/settings/key` | 204；清理账号保存的密文与内存 Key |
| `POST /api/settings/test-connection` | GET 提供方 `/models` 鉴权；模型列表不能证明识图准确或生成可用 |

身体/趋势/计划的通用日期区间限制由 `calculations.dates_between` 定义；饮食另限制 7 天。图表统计锚点不构成历史 API 的录入下限。

## 输入模型与幂等性

完整上下限以 [models.py](../src/fittrack/models.py) 为准；以下列出移植时最容易破坏的字段：

| 模型 | 字段与约束 |
|---|---|
| `Profile` | `effective_date`、`height_cm` 90–240、`initial_weight_kg` 20–350、可空 `body_fat_pct`、`sex`、可空 `age` 13–110；静息能量可手填 500–5000，留空时须有年龄用于 Mifflin–St Jeor 估算；`activity_level` 为久坐/轻度/中度/高度/非常活跃，旧 `activity_factor` 仍兼容。资料读取响应另含 `estimated_resting_kcal`、`estimated_maintenance_kcal`，保存请求不接受这两个派生字段 |
| `BodyRecord` | `date`、可空 `weight_kg`/`body_fat_pct`/`resting_kcal`、`note`；缺失测量不是零 |
| `FoodItem` | `name`、`consumed_part`、`estimated_edible_grams`、`kcal`、三大营养素必需；`fiber_g`、`sugar_g` 可空克数，`sodium_mg` 可空毫克。未知保持空值，旧记录读取兼容 |
| `Meal` | `date`、`slot=breakfast/lunch/dinner/snack`、`title`、`note`、`assumptions`、1–50 项 `items`、可空 `image_id`/`source_job_id`/`nutrition_label` |
| `Workout` | `date`、`title`、`kind=strength/cardio`、`activity`、`duration_minutes` (0,1440]、`intensity=light/moderate/vigorous`、可空 `met` 1–25、`net_kcal_override`、`plan_id`、`ai_estimate_job_id` |
| `Exercise` / `TrainingSet` | 动作 `name`、`sets`；每组 `reps` 和总外加 `weight_kg`，自重为 0 外加重量 |
| `TrainingPlan` | 日期、类别、运动类型、时长、强度、备注和可选动作明细；`status=planned/skipped`，实际完成由训练关联推导 |
| `WorkoutTemplate` | 名称、部位分类、图标标识、默认时长/强度、动作和默认组记录；属于当前用户个人库 |
| `AISettings` | 可选 `api_key`、`base_url`、`vision_model`、`coach_model`、`remember`；空白 Key 不应当作明确清除 |

餐食 `source_job_id`、实际训练 `plan_id` 有唯一性保护；同一来源确认/转训练返回原记录。不同来源的新餐食在当天累加，更新既有 ID 则修改该条记录。用户 ID 始终由会话得到，不相信客户端提交归属。

## 标签结构与确定性换算

`NutritionLabel={label:LabelReadout,portion:LabelPortion}`：

- 标签字段：`name`、`basis_kind=per_100g/per_serving/per_pack`、`basis_grams`、`energy_value`、`energy_unit=kJ/kcal`、`protein_g`、`carbs_g`、`fat_g`、可选 `fiber_g`、`sugar_g`、`sodium_mg`、`assumptions`。**读取草稿允许空值，计算确认不允许缺必要热量和三大营养素。**
- 份量：`mode=grams` 使用 `grams`；`mode=packs` 使用 `pack_grams × packs`，支持小数袋数。照片中出现几袋不代表实际吃几袋。
- `basis_kind=per_100g` 的基准重量按 100g，其他基准需要对应重量；具体完整性检查见 `nutrition.label_food`。
- `kcal = (kJ / 4.184 或原 kcal) × 实际克数 / 基准克数`，三大营养素同倍率缩放。374 kJ/100g、60g 为约 53.63 kcal，120g 约 107.27 kcal。
- 保存 `Meal.nutrition_label` 时后端重算 `items`，不信任客户端伪造的预览值。快照随餐食保存和备份；删除分析来源不移除标签快照。

## AI 任务合约

`JobRequest` 公共字段：`kind`、`date`、`request_key`（8–100 字符）；可选 `image_id`、`note`、`slot`。`meal` 可用照片、`meal_description` 文字描述或二者组合；`meal_mode=label` 仍要求照片。按用户和 `request_key` 幂等；手动重试生成新请求标识，网络重发同一请求使用原标识。

| kind | 附加输入 | 结果及入账边界 |
|---|---|---|
| `meal` | 普通模式需要 `image_id` 或至少 3 字符的 `meal_description`；`meal_mode=label` 需要 `image_id` | 普通模式含 `items`/汇总/假设；标签为 `result.label`。都须人工确认保存餐食 |
| `feedback` | 当日日期 | 每日反馈；与源指纹比较，不覆盖用户记录 |
| `goals` | `goal_profile:GoalProfile`，目标体重必填 | `goals`、`basis`、`stale`；采用后还要保存资料 |
| `cardio_estimate` | `cardio_input={kind:"cardio",activity,duration_minutes,intensity,description}` | 整段 `effective_met`、总/净消耗、理由、假设；保存训练再校验日期/输入指纹 |
| `weekly_review` | `week_start`；`date` 必须为该周末日 | summary、diet_findings、training_findings、next_week_plan、limitations；只保存报告 |

`goal_profile`、`cardio_input` 和 `week_start` 只能用于对应任务；非餐食不能使用标签模式。周报告需服务端认定周期已结束，七天都有确认餐食和完成状态；同周不并发重算。最新任务失败不删除上一份成功报告。

训练交换在浏览器本地完成：模板 JSON 为 `{format:"fittrack-training",version:1,templates:[...]}`；单模板二维码为 `{format:"fittrack-template",version:1,template:{...}}`，最多 2900 UTF-8 字节。排期 JSON 使用同一 `fittrack-training`/`version:1` 外壳和 `plans:[...]`。CSV 由用户映射日期、训练名、动作、组数、次数、重量和可选时长列；日期与训练名相同的动作行合并为一条待训练排期。导入排期不会自动生成实际训练。

任务状态为 `queued` → `running` → `done` 或 `failed`；重启/恢复后未完成任务转为 `interrupted`，不自动重发。`stale` 是源记录变化标记，不是新的执行状态。凭据快照仅传到工作线程，不写任务请求或结果。

`/api/weekly-review` 重要字段有 `week_start`、`week_end`、`week_number`、`earliest_generation_date`、`today`、`closed`、`completed_days`、`missing_dates`、`can_generate`、`reason`、`available_weeks`、`statistics`、`report`、`active_job`、`latest_job`；`missing_dates` 的各项包含日期和缺失原因，完整返回以 `coaching.weekly_status` 为准。

SSE 先发送 `event: ready`，随后 JSON 通知包含 `type=job/job_deleted/storage` 等相应事件，15 秒心跳。它用于触发刷新；不能把事件流当作可靠完整事务日志。

## 存储管理和运行模式接口

| 接口 | 合约与能力边界 |
|---|---|
| `GET /api/runtime`、`/api/storage` | 当前账号能力和位置/空间/操作；服务器隐藏物理根路径 |
| `POST /api/storage/pick-directory` | 本机目录选择；当前实现仅支持 Windows |
| `POST /api/storage/migrate` | `{path}`；202 存储操作，目标必须是根目录内合法个人子目录 |
| `POST /api/storage/open` | `{path:"workspace"/"backups"}`；管理员另可 root/logs；当前仅 Windows |
| `GET /api/storage/operations/{id}` | 当前账号的存储操作状态 |
| `GET/POST /api/backups` | 列表/创建，创建为 202 异步操作，存放根目录内 |
| `POST /api/backups/restore` | `{backup_id}`；恢复到新工作区再切换 |
| `POST /api/backups/import` | multipart `file`；暂存根目录 `tmp`，202 后验证并归入当前账号 |
| `GET /api/backups/{id}/download` | 仅服务器；本机使用打开备份目录，不自动下载 |
| `POST /api/local/stop`、`/root-migration` | 本机管理员；根迁移输入 `{path}`，等待任务与写入结束 |
| `GET /_local/health`、`POST /_local/stop` | 本机启动器的实例身份及带管理令牌的正常停服；不是公开管理接口 |

服务器模式禁用相应本机操作。当前本机能力返回还没有完整区分 Linux/Windows，不能仅凭 `choose_directory=true` 推导 Linux 支持。`/_local` 管理令牌不进入普通网页接口。

## 持久化与备份版本

- 根标识：`fittrack-root.json`，`format=fittrack-root`、`version=2`、随机根 ID；旧档/未完成迁移标志见 `paths`、`relocation`。
- 控制库：`control/accounts.sqlite3`，保存账号、会话、相对工作区映射、AI 非敏感参数/密文与 metadata。
- 工作区：`workspace.json` 的 `format=fittrack-workspace`/owner，个人 `fittrack.sqlite3` 的 `PRAGMA user_version=1`；不含登录密码与 API 密文。
- 健康 ZIP：新备份为 `manifest.json` 的 `format=fittrack-health`、`version=2`、含 `workout_templates` 的 `tables`，以及 `images/<sha>.<ext>` 原图；仍导入不含模板表的 v1 备份。按白名单验证，重归属当前账号；未完成任务恢复为中断。
- 导入限制：压缩文件 512 MiB、总解压 2 GiB、10002 文件、manifest 32 MiB；拒绝额外路径、重复项、链接、无效归属/关联及图像哈希不符。不是任意目录 ZIP 解压工具。
- 个人迁移用一致性数据库备份，整根迁移停服后复制核验；不能把普通文件复制当作运行中 SQLite 的一致备份。

跨平台修改时，应保持这些合约或设计明确升级路径，并用 [测试矩阵](migration.md) 回归。
