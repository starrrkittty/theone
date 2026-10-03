import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Download, Flag, RefreshCw } from 'lucide-react';
import { API_BASE_URL } from '../config';
import type { FormCorrectionResponse } from '../hooks/usePoseStream';
import { CountingEvidencePanel } from './CountingEvidencePanel';

type Segment = {
  exercise: string; repetitions: number; partial_repetitions: number; frames: number;
  hold_seconds?: number;
  agent_error?: string;
  analysis?: { cues?: { text: string; rationale: string }[]; safety_messages?: string[]; limitations?: string[] };
};
type CompletedSet = {
  set_id: string; status: string; retained_frames: number; dropped_frames: number;
  rejected_frames: number; segments: Segment[]; agent_error?: string;
};
const names: Record<string, string> = { squat: '深蹲', pushup: '俯卧撑', plank: '平板支撑', bicep_curl: '弯举', alternate_bicep_curl: '交替弯举' };

export function CompletedSetPanel({ response, processing, configured }: {
  response: FormCorrectionResponse | null; processing: boolean; configured: boolean;
}) {
  const [rememberedSessionId, setRememberedSessionId] = useState<string>();
  const sessionId = response?.action_report?.session_id ?? rememberedSessionId;
  const [result, setResult] = useState<CompletedSet | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [autoFinish, setAutoFinish] = useState(true);
  const [autoSplit, setAutoSplit] = useState(true);
  const [history, setHistory] = useState<CompletedSet[]>([]);
  const lastSplitAttempt = useRef(0);
  const previousRep = useRef(0);
  const [frames, setFrames] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const wasProcessing = useRef(processing);
  const session = useRef(sessionId);
  session.current = sessionId;
  useEffect(() => {
    if (response?.capture) setFrames(response.capture.frames);
    if (response?.action_report?.session_id) setRememberedSessionId(response.action_report.session_id);
  }, [response?.capture, response?.action_report?.session_id]);
  useEffect(() => { controller.current?.abort(); controller.current = null; setBusy(false); setResult(null); setHistory([]); setError(''); }, [sessionId]);
  useEffect(() => () => controller.current?.abort(), []);

  const analyze = useCallback(async (retry = false) => {
    if (!sessionId || controller.current) return;
    const request = new AbortController();
    controller.current = request;
    setBusy(true); setError('');
    try {
      const reply = await fetch(`${API_BASE_URL}/api/agent-a/sessions/${encodeURIComponent(sessionId)}/${retry ? 'review-set' : 'finish-set'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: request.signal,
        body: JSON.stringify({ include_agents: configured }),
      });
      const data = await reply.json();
      if (!reply.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '整组分析失败');
      if (session.current !== sessionId || request.signal.aborted) return;
      setResult(data);
      setHistory(previous=>[...previous.filter(item=>item.set_id!==data.set_id),data].slice(-20));
      if (!retry) setFrames(0);
    } catch (failure) {
      if (!request.signal.aborted) setError(failure instanceof Error ? failure.message : '分析失败');
    } finally {
      if (controller.current === request) { controller.current = null; setBusy(false); }
    }
  }, [configured, sessionId]);

  useEffect(() => {
    const stopped = wasProcessing.current && !processing;
    wasProcessing.current = processing;
    if (stopped && autoFinish && frames > 0) void analyze();
  }, [processing, autoFinish, frames, analyze]);

  useEffect(() => {
    const repetitions=response?.action_report?.repetition??0;
    const completedRep=repetitions>previousRep.current;
    previousRep.current=repetitions;
    const hold=response?.action_report?.recognized_exercise==='plank';
    if (processing && autoSplit && frames >= 1800 && (completedRep||hold||frames>=2250) && !busy && performance.now()-lastSplitAttempt.current > 10000) {
      lastSplitAttempt.current=performance.now();
      void analyze();
    }
  },[processing,autoSplit,frames,busy,analyze,response]);

  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `fitness-set-${result.set_id}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <section className="border-t border-gray-700 py-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold flex items-center gap-2"><Bot size={18} />整组分析</h2>
      <span className="text-xs text-gray-400">{frames} 帧待分析</span>
    </div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={autoFinish} onChange={event => setAutoFinish(event.target.checked)} />停止采集后分析</label>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={autoSplit} onChange={event => setAutoSplit(event.target.checked)} />长时间采集自动分段</label>
    {autoSplit&&<p className="text-xs text-amber-200">分段优先等待一次动作完成；缓冲区接近上限时可能截断动作，完整次数不包含截断部分。</p>}
    {history.length>0&&<p className="text-xs text-gray-400">本次保留最近 {history.length} 段 · {history.reduce((sum,item)=>sum+item.retained_frames,0)} 帧</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={busy || !sessionId || frames === 0} onClick={() => void analyze()} className="flex items-center gap-2 bg-emerald-700 px-3 py-2 rounded-md text-sm disabled:opacity-40"><Flag size={16} />{busy ? '整组处理中' : '结束本组并分析'}</button>
      <button type="button" disabled={busy || !configured || !result} onClick={() => void analyze(true)} title="重新请求专家评审" aria-label="重新请求专家评审" className="p-2 border border-gray-600 rounded-md disabled:opacity-40"><RefreshCw size={16} /></button>
      <button type="button" disabled={!result} onClick={download} title="下载整组报告" aria-label="下载整组报告" className="p-2 border border-gray-600 rounded-md disabled:opacity-40"><Download size={16} /></button>
    </div>
    {!configured && <p className="text-xs text-amber-200">本地分析可用；专家评价等待模型配置。</p>}
    {error && <p role="alert" className="text-sm text-red-300 break-words">{error}</p>}
    <CountingEvidencePanel result={result}/>
    {result && <div className="space-y-3">
      <p className="text-xs text-gray-400">已分析 {result.retained_frames} 帧 · {result.segments.length} 个动作片段</p>
      {(result.dropped_frames > 0 || result.rejected_frames > 0) && <p className="text-xs text-amber-200">采集不完整：丢弃 {result.dropped_frames} 帧，拒收 {result.rejected_frames} 帧。</p>}
      {result.status === 'awaiting_evidence' && <p className="text-sm text-amber-200">本组没有足够证据确认动作。</p>}
      {result.agent_error && <p className="text-xs text-amber-200">{result.agent_error}</p>}
      {result.segments.map((segment, index) => <div key={index} className="border-t border-gray-700 pt-3 space-y-2 text-sm break-words">
        <p className="font-medium">{names[segment.exercise] || segment.exercise} · {segment.exercise === 'plank' ? `${(segment.hold_seconds || 0).toFixed(1)} 秒` : `${segment.repetitions} 次`} · 未计入完整次数 {segment.partial_repetitions}</p>
        {segment.agent_error && <p className="text-amber-200">{segment.agent_error}</p>}
        {segment.analysis?.safety_messages?.map((text, i) => <p key={`s${i}`} className="text-red-300">{text}</p>)}
        {segment.analysis?.cues?.map((cue, i) => <div key={i}><p>{cue.text}</p><p className="text-xs text-gray-400">{cue.rationale}</p></div>)}
        {segment.analysis?.limitations?.map((text, i) => <p key={`l${i}`} className="text-xs text-amber-200">{text}</p>)}
      </div>)}
      <details><summary className="text-xs text-gray-400 cursor-pointer">完整整组报告</summary><pre className="text-xs whitespace-pre-wrap break-all max-h-72 overflow-auto mt-2">{JSON.stringify(result, null, 2)}</pre></details>
    </div>}
  </section>;
}
