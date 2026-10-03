import { PoseDetector, type PoseModel } from '../pose/PoseDetector';
import type { PoseLandmark } from '../pose/PoseDetector';

export type FileFrame = {
  timestamp: number; timestamp_ms: number; landmarks: PoseLandmark[];
  world_landmarks?: PoseLandmark[]; image_aspect_ratio: number;
};
export type Capture = {
  frames: FileFrame[];
  metadata: { model: PoseModel; delegate: string; fps: number; start_seconds: number;
    end_seconds: number; video_width: number; video_height: number; file_name: string;
    missing_pose_frames: number; processing_seconds: number; classification: string;
    model_initialization_seconds:number; inference_median_ms:number; inference_p95_ms:number;
    inference_fps:number; decoding_and_scheduling_seconds:number;
    seek_decode_seconds:number; yield_seconds:number;
    sampling_mode:'seek'|'sequential'; expected_samples:number; retained_samples:number };
};

export type SamplingMode = 'seek' | 'sequential';

async function sequentialFrames(video:HTMLVideoElement,start:number,stop:number,fps:number,
  signal:AbortSignal,onFrame:(mediaTime:number)=>Promise<void>) {
  return new Promise<void>((resolve,reject)=>{
    let finished=false, callback:number|null=null, next=start;
    let timer:ReturnType<typeof setTimeout>;
    const finish=(failure?:unknown)=>{
      if(finished)return;
      finished=true;clearTimeout(timer);
      if(callback!==null)video.cancelVideoFrameCallback(callback);
      video.pause();video.removeEventListener('ended',ended);video.removeEventListener('error',failed);
      signal.removeEventListener('abort',aborted);
      if(failure)reject(failure);else resolve();
    };
    const ended=()=>finish(), failed=()=>finish(Error('顺序视频解码失败'));
    const aborted=()=>finish(new DOMException('已取消','AbortError'));
    const schedule=()=>{
      if(finished)return;
      clearTimeout(timer);timer=setTimeout(()=>finish(Error('顺序解码超时，可尝试逐帧跳转模式')),15000);
      callback=video.requestVideoFrameCallback((_now,meta)=>{
        callback=null;
        if(finished)return;
        const time=meta.mediaTime;
        if(time>=stop){finish();return;}
        if(time<start||time+.001<next){schedule();return;}
        while(next<=time+.001)next+=1/fps;
        onFrame(time).then(schedule,finish);
      });
    };
    video.addEventListener('ended',ended);video.addEventListener('error',failed);
    signal.addEventListener('abort',aborted,{once:true});
    if(signal.aborted){aborted();return;}
    schedule();void video.play().catch(finish);
  });
}

function waitFor(video: HTMLVideoElement, event: string, action: () => void, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => { clearTimeout(timer); video.removeEventListener(event, done); video.removeEventListener('error', fail); signal.removeEventListener('abort', abort); };
    const done = () => { cleanup(); resolve(); };
    const fail = () => { cleanup(); reject(new Error('视频解码失败，请使用浏览器支持的 MP4 / WebM 格式')); };
    const abort = () => { cleanup(); reject(new DOMException('已取消', 'AbortError')); };
    const timer = setTimeout(() => { cleanup(); reject(new Error('视频读取超时')); }, 20000);
    video.addEventListener(event, done, {once:true}); video.addEventListener('error', fail, {once:true});
    signal.addEventListener('abort', abort, {once:true});
    if (signal.aborted) abort(); else action();
  });
}

export async function captureFile(file: File, model: PoseModel, fps: number, start: number,
  end: number | null, signal: AbortSignal, progress: (done: number, total: number, points: PoseLandmark[], video: HTMLVideoElement) => void,
  mode:SamplingMode='seek'): Promise<Capture> {
  const video = document.createElement('video');
  video.muted = true; video.playsInline = true; video.preload = 'auto';
  const url = URL.createObjectURL(file), detector = new PoseDetector({model});
  const yieldChannel = new MessageChannel();
  const started = performance.now();
  try {
    await waitFor(video, 'loadeddata', () => { video.src = url; video.load(); }, signal);
    const stop = end ?? video.duration;
    if (!Number.isFinite(video.duration) || !Number.isFinite(stop) || !Number.isFinite(start) ||
        start < 0 || stop > video.duration + .001 || stop <= start || ![5,10,20,30].includes(fps)) {
      throw new Error('视频区间无效');
    }
    const count = Math.ceil((stop-start)*fps);
    if (count > 2400) throw new Error(`本次超过 2400 帧，请缩短区间至 ${2400/fps} 秒以内`);
    const initStarted=performance.now();
    await detector.initialize();
    const initializationSeconds=(performance.now()-initStarted)/1000;
    signal.throwIfAborted();
    const frames: FileFrame[] = [], origin = Date.now();
    let missing = 0;
    let seekMs=0, yieldMs=0;
    const inferenceTimes:number[]=[];
    const samplingStarted=performance.now();
    const record=async(time:number)=>{
      signal.throwIfAborted();
      if (video.readyState < 2) throw new Error('目标帧尚未解码');
      const inferenceStarted=performance.now();
      const result = await detector.processFrame(video, (time-start)*1000+1);
      inferenceTimes.push(performance.now()-inferenceStarted);
      if (!result) throw new Error(`第 ${frames.length+1} 帧姿态推理失败`);
      if (!result.landmarks.length) missing++;
      frames.push({timestamp:origin+(time-start)*1000, timestamp_ms:time*1000,
        landmarks:result.landmarks, ...(result.worldLandmarks.length ? {world_landmarks:result.worldLandmarks} : {}),
        image_aspect_ratio:video.videoWidth/video.videoHeight});
      progress(frames.length,count,result.landmarks,video);
    };
    const actualMode=mode==='sequential'&&typeof video.requestVideoFrameCallback==='function'?'sequential':'seek';
    if(actualMode==='sequential'){
      if(start>0){
        const seekStarted=performance.now();
        await waitFor(video,'seeked',()=>{video.currentTime=start;},signal);
        seekMs+=performance.now()-seekStarted;
      }
      await sequentialFrames(video,start,stop,fps,signal,record);
    }else for (let i=0; i<count; i++) {
      signal.throwIfAborted();
      const time=start+i/fps;
      if (Math.abs(video.currentTime-time)>1e-7) {
        const seekStarted=performance.now();
        await waitFor(video, 'seeked', () => { video.currentTime=time; }, signal);
        seekMs+=performance.now()-seekStarted;
      }
      await record(time);
      // Timer clamping in background tabs can stall an otherwise fast model.
      const yieldStarted=performance.now();
      await new Promise<void>(resolve => {
        yieldChannel.port1.onmessage=()=>resolve();
        yieldChannel.port2.postMessage(null);
      });
      yieldMs+=performance.now()-yieldStarted;
    }
    const inferenceTotal=inferenceTimes.reduce((sum,n)=>sum+n,0);
    if(!frames.length)throw Error('所选区间没有可用的视频采样帧');
    const sorted=[...inferenceTimes].sort((a,b)=>a-b);
    return {frames, metadata:{model, delegate:detector.actualDelegate, fps, start_seconds:start,
      end_seconds:stop, video_width:video.videoWidth, video_height:video.videoHeight,
      file_name:file.name, missing_pose_frames:missing, processing_seconds:(performance.now()-started)/1000,
      model_initialization_seconds:initializationSeconds,
      inference_median_ms:sorted[Math.floor((sorted.length-1)*.5)],
      inference_p95_ms:sorted[Math.floor((sorted.length-1)*.95)],
      inference_fps:inferenceTotal>0?frames.length*1000/inferenceTotal:0,
      decoding_and_scheduling_seconds:Math.max(0,(performance.now()-samplingStarted-inferenceTotal)/1000),
      seek_decode_seconds:seekMs/1000, yield_seconds:yieldMs/1000,
      sampling_mode:actualMode, expected_samples:count,retained_samples:frames.length,
      classification:'backend HMM and temporal rules; no newly trained temporal classifier'}};
  } finally {
    yieldChannel.port1.close(); yieldChannel.port2.close();
    await detector.close(); video.removeAttribute('src'); video.load(); URL.revokeObjectURL(url);
  }
}
