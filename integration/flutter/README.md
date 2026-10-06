# Flutter 侧接入材料

`agent_coach_client.dart` 是独立的 Dart HTTP 客户端。APP 源码后来已克隆到同一工作区的 `AI_trainer`，实际接入实现位于其中的 `lib/features/product/data/agent_coach_repository.dart`、`ProductController` 和相关页面。本目录保留独立客户端作为契约参考；当前 APP 不直接导入此文件。

接入顺序：

1. APP 开发构建中创建客户端：`AgentCoachClient(baseUrl: Uri.parse('http://127.0.0.1:8803/api/app/v1/'))`。模拟器/USB 真机先执行 `adb reverse tcp:8803 tcp:8803`。生产构建使用 HTTPS 与正式身份鉴权。
2. 网络 `CoachRepository` 调用 `fetchPlan` 和 `fetchNutrition`，将返回 Map 映射到当前 `TrainingPlan`/`NutritionAdvice` 对象。`fetchPlan` 发送设备本地日期并利用已完成训练日产生当日/本周休息安排。`source` 按真实值展示；`template` 的休息安排或饮食限制提示不得伪称 AI 生成。
3. `fetchPlan` 在本机不适字段为 true 时抛出 `LOCAL_TRAINING_PAUSED`，APP 应显示本地暂停安排。`projectProfile` 不发送该字段。
4. `TrainingPlanItem` 增加 `exercise_id` 并传给 `TrainingLaunchArgs`。在 APP 确实支持俯卧撑入口前，保留默认 `executableExercises=['squat']`。
5. 保存原始 `SessionResult` 后，用持久安装 UUID 和本次训练调用 `fetchSummary`，把响应作为独立总结附加对象按 `session_id` 保存。取消/中断不能计入完成统计。历史参数排除当前 session。
6. `AgentCoachException` 的 code/retryable 映射到现有模板降级与稍后重试，不要把模型 Key 放进 APK。APP 当前控制器会同时回退计划与饮食，可改为各自降级。
7. 用户清除云端数据时调用 `deleteCachedSummaries`，并单独删除 APP 本地记录。
8. 首页或记录页需要周回顾时调用 `fetchWeeklyProgress`；返回完成训练日、总时长、端侧次数和保守下一步建议。`source=template` 表示模型未配置或不可用时的规则回顾。APP 仍使用自己的本地完成次数和连续天数作为主统计来源。

示例对象与完整错误码见 `../../docs/contracts/app_coach_v1_examples.json`、`../../docs/contracts/app_coach_v1.md`。没有 Dart/Flutter SDK 或 APP 项目可用于此文件的编译与真机验证；服务端接口的契约测试见 `backend/tests/test_app_mobile_contract.py`。
