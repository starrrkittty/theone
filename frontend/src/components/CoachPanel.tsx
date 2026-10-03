import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, RefreshCw, Send, Download, ExternalLink } from 'lucide-react';
import { API_BASE_URL } from '../config';
import type { ActionReport, FormCorrectionResponse } from '../hooks/usePoseStream';
import { CompletedSetPanel } from './CompletedSetPanel';

type Analysis = {
  status: string;
  cues?: { text: string; rationale: string }[];
  safety_messages?: string[];
  limitations?: string[];
  agent?: { model_called?: boolean; specialist?: string; model?: string };
};
type Result = { status: string; message?: string; analysis?: Analysis; normalized_movement?: unknown; perception_review?: unknown };

export function CoachPanel({ response, processing, voiceEnabled }: { response: FormCorrectionResponse | null; processing: boolean; voiceEnabled: boolean }) {
  const report = response?.action_report;
  const [configured, setConfigured] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const pending = useRef<AbortController | null>(null);
  const active = useRef<ActionReport | undefined>(report);
  const lastRequest = useRef(0);
  active.current = report;

  const refresh = useCallback(async () => {
    try {
      const reply = await fetch(`${API_BASE_URL}/api/status`);
      const status = await reply.json();
      if (!reply.ok) throw new Error(status.detail || '读取模型配置失败');
      setConfigured(Boolean(status.configured));
    } catch (failure) { setError(failure instanceof Error ? failure.message : '连接失败'); }
  }, []);
  useEffect(() => { void refresh(); const timer = setInterval(refresh, 15000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => { pending.current?.abort(); setResult(null); setError(''); }, [report?.session_id, report?.recognized_exercise]);

  const requestCoach = useCallback(async (sample: ActionReport) => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    lastRequest.current = performance.now();
    setBusy(true); setError('');
    try {
      const reply = await fetch(`${API_BASE_URL}/api/agent-a/coach`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ action_report: sample, form_confidence: response?.form_confidence }),
      });
      const data = await reply.json();
      if (!reply.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '专家调用失败');
      if (active.current?.session_id !== sample.session_id || active.current?.recognized_exercise !== sample.recognized_exercise) return;
      setResult(data);
      const analysis: Analysis | undefined = data.analysis;
      const text = [...(analysis?.safety_messages || []), ...(analysis?.cues?.slice(0, 2).map(cue => cue.text) || [])].join('。');
      if (voiceEnabled && text && data.status === 'completed' && data.feedback_scope !== 'historical' && Date.now()-sample.timestamp_ms <= 15000 && 'speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance(text); utterance.lang = 'zh-CN';
        window.speechSynthesis.speak(utterance);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '请求失败');
    } finally {
      if (pending.current === controller) { pending.current = null; setBusy(false); }
    }
  }, [response?.form_confidence, voiceEnabled]);

  useEffect(() => {
    if (!processing || !enabled || !configured || !report || report.recognition_status !== 'confirmed') return;
    if (report.perception_agent && !report.perception_agent.handoff_allowed) return;
    if (lastRequest.current && performance.now() - lastRequest.current < 20000) return;
    if (!report.agent_context.should_coach_now && result) return;
    void requestCoach(report);
  }, [report, processing, enabled, configured, result, requestCoach]);

  const download = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify({ action_report: report, form_confidence: response?.form_confidence }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'agent-a-report.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <><CompletedSetPanel response={response} processing={processing} configured={configured} />
    <details><summary className="text-sm text-gray-400 cursor-pointer">即时指导（可选）</summary>
    <section className="py-4 space-y-3">
    <div className="flex items-center justify-between gap-2">
      <h2 className="font-semibold flex gap-2 items-center"><Bot size={18} />B 组 AI 私教</h2>
      <button type="button" title="刷新模型配置" aria-label="刷新模型配置" onClick={refresh}><RefreshCw size={16} /></button>
    </div>
    <p className="text-xs text-gray-400">{configured ? '模型已配置' : '等待 coach/config.json 中的 API Key'}</p>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} disabled={!configured} />自动指导</label>
    <div className="flex flex-wrap gap-2">
      <button type="button" className="flex items-center gap-2 bg-emerald-700 px-3 py-2 rounded-md text-sm disabled:opacity-40" disabled={busy || report?.recognition_status !== 'confirmed'} onClick={() => report && void requestCoach(report)}><Send size={15} />{busy ? '专家处理中' : '请求专家指导'}</button>
      <button type="button" title="下载 A 组原始报告" aria-label="下载 A 组原始报告" onClick={download} disabled={!report} className="p-2 border border-gray-600 rounded-md"><Download size={16} /></button>
      <a href={`${API_BASE_URL}/coach`} target="_blank" rel="noreferrer" onClick={() => { if (report) localStorage.setItem('fitness-agent-a-handoff', JSON.stringify({ action_report: report, form_confidence: response?.form_confidence })); }} className="flex items-center gap-2 text-sm text-emerald-300"><ExternalLink size={15} />带入 B 工作台</a>
    </div>
    {!report || report.recognition_status !== 'confirmed' ? <p className="text-xs text-gray-400">等待动作识别确认</p> : null}
    {error && <p role="alert" className="text-sm text-red-300 break-words">{error}</p>}
    {result?.message && <p className="text-sm text-amber-200">{result.message}</p>}
    {result?.analysis && <div className="space-y-2 text-sm break-words">
      <p className="text-gray-400">{result.analysis.agent?.specialist} · {result.analysis.status === 'limited' ? '观测有限' : result.analysis.status}</p>
      {result.analysis.safety_messages?.map((text, index) => <p key={`s${index}`} className="text-red-300">{text}</p>)}
      {result.analysis.cues?.map((cue, index) => <div key={index}><p>{cue.text}</p><p className="text-xs text-gray-400">{cue.rationale}</p></div>)}
      {result.analysis.limitations?.map((text, index) => <p key={`l${index}`} className="text-xs text-amber-200">{text}</p>)}
    </div>}
    {result && <details><summary className="text-xs text-gray-400 cursor-pointer">完整专家结果</summary><pre className="text-xs whitespace-pre-wrap break-all max-h-72 overflow-auto mt-2">{JSON.stringify(result, null, 2)}</pre></details>}
  </section></details></>;
}
