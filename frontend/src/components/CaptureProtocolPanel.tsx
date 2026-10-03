import { useEffect, useState } from 'react';
import { API_BASE_URL } from '../config';

type Protocol = {label:string; preferred_view:string; views:Record<string,string[]>};
export function CaptureProtocolPanel() {
  const [protocols,setProtocols]=useState<Record<string,Protocol>>({});
  const [selected,setSelected]=useState('squat');
  const [error,setError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    fetch(`${API_BASE_URL}/api/agent-a/capture-protocols`,{signal:controller.signal})
      .then(async r=>{if(!r.ok)throw Error('拍摄规范暂不可用');return r.json();})
      .then(d=>setProtocols(d.exercises))
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);});
    return ()=>controller.abort();
  },[]);
  const spec=protocols[selected];
  return <section className="border-t border-gray-700 py-3 text-sm space-y-2">
    <label className="flex gap-3 items-center flex-wrap">动作拍摄规范
      <select aria-label="动作拍摄规范" value={selected} onChange={e=>setSelected(e.target.value)} className="bg-gray-800 border border-gray-600 rounded p-2">
        {Object.entries(protocols).map(([key,p])=><option value={key} key={key}>{p.label}</option>)}
      </select>
    </label>
    {spec&&<><p>推荐：{spec.preferred_view==='side'?'侧面':'正面'} · 固定机位、全身入镜、手脚保留边距、避免遮挡</p>
      {Object.entries(spec.views).map(([view,items])=><p key={view}>{view==='side'?'侧面':'正面'}：{items.join('、')}</p>)}</>}
    <p className="text-gray-400">单摄像头角度未经外部标定。遮挡关节无法评价；侧面无法确认双侧对称，正面无法确认深度方向幅度。</p>
    {error&&<p role="status">{error}</p>}
  </section>;
}
