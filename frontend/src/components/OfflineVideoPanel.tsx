import { useEffect, useRef, useState } from 'react';
import { Download, Play, Square, Upload } from 'lucide-react';
import { API_BASE_URL } from '../config';
import { captureFile, type Capture, type SamplingMode } from '../video/analyzeFile';
import type { PoseModel } from '../pose/PoseDetector';
import { POSE_CONNECTIONS } from '../pose/PoseDetector';
import { CountingEvidencePanel } from './CountingEvidencePanel';

export function OfflineVideoPanel({ onStart }: { onStart: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState<PoseModel>('full');
  const [fps, setFps] = useState(20), [start, setStart] = useState('0'), [end, setEnd] = useState('');
  const [busy, setBusy] = useState(false), [progress, setProgress] = useState('');
  const [error, setError] = useState(''), [capture, setCapture] = useState<Capture | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [agents, setAgents] = useState(false), [trace, setTrace] = useState(false);
  const [view,setView]=useState('auto');
  const [samplingMode,setSamplingMode]=useState<SamplingMode>('seek');
  const [preview, setPreview] = useState('');
  const overlay = useRef<HTMLCanvasElement>(null);
  const input = useRef<HTMLInputElement>(null), controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!file) {setPreview('');return;}
    const url=URL.createObjectURL(file);setPreview(url);
    return ()=>URL.revokeObjectURL(url);
  },[file]);
  const run = async (reuse=false) => {
    if (!file || controller.current) return;
    const request = new AbortController(); controller.current=request;
    setBusy(true); setError(''); setResult(null);
    onStart();
    if (!reuse) setCapture(null);
    try {
      setProgress(reuse?'使用已缓存骨架':'正在加载视频和姿态模型');
      let lastPreview=0;
      const data = reuse && capture ? capture : await captureFile(file,model,fps,Number(start),end.trim()?Number(end):null,request.signal,
        (done,total,points,video) => {
          const now=performance.now();
          if(done!==total&&now-lastPreview<100)return;
          lastPreview=now;
          setProgress(`骨架采样 ${done} / ${total}`);
          const canvas=overlay.current, ctx=canvas?.getContext('2d');
          if (!canvas||!ctx) return;
          canvas.width=640;canvas.height=Math.round(640*video.videoHeight/video.videoWidth);
          ctx.drawImage(video,0,0,canvas.width,canvas.height);ctx.strokeStyle='#25ef9e';ctx.lineWidth=3;
          for(const [a,b] of POSE_CONNECTIONS) {
            if (!points[a]||!points[b]||Math.min(points[a].visibility,points[b].visibility)<.5)continue;
            ctx.beginPath();ctx.moveTo(points[a].x*canvas.width,points[a].y*canvas.height);
            ctx.lineTo(points[b].x*canvas.width,points[b].y*canvas.height);ctx.stroke();
          }
          for(const point of points){
            if(point.visibility<.05)continue;
            ctx.fillStyle=point.visibility>=.5?'#25ef9e':'#fbbf24';
            ctx.beginPath();ctx.arc(point.x*canvas.width,point.y*canvas.height,3,0,2*Math.PI);ctx.fill();
          }
        },samplingMode);
      setCapture(data); setProgress(agents?'动作分析与专家评审中':'动作分析中');
      const reply = await fetch(`${API_BASE_URL}/api/agent-a/analyze-set`, {
        method:'POST', headers:{'Content-Type':'application/json'}, signal:request.signal,
        body:JSON.stringify({session_id:`file-${crypto.randomUUID()}`,frames:data.frames.map(frame=>({...frame,camera_view:view,capture_profile:'exercise_view_v1'})),
          include_agents:agents, include_trace:trace}),
      });
      const response = await reply.json();
      if (!reply.ok) throw new Error(typeof response.detail==='string'?response.detail:'分析请求失败');
      if (request.signal.aborted) return;
      setResult(response); setProgress('处理完成');
    } catch (failure) {
      setError(request.signal.aborted?'处理已取消':failure instanceof Error?failure.message:'处理失败');
    } finally { if (controller.current===request) {controller.current=null;setBusy(false);} }
  };
  const download = (data: unknown, name: string) => {
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const changeFile = (selected: File | null) => {setFile(selected);setCapture(null);setResult(null);setProgress('');setError('');};
  const loadDemo = async () => {
    if(controller.current)return;
    const request=new AbortController();controller.current=request;setBusy(true);setError('');
    try{
      const response=await fetch('/datasets/repcount-squat-demo.mp4',{signal:request.signal});
      if(!response.ok)throw Error('演示视频尚未准备好');
      changeFile(new File([await response.blob()],'repcount-squat-demo.mp4',{type:'video/mp4'}));
      setProgress('RepCount 官方压缩演示画面；无对应计数或姿势真值，不计入正式准确率');
    }catch(e){setError(request.signal.aborted?'已取消':e instanceof Error?e.message:'加载失败')}
    finally{controller.current=null;setBusy(false)}
  };
  return <section id="offline-video" className="border-t border-gray-700 mt-6 py-4 space-y-3">
    <h2 className="font-semibold">本地视频 · 离线分析</h2>
    <input ref={input} type="file" accept="video/*" className="hidden" onChange={e=>changeFile(e.target.files?.[0]??null)} />
    <div className="flex gap-3 items-center flex-wrap"><button disabled={busy} onClick={()=>input.current?.click()} className="flex gap-2 items-center border border-gray-600 rounded p-2 disabled:opacity-40"><Upload size={16}/>选择视频</button><button disabled={busy} onClick={()=>void loadDemo()} className="border border-gray-600 rounded p-2 disabled:opacity-40">RepCount 深蹲演示</button><span className="text-sm break-all">{file?.name??'未选择'}</span></div>
    {preview&&<div className="grid grid-cols-1 md:grid-cols-2 gap-4"><div><h3 className="text-sm mb-2">1. 原始画面</h3><video src={preview} controls muted playsInline className="w-full max-h-80 object-contain bg-black" /></div><div><h3 className="text-sm mb-2">2. 视频模型输出</h3><canvas ref={overlay} width="640" height="360" className="w-full max-h-80 object-contain bg-black" /></div></div>}
    <fieldset disabled={busy} className="flex gap-3 flex-wrap text-sm disabled:opacity-50">
      <label>姿态模型<select value={model} onChange={e=>{setModel(e.target.value as PoseModel);setCapture(null)}} className="block bg-gray-800 border border-gray-600 rounded p-2"><option value="lite">Lite</option><option value="full">Full</option><option value="heavy">Heavy</option></select></label>
      <label>采样帧率<select value={fps} onChange={e=>{setFps(Number(e.target.value));setCapture(null)}} className="block bg-gray-800 border border-gray-600 rounded p-2">{[5,10,20,30].map(n=><option key={n} value={n}>{n} FPS</option>)}</select></label>
      <label>视频采样<select value={samplingMode} onChange={e=>{setSamplingMode(e.target.value as SamplingMode);setCapture(null)}} className="block bg-gray-800 border border-gray-600 rounded p-2"><option value="sequential">顺序播放</option><option value="seek">固定时间逐帧跳转</option></select></label>
      <label>视频拍摄视角<select value={view} onChange={e=>setView(e.target.value)} className="block bg-gray-800 border border-gray-600 rounded p-2"><option value="auto">未声明</option><option value="front">正面</option><option value="side">侧面</option></select></label>
      <label>起点（秒）<input type="number" min="0" value={start} onChange={e=>{setStart(e.target.value);setCapture(null)}} className="block w-28 bg-gray-800 border border-gray-600 rounded p-2" /></label>
      <label>终点（秒）<input type="number" min="0" value={end} placeholder="视频末尾" onChange={e=>{setEnd(e.target.value);setCapture(null)}} className="block w-28 bg-gray-800 border border-gray-600 rounded p-2" /></label>
      <label className="flex gap-2 items-center"><input type="checkbox" checked={agents} onChange={e=>setAgents(e.target.checked)} />请求专家评审</label>
      <label className="flex gap-2 items-center"><input type="checkbox" checked={trace} onChange={e=>setTrace(e.target.checked)} />保留逐帧产物</label>
    </fieldset>
    <div className="flex gap-2 flex-wrap">
      <button disabled={!file||busy} onClick={()=>void run()} className="flex gap-2 items-center bg-emerald-700 rounded p-2 disabled:opacity-40"><Play size={16}/>分析所选区间</button>
      <button disabled={!capture||busy} onClick={()=>void run(true)} className="border border-gray-600 rounded p-2 disabled:opacity-40">重新分析缓存</button>
      <button disabled={!busy} title="取消处理" aria-label="取消处理" onClick={()=>controller.current?.abort()} className="border border-gray-600 rounded p-2 disabled:opacity-40"><Square size={16}/></button>
      <button disabled={!capture||busy} title="下载骨架数据" aria-label="下载骨架数据" onClick={()=>download(capture,'video-landmarks.json')} className="border border-gray-600 rounded p-2 disabled:opacity-40"><Download size={16}/></button>
      <button disabled={!result} onClick={()=>download({capture_metadata:capture?.metadata,...result},'video-analysis.json')} className="border border-gray-600 rounded p-2 disabled:opacity-40">下载分析产物</button>
    </div>
    <p role="status" className="text-sm text-gray-300">{progress}</p>
    <a href="/diagnostics/index.html" className="text-sm text-emerald-300 underline">查看逐帧分析产物</a>
    {error&&<p role="alert" className="text-sm text-red-300 break-words">{error}</p>}
    {capture&&<p className="text-sm text-gray-400">{capture.metadata.model} / {capture.metadata.delegate} · {capture.frames.length} 帧 · 未检测到人体 {capture.metadata.missing_pose_frames} 帧 · 采样耗时 {capture.metadata.processing_seconds.toFixed(1)} 秒</p>}
    {capture&&<p className="text-sm text-gray-400">模型初始化 {capture.metadata.model_initialization_seconds.toFixed(1)} 秒 · 单帧推理中位数 {capture.metadata.inference_median_ms.toFixed(1)} ms / P95 {capture.metadata.inference_p95_ms.toFixed(1)} ms · 推理吞吐 {capture.metadata.inference_fps.toFixed(1)} FPS · 解码与调度 {capture.metadata.decoding_and_scheduling_seconds.toFixed(1)} 秒</p>}
    {Boolean(result?.processing)&&<p className="text-sm text-gray-400">后端阶段耗时（ms）：{JSON.stringify(result?.processing)}</p>}
    {capture&&<p className="text-sm text-gray-400">跳转解码 {capture.metadata.seek_decode_seconds.toFixed(1)} 秒 · 调度等待 {capture.metadata.yield_seconds.toFixed(1)} 秒</p>}
    {capture&&<p className="text-sm text-gray-400">{capture.metadata.sampling_mode==='sequential'?'顺序播放采样':'固定时间采样'} · 目标采样 {capture.metadata.expected_samples} 帧 · 实际保留 {capture.metadata.retained_samples} 帧</p>}
    {capture&&capture.metadata.retained_samples<capture.metadata.expected_samples*.9&&<p role="status" className="text-sm text-amber-200">视频采样不足，计数与动作极值可能遗漏。请切换固定时间逐帧跳转模式复核；保留比例是采样密度，不是识别准确率。</p>}
    <CountingEvidencePanel result={result}/>
    {result&&<><p className="text-sm">{result.status==='analyzed'?'已确认动作片段':'暂未确认动作'} · {Array.isArray(result.segments)?result.segments.length:0} 段</p>{Array.isArray(result.segments)&&result.segments.map((segment,i)=><div key={i} className="border-t border-gray-700 py-2 text-sm"><p>{segment.exercise} · {segment.repetitions} 次 · 未计入完整次数 {segment.partial_repetitions}</p><p className="text-xs text-gray-400">观测来源：{segment.counting_observation}</p></div>)}<details><summary className="text-sm cursor-pointer">整组结果</summary><pre className="text-xs whitespace-pre-wrap break-all max-h-96 overflow-auto">{JSON.stringify({...result,trace:undefined},null,2)}</pre></details></>}
  </section>;
}
