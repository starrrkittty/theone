import {
  BrainCircuit,
  Download,
  Gauge,
  RefreshCw,
  Route,
  Volume2,
  VolumeX,
} from 'lucide-react';

import type {
  FormCorrectionResponse,
  RecognitionEvent,
} from '../hooks/usePoseStream';
import {
  EVALUATION_EXERCISES,
  type AgentTelemetry,
  type EvaluationExercise,
  summarizeAgentTelemetry,
} from '../agent/telemetry';

interface AgentInspectorProps {
  response: FormCorrectionResponse | null;
  telemetry: AgentTelemetry;
  expectedExercise: EvaluationExercise | null;
  recognitionHistory: RecognitionEvent[];
  voiceEnabled: boolean;
  onExpectedExerciseChange: (value: EvaluationExercise | null) => void;
  onVoiceEnabledChange: (value: boolean) => void;
  onResetTelemetry: () => void;
  recording: boolean;
  onRecordingChange: (value:boolean) => void;
  getRecording: () => object;
}

const DISPLAY_NAMES: Record<string, string> = {
  squat: '深蹲',
  pushup: '俯卧撑',
  plank: '前臂平板支撑',
  bicep_curl: '哑铃弯举',
  alternate_bicep_curl: '交替哑铃弯举',
  unknown: '尚未确认',
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
  expectedExercise,
  recognitionHistory,
  voiceEnabled,
  onExpectedExerciseChange,
  onVoiceEnabledChange,
  onResetTelemetry,
  recording,
  onRecordingChange,
  getRecording,
}: AgentInspectorProps) {
  const report = response?.action_report;
  const summary = summarizeAgentTelemetry(telemetry);
  const candidate = report?.candidate_exercises[0];

  const exportTelemetry = () => {
    const payload = {
      ...getRecording(),
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
            <dt className="text-gray-500">指导优先级</dt>
            <dd className="mt-0.5 text-gray-100">{report?.agent_context.priority ?? 'none'}</dd>
          </div>
        </dl>

        {recognitionHistory[0] && (
          <div className="mt-4 rounded-lg bg-cyan-500/10 border border-cyan-500/30 p-3 text-sm text-cyan-100">
            {recognitionHistory[0].message}
          </div>
        )}
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
              {exercise === 'unknown' ? '静止 / 非支持动作（负样本）' : DISPLAY_NAMES[exercise]} ({exercise})
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
          <Metric label="已确认帧正确率" value={percent(summary.confirmedAccuracy)} />
          <Metric label="全帧识别正确率" value={percent(summary.overallAccuracy)} />
          <Metric label="识别覆盖率" value={percent(summary.recognitionCoverage)} />
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
        <label className="flex gap-2 items-center mt-3 text-sm"><input type="checkbox" checked={recording} onChange={event => onRecordingChange(event.target.checked)} />采集评测关键点</label>
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
