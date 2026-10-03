type Cycle = {rep_number?:number; duration_seconds?:number; peak_angle?:number; trough_angle?:number;
  minimum_visibility?:number; observation_gap_ms?:number; reason?:string; gap_ms?:number};
type Counter = {accepted_cycles?:Cycle[]; rejected_cycles?:Cycle[]; uncertain_cycles?:Cycle[];
  rules?:Record<string,number|string>};
type Segment = {exercise:string; repetitions:number; uncertain_cycles?:number; counting_observation?:string;
  counting_only_frames?:number; skipped_frame_reasons?:Record<string,number>; counting_evidence?:Record<string,Counter>;
  action_report?:{kinematics?:{tracking_summary?:Record<string,unknown>}}};
const reasons:Record<string,string>={cycle_too_short:'周期过短',cycle_too_long:'周期超过当前计数上限',
  insufficient_observed_range:'观测幅度不足',low_visibility:'关键点可见度不足',
  extension_threshold_not_reached:'未观测到伸展区',flexion_threshold_not_reached:'未观测到屈曲区',
  occlusion_or_gap_interrupted_cycle:'长时间遮挡或缺帧，中断周期',
  counting_joints_unreliable:'计数关节不可用',incompatible_body_orientation:'身体朝向不支持当前动作'};
const number=(n:number|undefined)=>n===undefined?'未记录':n.toFixed(2);

export function CountingEvidencePanel({result}:{result:Record<string,unknown>|null}){
  const segments=Array.isArray(result?.segments)?result.segments as Segment[]:[];
  if(!segments.length)return null;
  return <section className="border-t border-gray-700 py-3 space-y-3">
    <h3 className="font-semibold text-sm">计数证据与遮挡诊断</h3>
    {segments.map((segment,index)=><div key={index} className="text-sm space-y-2 border-t border-gray-700 pt-2">
      <p>{segment.exercise} · 已确认完整周期 {segment.repetitions} · 遮挡中断、无法确认的周期 {segment.uncertain_cycles??0}</p>
      <p className="text-gray-400 break-words">计数来源：{segment.counting_observation} · 仅可计数、不足以评价姿势的帧 {segment.counting_only_frames??0}</p>
      {Object.entries(segment.skipped_frame_reasons??{}).map(([reason,count])=><p key={reason}>{reasons[reason]??reason}：{count} 帧</p>)}
      {Object.entries(segment.counting_evidence??{}).map(([name,counter])=><details key={name} open className="space-y-2">
        <summary className="cursor-pointer">{name==='rep_counter'?'动作周期':name==='left_rep_counter'?'左臂周期':'右臂周期'}</summary>
        <p className="text-xs text-gray-400 break-words">屈曲区 ≤ {number(counter.rules?.flex_zone_max_deg as number)}° · 伸展区 ≥ {number(counter.rules?.extend_zone_min_deg as number)}° · 最小观测幅度 {number(counter.rules?.minimum_observed_range_deg as number)}° · 可见度门槛 {number(counter.rules?.visibility_floor as number)} · 最长遮挡保留 {number(counter.rules?.max_observation_gap_seconds as number)} 秒</p>
        <p className="text-xs text-gray-400">计数门槛属于待实验验证的工程规则，不是正确姿势标准。周期记录最多保留最近 100 条。</p>
        <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead><tr><th className="py-2">判断</th><th>周期（秒）</th><th>观测夹角范围</th><th>遮挡间隔</th><th>依据</th></tr></thead><tbody>
          {(counter.accepted_cycles??[]).map((cycle,i)=><tr key={`a${i}`} className="border-t border-gray-700"><td className="py-2">确认 #{cycle.rep_number}</td><td>{number(cycle.duration_seconds)}</td><td>{number(cycle.trough_angle)}–{number(cycle.peak_angle)}°</td><td>{number(cycle.observation_gap_ms)} ms</td><td>实际观测到伸展→屈曲→伸展</td></tr>)}
          {(counter.rejected_cycles??[]).map((cycle,i)=><tr key={`r${i}`} className="border-t border-gray-700"><td className="py-2">未计入</td><td>{number(cycle.duration_seconds)}</td><td>{number(cycle.trough_angle)}–{number(cycle.peak_angle)}°</td><td>未记录</td><td>{reasons[cycle.reason??'']??cycle.reason}</td></tr>)}
          {(counter.uncertain_cycles??[]).map((cycle,i)=><tr key={`u${i}`} className="border-t border-gray-700"><td className="py-2">无法确认</td><td>未闭合</td><td>证据不足</td><td>{number(cycle.gap_ms)} ms</td><td>{reasons[cycle.reason??'']??cycle.reason}</td></tr>)}
        </tbody></table></div>
      </details>)}
    </div>)}
  </section>;
}
