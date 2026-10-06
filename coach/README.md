# B 组 AI 健身私教

本目录是交付版本。网页、HTTP 服务和命令行入口均使用真实模型调用。API 未配置时返回明确错误，不回退到旧规则或静态建议。

## 启动

合并到 Agent A 仓库后，推荐从仓库根目录启动统一后端：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

然后访问 `http://127.0.0.1:8000/coach`。A→B 映射接口、B 任务接口和 `/api/app/v1` 会由同一服务提供。

也可以仅启动 B 的独立联调服务：

1. 打开 `config.json`，填入 `api_key`。默认地址为 OpenAI、模型为 `gpt-4.1-mini`。账号须具备对应模型权限和可用余额。
2. 双击 `start.cmd`，或在本目录执行 `python serve_demo.py`。
3. 浏览器打开 http://127.0.0.1:8765/ 。

JSON 样例测试台位于 `http://127.0.0.1:8765/testbench`。它提供 6 个动作证据用例，以及训练计划、训练汇报和饮食建议样例；动作可先运行不调用模型的确定性检查，再调用真实 B Agent。也可载入本地 JSON 后编辑提交。API 未配置时，规则检查仍可用，模型请求会返回未配置提示。

个人记忆与聊天页位于 `http://127.0.0.1:8765/chat`。记忆按页面中的本地用户 ID 隔离，保存到 `data/history.sqlite3`。档案需显式点击保存；训练汇报、成功生成的计划/饮食摘要和聊天往来会自动保留有限记录。计划与营养 Agent 可读取该 ID 的档案和近期记录，聊天会携带有限的近期对话与记录请求已配置的模型。发送聊天或 Agent 请求时，相关上下文会发给模型服务。独立联调服务绑定 `127.0.0.1`，无账号认证，不应直接暴露到局域网或公网；删除按钮会清除该 ID 的全部记忆。

Python 3.10 或以上即可，网页服务器和 Agent 核心只使用标准库，无须安装第三方依赖。配置每次请求重新读取，填写后不需要重启。

如果使用其他 OpenAI 兼容服务，同时填写 `base_url`（例如服务的 `/v1` 地址）和 `model`。服务须支持 `/chat/completions` 与文本 JSON 返回。若不支持 `response_format`，将 `json_mode` 设为 false。也可用 `FITNESS_API_KEY`、`FITNESS_BASE_URL`、`FITNESS_MODEL` 环境变量覆盖文件配置。Key 不发送到网页，不写入日志和训练历史。

本机已可用的替代启动命令：`C:\Python314\python.exe serve_demo.py`。如默认 Python 的 HTTPS 访问有证书问题，请使用系统证书配置正确的 Python；不要关闭 TLS 校验。

## 网页功能

- 动作评价：表单或导入 A 组 JSON，自动路由到对应动作专家。
- 阶段规划：目标、经验、时间、器材、限制和历史决定阶段及周安排。
- 训练汇报：程序计算事实，模型生成总结和下次建议。
- 饮食规划：偏好、过敏、背景及训练情况生成餐食示例、替换和训练日建议。
- 专家目录：8 个动作专家、33 个动作 ID；另有规划、汇报、营养 Agent。整合版增加双臂与交替弯举。
- 动作表单支持逐关节指定角度定义；“检查测量条件”不调用模型，可先查看视角、阶段、测量定义和置信度限制。
- 各模块的 JSON 输入支持用户画像和自定义上下文；结果可下载 JSON。
- 提供用户编号后，汇报保存在本地 SQLite，同一用户同一 session_id 更新一条记录；后续任务自动读取近期汇报。个人档案、训练、计划、饮食摘要和聊天记录可在聊天页查看与按 ID 删除。
- 总览提供串联流程 JSON 入口，将动作、汇报、画像、营养交给对应 Agent，并输出 C/D 组接口数据。

串联样例在 `examples/workflow_input.json`，可贴入总览的串联入口。它会调用四次模型，方便检查完整流程。

网页顶部可填写共享用户编号及背景 JSON，例如 `{"previous_plan": {...}, "budget": "食堂日常预算", "cooking_conditions": "不能做饭"}`。背景仅在提交时发送给模型。没有用户编号时不保存结果。此服务绑定 localhost，是本地联调工具，不含账号认证和多人部署权限管理。

## Agent 流程

`JSON → 输入校验 → 安全检查 → 专家路由 → 加载 Skill → 检索知识/读取历史/计算报告事实 → 模型生成 → JSON 与事实校验 → 必要时修复一次 → 网页及其他组`

这是固定工具步骤的 Agent 工作流。模型负责评价与规划，程序负责路由、检索、事实和校验；不依赖模型自由决定工具调用。所有角色共用一个配置的模型，通过不同角色指令、知识及 Skill 区分。

四个运行时 Skills 位于 `skills/`：`movement-report`、`training-plan`、`training-report`、`nutrition-advice`。实际调用会读取 SKILL.md 和 references 内容，并随角色指令与输出契约发送给模型。阶段参考包括适应、基础、专项、巩固四类，不强制按固定周数进阶。

`app/output_contracts.py` 定义模型输出结构；`app/agents.py` 校验身份、数值、置信度、引用、汇报事实及计划天数。观测不生成无依据的动作总分。两次输出都不合格返回 502，页面展示错误。

## 知识库

`knowledge/entries.json` 是运行时检索的简短中文条目，`sources.json` 保存出处和审核状态。已读取 ACE 的自重深蹲、前臂平板、跪姿俯卧撑、杠铃划船、抗旋转后弓步页面，Fry 2003 膝前移研究摘要（经 Europe PMC），WHO 健康饮食页面和 WHO 2020 活动指南索引；获取时间、内容哈希与失败记录在 `fetch_manifest.json`。知识按动作变式筛选，不把一种变式的口令外推到所有运动。

执行 `python knowledge/refresh.py` 可获取公开页面文本快照。抓取不等于科学审查，也不会自动把网页全部加入提示。其他动作当前采用明确标记的项目专家检查表。ACSM 文献仅为出处线索，未声称已阅读全文。生产级动作标准仍需教练审核及带标注数据评估。

`app/movement_evidence.py` 给模型提供程序计算的测量审核和专项姿势检查表。只有关节定义、置信度、阶段、视角/标定满足条件，才允许确定性 caution 反馈；没有专项可解释观测时必须 limited。0.55 是项目数据质量门槛，不是科学动作标准。角度零点、相机平面和动作阶段要由 A 组明确提供。输入示例见 `examples/movement_measurements.json`，职责检查和后续优先级见 `B_GROUP_AUDIT.md`。

## 联调与检查

`python run_demo.py all` 调用真实模型运行示例，需要配置 API，会产生模型费用；也可选择 movement、report、plan、nutrition、experts。

`python verify_integration.py` 使用本地模拟 Chat Completions 服务，不联网、不花费模型额度、不改变 config.json，检查全部任务、所有动作路由、Skill/知识注入、鉴权请求、一次修复、事实/引用保护、安全门、历史和组间串联。模拟结果仅用于接口检查。

没有提供真实 API Key，因此当前验证不证明真实模型的回答质量或端到端联网成功。接入后应先用 examples 的少量样例查看输出和成本。

可选 FastAPI 服务需要安装 requirements.txt，再启动 `uvicorn app.main:app --reload`，路由前缀 `/api/v1`，主要用于其他组集成；网页入口使用标准库服务。

## 文件与限制

`EXPERTS.md` 解释专家结构；`INTEGRATION.md` 列出组间接口。旧 `engine.analyze_movement`、`coaching.phase_plan/nutrition_advice` 保留为早期参考，不是任何当前网页/CLI/HTTP 入口的生成路径。`examples/squat_output.json` 为旧输出结构样例，不是当前模型的实测结果。

实时指导以 A 组动作事件为输入，输出给 C 组展示/播报；没有实现视频识别、视频通话或逐帧模型推理。基础记录校验与重复会话去重不能证明视频真实性，全面反作弊需要 A/C 的可信采集。系统不诊断伤病，不提供医疗营养治疗，模型建议还需人工评估。
