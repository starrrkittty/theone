# 公共数据集训练与可视化

本目录提供一条可复现的轻量 ST-GCN 训练链路。它不会使用仓库内少量合成轨迹冒充真实训练数据，也不会把同一受试者的相邻帧同时放进训练集和测试集。

## 推荐数据顺序

1. MM-Fit：覆盖其 10 种公开健身动作与动作间歇 `unknown`，其中三类进入当前专项链路，其余作为语义识别和通用专家路由基线。
2. Fit3D：用于更多机位、极端健身姿态和高质量 3D 姿态评测，不直接假设它覆盖本项目的全部动作标签。
3. UI-PRMD：可用于深蹲等康复动作的轨迹/动作质量研究，不适合作为本项目五类动作的唯一分类训练集。
4. 团队自录视频通话数据：补充 `plank`、普通弯举、低光、遮挡、多人和非运动负样本。

补充数据的采用门槛是：来源可追溯、许可可记录、动作定义与本项目一致，并且能按独立人物或独立源视频划分。仅有 GitHub 代码、没有可靠视频来源和许可的数据，不进入正式模型。

MM-Fit 官方入口：https://mmfit.github.io/

实际下载约束：

- MM-Fit 在 Zenodo 发布的 RGB/Depth 视频约 40.8 GB，许可信息清楚，适合最终的同输入域训练。
- MM-Fit 姿态/传感器压缩包约 1.66 GB，下载更轻，但其公开下载页未清楚声明数据许可，而且 Human3.6M 17 点定义与本项目 MediaPipe 17 点子集不同，只建议做预训练或研究对照。
- Fit3D 训练集约 18 GB、测试集约 1.4 GB，需要注册，并受非商业研究许可限制。

本机数据统一放在 `D:\datasets`，模型输出统一放在 `D:\datasets\ai-fitness-runs`，不要把原视频、窗口文件或训练权重提交到 Git 仓库。

公开数据不要直接使用其现成骨架格式训练后就宣称可部署。当前应用输入是 MediaPipe Pose Landmarker 的坐标，因此推荐把公开 RGB 视频重新通过同一套 `pose_landmarker_lite.task` 提取，以减少关键点定义和坐标分布差异。

本项目提供按字节分块、断点保留、最终核对 Zenodo 官方 MD5 的下载器。例如只下载 5 个独立受试者对应的较小 RGB 文件：

```powershell
.\.training-venv\Scripts\python.exe training\download_zenodo_files.py `
  --record 7607736 `
  --output D:\datasets\mmfit\rgb `
  --files w16_rgb.mp4 w17_rgb.mp4 w18_rgb.mp4 w19_rgb.mp4 w20_rgb.mp4 `
  --connections 8
```

这里的 8 路并发只用于网络流式下载，每路按 1MB 缓冲，不会把视频读入内存。

若 RGB 尚未下载，可先使用官方 2D COCO 骨架训练公开数据预训练基线：

```powershell
.\.training-venv\Scripts\python.exe training\build_mmfit_pose_windows.py `
  --dataset-root D:\datasets\mmfit\extracted\mm-fit `
  --output D:\datasets\mmfit\pose2d-pretrain-v1
```

该输出会写入 `provenance.json`，明确标记 `deployable_without_rgb_finetune=false`。它适合验证类别可分性和训练管线，不能替代 RGB→MediaPipe 同域微调与真实视频验收。

## 1. 准备环境

使用仓库内被 Git 忽略的独立环境；仓库本身位于 D 盘，因此依赖不会写进 C 盘项目目录：

```powershell
python -m venv .training-venv
.\.training-venv\Scripts\python.exe -m pip install -r training\requirements.txt
```

## 2. 从 MM-Fit 官方标注建立片段清单

官方标签格式为 `(Start Frame, End Frame, Repetition Count, Activity)`。下载并解压 RGB 视频和标签后运行：

```powershell
.\.training-venv\Scripts\python.exe training\prepare_mmfit_manifest.py `
  --dataset-root D:\datasets\mmfit\extracted `
  --output D:\datasets\mmfit\manifest.json
```

脚本会映射 MM-Fit 的 10 类动作，并从动作间隙自动抽取 `unknown`。也可以手工建立 manifest：

复制 `training/example_manifest.json`，给每个运动区间填写：

- `path`：相对于 manifest 所在目录的视频路径。
- `label`：统一标签。
- `subject`：受试者或 workout session ID。
- `start_sec`、`end_sec`：该动作在原始视频中的时间区间。

当前训练管线允许的公开集标签为：

```text
squat
pushup
plank
bicep_curl
alternate_bicep_curl
lunge
situp
tricep_extension
dumbbell_row
jumping_jack
shoulder_press
lateral_raise
burpee
jump_rope
pullup
running_in_place
crunch
side_lunge
one_arm_pushup
battle_rope
yoga_tree
yoga_triangle
unknown
```

必须加入 `unknown`，包括坐下、弯腰、喝水、走动和其他不支持运动，否则分类器会被迫把任何动作归入五类运动之一。

### 从“类别/人物/视频”目录生成 manifest

对 HAA500 子集、团队自录视频或其他按目录整理的数据，可先生成带来源审计的 manifest：

```powershell
.\.training-venv\Scripts\python.exe training\prepare_directory_manifest.py `
  --dataset-root D:\datasets\haa500\selected `
  --label-map training\example_directory_label_map.json `
  --output D:\datasets\haa500\selected-manifest.json `
  --dataset-id haa500-v1.1-selected `
  --source-url https://cse.hkust.edu.hk/haa/ `
  --license MIT `
  --license-url https://cse.hkust.edu.hk/haa/LICENSE `
  --subject-mode file
```

支持两种常见布局：

- `<原始类别>/<人物或录制场次>/<视频>`：使用默认 `--subject-mode parent`。
- `<原始类别>/<独立源视频>`：仅当每个文件确实来自不同源录制时使用 `--subject-mode file`。

脚本默认要求每个目标类别至少 3 个独立人物/场次，并输出同名 `.provenance.json`，记录来源、许可、标签映射、类别数量和被忽略的视频。它不会把公开数据集的类别标签误当成动作质量标签。

## 3. 用与产品一致的 MediaPipe 模型提取窗口

对 MM-Fit 原始帧号标注，优先使用专用脚本；它会保留官方 participant 身份，按视频逐段处理并写分片：

```powershell
.\.training-venv\Scripts\python.exe training\build_mmfit_rgb_windows.py `
  --dataset-root D:\datasets\mmfit\extracted\mm-fit `
  --rgb-root D:\datasets\mmfit\rgb `
  --pose-model frontend\public\models\pose_landmarker_lite.task `
  --output D:\datasets\mmfit\mediapipe-rgb-v1 `
  --workouts w16 w17 w18 w19 w20 `
  --target-fps 15
```

对团队自录或其他按秒标注的视频，使用通用 manifest 脚本：

```powershell
.\.training-venv\Scripts\python.exe training\build_windows.py `
  --manifest D:\datasets\mmfit\manifest.json `
  --model frontend\public\models\pose_landmarker_lite.task `
  --output D:\datasets\mmfit\pose-windows-v1 `
  --workers 0 `
  --memory-reserve-gb 6 `
  --max-windows-per-segment 160
```

`--workers 0` 会根据当前可用物理内存自动选择并发数，上限为 4；每个 worker 按 1.5 GB 估算并预留指定内存。任务队列最多保留 `2×worker` 个片段。每个片段先写临时分片，最终合并为 `.npy` 内存映射文件，不会在 RAM 中堆积整个数据集。

HAA500 这类已裁剪的 atomic-action 视频常短于 2 秒。仅对这种“整段只有一个动作”的公开短片可增加 `--short-clip-policy resample --minimum-short-frames 8`，把不足 30 个有效姿态帧的片段线性重采样为一个窗口；连续视频通话、自录长视频和带开始/结束标注的片段仍使用默认 `drop`，避免把停顿或跨动作区间压进一个窗口。

每个样本是连续 30 帧、17 个关键关节、3 个坐标，归一化方法与浏览器一致。输出保留 `subject`，训练脚本按人员/session划分数据。

## 4. 训练并导出浏览器可读权重

```powershell
.\.training-venv\Scripts\python.exe training\train_stgcn.py `
  --dataset D:\datasets\mmfit\pose-windows-v1 `
  --output-dir D:\datasets\ai-fitness-runs\mmfit-v1 `
  --epochs 40 `
  --patience 6 `
  --coordinate-mode xy `
  --target-fps 15 `
  --train-subjects p05 p07 p09 `
  --validation-subjects p06 `
  --test-subjects p08 `
  --init-checkpoint D:\datasets\ai-fitness-runs\mmfit-pose2d-15fps-temporal-xy\stgcn_checkpoint.pt `
  --batch-size 64 `
  --dataloader-workers 0
```

Windows 上默认 `dataloader-workers=0`，避免多进程复制内存映射数组。均值和方差按块计算，训练样本在 `Dataset.__getitem__` 中逐批归一化。

MM-Fit 的公开预提取骨架只有 2D 坐标，因此该预训练模型使用 `--coordinate-mode xy`，并在导出权重中记录这个契约；浏览器会自动忽略 z。不要让一个从未见过 z 分布的模型直接读取 MediaPipe z。前端也按导出的 `target_fps` 采样，避免不同设备帧率改变速度特征。训练连续若干轮不提升时会早停，并恢复验证集最优权重。

`--init-checkpoint` 用于公开骨架预训练后的 RGB 同域微调；不传该参数就是从头训练。二者必须使用完全相同的人员划分再比较，避免把“换了测试人”误当成模型提升。

可使用 `--augmentation light` 仅对训练窗口做保守骨架增强：左右镜像时同步交换左右关节，并加入小角度旋转、缩放与关键点抖动。验证集和测试集始终保持原样；增强候选仍必须通过同人员划分的独立门禁，不因增加了技术名词就默认更好。

含 `unknown` 负样本时，可用 `--selection-metric balanced_accuracy_minus_unknown_far --unknown-far-penalty 1.0` 让早停同时考虑类别均衡准确率和验证集 unknown 误接收。惩罚系数必须预先固定，不能看测试集后反复调整；最终仍要运行逐类阈值校准和跨来源测试。

若新增数据带来新类别（例如在现有 MM-Fit 数据上新增 HAA500 `plank`），先进行内存映射合并：

```powershell
.\.training-venv\Scripts\python.exe training\merge_datasets.py `
  --inputs D:\datasets\mmfit\mediapipe-rgb-p05-p09 D:\datasets\haa500\plank-windows `
  --output D:\datasets\combined\mmfit-haa500-v1
```

合并器按标签名称重映射类别，不要求各来源拥有完全相同的标签表。训练时显式使用 `--init-classifier-mode shared`，只继承旧模型的骨干参数和同名分类头，新增类别的分类头随机初始化后共同微调：

```powershell
.\.training-venv\Scripts\python.exe training\train_stgcn.py `
  --dataset D:\datasets\combined\mmfit-haa500-v1 `
  --output-dir D:\datasets\ai-fitness-runs\mmfit-haa500-v1 `
  --init-checkpoint D:\datasets\ai-fitness-runs\mmfit-rgb-finetuned-balanced\stgcn_checkpoint.pt `
  --init-classifier-mode shared `
  --dataloader-workers 0
```

新增类别后必须重新做独立人员/源视频测试和阈值校准，不能仅因训练 loss 下降就覆盖部署权重。

若某一标签在姿态域不可辨认，或只是已有动作的细粒度变体，应在合并前先筛选或映射，而不是强迫姿态模型学习视觉上不存在的信息：

```powershell
.\.training-venv\Scripts\python.exe training\filter_dataset_labels.py `
  --dataset D:\datasets\haa500\semantic-expansion-mediapipe-15fps-v1 `
  --output D:\datasets\haa500\semantic-expansion-no-battle-rope-15fps-v1 `
  --exclude-labels battle_rope

.\.training-venv\Scripts\python.exe training\remap_dataset_labels.py `
  --dataset D:\datasets\haa500\semantic-expansion-no-battle-rope-15fps-v1 `
  --output D:\datasets\haa500\semantic-expansion-pose-families-15fps-v1 `
  --label-map training\configs\pose-family-label-map.json
```

当前映射把 `crunch → situp`、`one_arm_pushup → pushup`、`side_lunge → lunge`；`battle_rope` 不进入姿态分类器，必须由 RGB/Video LLM 看到器械后再细化。两个工具都使用内存映射分块写入，避免在 RAM 中复制整个数据集。

训练输出：

- `training_report.json`：数据划分、每轮 loss/accuracy、测试准确率和混淆矩阵。
- `training_curves.png`：训练集/验证集的 loss 和 accuracy 曲线。
- `confusion_matrix.png`：独立测试人员上的混淆矩阵。
- `confusion_matrix_normalized.png`：按真实类别归一化的混淆矩阵，更容易发现某一类被系统性误判。
- `stgcn_weights.json`、`stgcn_scaler.json`：与前端推理器兼容的权重。
- `stgcn_checkpoint.pt`：用于跨输入域复评和后续微调的 PyTorch 检查点，不提交 Git。

在 RGB→MediaPipe 数据上复评预训练模型：

```powershell
.\.training-venv\Scripts\python.exe training\evaluate_stgcn.py `
  --dataset D:\datasets\mmfit\mediapipe-rgb-v1 `
  --checkpoint D:\datasets\ai-fitness-runs\mmfit-pose2d-temporal-xy\stgcn_checkpoint.pt `
  --output-dir D:\datasets\ai-fitness-runs\mmfit-rgb-domain-eval
```

该复评会单独输出 `evaluation_report.json` 和两张混淆矩阵。若跨域指标明显下降，应先做 RGB 同域适配，不能直接覆盖前端权重。

只有满足以下条件后才替换当前权重：

1. 测试集人员没有出现在训练集。
2. 含 `unknown` 负样本。
3. 新模型在固定测试集上优于规则基线或现有权重。
4. 不只是总 accuracy 提升，`training_report.json` 中的 balanced accuracy、每类 precision/recall/F1 和 `unknown_false_accept_rate` 也可接受。

替换前先备份并对比：

```powershell
Copy-Item D:\datasets\ai-fitness-runs\mmfit-v1\stgcn_weights.json frontend\public\stgcn_weights.json
Copy-Item D:\datasets\ai-fitness-runs\mmfit-v1\stgcn_scaler.json frontend\public\stgcn_scaler.json
```

## 5. 校准长尾语义识别

不要把 11 类 argmax 直接当作产品最终识别结果。核心动作由规则/HMM 专项模块确认；本地 ST-GCN 仅对没有专项模块的长尾动作产生语义候选，并按验证人员校准每类阈值：

```powershell
.\.training-venv\Scripts\python.exe training\calibrate_semantic_threshold.py `
  --dataset D:\datasets\mmfit\mediapipe-rgb-p05-p09 `
  --checkpoint D:\datasets\ai-fitness-runs\mmfit-rgb-finetuned-balanced\stgcn_checkpoint.pt `
  --validation-subjects p06 `
  --test-subjects p08 `
  --output-dir D:\datasets\ai-fitness-runs\mmfit-rgb-finetuned-semantic-calibration `
  --max-validation-unknown-far 0.10 `
  --per-class-min-precision 0.85 `
  --per-class-max-unknown-far 0.03 `
  --minimum-runtime-threshold 0.72
```

脚本只使用验证人员选择阈值，最后一次才报告未见测试人员。输出包括：

- `semantic_calibration_report.json`：全局阈值、逐类阈值、验证集和测试集指标。
- `semantic_threshold_curve.png`：阈值、balanced accuracy 和 unknown false accept rate 的关系。

运行时还要连续命中 2 次才确认。阈值应同步到 `backend/recognition/semantic.py` 和 `frontend/public/stgcn_model_card.json`，并在模型卡中保留模型、数据和阈值的对应关系。

普通 argmax 复评不能代表产品运行时的拒识逻辑。候选模型还应在独立来源的视频数据上应用相同的逐类阈值：

```powershell
.\.training-venv\Scripts\python.exe training\evaluate_semantic_thresholds.py `
  --dataset D:\datasets\combined\mmfit-haa500-15fps-v1 `
  --checkpoint D:\datasets\ai-fitness-runs\mmfit-rgb-augmented-v1\stgcn_checkpoint.pt `
  --thresholds-json D:\datasets\ai-fitness-runs\mmfit-rgb-augmented-v1-calibration\semantic_calibration_report.json `
  --output-dir D:\datasets\ai-fitness-runs\haa500-semantic-augmented-v1 `
  --subjects <held-out HAA500 clip ids> `
  --cpu-threads 4 `
  --dataloader-workers 0
```

脚本按标签名映射不同数据集的标签表，只评估阈值文件中的语义动作与 `unknown`。它模拟单窗口阈值门控，但不会把运行时“连续两次命中”带来的额外保护算进去。

若要检查一个完整分类报告是否满足统一门槛，可运行：

```powershell
.\.training-venv\Scripts\python.exe training\check_model_gate.py `
  --report D:\datasets\ai-fitness-runs\mmfit-v1\training_report.json `
  --min-accuracy 0.80 `
  --min-balanced-accuracy 0.75 `
  --min-class-precision 0.55 `
  --min-class-recall 0.55 `
  --min-class-support 10 `
  --max-unknown-false-accept 0.10
```

这条门槛适合“完整分类器”候选。当前部署模型的直接 argmax 不通过 unknown 误接收门槛，因此实际产品采用“核心规则确认 + 长尾逐类阈值 + 连续确认”的混合方案，不应对外声称已有一个万能全动作分类器。

## 怎么看可视化

训练阶段直接打开：

- `D:\datasets\ai-fitness-runs\mmfit-v1\training_curves.png`
- `D:\datasets\ai-fitness-runs\mmfit-v1\confusion_matrix.png`
- `D:\datasets\ai-fitness-runs\mmfit-v1\confusion_matrix_normalized.png`

部署权重后打开 `http://127.0.0.1:3000/`：

1. 上传一段已知动作视频。
2. 在“开发者评测模式”选择 Ground Truth。
3. 在“识别证据与拒识原因”查看 ST-GCN 四/多类概率、原始 Top-1、标签映射、规则候选和模型是否被融合。
4. 查看首次确认、确认准确率、未知帧率、不可靠画面率和误识别帧。
5. 导出 JSON，保存本次测试结果。

开发者面板中的“本地动作模型”默认使用稳定模型。`v9 扩类候选（仅验收）` 可用于同一视频的 A/B 对比，但在真实视频门禁通过前不得改为默认。

训练曲线只能说明优化过程，不能证明产品质量；最终结论以独立人员、真实视频通话场景的回放测试为准。

## 6. 真实视频通话批量验收

开发者评测模式现在会导出 `agent-a-runtime-evaluation/v1` 证据包，包含匿名参与者/片段 ID、场景条件、逐响应识别轨迹、确认事件和模型 ID。非支持动作必须标为 `unknown`，不能只测系统已支持的五类动作。

收集完成后运行：

```powershell
.\.training-venv\Scripts\python.exe training\aggregate_runtime_evaluations.py `
  --input D:\datasets\agent-a-runtime-eval\exports `
  --output-dir D:\datasets\agent-a-runtime-eval\reports
```

脚本按片段而非按高度相关的连续帧评分，并检查人数、类别覆盖、已支持动作召回率、unknown 误接收、首次确认延迟、错误切换和不可靠关键点比例。完整录制矩阵与默认门槛见 `docs/REAL_VIDEO_ACCEPTANCE.md`。
