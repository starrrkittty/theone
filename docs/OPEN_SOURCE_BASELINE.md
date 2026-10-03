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
- 决策：只提取目标类别并重新运行产品同款 MediaPipe；作为补充训练和独立跨域评测，不单独作为万能动作模型。

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
- 用途：后续通用重复动作计数和 RepCount-pose 对照。
- 不直接采用原因：专项计数状态机已可解释且低延迟；先测量跨动作计数误差，再决定是否引入模型。

### Fitness-AI-Trainer BiLSTM

- 仓库：https://github.com/RiccardoRiccio/Fitness-AI-Trainer-With-Automatic-Exercise-Recognition-and-Counting
- 数据页：https://huggingface.co/datasets/RickyRiccio/Real_Time_Exercise_Recognition_Dataset
- 可借鉴内容：MediaPipe 时序窗口、自动动作识别和专项计数解耦。
- 不直接并入训练集原因：数据页声明 CC BY-NC-SA 4.0，但说明中还混有 Kaggle、InfiniteRep、在线抓取及 Shutterstock 等来源；逐视频权利链和商业可用性不够清楚。可用于研究对照，不作为参赛发布模型的默认训练源。

### PocketGym 等个人演示仓库

- 示例：https://github.com/musickevan1/pocket-gym
- 可借鉴内容：浏览器/摄像头交互、角度提示和动作模块化界面。
- 不直接采用原因：代码规模、测试证据、数据来源和模型评测不如官方论文仓库；只借鉴交互，不把 README 中的支持动作数量当成模型质量证据。

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
- 尚未引入 ActionCLIP、RTMPose 或 PoseRAC；只有真实视频通话评测证明现方案在开放词汇、遮挡姿态或通用计数上不足时才升级。

这意味着“借鉴 GitHub repo”已经转化成了可复现实现和选择依据，但没有为了展示技术栈而堆砌三个重复解决同一问题的模型。
