# 公开数据与开源仓库采用决策

## 直接使用

### MM-Fit

- 官方项目页：https://mmfit.github.io/
- 官方 starter code：https://github.com/KDMStromback/mm-fit
- 视频发布页：https://zenodo.org/records/7607736
- 用途：10 类健身动作分类、动作间隙 `unknown`、跨 workout 测试。
- 决策：标签与 starter code 作为训练基准；RGB 视频必须重新经过产品同款 MediaPipe，以避免关键点定义偏移。

MM-Fit 类别映射：

| MM-Fit | 本项目 |
|---|---|
| squats | squat |
| lunges | lunge |
| bicep_curls | alternate_bicep_curl |
| situps | situp |
| pushups | pushup |
| tricep_extensions | tricep_extension |
| dumbbell_rows | dumbbell_row |
| jumping_jacks | jumping_jack |
| dumbbell_shoulder_press | shoulder_press |
| lateral_shoulder_raises | lateral_raise |

### HAA500（目标类别补充）

- 官方页面：https://cse.hkust.edu.hk/haa/
- 论文：https://arxiv.org/abs/2009.05224
- 用途：官方 500 类中包含 `Gym Plank`，每类约 20 个经过人工裁剪的短视频，可补充 MM-Fit 缺失的平板支撑画面。
- 限制：类别表中没有可直接等价为本项目“普通双臂哑铃弯举”的类别；不能用相近的 `Gym Lift` 或 `Workout Chest-Pull` 偷换标签。
- 许可判断：项目页面附有 MIT LICENSE，但视频源自第三方 YouTube 片段。训练时保留 URL/片段来源，仓库不再分发原视频，商业使用前仍需复核原视频权利。
- 决策：目标动作和非运动 hard negatives 都重新运行产品同款 MediaPipe；作为补充训练和独立跨域评测，不单独作为万能动作模型。
- 已增加 15 类、300 段 hard-negative 视频：挥手、梳头、刷牙、喝饮料、看书、吃东西、戴口罩等视频通话常见行为。按原片编号 `000–015` / `016` / `017–019` 固定训练、验证和测试，未把测试片段回灌训练。

## 借鉴，不直接并入第一版依赖

### MMAction2 / PoseC3D

- 仓库：https://github.com/open-mmlab/mmaction2
- 用途：作为后续骨架模型升级和多人场景对照。
- 不直接采用原因：依赖和部署成本明显高于当前浏览器轻量模型；应先用固定测试集证明轻量模型不够。

### ActionCLIP

- 官方实现：https://github.com/sallymmx/ActionCLIP
- 用途：开放词汇动作识别思路和离线对照。
- 不直接采用原因：原仓库面向研究训练与视频分类，不是浏览器实时 SDK；第一版长尾语义识别优先用受控关键帧 API。

### MMPose / RTMPose

- 仓库：https://github.com/open-mmlab/mmpose
- 用途：MediaPipe 在遮挡、多人或特殊视角下表现不足时的姿态提取替代方案。
- 不直接采用原因：当前 MediaPipe 已能本地浏览器运行，替换姿态模型需要重新验证坐标、速度和移动端部署。

### PoseRAC

- 官方实现：https://github.com/MiracleDance/PoseRAC
- 证据：论文官方实现，MIT 许可；输入人体姿态，在 RepCount-pose 上输出通用重复动作次数，并提供预训练权重和可视化脚本。
- 用途：后续通用重复动作计数和 RepCount-pose 离线对照。
- 不直接采用原因：它解决“已经知道是一段重复动作后如何计数”，不能替代动作识别、动作质量纠错或 unknown 拒识；当前专项状态机更适合浏览器实时解释。先用真实视频计数误差证明现方案不足，再引入模型。

### TransRAC

- 官方实现：https://github.com/SvipRepetitionCounting/TransRAC
- 证据：CVPR 2022 Oral 官方实现，Apache-2.0；使用 Video Swin 和多尺度时序相关性预测周期密度图，适合长视频、动作中断和不规则周期。
- 可借鉴内容：把“次数”建模为随时间积分的密度图，而不是只靠单个峰值阈值；可用于离线计数基准和解释性可视化。
- 不直接采用原因：64 帧 RGB/Video Swin 路线明显重于当前 17 点骨架状态机，不适合第一版浏览器主链路。

### Fitness-AQA / NS-AQA

- Fitness-AQA：https://github.com/ParitoshParmar/Fitness-AQA
- NS-AQA：https://github.com/laurenok24/NSAQA
- 可借鉴内容：把动作质量拆成阶段、规则、错误证据和可解释报告；这与本项目“几何/HMM 做确定性纠错，Agent 解释复杂上下文”的边界一致。
- 限制：Fitness-AQA 数据需填写表单申请且仅限非商业使用，集中于 back squat、overhead press、barbell row；NS-AQA 代码和数据同样标明仅非商业使用，示例任务是跳水。代码不可直接复制进商业产品。
- 决策：借鉴神经符号分层报告结构，在本项目中用自有规则和许可清晰的数据重新实现；若仅用于竞赛研究，可在用户本人接受数据条款后再做离线对照。

### Fitness-AI-Trainer BiLSTM

- 仓库：https://github.com/RiccardoRiccio/Fitness-AI-Trainer-With-Automatic-Exercise-Recognition-and-Counting
- 数据页：https://huggingface.co/datasets/RickyRiccio/Real_Time_Exercise_Recognition_Dataset
- 可借鉴内容：MediaPipe 时序窗口、自动动作识别和专项计数解耦。
- 不直接并入训练集原因：数据页声明 CC BY-NC-SA 4.0，但说明中还混有 Kaggle、InfiniteRep、在线抓取及 Shutterstock 等来源；逐视频权利链和商业可用性不够清楚。可用于研究对照，不作为参赛发布模型的默认训练源。

### PocketGym 等个人演示仓库

- 示例：https://github.com/musickevan1/pocket-gym
- 可借鉴内容：浏览器/摄像头交互、角度提示和动作模块化界面。
- 不直接采用原因：代码规模、测试证据、数据来源和模型评测不如官方论文仓库；只借鉴交互，不把 README 中的支持动作数量当成模型质量证据。

### InfiniteRep 研究归档（审计后未采用）

- 归档页：https://huggingface.co/datasets/FatimahEmadEldin/infiniterep-physiotherapy
- 原计划用途：用合成人体的 `curl`、`pushup`、`squat` 实例增加视角与人体外观变化。
- 实际审计：随机下载并解压 `curl/000000_img_labels.zip`，内部只有 `cseg`/`iseg` 分割 PNG，没有产品同域 RGB、可直接映射的人体关键点或相机参数。
- 决策：不批量下载，不将分割图伪装成动作识别数据。若后续获得原始 RGB/关键点与明确许可，再重新评估。

### QEVD（优先候选，需用户接受许可）

- 官方页：https://www.qualcomm.com/developer/software/qevd-dataset
- 价值：真实健身视频、动作变体、常见错误、非运动负类与教练纠错标注，和视频通话健身私教最接近。
- 限制：官方要求 Qualcomm ID 并接受 Research Use 数据许可；本仓库不代替用户接受协议，也不绕过下载门禁。

### FLEX / MyoMechanix 动作质量数据（需申请，当前不采用）

- 当前仓库：https://github.com/HaoYin116/FLEX
- 论文：https://arxiv.org/abs/2506.03198
- 价值：论文描述 38 人、20 种负重动作、5 视角，并含动作阶段、错误类型和质量分数。
- 当前状态：旧项目页已失效；仓库现名 MyoMechanix，数据需提交访问申请并同意仅学术/研究用途，代码与预训练模型仍标为后续发布。
- 决策：不能把论文中的“将发布”当成已经可用的数据或模型。用户本人完成许可申请前，不下载、不训练、不声称采用。

## 采用原则

1. 数据许可、下载来源和引用信息必须保留。
2. 按人物或 workout 划分，禁止相邻窗口跨训练/测试泄漏。
3. 公开骨架只用于预训练或对照；部署模型优先从 RGB 重新提取产品同域关键点。
4. 新模型必须在固定真实视频集上优于当前规则/轻量模型，才能替换。
5. 开源代码只借鉴明确需要的组件，保留许可证，不整仓复制到产品。

## 当前落地状态

- 已实际使用 MM-Fit 的官方标签、骨架数据和 Zenodo RGB 视频完成预训练、跨域复评与 RGB 同域微调。
- 已借鉴 MMAction2/PoseC3D 的骨架时序建模思路，在现有浏览器轻量模型中加入 mean、std、absolute velocity 和 range 时序池化；没有引入 MMAction2 的重依赖。
- 已把部署模型限定为“长尾语义候选器”，核心动作继续走可解释专项模块。
- 已增加目录视频到 manifest 的通用导入器、来源/许可审计、跨标签表内存映射合并，以及新增类别时按同名标签继承分类头的训练能力。
- 已增加训练期骨架镜像/旋转/缩放/抖动、不同标签表安全复评、运行时逐类阈值跨域复评和按官方片段编号扩展数据划分的工具。
- 已用 HAA500 的 15 类 hard negatives 实际训练；新增负样本独立测试 unknown 误接纳率降至 0.098，但全部 HAA500 独立负样本合并后仍为 0.239，因此候选模型没有覆盖当前部署权重。
- 尚未引入 ActionCLIP、RTMPose 或 PoseRAC；只有真实视频通话评测证明现方案在开放词汇、遮挡姿态或通用计数上不足时才升级。

这意味着“借鉴 GitHub repo”已经转化成了可复现实现和选择依据，但没有为了展示技术栈而堆砌三个重复解决同一问题的模型。
