# 公共数据集训练与可视化

本目录提供一条可复现的轻量 ST-GCN 训练链路。它不会使用仓库内少量合成轨迹冒充真实训练数据，也不会把同一受试者的相邻帧同时放进训练集和测试集。

## 推荐数据顺序

1. MM-Fit：先覆盖 `squat`、`pushup`、`alternate_bicep_curl` 和动作间歇的 `unknown`。
2. Fit3D：用于更多机位、极端健身姿态和高质量 3D 姿态评测，不直接假设它覆盖本项目的全部动作标签。
3. UI-PRMD：可用于深蹲等康复动作的轨迹/动作质量研究，不适合作为本项目五类动作的唯一分类训练集。
4. 团队自录视频通话数据：补充 `plank`、普通弯举、低光、遮挡、多人和非运动负样本。

MM-Fit 官方入口：https://mmfit.github.io/

实际下载约束：

- MM-Fit 在 Zenodo 发布的 RGB/Depth 视频约 40.8 GB，许可信息清楚，适合最终的同输入域训练。
- MM-Fit 姿态/传感器压缩包约 1.66 GB，下载更轻，但其公开下载页未清楚声明数据许可，而且 Human3.6M 17 点定义与本项目 MediaPipe 17 点子集不同，只建议做预训练或研究对照。
- Fit3D 训练集约 18 GB、测试集约 1.4 GB，需要注册，并受非商业研究许可限制。

脚本不会自动下载这些数据。先确认团队可用磁盘空间和许可，再把数据放入被 `.gitignore` 忽略的 `training/data/`，不要提交原视频到 Git 仓库。

公开数据不要直接使用其现成骨架格式训练后就宣称可部署。当前应用输入是 MediaPipe Pose Landmarker 的坐标，因此推荐把公开 RGB 视频重新通过同一套 `pose_landmarker_lite.task` 提取，以减少关键点定义和坐标分布差异。

## 1. 准备环境

建议使用 Python 3.11 的独立环境：

```powershell
python -m venv .training-venv
.\.training-venv\Scripts\python.exe -m pip install -r training\requirements.txt
```

## 2. 建立片段清单

复制 `training/example_manifest.json`，给每个运动区间填写：

- `path`：相对于 manifest 所在目录的视频路径。
- `label`：统一标签。
- `subject`：受试者或 workout session ID。
- `start_sec`、`end_sec`：该动作在原始视频中的时间区间。

统一标签建议为：

```text
squat
pushup
plank
bicep_curl
alternate_bicep_curl
unknown
```

必须加入 `unknown`，包括坐下、弯腰、喝水、走动和其他不支持运动，否则分类器会被迫把任何动作归入五类运动之一。

## 3. 用与产品一致的 MediaPipe 模型提取窗口

```powershell
.\.training-venv\Scripts\python.exe training\build_windows.py `
  --manifest training\data\manifest.json `
  --model frontend\public\models\pose_landmarker_lite.task `
  --output training\data\mmfit_windows.npz
```

每个样本是连续 30 帧、17 个关键关节、3 个坐标，归一化方法与浏览器一致。输出还保留 `subject`，训练脚本会按人员/session划分数据。

## 4. 训练并导出浏览器可读权重

```powershell
.\.training-venv\Scripts\python.exe training\train_stgcn.py `
  --dataset training\data\mmfit_windows.npz `
  --output-dir training\runs\mmfit-v1 `
  --epochs 40
```

训练输出：

- `training_report.json`：数据划分、每轮 loss/accuracy、测试准确率和混淆矩阵。
- `training_curves.png`：训练集/验证集的 loss 和 accuracy 曲线。
- `confusion_matrix.png`：独立测试人员上的混淆矩阵。
- `confusion_matrix_normalized.png`：按真实类别归一化的混淆矩阵，更容易发现某一类被系统性误判。
- `stgcn_weights.json`、`stgcn_scaler.json`：与前端推理器兼容的权重。

只有满足以下条件后才替换当前权重：

1. 测试集人员没有出现在训练集。
2. 含 `unknown` 负样本。
3. 新模型在固定测试集上优于规则基线或现有权重。
4. 不只是总 accuracy 提升，`training_report.json` 中的 balanced accuracy、每类 precision/recall/F1 和 `unknown_false_accept_rate` 也可接受。

替换前先备份并对比：

```powershell
Copy-Item training\runs\mmfit-v1\stgcn_weights.json frontend\public\stgcn_weights.json
Copy-Item training\runs\mmfit-v1\stgcn_scaler.json frontend\public\stgcn_scaler.json
```

## 怎么看可视化

训练阶段直接打开：

- `training/runs/mmfit-v1/training_curves.png`
- `training/runs/mmfit-v1/confusion_matrix.png`
- `training/runs/mmfit-v1/confusion_matrix_normalized.png`

部署权重后打开 `http://127.0.0.1:3000/`：

1. 上传一段已知动作视频。
2. 在“开发者评测模式”选择 Ground Truth。
3. 在“识别证据与拒识原因”查看 ST-GCN 四/多类概率、原始 Top-1、标签映射、规则候选和模型是否被融合。
4. 查看首次确认、确认准确率、未知帧率、不可靠画面率和误识别帧。
5. 导出 JSON，保存本次测试结果。

训练曲线只能说明优化过程，不能证明产品质量；最终结论以独立人员、真实视频通话场景的回放测试为准。
