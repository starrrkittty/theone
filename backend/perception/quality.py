"""Descriptive sequence quality diagnostics, never anatomical judgements."""
import math
import numpy as np

HINGES = {"left_elbow":(11,13,15), "right_elbow":(12,14,16),
          "left_knee":(23,25,27), "right_knee":(24,26,28)}


def sequence_quality(frames):
    missing, gaps = 0, []
    previous = None
    values = {name:[] for name in HINGES}
    degenerate = {name:0 for name in HINGES}
    visible = {name:0 for name in HINGES}
    for payload in frames:
        stamp = payload["timestamp"]
        if previous is not None:
            gaps.append(stamp-previous)
        previous = stamp
        landmarks = payload["landmarks"]
        if len(landmarks) != 33:
            missing += 1
            continue
        points = np.asarray([[p["x"],p["y"]/payload.get("image_aspect_ratio",1),p.get("z",0)] for p in landmarks])
        for name, (a,b,c) in HINGES.items():
            if min(landmarks[i].get("visibility",0) for i in (a,b,c)) < .5:
                continue
            visible[name] += 1
            u,v = points[a]-points[b],points[c]-points[b]
            norm = np.linalg.norm(u)*np.linalg.norm(v)
            if norm < 1e-10:
                degenerate[name] += 1
                continue
            angle = math.degrees(math.acos(float(np.clip(np.dot(u,v)/norm,-1,1))))
            values[name].append((stamp,angle))
    joints = {}
    for name, rows in values.items():
        jumps = sum(1 for (t0,a0),(t1,a1) in zip(rows,rows[1:])
                    if 0 < t1-t0 <= 750 and abs(a1-a0)/((t1-t0)/1000) > 720)
        joints[name] = {"visible_frames":visible[name], "degenerate_frames":degenerate[name],
                        "raw_angle_min_deg":min((a for _,a in rows),default=None),
                        "raw_angle_max_deg":max((a for _,a in rows),default=None),
                        "fast_angle_change_pairs":jumps}
    return {"frames":len(frames), "missing_pose_frames":missing,
            "missing_pose_fraction":missing/len(frames) if frames else None,
            "timestamp_discontinuities":sum(g <= 0 or g > 750 for g in gaps),
            "median_frame_interval_ms":float(np.median(gaps)) if gaps else None,
            "joint_diagnostics":joints,
            "coordinate_space":"raw_image_width_normalized",
            "limitations":["Visibility is a model score, not calibrated measurement accuracy.",
                            "Fast change threshold 720 deg/s is a diagnostic heuristic, not a fitness standard.",
                            "No labels or anatomical correctness are inferred from these diagnostics."]}
