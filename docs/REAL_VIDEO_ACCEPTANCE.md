# Agent A 真实视频通话验收协议

公开数据集用于预训练、跨域测试和补充负样本；是否适合比赛现场，最终由本协议下的真实视频通话回放集决定。训练集分数、单人演示成功和网页上偶然识别正确都不能代替验收。

## 1. 最小验收集

首轮门禁至少包含 5 名参与者、30 段相互独立的片段。每名参与者至少录制：

- 深蹲、俯卧撑、前臂平板支撑、双臂弯举、交替弯举各 1 段；
- `unknown` 至少 1 段，内容从挥手、喝水、走动、整理头发、坐下休息、拿手机中选择；
- 每段 8–15 秒，动作类至少覆盖 3 个完整重复或稳定保持 8 秒；
- 同一参与者的全部片段始终属于同一数据划分，严禁把同一个人的裁剪片段分别放入训练集和测试集。

首轮通过后再扩展到每类至少 15 段，并加入以下压力场景：

- 正面、侧面和斜侧机位；
- 正常光、昏暗、逆光；
- 手腕、脚踝或躯干部分出画；
- 第二个人路过、两人交叉、主体离开后重新进入；
- 动作切换、组间休息、错误动作和半程动作；
- 不同手机、笔记本摄像头、网络卡顿和不同房间背景。

### v9 扩类候选门禁

上面的 30 段是五类核心专项能力的 `core-v1` 门禁，不能证明 v9 新增语义类别已经可用。候选模型升为默认前，还必须运行 `semantic-v9` 门禁：

- 覆盖五类核心动作、13 类长尾语义动作和 `unknown`，共 19 类；
- 每类至少 5 段，因此最低为 95 段；
- 每名参与者都应覆盖多个类别，且同一个人的全部片段不能跨训练与验收；
- `jump_rope`、`running_in_place`、`lateral_raise` 和不同弓步形式应优先增加侧面/斜侧机位；
- 器械依赖的战绳不属于 v9 姿态模型门禁，等 Video LLM 链路接通后单独验收。

这两个门禁不能混为一个报告：`core-v1` 保护已验证的专项能力，`semantic-v9` 决定扩类模型是否有资格成为默认模型。

## 2. 录制和目录约定

原始视频及导出的 JSON 不进 Git。建议保存在：

```text
D:\datasets\agent-a-runtime-eval\
  raw\p01\
  raw\p02\
  exports\
  reports\
```

片段命名使用匿名参与者 ID：

```text
p01-squat-front-normal-01.mp4
p01-unknown-wave-front-normal-01.mp4
```

不要在文件名、备注或导出 JSON 中填写真实姓名。参赛者应明确知道视频用于项目测试；没有授权的视频不能拿来训练或公开展示。

先生成逐人逐动作的拍摄清单，避免漏类、重名或重复计数：

```powershell
.\.training-venv\Scripts\python.exe training\create_runtime_evaluation_plan.py `
  --profile core-v1 `
  --output D:\datasets\agent-a-runtime-eval\plans\core-v1.csv

.\.training-venv\Scripts\python.exe training\create_runtime_evaluation_plan.py `
  --profile semantic-v9 `
  --output D:\datasets\agent-a-runtime-eval\plans\semantic-v9.csv
```

生成器默认使用匿名 ID `p01`–`p05`，核心计划得到 30 行，v9 计划得到 95 行。CSV 同时记录推荐机位、目标模型 ID、建议视频路径、导出路径和 `todo` 状态；完成一段后把状态改为 `done`。脚本拒绝真实姓名式的非 ASCII ID、重复 ID 和少于 5 人的计划。

## 3. 单段采集步骤

1. 打开 `http://127.0.0.1:3000/`，上传片段或进入实时视频通话模式。
2. 在“开发者评测模式”选择真实动作。非支持动作、休息和日常行为统一选择 `unknown`。
3. 填写匿名参与者 ID、唯一片段 ID、来源、机位、光照、遮挡和多人信息。
4. 切换片段前点击“重置”。当前版本会同时清空前端指标和后端 HMM、状态机、计数器。
5. 从头播放完整片段，结束后导出 `agent-a-evaluation-*.json`。
6. 不要删掉失败片段；失败样本正是下一轮阈值调整、hard-negative 扩充或专项模块修复的依据。

导出文件包含版本号、模型 ID、场景元数据、逐响应轨迹、拒识原因、确认事件、首次确认延迟和最终动作报告。逐响应轨迹最多保留 5000 条，足够覆盖普通验收片段。

## 4. 批量汇总与硬门禁

```powershell
Set-Location D:\OneDrive\文档\ChatGPT\小有可为\ai-fitness-agent-a
.\.training-venv\Scripts\python.exe training\aggregate_runtime_evaluations.py `
  --input D:\datasets\agent-a-runtime-eval\exports `
  --output-dir D:\datasets\agent-a-runtime-eval\reports\core-v1 `
  --profile core-v1
```

v9 扩类候选使用独立导出目录和报告目录，避免稳定模型与候选模型混入同一报告：

```powershell
.\.training-venv\Scripts\python.exe training\aggregate_runtime_evaluations.py `
  --input D:\datasets\agent-a-runtime-eval\exports-v9 `
  --output-dir D:\datasets\agent-a-runtime-eval\reports\semantic-v9 `
  --profile semantic-v9
```

命名 profile 会同时锁定要求标签和模型 ID；如果导出文件混入稳定模型或缺少模型 ID，脚本会 fail closed。`core-v1` 自动要求至少 30 段，`semantic-v9` 自动要求至少 95 段。

默认门禁：

- 至少 5 名参与者、30 段视频；
- 六个真值类别各至少 5 段；
- 总片段准确率不低于 80%；
- 每个已支持动作的召回率不低于 70%；
- `unknown` 片段误接收率不高于 10%；
- 首次确认延迟中位数不超过 4 秒，P90 不超过 6 秒；
- 出现错误动作切换的片段比例不高于 10%；
- 不可靠关键点帧率不高于 30%。

输出包括：

- `runtime-evaluation-summary.json`：机器可读总报告和每段判定；
- `runtime-evaluation-clips.csv`：便于在表格中筛选失败场景；
- `runtime-evaluation-summary.md`：答辩和团队同步用摘要。

脚本默认 fail closed，任一覆盖量或质量门槛不满足即返回非零退出码。探索阶段如只想看报告可加 `--no-fail`，但该参数不能用于批准部署。

## 5. 训练和部署决策

失败后先按类型处理：

- 关键点不可靠：补机位指引、主体跟踪或 MediaPipe 前处理，不先训练分类器；
- 支持动作之间混淆：补该动作真实视频并按人划分，微调时保持固定测试人员；
- 日常行为被误认成健身：把对应行为加入 hard negatives，重新校准逐类阈值；
- 关节角或次数错误：修专项几何、状态机和 URDF 约束，不交给 LLM；
- 开放词汇或复杂语境不足：由 Video LLM/Agent 作为补充解释，不能覆盖确定性安全门禁。

候选模型必须同时通过公开数据固定测试集和本协议的真实视频门禁，才能替换前端权重。任何只改善一个域、却显著恶化另一个域的候选都保留为实验，不部署。
