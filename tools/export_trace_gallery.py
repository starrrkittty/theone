"""Export actual local pipeline artifacts for the static diagnostic viewer."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT / 'backend'), str(ROOT / 'coach')]
from state_machine.manager import FormManager
from reporting.builder import ActionReportBuilder
from perception.agent import PerceptionSession
from perception.pipeline import process_pose_frame
from perception.sets import analyze_set
from app.action_report_adapter import normalize
from app.engine import analyze_movement, InputError


def export():
    destination = ROOT / 'frontend' / 'public' / 'diagnostics'
    destination.mkdir(parents=True, exist_ok=True)
    index = []
    for filename in ('public_sample.json', 'synthetic_cases.json'):
        document = json.loads((ROOT / 'evaluation' / filename).read_text(encoding='utf-8-sig'))
        for number, sequence in enumerate(document['sequences']):
            manager, builder, session = FormManager(), ActionReportBuilder(sequence['id']), PerceptionSession()
            rows, inputs = [], []
            for frame in sequence['frames']:
                payload = {**frame, 'timestamp': 1700000000000 + frame['timestamp_ms']}
                state, report, event, policy, timing = process_pose_frame(manager, builder, session, payload)
                inputs.append(payload)
                rows.append({'input': payload, 'filtered_landmarks': state.filtered_landmarks,
                             'candidate': state.candidate_exercise.value if state.candidate_exercise else None,
                             'source': state.exercise_source, 'action_report': report.model_dump(),
                             'urdf_xml': session.fitter.xml, 'policy': policy, 'timings_ms': timing,
                             'event': event.model_dump() if event else None})
            completed, snapshots = analyze_set(inputs, sequence['id'])
            downstream = []
            for segment in completed['segments']:
                try:
                    movement = normalize(segment['action_report'])
                    downstream.append({'input': movement, 'local_rule_feedback': analyze_movement(movement)})
                except (InputError, KeyError, ValueError) as error:
                    downstream.append({'blocked_reason': str(error)})
            name = ('public' if filename.startswith('public') else 'synthetic') + f'-{number}.json'
            result = {'id': sequence['id'], 'expected': sequence['expected_exercise'],
                      'original_label': sequence.get('original_label'),
                      'reference_repetitions': sequence.get('reference_repetitions'),
                      'evidence_type': document.get('evidence_type'), 'dataset': document.get('dataset'),
                      'limitations': document.get('limitations', []), 'raw_video': None,
                      'frames': rows, 'completed_set': completed, 'b_group': downstream,
                      'model_agents': {'executed': False, 'reason': 'This export makes no API calls. No generated expert report or training plan is included.'}}
            (destination / name).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            index.append({'file': name, 'id': result['id'], 'expected': result['expected'],
                          'type': result['evidence_type'], 'frames': len(rows)})
    (destination / 'index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    shutil.copytree(destination, ROOT / 'frontend' / 'dist' / 'diagnostics', dirs_exist_ok=True)
    print(f'Exported {len(index)} sample traces')


if __name__ == '__main__':
    export()
