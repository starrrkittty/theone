import { useEffect, useRef, useState } from 'react';
import { BrainCircuit, Download, RefreshCw, ScanLine } from 'lucide-react';
import type { ActionReport, FormCorrectionResponse } from '../hooks/usePoseStream';
import { API_BASE_URL } from '../config';

type Review = { status: string; action_report: ActionReport; perception_agent: NonNullable<ActionReport['perception_agent']> };
const REQUESTS: Record<string, string> = {none: '无需补充观测', show_full_body: '请让肩、髋与相关肢体完整入镜', side_view: '请调整为侧面机位', continue_motion: '请继续完成动作'};
const DECISIONS: Record<string, string> = {observe: '继续观察', request_view: '调整机位', handoff: '可交给专家'};

export function PerceptionPanel({ response }: { response: FormCorrectionResponse | null }) {
  const report = response?.action_report;
  const session = report?.session_id;
  const [configured, setConfigured] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [review, setReview] = useState<Review | null>(null);
  const pending = useRef<AbortController | null>(null);
  const latest = useRef(report); latest.current = report;
  const refresh = async () => {
    try {
      const reply = await fetch(`${API_BASE_URL}/api/agent-a/status`);
      const data = await reply.json();
      if (!reply.ok) throw new Error(data.detail || '无法读取 A Agent 状态');
      setConfigured(Boolean(data.model.configured)); setError('');
    } catch (failure) { setError(failure instanceof Error ? failure.message : '连接失败'); }
  };
  useEffect(() => { void refresh(); return () => pending.current?.abort(); }, []);
  useEffect(() => { pending.current?.abort(); pending.current = null; setBusy(false); setReview(null); setError(''); }, [session, report?.recognized_exercise]);
  const inspect = async () => {
    if (!session || pending.current) return;
    const stamp = report?.timestamp_ms;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError('');
    try {
      const reply = await fetch(`${API_BASE_URL}/api/agent-a/sessions/${encodeURIComponent(session)}/review`, {method:'POST', signal:controller.signal});
      const data = await reply.json();
      if (!reply.ok) throw new Error(data.detail || 'A Agent 审查失败');
      if (latest.current?.session_id === session && latest.current.timestamp_ms >= (stamp || 0)) setReview(data);
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '请求失败'); }
    finally { if (pending.current === controller) { pending.current = null; setBusy(false); } }
  };
  const download = (value: unknown, filename: string) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const kin = report?.kinematics;
  const downloadFull = async () => {
    if(!session)return;
    try{
      const reply=await fetch(`${API_BASE_URL}/api/agent-a/sessions/${encodeURIComponent(session)}?historical=true`);
      const data=await reply.json();
      if(!reply.ok)throw Error(data.detail||'完整观测导出失败');
      download(data.action_report,'perception-report.json');
    }catch(e){setError(e instanceof Error?e.message:'完整观测导出失败');}
  };
  const policy = report?.perception_agent;
  const reviewFresh = review && review.status === 'completed' && report && Math.abs(report.timestamp_ms-review.action_report.timestamp_ms) <= 15000;
  const stats = review?.perception_agent.optimization as {model_calls?: number; input_chars_total?: number; latency_ms?: number; usage_total?: {total_tokens?: number}} | undefined;
  return <section className="border-t border-gray-700 pt-4 space-y-3">
    <div className="flex items-center justify-between gap-2"><h2 className="font-semibold flex items-center gap-2"><ScanLine size={18}/>A 感知 Agent</h2><button type="button" title="刷新 API 状态" aria-label="刷新 API 状态" onClick={() => void refresh()}><RefreshCw size={16}/></button></div>
    <div className="text-xs text-gray-400 flex flex-wrap gap-x-4 gap-y-1"><span>{configured ? '模型已配置' : '模型待配置'}</span><span>{kin?.parser || '等待骨架'}</span></div>
    <p className="text-sm">{policy ? DECISIONS[policy.decision] || policy.decision : '等待实时观测'}</p>
    {policy && policy.observation_request !== 'none' && <p className="text-sm text-amber-200">{REQUESTS[policy.observation_request]}</p>}
    {kin?.joint_states && <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead className="text-gray-400"><tr><th className="py-2">关节</th><th>弯曲代理值 / rad</th><th>可见度</th></tr></thead><tbody>{Object.entries(kin.joint_states).map(([name, value]) => <tr key={name} className="border-t border-gray-700"><td className="py-2">{name.replace('_joint','')}</td><td>{value.position_rad.toFixed(3)}</td><td>{Math.round(value.visibility*100)}%</td></tr>)}</tbody></table></div>}
    {kin?.status === 'available' && <p className="text-xs text-amber-200">{kin.coordinate_units === 'estimated_meters' ? '三维米制估计 · 未经标定' : '图像归一化骨架 · 非米制尺度'} · 肘膝为弯曲代理值</p>}
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" disabled={!configured || !session || busy} onClick={() => void inspect()} className="flex items-center gap-2 text-sm bg-emerald-700 px-3 py-2 rounded-md disabled:opacity-40"><BrainCircuit size={16}/>{busy ? 'A Agent 审查中' : '审查运动证据'}</button>
      <button type="button" title="下载完整骨架和动作 JSON" aria-label="下载完整骨架和动作 JSON" disabled={!report} onClick={() => void downloadFull()} className="p-2 border border-gray-600 rounded-md"><Download size={16}/></button>
      {session && kin?.status === 'available' && <a href={`${API_BASE_URL}/api/agent-a/sessions/${encodeURIComponent(session)}/urdf`} className="text-sm text-emerald-300">URDF ↓</a>}
    </div>
    {error && <p role="alert" className="text-sm text-red-300 break-words">{error}</p>}
    {stats && <div className="text-xs text-gray-400 flex flex-wrap gap-x-4 gap-y-1"><span>{review?.perception_agent.cache_hit ? '复用有效审查' : `${stats.model_calls ?? 0} 次模型调用`}</span><span>输入 {stats.input_chars_total ?? 0} 字符</span>{stats.usage_total?.total_tokens !== undefined && <span>{stats.usage_total.total_tokens} tokens</span>}{stats.latency_ms !== undefined && <span>{(stats.latency_ms/1000).toFixed(1)} 秒</span>}</div>}
    {review && <div className="text-sm space-y-2"><p className="text-gray-400">{reviewFresh ? '模型审查' : '历史审查'} · {DECISIONS[review.perception_agent.decision]}</p><p className="break-words">{review.perception_agent.reason}</p><button type="button" title="下载模型审查 JSON" aria-label="下载模型审查 JSON" onClick={() => download(review, 'agent-a-review.json')}><Download size={16}/></button><details><summary className="text-xs text-gray-400 cursor-pointer">工具调用记录</summary><pre className="text-xs whitespace-pre-wrap break-all max-h-64 overflow-auto mt-2">{JSON.stringify(review.perception_agent, null, 2)}</pre></details></div>}
    {report && <details><summary className="text-xs text-gray-400 cursor-pointer">骨架与关节状态</summary><pre className="text-xs whitespace-pre-wrap break-all max-h-64 overflow-auto mt-2">{JSON.stringify(kin, null, 2)}</pre></details>}
  </section>;
}
