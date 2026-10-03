# 专家 Agent

实际执行入口为 `app/agents.py:AgentService.run`。每个角色有不同指令、任务 Skill 和检索条目，共用 `app/model_client.py` 的一个模型服务。

| 专家 | 任务重点 | Skill |
| --- | --- | --- |
| squat_form | 深蹲变式、阶段、髋膝与躯干观测 | movement-report |
| hinge_form | 髋铰链、硬拉和摆动变式；不从倾角判断脊柱负荷 | movement-report |
| push_form | 水平/垂直推、肘肩与躯干 | movement-report |
| pull_form | 划船变式及肩肘观测 | movement-report |
| lunge_form | 单腿动作、左右观测及视角限制 | movement-report |
| plank_form | 静态支撑与动态躯干动作的区别 | movement-report |
| balance_form | 稳定支撑、环境与时间序列限制 | movement-report |
| curl_form | 同时/交替弯举、肘角定义及躯干时间序列限制 | movement-report |
| planning_agent | 四类阶段、周安排、恢复、历史调整 | training-plan |
| report_agent | 真实记录的汇总、反馈与下次建议 | training-report |
| nutrition_agent | 一般饮食、餐食替换、训练日前后建议 | nutrition-advice |

注册目录 `app/experts/movement.py:BY_EXERCISE` 列出 33 个可路由动作，`GET /api/experts` 可查询。整合版新增双臂与交替弯举，其检查表标为工程规则，尚需已核验的专项科学来源。旧数值触发规则不参与当前 Agent 生成。不要在没有科学或测量依据时自行增加通用纠错阈值。

`app/movement_evidence.py` 为每个专家提供细化姿势检查表，以及每个观测的解释条件。姿势条件包括：深蹲脚跟/髋膝协调；推类的肘屈曲与上臂外展区别；平板的肩肘位置/躯干形状；单腿动作的同阶段左右比较。缺失条件必须说明；不能把这些检查表当成程序已经从视频识别出的结果。

## 增加专家

1. 注册规范动作 ID 和 specialist_id，并明确观测字段。
2. 在 SPECIALIST_INSTRUCTIONS 增加角色任务边界。
3. 在 entries.json 增加按 specialist_id 标记的知识及真实出处；项目策略必须标明其性质。
4. 必要时扩展输出契约和事实校验，再从 HTTP 或网页提交同一 JSON。

专家输出 findings 只引用已提供关节；角度/置信度必须一致；引文须来自本次检索。低置信度不能产生确定性纠错。总分始终为空，安全门的停止响应不调用模型。
