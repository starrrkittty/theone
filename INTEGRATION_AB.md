# A + B 整合说明

2026-10-03：新增在线 URDF/关节状态与 A Agent，最新架构、API 和限制见 [AGENT_A_FRAMEWORK.md](AGENT_A_FRAMEWORK.md)。

最新完整链路审查、修复及验证边界见 [A_GROUP_AUDIT.md](A_GROUP_AUDIT.md)。

## 来源与启动

A：本地 `C:/Users/woshi/theone` 的 `origin/codex/agent-a-v1`，提交 `14d8b54`。main 只有 README，因此使用本机已克隆的功能分支。原仓库未改写，保留原 LICENSE。
B：当前工作区 outputs/b_group 的代码、四项任务 Skill、知识库与工作台。未复制旧 API Key、训练历史或上传文件。

通常先运行 setup.cmd，再运行 start.cmd。在 coach/config.json 填写 API Key；其他 OpenAI 兼容服务还需调整 base_url 和 model。所有专家共用配置，Key 不发送给浏览器。

当前机器已准备 .deps 和前端静态构建，可使用 `C:/Users/woshi/anaconda3/python.exe launch.py`。
网页：http://127.0.0.1:8800/；B 工作台：http://127.0.0.1:8800/coach；接口目录：/docs。
端口冲突时使用 `python launch.py --port 8801`。

当前环境的 Vite 子进程受限，frontend/build-local.ps1 使用同一份 React 源码、esbuild 和 Tailwind 构建；通常环境继续 npm run build。
tools/bootstrap_local.py 为本机替代安装工具，下载固定版本纯 Python wheel 并校验 PyPI SHA256；依赖主机已有 numpy/scipy/pydantic/settings。常规安装用 setup.cmd。

## 流程

1. 摄像头或视频进入 A 的 MediaPipe、动作识别、计次与姿势算法；image/world 关键点同时用于简化骨架拟合、URDF 解析与连续关节状态。
2. A 输出 ActionReport v1，补充逐关节可见度；前端时间戳修正为 Unix 毫秒。
3. 适配器将动作、阶段、角度定义和置信度转为 B 输入，保留 A 算法观察。
4. 新报告先运行 A 的 perception-urdf Skill 与证据工具循环；交接通过后 B 进行观测检查、分类路由、Skill 加载、知识检索、模型调用与输出校验。
5. A 页面显示与可选播报专家反馈；自动调用需勾选，最多每 20 秒一次；暂停保留最新报告。
6. “带入 B 工作台”将最新 A JSON 放入 B 动作编辑器。其他训练汇报、规划、营养与历史功能保留。

## 接口

| 路径 | 用途 |
| --- | --- |
| POST /api/agent-a/normalize | 转换 A v1 并返回观测检查，不调用模型 |
| POST /api/agent-a/coach | 转换并调用 B 专家；未确认动作等待识别 |
| POST /api/movement/analyze | 接受 B v1.0 或 A v1/封装输出 |
| POST /api/workouts/summary | 真实训练记录汇报 |
| POST /api/plans/phase | 用户目标、时间、器材、恢复背景的规划 |
| POST /api/workflow | B 与 C/D/E 接口串联，详见 coach/INTEGRATION.md |

支持 A 的 squat/pushup/plank 与同时/交替弯举；对应 B 的 bodyweight_squat/push_up/forearm_plank 与新增 curl_form。整合版有 8 个动作专家和 33 个可路由动作。

## 边界与待验收

- A 使用归一化 MediaPipe xyz，膝肘为骨段夹角；肩角不改称肩屈曲。适配器明确 included_segment_angle。
- 逐关节置信度取相关输入关键点 visibility 的最小值，不是经过校准的角度误差；旧输入仅用 form_confidence，无则为 0。不使用动作识别置信度替代姿势置信度。
- 未标定的 3D 数据不得产生确定性角度纠错。A 的违规、疲劳和 rep_quality 保留为上游启发式观察。非相关关节默认 0 值不转发。
- 已新增 MediaPipe → 简化逐帧 URDF → parser → 关节状态 JSON → A Agent；尚非经过标定的完整人体运动学模型。原 A 仓库不变。
- 最新单帧不是完整训练记录。汇报仍需真实开始/结束时间、组数、目标次数及用户反馈；不自动编造 RPE、时长、热量或肌肉增长。
- 弯举知识目前是明确标注的工程检查表，尚需补充已审核的专项科学来源。
- 无 Key 可运行 A 识别与观测检查；真实 AI 指导、汇报和规划需配置模型。尚未完成真实模型/人体动作效果验收。
- A 瑜伽接口保留，但未新增 B 瑜伽专家。摄像头需用户授权，MediaPipe 模型与 WASM 首次加载需要网络。

正式部署前仍需真实视频端到端验收、动作测量标定和人工专家审核。
