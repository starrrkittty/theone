# AI 智能健身私教：Agent A 运动感知服务

这是团队 **Agent A（运动感知与数据底座）** 的第一版可运行实现。它从 App 视频通话画面中取得的 33 点 MediaPipe Pose 骨架出发，完成动作候选识别、时间稳定确认、动作阶段/次数/姿态问题分析，并输出一个稳定、紧凑的 `ActionReport v1` 给 Agent B。

> 这里的前端只是开发与联调控制台。最终产品由 App 端建立用户与 AI 私教的视频通话，再把通话画面中的骨架帧发送给本服务；用户不需要先选择运动类型。

## 第一版已经具备什么

- 用户无须选类型：对深蹲、俯卧撑、前臂平板支撑、普通/交替哑铃弯举进行自动候选识别与多帧确认。
- 识别确认只触发一次 `recognition_event`，可直接播报：
  “小主，识别到您正在做深蹲，我这就去找深蹲专家带您锻炼哦。”
- 输出动作阶段、次数或静态保持时长、关节角度、置信度、画面质量、错误和纠正建议。
- 用 Kalman、HMM、规则门控和滞回机制降低单帧抖动与误切换。
- 支持浏览器 ST-GCN 或后续 ActionCLIP 服务通过 `client_probs` 提供第二路动作分类证据。
- 读取标准 URDF 的关节树、轴、原点和上下限，并校验 MediaPipe 到 URDF 的映射。
- 将连续错误、疲劳迹象和指导优先级压缩为 `agent_context`，供 Agent B 决定何时说话、说什么。
- 保留既有瑜伽姿势、视频上传和开发前端能力，方便扩展及回放测试。

第一版不声称解决多人跟踪、医学诊断或任意运动识别。平板支撑目前是前臂平板支撑 beta；动作集合之外的输入应保持 `unknown`，而不是强行猜测。

## 架构边界

```text
App 视频通话
  -> 端侧 MediaPipe（只提取 33 点骨架，不上传原始视频）
  -> 可选 ST-GCN / ActionCLIP 动作概率
  -> Agent A：校验、平滑、识别、阶段、计数、纠错
  -> ActionReport v1 + recognition_event
  -> Agent B：专项教练、主动话术、阶段计划、训练总结、饮食建议
```

数值计算和实时判断由确定性算法完成。LLM 不直接读取长 URDF、不逐帧计算关节角，也不负责简单阈值判断；它消费 Agent A 的结构化报告，用于复杂语境理解、主动关怀和个性化规划。详见 [架构与技术边界](docs/ARCHITECTURE.md) 和 [团队分工](docs/TEAM_SCOPE.md)。

## 开源模型与 API 的分界

| 能力 | 第一版实现 | 是否需要云端 API Key |
| --- | --- | --- |
| 人体关键点 | 浏览器 MediaPipe Tasks Vision | 否 |
| 基础动作识别 | HMM + 姿态规则；浏览器 ST-GCN 可选 | 否 |
| ActionCLIP/更强视频分类 | 预留 `client_probs` 适配口，尚未捆绑权重与推理服务 | 取决于部署方式；本地开源模型不需要 |
| URDF 读取 | Python XML 确定性解析器 | 否 |
| 动作计数与纠错 | 几何特征、状态机和专项模块 | 否 |
| 对话、计划、饮食建议 | 由 Agent B 调用 LLM | 是；密钥必须由服务端保管 |

本项目第一版**不训练或微调模型**。当前目标是把成熟开源感知组件和清晰接口组合成稳定原型，先验证识别—纠错—指导闭环。

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
  }
}
```

`landmarks` 应包含 33 个 MediaPipe Pose 点。`client_probs` 可选，用来接入浏览器 ST-GCN 或独立 ActionCLIP 服务；服务端会过滤未知标签、非法分数和置信差不足的结果。

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
    "schema_version": "v1",
    "session_id": "demo-user",
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
    }
  }
}
```

`recognition_event` 只在首次确认或运动切换时出现，避免每帧重复播报。完整响应还保留旧版字段，方便现有前端兼容。

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

当前验证基线：后端 113 项、前端 10 项测试通过，前端生产构建通过。`npm audit` 仍报告上游依赖链中的安全告警，升级前需要单独做兼容性验证，不应在竞赛主线中直接执行破坏性强制升级。

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
