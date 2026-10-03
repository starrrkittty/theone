# Agent A 模型训练状态

更新时间：2026-10-04

## 当前结论

公开数据训练已经完成一轮可部署闭环，不再处于“只有规则、尚未训练”的状态：

- 5 个核心动作仍由关节几何、HMM/状态机和专项模块确认，负责计数与纠错；分类模型不能绕过这些安全门。
- MM-Fit 的 7 个长尾动作由本地轻量 ST-GCN 提供保守语义候选：`dumbbell_row`、`jumping_jack`、`lateral_raise`、`lunge`、`shoulder_press`、`situp`、`tricep_extension`。
- 长尾候选必须达到按类别校准的置信度，并连续命中 2 次，才会触发自动识别播报与通用教练路由。
- 40+ 动作目录用于统一名称、别名和后续开放词汇路由；没有专项验证的动作不会冒充“精确纠错专家”。

部署模型编号为 `mmfit-mediapipe-semantic-v1`，模型卡见 `frontend/public/stgcn_model_card.json`。

## 数据来源与许可

- 数据：MM-Fit workout sessions。
- 官方项目：https://mmfit.github.io/
- 官方代码：https://github.com/KDMStromback/mm-fit
- RGB/Depth 发布：https://zenodo.org/records/7607736
- DOI：`10.5281/zenodo.7607736`
- Zenodo RGB/Depth 记录许可：CC BY 4.0。
- 本机数据目录：`D:\datasets\mmfit`。
- 训练产物目录：`D:\datasets\ai-fitness-runs`。
- 原视频、窗口文件、PyTorch checkpoint 和虚拟环境不提交 Git；浏览器推理所需的压缩 JSON 权重和模型卡提交仓库。

## 已完成的数据处理

### 15fps 公开 2D 骨架预训练集

- 路径：`D:\datasets\mmfit\pose2d-pretrain-15fps-v1`。
- 规模：39,517 个 30 帧窗口。
- 输入：MM-Fit COCO-18 映射为产品 17 点，`xy`，15fps。
- 用途：预训练和管线验证，不直接作为浏览器部署模型。

### RGB→产品同款 MediaPipe 同域数据集

- 路径：`D:\datasets\mmfit\mediapipe-rgb-p05-p09`。
- 来源视频：`w16` 至 `w20`，共 5 名独立参与者。
- 规模：6,769 个 30 帧窗口，含 10 类 MM-Fit 动作和 `unknown`。
- 输入：仓库内同款 MediaPipe Pose Landmarker Lite，15fps，`xy`，`torso_xy` 归一化。
- 固定人员划分：
  - 训练：`p05/w16`、`p07/w18`、`p09/w20`。
  - 验证及阈值校准：`p06/w17`。
  - 最终测试：`p08/w19`。

同一人的相邻窗口不会跨训练、验证和测试集合。

## 已验证结果

### 1. 公开 2D 骨架源域基线

- 产物：`D:\datasets\ai-fitness-runs\mmfit-pose2d-15fps-temporal-xy`。
- 独立测试 accuracy：0.9133。
- balanced accuracy：0.8823。
- unknown false accept rate：0.0343。

这组结果只能证明公开骨架源域内可分，不能证明产品摄像画面中的效果。

### 2. 源域模型直接迁移到 RGB→MediaPipe

- 测试人：`p08/w19`，未参与训练。
- 产物：`D:\datasets\ai-fitness-runs\mmfit-rgb-w19-domain-eval-15fps`。
- accuracy：0.6901。
- balanced accuracy：0.5765。
- unknown false accept rate：0.1250。

结论：直接使用公开预提取骨架存在明显输入域差异，不能部署。因此后续训练使用官方 RGB 视频重新提取产品同款 MediaPipe 关键点。

### 3. RGB 同域微调模型

- 产物：`D:\datasets\ai-fitness-runs\mmfit-rgb-finetuned-balanced`。
- 初始化：15fps 公开骨架 checkpoint。
- 固定 `p08` 测试 accuracy：0.8459。
- 固定 `p08` 测试 balanced accuracy：0.8383。
- 直接 argmax 的 unknown false accept rate：0.2212。

直接把 11 类 argmax 当最终产品识别并不可靠：`unknown` 误接收过高，而且 `squat` 在此人的画面上塌缩到相邻弯举标签。因此模型不负责核心动作的专项判定，只负责长尾语义候选。

### 4. 长尾语义阈值校准

- 校准产物：`D:\datasets\ai-fitness-runs\mmfit-rgb-finetuned-semantic-calibration`。
- 阈值只用 `p06` 选择，`p08` 不参与调参。
- 验证集 balanced accuracy：0.8574。
- 验证集 unknown false accept rate：0.0912。
- 未见测试人 `p08` balanced accuracy：0.7349。
- 未见测试人 `p08` unknown false accept rate：0.0481。
- 运行时还要求连续 2 次命中；上述数字是更保守的单窗口评测，没有计入连续确认带来的进一步降误报。

部署阈值：

| 动作 | 阈值 | `p08` precision | `p08` recall |
|---|---:|---:|---:|
| dumbbell row | 0.750 | 0.984 | 0.829 |
| jumping jack | 0.720 | 未覆盖 | 未覆盖 |
| lateral raise | 0.995 | 0.846 | 0.458 |
| lunge | 0.970 | 0.986 | 0.455 |
| shoulder press | 0.720 | 1.000 | 0.507 |
| sit-up | 0.999 | 0.985 | 0.943 |
| tricep extension | 0.990 | 0.972 | 1.000 |

`p08/w19` 没有 jumping jack 样本，因此该类只有验证集证据，不能声称已在未见人员上验证。lateral raise、lunge 和 shoulder press 当前倾向“宁可不报，也不乱报”，召回率仍需真实视频补强。

## 已部署内容

- `frontend/public/stgcn_weights.json`：RGB 同域微调权重。
- `frontend/public/stgcn_scaler.json`：训练集归一化统计。
- `frontend/public/stgcn_model_card.json`：数据、人员划分、阈值、指标与限制。
- `backend/recognition/semantic.py`：按类别阈值和连续命中确认。
- `backend/exercises/catalog.py`：40+ 动作目录与能力边界。
- `backend/recognition/routing.py`：专项专家、通用指导和继续观察三种路由。

## 仍需完成的参赛验收

1. 团队自录真实视频通话测试集：不同手机、距离、机位、光照、遮挡、多人、出画、休息和非运动负样本。
2. 补齐 MM-Fit 没有的 `plank`、普通双臂弯举，以及比赛演示一定会出现的动作。
3. 对低召回长尾类补采并微调；任何新增人员都继续按人划分，不能随机拆帧。
4. 为每个拟宣传为“专项纠错”的动作建立动作质量标注和独立验收，不能只凭动作类别分类准确率。
5. API Key 明确后接入受控 Video LLM 作为开放词汇和复杂场景补充；LLM 不参与关节角、次数、URDF 约束或确定性阈值计算。

公开数据解决的是可复现基线和初始泛化，不等于真实视频通话验收完成。后续最有价值的数据不是再盲目扩大通用动作集，而是按上述失败场景定向补采。
