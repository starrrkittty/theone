"""Generate engineering diagnostics, explicitly not real-video accuracy evidence."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pose(angle=180):
    points = [{"x":.5,"y":.2,"z":0.,"visibility":.95} for _ in range(33)]
    for indices,x in (((11,13,15,23,25,27),.43),((12,14,16,24,26,28),.57)):
        for index,y in zip(indices,(.26,.42,.58,.56,.77,.98)):
            points[index]["x"],points[index]["y"] = x,y
    for elbow,wrist in ((13,15),(14,16)):
        points[wrist]["x"] = points[elbow]["x"] + .16*math.sin(math.radians(angle))
        points[wrist]["y"] = points[elbow]["y"] - .16*math.cos(math.radians(angle))
    return points


def squat(index, crop=0):
    points = pose(85)
    depth = (1-math.cos(index/18))/2
    for shoulder,elbow,wrist,hip,knee,ankle in ((11,13,15,23,25,27),(12,14,16,24,26,28)):
        x = points[hip]["x"]
        points[hip]["x"] = x-.08*depth
        points[hip]["y"] += .22*depth
        points[knee]["x"] = x+.12*depth
        for joint in (shoulder,elbow,wrist):
            points[joint]["y"] += .22*depth
        for joint in (shoulder,elbow,wrist,hip,knee,ankle):
            points[joint]["y"] = points[joint]["y"]*.7 + crop
    return points


def alternating_curl(index):
    left = 115+55*math.cos(index*2*math.pi/90)
    right = 230-left
    points = pose(left)
    points[16]["x"] = points[14]["x"] + .16*math.sin(math.radians(right))
    points[16]["y"] = points[14]["y"] - .16*math.cos(math.radians(right))
    return points


def horizontal_pose(angle=90, forearm=False):
    points = pose()
    for shoulder,elbow,wrist,hip,knee,ankle,shift in (
        (11,13,15,23,25,27,0), (12,14,16,24,26,28,.02)):
        coords = {shoulder:(.24,.30+shift), elbow:(.24 if forearm else .32,.44+shift),
                  hip:(.52,.31+shift), knee:(.68,.32+shift), ankle:(.86,.33+shift)}
        for joint,(x,y) in coords.items():
            points[joint].update(x=x,y=y)
        if forearm:
            points[wrist].update(x=.4,y=.44+shift)
        else:
            dx,dy = coords[shoulder][0]-coords[elbow][0],coords[shoulder][1]-coords[elbow][1]
            length = math.hypot(dx,dy)
            a = math.radians(angle)
            points[wrist].update(x=coords[elbow][0]+.16*(dx*math.cos(a)-dy*math.sin(a))/length,
                                 y=coords[elbow][1]+.16*(dx*math.sin(a)+dy*math.cos(a))/length)
    return points


def cases():
    result = []
    for name,label,make,repetitions,hold in (
        ("static_standing","unknown",lambda i:pose(),None,None),
        ("static_bent_arms","unknown",lambda i:pose(80),None,None),
        ("moving_curl","bicep_curl",lambda i:pose(115+55*math.cos(i*2*math.pi/90)),2,None),
        ("alternating_curl","alternate_bicep_curl",alternating_curl,1,None),
        ("moving_pushup","pushup",lambda i:horizontal_pose(115+55*math.cos(i*2*math.pi/90)),2,None),
        ("forearm_plank","plank",lambda i:horizontal_pose(forearm=True),0,179/30),
        ("static_pushup_bottom","unknown",lambda i:horizontal_pose(80),None,None),
        ("squat_hands_bent_low_crop","squat",lambda i:squat(i,.28),None,None),
        ("squat_hands_bent_high_crop","squat",lambda i:squat(i,.02),None,None),
        ("person_disappears","unknown",lambda i:[],None,None)):
        result.append({"id":name,"expected_exercise":label,
                       "reference_repetitions":{label:repetitions} if repetitions is not None else None,
                       "reference_hold_seconds":hold,
                       "frames":[{"timestamp_ms":i*1000/30,"landmarks":make(i)} for i in range(180)]})
    return result


if __name__ == "__main__":
    target = ROOT/"evaluation"/"synthetic_cases.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps({"evidence_type":"synthetic","dataset":"Engineered skeleton fixtures",
                                 "limitations":["Not captured people or RGB videos; not recognition accuracy evidence.",
                                                 "Alternate curl reference counts complete left/right pairs, not individual arm repetitions."],
                                 "sequences":cases()}),encoding="utf-8")
    print(target)
