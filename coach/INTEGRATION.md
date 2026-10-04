# 组间接口

独立启动 B 控制台时使用 `http://127.0.0.1:8765`；从本仓库统一后端启动时使用后端端口（默认 `http://127.0.0.1:8000`）。Content-Type 使用 application/json，响应均为 JSON。模型生成通常需要数秒至数十秒；不要逐帧调用。无模型配置 503，模型连接/生成失败 502，输入无效 400/422。

| 方法与路径 | 输入/输出 |
| --- | --- |
| GET /api/status | 配置状态和模型名，无密钥 |
| GET /api/experts | 动作专家、支持动作和任务 Agent |
| GET /api/integration/contract | A/B 基础契约 |
| POST /api/movement/analyze | examples/squat_input.json → 动作报告 |
| POST /api/movement/evidence | 动作 JSON → 程序测量审核，不调用模型 |
| POST /api/plans/phase | examples/user_profile.json → 阶段及周计划 |
| POST /api/workouts/summary | examples/workout_session.json → 训练汇报 |
| POST /api/nutrition/advice | examples/nutrition_request.json → 饮食建议及餐食替换 |
| POST /api/workflow | movement/report/profile/nutrition 的组合 → 生成结果和 C/D 事件 |
| GET /api/history?user_id=user-001 | 此用户最近 20 份汇报 |
| POST /api/history/delete | {"user_id":"user-001"} → 删除此用户记录 |
| POST /api/agent-a/normalize | ActionReport v1/v2 → 确定性字段映射与测量条件检查，不调用模型 |
| POST /api/agent-a/coach | ActionReport v1/v2 → B 动作专家；未确认或无专家时不调用模型 |
| GET /api/app/v1/capabilities | 最终 App 的瘦接口能力声明 |

## A → B

推荐直接传 A 的 `ActionReport v2` 或包含 `action_report` 的完整 WebSocket 响应；适配器同时保留 v1 兼容。也可直接提供 B 的 schema_version、session_id、ISO-8601 timestamp（含时区）、exercise_id、rep_index、phase、joints。joints 每个条目包含 angle_deg 和可选 confidence；仅接受角度观测，保持时长等放入 metadata，不要把秒数伪装成角度。

适配器识别 squat→bodyweight_squat、lunge→forward_lunge、pushup→push_up、plank→forearm_plank 等别名，并将 eccentric/concentric 转换为 descent/ascent。A 组必须给出关节和时间等必要字段；纯分类标签只能得到受限反馈。A 已识别但 B 尚无专家的动作返回 `expert_unavailable`，不能假装已完成专项指导。

metadata 应包含 camera_view、angle_convention；缺失时模型须说明限制。reported_symptoms 的停止信号为 sharp_pain、chest_pain、dizziness、breathing_difficulty、faintness。没有动作识别置信度时，B 不知道分类是否可靠；A 应在 context/metadata 提供识别依据。

每个 joints 条目可提供 definition：flexion_from_extension（伸直为零点屈曲角）、included_segment_angle（两骨段夹角）、inclination_from_vertical、inclination_from_horizontal、projected_deviation。后者仍须由 A 定义基准和算法，B 不把它直接解释为三维解剖结论。全局 internal_flexion_degrees/anatomical_flexion_degrees 只映射屈曲字段，不用于解释躯干倾角。

metadata.measurement_space 默认 2d；声明 3d 时需 calibrated=true。camera_view 支持 front、rear、side、oblique、unknown；侧面适于矢状面角度，正面/背面适于正面代理指标。提供 classification_confidence 时低置信度阻止确定性纠错；A 顶层 confidence 会适配到此字段。左右膝比较还需 sides_same_phase=true 及相同角度定义。支撑时间放 metadata.hold_duration_seconds；支撑环境放 metadata.support_used，不放角度字段。

返回的 measurement_review 是后端计算的数据条件检查，并非模型自评。它包括专项检查表、可解释角度、限制及可比较的左右差值。它不提供通用正确姿势阈值。

## E / D → B

规划使用 goal、experience、days_per_week、minutes_per_session、equipment、limitations。串联 profile 也接受文档里的 available_days、session_duration、injury_notes，并映射到同一字段。康复目标不作为自动医疗处方。

可选 user_id 启用本地汇报历史；context 可提供上次计划、恢复、预算、烹饪条件、最新动作及训练历史。真实已记录汇报由后端读取并单独注入，模型不能修改保存的数据。持久化只保存成功生成的汇报。

report.sets 每项代表一份组次记录，reps 是该记录的实际次数；汇报次数为相加结果。可选 sets_completed 是上游提供的总组数，不会拿它乘以 reps 再猜测次数。建议 A 逐组提供记录以获得准确统计。

## B → C / D

app/group_adapters.py 的 to_group_c_live_event 提供 event/session/rep/exercise/status/cues/safety_messages；C 可展示或播报。to_group_d_view 提供汇报展示字段。所有生成结果的 agent 元数据标明真实调用、模型、Skill、知识条目及尝试次数；安全门标明 model_called=false。

串联入口按 movement→report→plan→nutrition 顺序执行，前一步结果加入后一步上下文。若中途模型失败，返回错误；不是数据库全有或全无事务，已成功保存的汇报仍保留。

## 部署边界

此服务仅监听本机，不含认证、公共排行榜、防视频伪造或分布式队列。重复 session_id 更新一条记录，基础输入校验拒绝负数和不合法数据。记录可靠性取决于 A 的采集。其他组若部署到网络，须由 C/E 接入身份、权限、事件节流及错误重试管理。
