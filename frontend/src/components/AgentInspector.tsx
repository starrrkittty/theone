import {
  BrainCircuit,
  Download,
  Gauge,
  RefreshCw,
  Route,
  Volume2,
  VolumeX,
  Users,
  ScanSearch,
} from 'lucide-react';

import type {
  FormCorrectionResponse,
  RecognitionEvent,
} from '../hooks/usePoseStream';
import type { PoseTrackingInfo } from '../pose';
import {
  EVALUATION_EXERCISES,
  type AgentTelemetry,
  type EvaluationExercise,
  summarizeAgentTelemetry,
} from '../agent/telemetry';

interface AgentInspectorProps {
  response: FormCorrectionResponse | null;
  telemetry: AgentTelemetry;
  poseTracking: PoseTrackingInfo | null;
  clientProbabilities: Record<string, number> | null;
  expectedExercise: EvaluationExercise | null;
  recognitionHistory: RecognitionEvent[];
  voiceEnabled: boolean;
  onExpectedExerciseChange: (value: EvaluationExercise | null) => void;
  onVoiceEnabledChange: (value: boolean) => void;
  onResetTelemetry: () => void;
}

const DISPLAY_NAMES: Record<string, string> = {
  squat: '深蹲',
  pushup: '俯卧撑',
  plank: '前臂平板支撑',
  bicep_curl: '哑铃弯举',
  alternate_bicep_curl: '交替哑铃弯举',
  unknown: '尚未确认',
};

const RAW_MODEL_LABEL_NAMES: Record<string, string> = {
  'curl-stand': '站姿双臂弯举',
  'curl-seat': '坐姿双臂弯举',
  'alt-stand': '站姿交替弯举',
  'alt-seat': '坐姿交替弯举',
};

const MODEL_SCOPE_NAMES: Record<string, string> = {
  curl_only: '仅弯举变体（不能单独判定运动类型）',
  general: '通用动作分类',
};

const REJECTION_NAMES: Record<string, string> = {
  invalid_landmarks: '关键点数据格式无效',
  low_pose_quality: '关键点可见度或画面质量不足',
  no_supported_motion_match: '没有匹配到已支持运动',
  candidate_confidence_too_low: '候选运动置信度不足',
  stationary_non_plank: '人体基本静止，暂不确认运动',
};

const EXTERNAL_REASON_NAMES: Record<string, string> = {
  no_external_probabilities: '尚未获得 ST-GCN 概率',
  invalid_or_empty_probabilities: '外部概率为空或格式无效',
  external_predicted_unknown: '外部模型输出 unknown',
  below_confidence_or_margin_threshold: '置信度或候选差距不足',
  unsupported_mapped_label: '标签不在统一动作列表中',
  curl_model_requires_curl_candidate: '弯举模型被安全门控：规则尚未确认弯举',
  fused_with_candidate: '已与规则/HMM候选融合',
  supplied_missing_candidate: '外部通用模型补充了候选',
  high_confidence_override: '外部模型高置信覆盖低置信候选',
  disagreed_without_override: '外部模型与规则不同，未达到覆盖条件',
  pending: '正在判断是否采用',
};

function percent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function statusStyle(status: string): string {
  if (status === 'confirmed') return 'bg-green-500/20 text-green-300 border-green-500/40';
  if (status === 'candidate') return 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
  return 'bg-gray-700 text-gray-300 border-gray-600';
}

export function AgentInspector({
  response,
  telemetry,
  poseTracking,
  clientProbabilities,
  expectedExercise,
  recognitionHistory,
  voiceEnabled,
  onExpectedExerciseChange,
  onVoiceEnabledChange,
  onResetTelemetry,
}: AgentInspectorProps) {
  const report = response?.action_report;
  const summary = summarizeAgentTelemetry(telemetry);
  const candidate = report?.candidate_exercises[0];
  const debug = response?.recognition_debug;
  const external = debug?.external;
  const inferredModelScope = external?.scope
    ?? (clientProbabilities && Object.keys(clientProbabilities).every((label) => label in RAW_MODEL_LABEL_NAMES)
      ? 'curl_only'
      : clientProbabilities
      ? 'general'
      : null);

  const exportTelemetry = () => {
    const payload = {
      exported_at: new Date().toISOString(),
      expected_exercise: expectedExercise,
      telemetry,
      summary,
      recognition_history: recognitionHistory,
      latest_action_report: report ?? null,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `agent-a-evaluation-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <section className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="flex items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <BrainCircuit className="w-5 h-5 text-cyan-400" />
            <h3 className="font-semibold">Agent A 实时状态</h3>
          </div>
          <button
            type="button"
            onClick={() => onVoiceEnabledChange(!voiceEnabled)}
            className="flex items-center gap-1.5 rounded-lg bg-gray-700 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-600"
            title="识别确认后是否自动播报"
          >
            {voiceEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            {voiceEnabled ? '播报开启' : '播报关闭'}
          </button>
        </div>

        <div className="flex items-center justify-between mb-4">
          <span className={`border rounded-full px-3 py-1 text-xs font-medium ${statusStyle(report?.recognition_status ?? 'unknown')}`}>
            {report?.recognition_status === 'confirmed'
              ? '已确认'
              : report?.recognition_status === 'candidate'
              ? '候选确认中'
              : '扫描中'}
          </span>
          <span className="font-mono text-sm text-cyan-300">
            {percent(report?.recognition_confidence ?? 0)}
          </span>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-gray-500">识别运动</dt>
            <dd className="mt-0.5 text-gray-100">
              {DISPLAY_NAMES[report?.recognized_exercise ?? 'unknown'] ?? report?.recognized_exercise}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">候选运动</dt>
            <dd className="mt-0.5 text-gray-100">
              {candidate
                ? `${DISPLAY_NAMES[candidate.exercise] ?? candidate.exercise} ${percent(candidate.confidence)}`
                : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">专项 Agent</dt>
            <dd className="mt-0.5 text-gray-100 break-all">{report?.specialist ?? '尚未路由'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">证据来源</dt>
            <dd className="mt-0.5 text-gray-100">{response?.exercise_source ?? candidate?.source ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">画面质量</dt>
            <dd className="mt-0.5 text-gray-100">{report?.pose_quality ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">估计机位</dt>
            <dd className="mt-0.5 text-gray-100">{report?.camera_view ?? response?.camera_view ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">画面人数</dt>
            <dd className="mt-0.5 text-gray-100">
              {poseTracking ? `${poseTracking.personCount} 人` : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">主体锁定</dt>
            <dd className={poseTracking?.subjectLocked ? 'mt-0.5 text-green-300' : 'mt-0.5 text-yellow-300'}>
              {poseTracking ? poseTracking.subjectLocked ? '已锁定' : '存在歧义，暂停上传' : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">指导优先级</dt>
            <dd className="mt-0.5 text-gray-100">{report?.agent_context.priority ?? 'none'}</dd>
          </div>
        </dl>

        {recognitionHistory[0] && (
          <div className="mt-4 rounded-lg bg-cyan-500/10 border border-cyan-500/30 p-3 text-sm text-cyan-100">
            {recognitionHistory[0].message}
          </div>
        )}

        {poseTracking?.warning && (
          <div className={`mt-3 rounded-lg border p-3 text-sm ${poseTracking.subjectLocked
            ? 'bg-blue-500/10 border-blue-500/30 text-blue-100'
            : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-100'}`}>
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4" />
              {poseTracking.warning}
            </div>
          </div>
        )}
      </section>

      <section className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="flex items-center gap-2 mb-3">
          <ScanSearch className="w-5 h-5 text-amber-400" />
          <h3 className="font-semibold">识别证据与拒识原因</h3>
        </div>

        <div className="grid grid-cols-2 gap-2 text-sm mb-3">
          <Metric
            label="规则/HMM候选"
            value={debug?.candidate
              ? `${DISPLAY_NAMES[debug.candidate] ?? debug.candidate} ${percent(debug.candidate_confidence)}`
              : '无'}
          />
          <Metric
            label="最终拒识原因"
            value={debug?.rejection_reason
              ? REJECTION_NAMES[debug.rejection_reason] ?? debug.rejection_reason
              : '无'}
          />
          <Metric
            label="ST-GCN原始Top-1"
            value={external?.raw_top1
              ? `${RAW_MODEL_LABEL_NAMES[external.raw_top1] ?? external.raw_top1} ${percent(external.confidence ?? 0)}`
              : '—'}
          />
          <Metric
            label="映射后标签"
            value={external?.mapped_top1
              ? DISPLAY_NAMES[external.mapped_top1] ?? external.mapped_top1
              : '—'}
          />
          <Metric
            label="当前模型覆盖范围"
            value={inferredModelScope
              ? MODEL_SCOPE_NAMES[inferredModelScope] ?? inferredModelScope
              : '尚未加载输出'}
          />
          <Metric
            label="模型证据是否采用"
            value={external?.received
              ? external.accepted ? '已采用' : '未采用'
              : '等待30帧窗口'}
          />
        </div>

        <div className="space-y-2">
          {Object.entries(clientProbabilities ?? {}).map(([label, probability]) => (
            <div key={label}>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>{RAW_MODEL_LABEL_NAMES[label] ?? DISPLAY_NAMES[label] ?? label}</span>
                <span className="font-mono">{percent(probability)}</span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-900 overflow-hidden">
                <div
                  className="h-full rounded-full bg-cyan-500 transition-all"
                  style={{ width: `${Math.max(0, Math.min(1, probability)) * 100}%` }}
                />
              </div>
            </div>
          ))}
          {!clientProbabilities && (
            <div className="text-xs text-gray-500">收集满30帧后显示 ST-GCN 输出概率。</div>
          )}
        </div>

        <div className={`mt-3 rounded-lg border p-3 text-xs ${external?.accepted
          ? 'bg-green-500/10 border-green-500/30 text-green-200'
          : 'bg-gray-900/70 border-gray-700 text-gray-400'}`}>
          {EXTERNAL_REASON_NAMES[external?.reason ?? 'no_external_probabilities']
            ?? external?.reason
            ?? '尚无外部模型信息'}
        </div>
      </section>

      <section className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="flex items-center gap-2 mb-3">
          <Gauge className="w-5 h-5 text-violet-400" />
          <h3 className="font-semibold">开发者评测模式</h3>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          只在测试视频时填写真实动作，用于计算识别准确率；正式用户不需要选择运动。
        </p>

        <label className="block text-xs text-gray-400 mb-1" htmlFor="expected-exercise">
          测试视频真实动作（Ground Truth）
        </label>
        <select
          id="expected-exercise"
          value={expectedExercise ?? ''}
          onChange={(event) => onExpectedExerciseChange(
            event.target.value ? event.target.value as EvaluationExercise : null,
          )}
          className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
        >
          <option value="">不标注，只看运行数据</option>
          {EVALUATION_EXERCISES.map((exercise) => (
            <option key={exercise} value={exercise}>
              {DISPLAY_NAMES[exercise]} ({exercise})
            </option>
          ))}
        </select>

        <div className="grid grid-cols-2 gap-2 mt-4 text-sm">
          <Metric label="处理帧数" value={String(telemetry.frames)} />
          <Metric
            label="首次确认"
            value={summary.firstConfirmedLatencyMs === null
              ? '—'
              : `${summary.firstConfirmedLatencyMs.toFixed(0)} ms`}
          />
          <Metric label="确认准确率" value={percent(summary.confirmedAccuracy)} />
          <Metric label="未知帧率" value={percent(summary.unknownRate)} />
          <Metric label="平均识别置信度" value={percent(summary.averageRecognitionConfidence)} />
          <Metric label="不可靠画面率" value={percent(summary.unreliableRate)} />
          <Metric label="识别事件" value={String(telemetry.recognitionEvents)} />
          <Metric label="误识别帧 / 切换数" value={`${telemetry.incorrectConfirmedFrames}/${telemetry.exerciseSwitches}`} />
        </div>

        <div className="flex gap-2 mt-4">
          <button
            type="button"
            onClick={onResetTelemetry}
            className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-gray-700 px-3 py-2 text-xs hover:bg-gray-600"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            重置
          </button>
          <button
            type="button"
            onClick={exportTelemetry}
            disabled={telemetry.frames === 0}
            className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs hover:bg-violet-500 disabled:bg-gray-700 disabled:text-gray-500"
          >
            <Download className="w-3.5 h-3.5" />
            导出 JSON
          </button>
        </div>

        <div className="mt-3 flex items-start gap-2 text-xs text-gray-500">
          <Route className="w-4 h-4 shrink-0" />
          在线统计只能衡量当前视频；正式能力结论需要多人、多光照、多机位的标注回放集。
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-900/70 p-2.5">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 font-mono text-gray-100">{value}</div>
    </div>
  );
}
