"""Fetch a pinned small UI-PRMD mirror sample for local research replay."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
REVISION = "d69141abc6743644bc2fcc12e42ca7825587c3c6"
BASE = f"https://raw.githubusercontent.com/tejas1904/UI-PRMD-Visualize-python-port/{REVISION}/data/"
PARENTS = [-1,0,1,2,3,4,2,6,7,8,2,10,11,12,0,14,15,16,0,18,19,20]
MAP = {0:4, 11:7,12:11,13:8,14:12,15:9,16:13,23:14,24:18,
       25:15,26:19,27:16,28:20,29:16,30:20,31:17,32:21}
MOVEMENTS = ["deep_squat", "hurdle_step", "inline_lunge", "side_lunge", "sit_to_stand",
             "straight_leg_raise", "shoulder_abduction", "shoulder_extension", "shoulder_rotation", "shoulder_scaption"]


def global_positions(positions, angles):
    p = positions.reshape(-1,22,3)
    local = Rotation.from_euler("xyz", angles.reshape(-1,3), degrees=True).as_matrix().reshape(-1,22,3,3)
    result = np.zeros_like(p)
    rotations = np.zeros_like(local)
    for joint, parent in enumerate(PARENTS):
        if parent < 0:
            result[:,joint] = p[:,joint]
            rotations[:,joint] = local[:,joint]
        else:
            result[:,joint] = result[:,parent] + np.einsum("nij,nj->ni", rotations[:,parent], p[:,joint])
            rotations[:,joint] = rotations[:,parent] @ local[:,joint]
    return result


def prepare(output):
    raw = output.parent / "public_sample_raw"
    raw.mkdir(parents=True, exist_ok=True)
    records, clips = [], []
    for movement in range(1,11):
        matrices = []
        for kind in ("positions", "angles"):
            name = f"m{movement:02d}_s01_e01_{kind}.txt"
            path = raw / name
            if not path.exists():
                with urlopen(BASE+name, timeout=30) as response:
                    blob = response.read(1_000_001)
                if len(blob) > 1_000_000:
                    raise ValueError("Unexpected sample size")
                path.write_bytes(blob)
            blob = path.read_bytes()
            records.append({"file":name, "url":BASE+name, "sha256":hashlib.sha256(blob).hexdigest(), "bytes":len(blob)})
            matrix = np.loadtxt(io.BytesIO(blob), delimiter=",")
            if matrix.ndim != 2 or matrix.shape[1] != 66 or not np.isfinite(matrix).all():
                raise ValueError("Invalid 22-joint sample matrix")
            matrices.append(matrix)
        if matrices[0].shape != matrices[1].shape:
            raise ValueError("Positions/angles frame count mismatch")
        clips.append(global_positions(*matrices))
        print(f"Loaded movement {movement}: {len(clips[-1])} frames", flush=True)
    all_points = np.concatenate(clips)
    center = (all_points[:,:,:2].max(axis=(0,1)) + all_points[:,:,:2].min(axis=(0,1))) / 2
    scale = float(np.ptp(all_points[:,:,:2], axis=(0,1)).max()) * 1.2
    sequences = []
    for index, points in enumerate(clips):
        frames = []
        for tick, pose in enumerate(points):
            landmarks = [{"x":.5,"y":.5,"z":0.,"visibility":0.} for _ in range(33)]
            for target, source in MAP.items():
                x,y,z = pose[source]
                landmarks[target] = {"x":float(.5+(x-center[0])/scale),
                                     "y":float(.5-(y-center[1])/scale),
                                     "z":float((z-pose[0,2])/scale), "visibility":1.}
            frames.append({"timestamp_ms":tick*1000/30, "landmarks":landmarks, "image_aspect_ratio":1.0})
        sequences.append({"id":f"m{index+1:02d}_s01_e01", "subject_id":"s01",
                          "original_label":MOVEMENTS[index], "expected_exercise":"squat" if index==0 else "unknown",
                          "reference_repetitions":{"squat":1} if index==0 else None, "frames":frames})
    document = {"evidence_type":"public_skeleton_derived", "dataset":"UI-PRMD mirror subset",
                "unique_subjects":1, "unique_trials":10, "fps":30,
                "label_granularity":"clip labels propagated to frames; not phase-level ground truth",
                "provenance":{"original_url":"https://webpages.uidaho.edu/ui_prmd/", "mirror_revision":REVISION,
                              "license_status":"Mirror has no explicit dataset license; local research sample, not a redistributed training dataset",
                              "files":records},
                "limitations":["No RGB/video-to-pose validation", "Visibility=1 is an adapter assumption, not a measured confidence",
                                "22-joint relative offsets reconstructed with xyz Euler hierarchy; conversion not verified against official loader",
                                "Fixed image framing derived across this sample; missing MediaPipe landmarks remain invisible",
                                "Nine unsupported classes test abstention, not exercise form correctness", "One subject and one trial per action are not independent generalization evidence"],
                "sequences":sequences}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    (output.parent/"public_sample_manifest.json").write_text(json.dumps({key:value for key,value in document.items() if key!="sequences"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT/"evaluation/public_sample.json")
    prepare(parser.parse_args().output)
