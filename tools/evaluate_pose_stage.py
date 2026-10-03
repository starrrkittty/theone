"""Compare video-model image landmarks with independent labelled image points."""
import argparse
import json
import math
from pathlib import Path

JOINTS=(11,12,13,14,15,16,23,24,25,26,27,28)
HINGES={'left_elbow':(11,13,15),'right_elbow':(12,14,16),
        'left_knee':(23,25,27),'right_knee':(24,26,28)}


def angle(points, ids, aspect):
    a,b,c=(points[i] for i in ids)
    u=(a['x']-b['x'],(a['y']-b['y'])/aspect)
    v=(c['x']-b['x'],(c['y']-b['y'])/aspect)
    length=math.hypot(*u)*math.hypot(*v)
    return math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(u,v))/length)))) if length>1e-10 else None


def evaluate(predicted, reference):
    if reference.get('annotation_kind')!='independent_manual_2d':
        raise ValueError('Reference must explicitly identify independent manual 2D annotations')
    predictions=predicted['frames']
    stamps=[f['timestamp_ms'] for f in predictions]
    if any(not math.isfinite(t) for t in stamps) or any(b<=a for a,b in zip(stamps,stamps[1:])):
        raise ValueError('Predicted media timestamps must strictly increase')
    indexed={round(f['timestamp_ms'],3):f for f in predictions}
    errors,angular,missing,visible=[],{name:[] for name in HINGES},0,0
    matched=0
    for frame in reference['frames']:
        row=indexed.get(round(frame['timestamp_ms'],3))
        if row is None:
            raise ValueError('Reference frame has no matching sampled media timestamp')
        truth=frame['landmarks']; estimate=row['landmarks']; matched+=1
        if len(truth)!=33 or len(estimate) not in (0,33):
            raise ValueError('Landmarks must use the 33-point MediaPipe index convention')
        aspect=row.get('image_aspect_ratio',1)
        center=lambda a,b:((truth[a]['x']+truth[b]['x'])/2,(truth[a]['y']+truth[b]['y'])/2/aspect)
        shoulder,hip=center(11,12),center(23,24)
        scale=math.dist(shoulder,hip)
        if scale<=1e-8 or any(truth[i].get('visibility',0)<.5 for i in (11,12,23,24)):
            raise ValueError('Reference torso must be independently annotated and visible for normalization')
        for joint in JOINTS:
            if truth[joint].get('visibility',0)<.5:
                continue
            visible+=1
            if not estimate or estimate[joint].get('visibility',0)<.5:
                missing+=1;continue
            error=math.hypot(estimate[joint]['x']-truth[joint]['x'],(estimate[joint]['y']-truth[joint]['y'])/aspect)/scale
            errors.append(error)
        for name,ids in HINGES.items():
            if estimate and all(min(truth[i].get('visibility',0),estimate[i].get('visibility',0))>=.5 for i in ids):
                actual,observed=angle(truth,ids,aspect),angle(estimate,ids,aspect)
                if actual is not None and observed is not None:
                    angular[name].append(abs(actual-observed))
    return {'stage':'video_to_image_landmarks','matched_frames':matched,'reference_visible_points':visible,
            'missed_visible_points':missing,'coverage':(visible-missing)/visible if visible else None,
            'mean_error_torso_units':sum(errors)/len(errors) if errors else None,
            'pck_0_2_torso_all_visible':sum(e<=.2 for e in errors)/visible if visible else None,
            'image_angle_mae_deg':{name:sum(v)/len(v) if v else None for name,v in angular.items()},
            'angle_sample_counts':{name:len(v) for name,v in angular.items()},
            'limitations':['2D projected angles do not validate anatomical 3D angles.',
                           'PCK threshold is 20% of independently annotated torso length; misses count as failures.',
                           'No URDF parser or B model is involved in this evaluation.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('predicted',type=Path)
    parser.add_argument('reference',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=evaluate(json.loads(args.predicted.read_text(encoding='utf-8-sig')),
                    json.loads(args.reference.read_text(encoding='utf-8-sig')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
