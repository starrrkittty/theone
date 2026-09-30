```markdown
# Agent 部分 TODO List
## 一、A 组：运动感知与数据底座

### 必须做
- [ ] 姿态识别
- [ ] 多人检测
- [ ] 自动运动类型识别
- [ ] 动作阶段识别（下蹲/起身/顶点/底部）
- [ ] URDF 读取 → 关节角度、动作计数
- [ ] 关键点置信度
- [ ] 身体遮挡检测
- [ ] 输出结构化动作报告（JSON）

### A 的输出接口（给 B）
```json
{
  "detected_exercise": "squat",
  "confidence": 0.92,
  "phase": "bottom",
  "rep_count": 8,
  "joint_angles": {},
  "issues": [],
  "overall_score": 76,
  "occlusion": false,
  "keypoint_confidence": 0.91
}
```
---

## 二、B 组：智能教练、阶段规划与饮食规划

### 必须做
- [ ] Agent Router（任务分发）
- [ ] 专项 Agent（部分）
- [ ] 实时动作指导（主动说话）
- [ ] 一个阶段计划模板
- [ ] 训练总结
- [ ] 一份基础饮食建议
- [ ] 一个安全提醒

### B 的输入
- [ ] 用户画像（来自 App/D）
- [ ] A 的动作结构化数据
- [ ] 训练历史
- [ ] 当前阶段模板

### B 的输出
- [ ] 实时指导话术
- [ ] 训练计划（周/日）
- [ ] 训练总结
- [ ] 饮食建议
- [ ] 安全提醒


