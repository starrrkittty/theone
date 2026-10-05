# APP Coach HTTP v1：首轮对接契约

日期：2026-10-03，2026-10-04 对照克隆的 `AI_trainer` Flutter 源码接入。本文件是 Agent 侧联调契约；实际 APP 接入见 `AI_trainer/docs/AGENT_INTEGRATION.md`。

## 范围与瘦身

Android CameraX/MediaPipe -> 端侧计数与短反馈 -> Flutter 保存原始 SessionResult -> HTTP 请求训练后总结。画像 -> HTTP 计划/饮食 -> Flutter 展示。本轮不要求 APP 上传视频、图片、URDF、逐帧关键点，不接训练中 WebSocket，不让原生模块调用大模型。

首页/记录页还可从原始历史请求本周回顾。它汇总已完成训练日、有效时长与端侧动作次数，Agent 只选择有限的下一步建议，不生成姿势进步结论。

原有 Web 视频研究、A 感知 Agent、URDF 和完整 B 专家接口保留为独立研究路径。新接口不跑这些环节，不启动动作专家评价。APP 缺少质量证据时，服务端不会生成姿势质量或主要错误。这是能力边界，不代表姿态识别精度已解决。

## 地址与开发鉴权

- 合并后的统一后端默认地址为 `http://127.0.0.1:8000/api/app/v1`，交互文档为 `http://127.0.0.1:8000/docs`；端口可由启动命令调整。
- Android 模拟器可用 `adb reverse tcp:8000 tcp:8000`，APP Base URL 使用 `http://127.0.0.1:8000/api/app/v1`。USB 真机也可通过 adb reverse 联调；仅开发构建允许本地明文 HTTP。
- 推荐用 `uvicorn backend/main.py` 对应的 `main:app` 启动统一服务。没有账号、正式身份验证或多设备同步。无开发 token 时，仅允许 loopback 请求；不要直接将整个研究服务公网部署。
- 如设置服务端环境变量 `FITNESS_APP_DEV_TOKEN`，每次请求带 `Authorization: Bearer <开发访问凭据>`。这是受控联调凭据，不是用户鉴权；不能硬编码进发布 APK。开发 token 和模型供应商 API Key 是两种不同凭据。
- 模型密钥只放 `coach/config.json` 或服务端 FITNESS_API_KEY；沿用 MODEL_CONNECTION.md 的 Chat Completions 配置。APP 不接触模型密钥。
- 本轮不提供测试账号，因为没有账户系统。正式发布前需独立的用户鉴权与数据隔离设计。

## 请求画像：必须在 APP 投影

沿用中文枚举，profile 只接受：schema_version=1、goal（建立运动习惯/提升力量/改善体能）、experience（新手/有规律运动）、days_per_week（1-4）、minutes_per_session（10/15/20/30）、has_equipment、diet_preference（无特别偏好/素食/有过敏或特殊限制）。

**不要直接序列化完整 UserProfileSnapshot。has_current_discomfort 不允许上传，提交会返回 422。** APP 仍在本机检查该字段，存在不适时显示本地暂停安排、不给训练启动入口；不得因收到远程建议绕开本地暂停逻辑。本轮不要求团队授权上传健康字段。

SessionResult 中 schema_version=1；status=completed/cancelled/interrupted；finished_at 必须包含时区；duration_seconds 是扣除暂停的端侧记录时长；completed 的 exercises 必须有一个，cancelled/interrupted 可以为空或有一个；如有动作则 exercise_id=squat/push_up、completed_sets=0/1、completed_reps 为非负整数。原生 bridge 的 agent_summary/quality_trend/main_error_code 仍为 null，next_plan_changed=false，source=real。

history 最多最近 30 条原始桥记录，不提交生成的 Agent 总结。history 排除当前 session，session_id 去重。未知字段会被拒绝，避免静默接受不能解释的新质量数据。

## 接口

### GET /capabilities

返回默认动作 squat、桥动作 squat/push_up、max_sets=1、pose_quality_evaluation=false、persistent_plan_updates=false、health_profile_upload=false。用于检查联调版本；不是模型已经配置的证明。

### POST /plan

请求 `{ "profile": <投影画像>, "history": [], "executable_exercises": ["squat"], "local_date": "2026-10-04" }`。`local_date` 是 APP 设备本地日期，YYYY-MM-DD；省略时使用服务端本地日期，跨时区可能误判本周。

成功响应与当前 TrainingPlan 基本同形：plan_id、stage_name、headline、reason、item、source。item 为 null 表示不安排训练；否则为 id、**exercise_id**、title、target_sets=1、target_reps、rest_seconds=45。新手上限 6 次、有规律运动上限 8 次，是保守联调规则，不是科学个体化上限。rest_seconds 不意味着原生执行自动休息。

服务端从最近 30 条原生记录按本地日历日计算本周已完成训练天数。当天已经完成训练，或本周达到 days_per_week 时，返回 item=null 的休息安排、source=template，不调用模型；取消/中断不计入完成天数。其余情况 Agent 只接收精简历史摘要，reason 会展示本周进度，并说明没有动作质量和恢复证据。该规则安排的是本周训练频率，不证明已完成动作的正确性。

plan_id 和 item.id 由服务端生成，属于一次建议的标识，不是已保存计划版本。重复 fetchPlan 可返回不同建议 ID；不要仅凭 ID 变化标记 next_plan_changed=true。

APP 当前缺少 exercise_id：在 TrainingPlanItem 增加该字段并传入 launchArgs；完成之前只请求 squat，适配层可安全固定为 squat。完成俯卧撑入口及运动启动验证后，才在 executable_exercises 中加入 push_up。不从 title 解析动作。服务端会拒绝模型生成不在列表内的项目。

### POST /nutrition

请求 `{ "profile": <投影画像> }`；服务端只将目标和饮食偏好送给饮食 Agent。

通常成功返回 `{ "title": "...", "body": "...", "source": "agent" }`。Agent 只选择一般饮食、训练日进餐或补水关注点，服务端根据普通/素食偏好渲染固定建议，不直接展示模型自由文本。特殊限制未明确时，服务端直接返回 `source=template` 的固定提示，不调用模型或猜测安全食物。APP 应按来源标示它是规则提示。服务端不开热量或治疗处方。

### POST /progress/weekly

请求 `{ "profile": <投影画像>, "history": [<最近最多30条原始SessionResult>], "local_date": "2026-10-04" }`。供首页或记录页显示本周回顾；APP 现有界面尚需新增展示位置。

响应包括 week_start/week_end、completed_training_days、weekly_day_goal、completed_sessions、total_duration_seconds、total_reps、reps_by_exercise、cancelled_sessions、interrupted_sessions、status、summary、next_step、quality_available=false 和 source。相同日期两次完成只算一个训练日，取消/中断不计入训练日、时长或次数。服务端不保存这份回顾，不修改 APP 本地历史。

统计由程序从端侧记录计算，次数未经过人工复核。Agent 只能从保守的下一步建议中选择，且无完成记录和已达目标两种状态有固定匹配规则；模型未配置或不可用时仍返回 `source=template` 的规则回顾。APP 本地完成次数和连续训练天数仍由 APP 自己计算，避免两个统计来源互相覆盖。

### POST /sessions/summary

请求 `{ "installation_id": "<本机随机UUID>", "profile": <投影画像>, "session": <原始SessionResult>, "history": [] }`。

响应包含 session_id、agent_summary、quality_trend=null、main_error_code=null、next_plan_changed=false、updated_plan=null、source=agent，以及 facts 和 limitations。agent_summary 的首段由程序拼接状态、时长、组数和次数；后续由模型选择有限的解释/建议枚举，再由程序渲染，避免自由文本虚构动作质量。facts 明确 quality_available=false，error_evidence_available=false。

将响应作为与原始 SessionResult 分开的总结附加对象保存，以 session_id 关联。不要覆盖原生 source=real/status，也不要把整份响应再次送给严格的 Training Bridge v1 解析器。APP 需要添加保存记录后的单独总结调用；当前仅刷新计划/饮食不会自动触发总结。

本轮 **不会更新或持久化新计划**，所以 next_plan_changed 永远为 false。后续需要保存完整计划版本、基于已知自觉强度/恢复等条件调整，再增加更新能力；不能只输出 changed=true。

### POST /data/delete

请求 `{ "installation_id": "<同一随机UUID>" }`，删除该开发安装的已缓存总结。响应 `{ "deleted": true }`。APP 本地记录需在本机另行删除。

## 幂等与保存

summary 的键为 installation_id + session_id；installation_id 在设备首次安装生成随机 UUID，不用手机号/姓名/账号代替，也不是认证身份。服务端保存哈希后的安装范围、session_id、输入 session 指纹、响应，不保存原始画像/视频/历史。总结本身仍包含训练信息，应在 APP 发起传输前有告知与授权。

成功响应保存于 coach/data/app_results.sqlite3，最多保留 30 天，清理在后续总结请求时发生。相同 session 事实重试返回同一结果，不重复调用模型；仅画像/历史变化不重生成。相同键不同训练事实返回 409。处理中重复请求返回 409 REQUEST_IN_PROGRESS；崩溃遗留处理租约 10 分钟后可重试。模型调用失败不缓存成功结果。

计划/饮食只按次生成，不保存。没有正式云账号、远程数据库、云端质量评价或计划状态。本 SQLite 是本机开发存储，不是移动端发布架构。

## 错误、超时与降级

统一业务错误：`{ "detail": { "code": "MODEL_NOT_CONFIGURED", "message": "模型未配置，请使用 APP 本地模板。", "retryable": false } }`。

| HTTP | code | APP 行为 |
|---|---|---|
| 401 | UNAUTHORIZED | 检查开发访问凭据，不重试 |
| 422 | INVALID_REQUEST | 修正字段/枚举；不重试同一请求 |
| 409 | SESSION_CONFLICT | 排查 session_id 重用；不得生成新 ID 来绕过冲突 |
| 409 | REQUEST_IN_PROGRESS | 延迟后复用原请求 |
| 409 | REQUEST_SUPERSEDED | 结果生成期间被删除或租约替换，先检查本地记录 |
| 503 | MODEL_NOT_CONFIGURED / APP_ACCESS_NOT_CONFIGURED | 本地模板降级，提示配置问题 |
| 503 | STORAGE_UNAVAILABLE | 保留本地原始训练；延迟重试总结 |
| 502 | MODEL_UNAVAILABLE / INVALID_MODEL_OUTPUT | 保留原始记录，暂用本地模板 |

供应商超时配置沿用 coach/config.json（默认单次 90 秒），输出校验最多两次调用。APP 可设置 5 秒连接、30 秒前台等待，超时后展示本地模板并允许稍后重试总结；服务端可能仍在生成，总结用同一幂等键收取。不要快速重复调用计划/饮食。

建议最多两次客户端延迟重试（例如 2/5 秒并加抖动），只重试 retryable=true 或网络失败。共享模型最多两路并发，繁忙返回 MODEL_UNAVAILABLE；没有正式每用户限流或 Retry-After 保证。模型失败时服务不会返回 source=agent 的假成功。

## APP 接入状态

以下项目已在同工作区 `AI_trainer` 落地源码，仍需 Flutter 编译和真机联调确认：

1. 实现网络 CoachRepository，将画像投影后请求 /plan 和 /nutrition。兼容 item=null；按 source 区分真实 Agent 与本地 template。
2. 计划/饮食分别降级，避免饮食失败把成功的 Agent 计划一起丢弃。用户修改画像后以请求版本号抑制过期响应。
3. TrainingPlanItem 增加 exercise_id，当前固定 squat；接通 push_up 后才扩大请求能力。
4. 保存原始 session 后异步请求 /sessions/summary；失败不能阻止历史保存，迟到结果不能覆盖另一 session 页面。
5. 单独存储总结附加对象与安装 UUID，支持重试/清除。取消与中断仍不计完成天数。
6. 保持本机不适检查、模板降级、原生冻结协议。不要暴露完整研究接口或模型 Key 给 APP。
7. 如在首页/记录页展示本周回顾，使用 /progress/weekly；保留 APP 原有本地统计，不把次数趋势写成姿势质量趋势。

## 固定样例与验证边界

docs/contracts/app_coach_v1_examples.json 提供固定请求/成功响应/无项目/普通与特殊饮食/错误/本周回顾样例，可供 APP 写映射测试；这是人工编写的契约夹具，不是真实 Agent 运行结果。APP 仓库 `AI_trainer` 已有网络适配源码，尚未完成 Flutter 编译或真机联调；未配置 API 时真实生成接口返回 503，特殊饮食限制和周回顾降级返回标明 template 来源的固定提示。
