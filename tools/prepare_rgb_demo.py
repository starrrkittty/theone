"""Prepare official RGB demonstration footage, not a labelled benchmark clip."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = '68bdd4daa60ed7c3174a7f6bf86f6537b6fa0979'
BASE = f'https://raw.githubusercontent.com/SvipRepetitionCounting/TransRAC/{REVISION}/'


def fetch(path, destination):
    with urlopen(BASE+path, timeout=45) as response:
        content=response.read()
    destination.write_bytes(content)
    return {'url':BASE+path,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}


def main():
    target=ROOT/'frontend/public/datasets'
    target.mkdir(parents=True,exist_ok=True)
    raw=ROOT/'evaluation/rgb_demo_raw'
    raw.mkdir(parents=True,exist_ok=True)
    provenance=fetch('figures/squat.gif',raw/'squat.gif')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg is required for GIF-to-MP4 conversion')
    output=target/'repcount-squat-demo.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(raw/'squat.gif'),
                    '-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(output)],check=True)
    labels=[]
    for split in ('train','valid','test'):
        file=raw/f'{split}.csv'
        source=fetch(f'open_set/new_{split}.csv',file)
        with file.open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        labels.append({'split':split,'rows':len(rows),'source':source})
    manifest={'id':'repcount-squat-demo','video_url':'/datasets/repcount-squat-demo.mp4',
              'evidence_type':'rgb_demo_not_benchmark','reference_repetitions':None,
              'source':provenance,'revision':REVISION,'labels_downloaded':labels,
              'limitations':['Official GIF illustration re-encoded to MP4; compressed, edited demonstration footage.',
                             'No corresponding clip label/count/pose annotation has been verified.',
                             'Separate official annotation CSVs do not provide ground truth for this GIF.',
                             'Local research only; dataset/video redistribution rights not established.']}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    shutil.copytree(target,ROOT/'frontend/dist/datasets',dirs_exist_ok=True)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
