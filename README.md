# AI 智能健身私教：Agent A 运动感知服务

这是团队 **Agent A（运动感知与数据底座）** 的第一版可运行实现。它从 App 视频通话画面中取得的 33 点 MediaPipe Pose 骨架出发，完成动作候选识别、时间稳定确认、动作阶段/次数/姿态问题分析，并输出一个稳定、紧凑的 `ActionReport v2` 给 Agent B。

> 这里的前端只是开发与联调控制台。最终产品由 App 端建立用户与 AI 私教的视频通话，再把通话画面中的骨架帧发送给本服务；用户不需要先选择运动类型。

## 第一版已经具备什么

- 用户无须选类型：对深蹲、俯卧撑、前臂平板支撑、普通/交替哑铃弯举进行自动候选识别与多帧确认。
- 识别确认只触发一次 `recognition_event`，可直接播报：
  “小主，识别到您正在做深蹲，我这就去找深蹲专家带您锻炼哦。”
- 输出动作阶段、次数或静态保持时长、关节角度、置信度、画面质量、错误和纠正建议。
- 用 Kalman、HMM、规则门控和滞回机制降低单帧抖动与误切换。
- 浏览器内置在 MM-Fit 官方 RGB 视频上微调的轻量 ST-GCN，为 7 个长尾动作提供经过逐类阈值校准的第二路语义证据。
- 40+ 动作目录统一中英文别名和路由；无专项验证的动作只进入通用指导，不伪造精确计数或纠错能力。
- 读取标准 URDF 的关节树、轴、原点和上下限，并校验 MediaPipe 到 URDF 的映射。
- 将连续错误、疲劳迹象和指导优先级压缩为 `agent_context`，供 Agent B 决定何时说话、说什么。
- 保留既有瑜伽姿势、视频上传和开发前端能力，方便扩展及回放测试。

第一版不声称解决稳定多人跟踪、医学诊断或任意运动的精确识别。平板支撑目前是前臂平板支撑 beta；证据不足的输入应保持 `unknown`，而不是强行猜测。

## 架构边界

```text
App 视频通话
  -> 端侧 MediaPipe（只提取 33 点骨架，不上传原始视频）
  -> 本地 ST-GCN 长尾语义候选 / 后续 Video LLM 开放词汇补充
  -> Agent A：校验、平滑、识别、阶段、计数、纠错
  -> ActionReport v2 + recognition_event
  -> Agent B：专项教练、主动话术、阶段计划、训练总结、饮食建议
```

数值计算和实时判断由确定性算法完成。LLM 不直接读取长 URDF、不逐帧计算关节角，也不负责简单阈值判断；它消费 Agent A 的结构化报告，用于复杂语境理解、主动关怀和个性化规划。详见 [架构与技术边界](docs/ARCHITECTURE.md) 和 [团队分工](docs/TEAM_SCOPE.md)。

## 开源模型与 API 的分界

| 能力 | 第一版实现 | 是否需要云端 API Key |
| --- | --- | --- |
| 人体关键点 | 浏览器 MediaPipe Tasks Vision | 否 |
| 核心动作识别 | HMM + 姿态规则 + 专项模块 | 否 |
| 长尾动作识别 | MM-Fit RGB 同域微调的浏览器 ST-GCN + 逐类阈值 + 连续确认 | 否 |
| Video LLM/开放词汇补充 | 预留结构化 `semantic_result` 入口，尚未配置供应商 API | 是；密钥必须由服务端保管 |
| URDF 读取 | Python XML 确定性解析器 | 否 |
| 动作计数与纠错 | 几何特征、状态机和专项模块 | 否 |
| 对话、计划、饮食建议 | 由 Agent B 调用 LLM | 是；密钥必须由服务端保管 |

本项目不从零训练大模型，也不训练人体关键点模型；MediaPipe 使用公开预训练模型。项目已经在 MM-Fit 公开数据上完成轻量 ST-GCN 预训练、RGB→MediaPipe 同域微调和按人员独立测试，用于长尾动作语义候选。完整数据、指标、阈值和限制见 [训练状态](docs/TRAINING_STATUS.md)，GitHub 仓库采用决策见 [公开数据与开源仓库](docs/OPEN_SOURCE_BASELINE.md)。

## 快速启动

需要 Python 3.11+、Node.js 20+。

### 后端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`

### 开发前端

```powershell
cd frontend
npm install
npm run dev
```

前端用于本地摄像头/视频回放和 A 端能力观察，不等同于最终 App 的视频通话界面。

## 核心接口

### 输入

```text
WS /api/ws/pose/{client_id}
```

```json
{
  "landmarks": [{"x": 0.5, "y": 0.3, "z": -0.1, "visibility": 0.99}],
  "timestamp": 1778390000000,
  "camera_view": "auto",
  "client_probs": {
    "squat": 0.91,
    "pushup": 0.04,
    "plank": 0.03,
    "unknown": 0.02
  },
  "client_model_id": "mmfit-mediapipe-semantic-v1"
}
```

`landmarks` 应包含 33 个 MediaPipe Pose 点。`client_probs` 可选，用来接入浏览器 ST-GCN；`client_model_id` 必须与后端已校准阈值对应，否则这些概率不能触发长尾语义路由。服务端同时过滤未知标签、非法分数和低于逐类阈值的结果。

### 给 Agent B 的关键输出

```json
{
  "recognition_event": {
    "event": "exercise_confirmed",
    "exercise": "squat",
    "confidence": 0.91,
    "specialist": "squat_specialist",
    "message": "小主，识别到您正在做深蹲，我这就去找深蹲专家带您锻炼哦。"
  },
  "action_report": {
    "schema_version": "v2",
    "session_id": "demo-user",
    "report_id": "demo-user:1:42",
    "session_generation": 1,
    "sequence": 42,
    "recognition_status": "confirmed",
    "recognized_exercise": "squat",
    "recognition_confidence": 0.91,
    "specialist": "squat_specialist",
    "phase": "eccentric",
    "repetition": 3,
    "pose_quality": "good",
    "camera_view": "side",
    "metrics": {
      "joint_angles": {"left_knee": 96.4},
      "joint_confidences": {"left_knee": 0.91},
      "confidence_method": "landmark_visibility_min",
      "hold_seconds": 0.0,
      "rep_quality": 0.86,
      "partial_reps": 0
    },
    "violations": [],
    "agent_context": {
      "should_coach_now": false,
      "priority": "encouragement",
      "recommended_intent": "reinforce_good_form",
      "repeated_error_count": 0,
      "possible_fatigue": false
    },
    "coach_trigger": {
      "triggered": false,
      "reason": "none",
      "priority": "none",
      "recommended_intent": "observe",
      "report_id": "demo-user:1:42",
      "cooldown_ms": 8000
    }
  }
}
```

`recognition_event` 只在首次确认或运动切换时出现，避免每帧重复播报。`coach_trigger` 只在动作确认/切换、持续错误、疲劳趋势或安全事件达到门槛时触发，B 不应逐帧调用大模型。`joint_angles` 只包含本帧实际测得且关键点可见度达标的角度；缺失角度不会用 0 填充。完整响应还保留旧版字段，方便现有前端兼容。

### A 与 B 的合并联调

B 的教练 Agent 已放在 `coach/`，统一后端启动后可直接使用：

- `POST /api/agent-a/normalize`：把 A 的 `ActionReport v1/v2` 映射为 B 的动作观测并检查证据，不调用模型。
- `POST /api/agent-a/coach`：只在动作已确认、`coach_trigger.triggered=true` 且 B 有对应专家时调用动作 Agent；用户主动提问可在请求顶层设置 `user_initiated=true`，不受主动播报冷却限制。
- `POST /api/plans/phase`、`POST /api/workouts/summary`、`POST /api/nutrition/advice`：阶段计划、训练总结和饮食建议。
- `GET /api/app/v1/capabilities`：最终 App 的精简接口能力声明；完整契约见 `docs/contracts/app_coach_v1.md`。
- `/coach`：B 的本地联调控制台。

模型 Key 只配置在服务端 `coach/config.json` 或环境变量 `FITNESS_API_KEY`，不得放到前端或 App。没有 Key 时，确定性映射接口仍可验证；真正的生成接口会明确返回 503。

其他接口：

- `GET /api/health`：运行状态与支持的运动。
- `GET /api/exercises`：运动标签契约。
- `POST /api/reset/{client_id}`：重置会话。
- `WS /api/ws/yoga/{client_id}`：既有瑜伽保持模式。

## URDF 怎么用

- 示例骨架：[assets/human_minimal.urdf](assets/human_minimal.urdf)
- MediaPipe 映射：[assets/mediapipe_to_urdf.json](assets/mediapipe_to_urdf.json)
- 解析器：[backend/kinematics/urdf_loader.py](backend/kinematics/urdf_loader.py)

URDF 在这里是人体运动学约束和统一命名的依据，不是让 LLM 直接阅读的提示词。解析器先将 XML 转成紧凑关节表，A 端再把真正有用的角度与问题写入 `ActionReport`。这比把整份 URDF 塞给 LLM 更可靠、更省 token。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm test
npm run build
```

当前验证基线：后端 114 项、前端 13 项测试通过，前端生产构建通过。`npm audit` 仍报告上游依赖链中的安全告警，升级前需要单独做兼容性验证，不应在竞赛主线中直接执行破坏性强制升级。

### 开发者评测模式

开发控制台提供独立于正式产品流程的 Ground Truth 选择器。测试人员可在播放已知动作的视频前填写真实类别，页面将实时统计：

- 从第一帧到首次稳定确认的延迟。
- 已确认帧准确率、未知帧率和不可靠画面率。
- 平均识别/动作置信度、识别事件数和运动切换数。
- 最近的专项 Agent 路由事件。

这些指标可以导出为 JSON。正式用户仍然不需要选择运动；Ground Truth 只用于研发评测。单段视频的在线统计不代表泛化能力，正式比较必须使用多人、多光照、多机位的标注回放集。

## 目录

```text
assets/                     最小人体 URDF 与 MediaPipe 映射
backend/api/                WebSocket / REST 接口
backend/exercises/          各运动专项分析模块
backend/kinematics/         URDF 读取与校验
backend/recognition/        外部分类证据适配
backend/reporting/          ActionReport 构建与时序上下文
backend/schemas/            A -> B 版本化数据契约
backend/state_machine/      自动识别、切换、计数编排
backend/tests/              后端测试
frontend/                   本地联调与能力观察界面
docs/                       架构、分工与原有接口说明
```

## 来源与许可

本实现基于 MIT 许可的 [shahmir2004/exercise-form-correction](https://github.com/shahmir2004/exercise-form-correction) 改造。上游版权和许可文本保留在 [LICENSE](LICENSE)，改造说明见 [NOTICE.md](NOTICE.md)。
