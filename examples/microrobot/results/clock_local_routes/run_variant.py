"""One physically gated stage-local 4 ms/25 ns run; --audit-only never simulates.

Physical generation (fresh directory):
  python -m examples.microrobot.clock_layout --output examples/microrobot/local_runs/clock_layout/stage_local_v1 --routing stage_local
Then run this script once. Full transient stays under local_runs.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

DEST = Path(__file__).resolve().parent
REPO = DEST.parents[3]
REVIEW = DEST.parent / 'clock_layout_review'
LOCAL = REPO / 'examples/microrobot/local_runs/clock_layout'
BASE = LOCAL / 'contact_escape_v2'
PHYSICAL = LOCAL / 'stage_local_v1'
RUN = PHYSICAL / 'extracted_25ns'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnostic = load('ablation_audit', DEST.parent / 'clock_cap_ablation/run_diagnostic.py')
layout_audit = load('layout_audit', REVIEW / 'audit.py')
sha, dump, counts = diagnostic.sha, diagnostic.dump, diagnostic.counts


def inputs():
    report = json.loads((PHYSICAL / 'report.json').read_text())
    assert all(report[k] for k in ['native_drc_pass', 'native_lvs_pass', 'negative_control_rejected', 'roundtrip_drc_pass', 'roundtrip_lvs_pass'])
    assert not (PHYSICAL / 'streamout_feedback.tcl').read_text().strip()
    assert report['routing_variant'] == 'stage_local'
    for name in ['physical_clock.spice', 'instance_pins.json', 'microrobot_bias.mag']:
        assert sha(PHYSICAL / name) == sha(BASE / name), name
    normalize_mag = lambda path: re.sub(r'^timestamp \d+$', 'timestamp 0', path.read_text(), flags=re.M)
    assert normalize_mag(PHYSICAL / 'clock_cells.mag') == normalize_mag(BASE / 'clock_cells.mag')
    # Device-model geometries/connectivity remain exactly equal before RC splitting.
    devices = lambda text: [line for line in text.splitlines() if line.startswith('X')]
    assert devices((PHYSICAL / 'clock_capacitance.spice').read_text()) == devices((BASE / 'clock_capacitance.spice').read_text())
    original = (REVIEW / 'provenance/clock_rc.spice').read_text()
    assert sha(REVIEW / 'provenance/clock_rc.spice') == diagnostic.SOURCE_SHA == sha(BASE / 'clock_rc.spice')
    variant = (PHYSICAL / 'clock_rc.spice').read_text()
    assert counts(variant) == {'R': 851, 'C': 374, 'FET': 29, 'MIM': 7}
    deck = (REVIEW / 'extracted_25ns/clock.spice').read_text()
    assert deck.count(original) == 1
    changed = deck.replace(original, variant, 1)
    assert changed.replace(variant, original, 1) == deck
    assert [x for x in changed.splitlines() if x.startswith('tran ')] == ['tran 2.5e-08 0.004 0 2.5e-08']
    library = Path(re.search(r'^\.lib "([^"]+)" tt$', deck, re.M)[1])
    assert sha(library) == json.loads((REVIEW / 'extracted_25ns/metrics.json').read_text())['library_sha256']
    return report, original, variant, deck, changed, library


def execute():
    _, _, _, _, changed, _ = inputs()
    RUN.mkdir(exist_ok=False)
    (RUN / 'clock.spice').write_text(changed)
    for name in ['.spiceinit', 'receiver_cells.spice']:
        shutil.copy2(REVIEW / 'extracted_25ns' / name, RUN / name)
    executable = shutil.which('ngspice')
    if not executable:
        raise FileNotFoundError('ngspice is required')
    command = [executable, '-b', 'clock.spice']
    record = {'command': command, 'cwd': str(RUN.relative_to(REPO)), 'timeout_s': 180,
              'fresh_run_directory': True, 'simulator_invocations': 1,
              'maximum_timestep_s': 25e-9, 'requested_stop_s': .004, 'status': 'started'}
    dump(RUN / 'execution.json', record)
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd=RUN, capture_output=True, text=True, timeout=180)
        record.update(returncode=result.returncode, status='returned')
        log = result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        record.update(returncode=None, status='timeout')
        to_text = lambda v: v.decode(errors='replace') if isinstance(v, bytes) else (v or '')
        log = str(exc) + '\n' + to_text(exc.stdout) + to_text(exc.stderr)
    record['wall_s'] = time.monotonic() - start
    (RUN / 'ngspice.log').write_text(log)
    dump(RUN / 'execution.json', record)
    print(json.dumps(record), flush=True)


def extent(path):
    text = path.read_text()
    assert 'magscale 1 2' in text
    layer, rectangles = None, []
    for line in text.splitlines():
        if line.startswith('<< '):
            layer = line[3:-3]
        fields = line.split()
        if fields and fields[0] == 'rect' and layer not in {'checkpaint', 'labels'}:
            rectangles.append([int(v) * .005 for v in fields[1:5]])
    box = [min(r[0] for r in rectangles), min(r[1] for r in rectangles), max(r[2] for r in rectangles), max(r[3] for r in rectangles)]
    return {'paint_extent_um': box, 'width_um': box[2]-box[0], 'height_um': box[3]-box[1],
            'bounding_box_area_um2': (box[2]-box[0]) * (box[3]-box[1]),
            'meaning': 'Flat physical paint bounding box; checkpaint omitted; no footprint signoff'}


def audit():
    report, original, variant, deck, changed, library = inputs()
    assert (RUN / 'clock.spice').read_text() == changed
    for name in ['.spiceinit', 'receiver_cells.spice']:
        assert sha(RUN / name) == sha(REVIEW / 'extracted_25ns' / name)
    reviewed = json.loads((REVIEW / 'review_metrics.json').read_text())
    cases = {name: diagnostic.audit_case(BASE / name) for name in ['schematic_25ns', 'extracted_25ns']}
    for name, case in cases.items():
        for file in ['clock.dat', 'clock.spice']:
            assert case['sha256'][file] == reviewed['cases'][name]['sha256'][file]
    cases['stage_local_25ns'] = diagnostic.audit_case(RUN)
    caps = {}
    for name, path in [('baseline', BASE), ('stage_local', PHYSICAL)]:
        layout_audit.LOCAL = path
        caps[name] = layout_audit.capacitance_audit()
    for name in ['clock.spice', '.spiceinit', 'receiver_cells.spice', 'ngspice.log', 'execution.json']:
        shutil.copy2(RUN / name, DEST / name)
    physical = DEST / 'physical'
    for source in sorted(PHYSICAL.rglob('*')):
        relative = source.relative_to(PHYSICAL)
        if source.is_file() and 'extracted_25ns' not in relative.parts and source.suffix in {'.spice', '.json', '.txt', '.tcl', '.log', '.mag', '.gds'}:
            target = physical / relative
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(source, target)
    shutil.copy2(REPO / 'examples/microrobot/clock_layout.py', DEST / 'clock_layout.py.snapshot')
    shutil.copy2(REVIEW / 'provenance/pv_fit.json', DEST / 'pv_fit.json')
    for name, before, after in [('netlist', original, variant), ('deck', deck, changed),
                                ('routing', (BASE / 'route_extract.tcl').read_text(), (PHYSICAL / 'route_extract.tcl').read_text())]:
        (DEST / f'{name}.diff').write_text(''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile='reviewed/'+name, tofile='stage_local/'+name)))
    result = {'status': 'Reviewed and accepted as routing-improvement evidence; no electrical design acceptance',
              'physical_gates': report, 'execution': json.loads((RUN / 'execution.json').read_text()),
              'proof': {'original_counts': counts(original), 'variant_counts': counts(variant),
                        'physical_source_and_placement_identical': True, 'placement_comparison': 'MAG bytes identical after timestamp normalization; pin JSON byte-identical', 'cap_only_device_lines_identical': True,
                        'deck_unchanged_outside_replaced_RC': True,
                        'baseline_rc_sha256': diagnostic.SOURCE_SHA, 'variant_rc_sha256': sha(PHYSICAL / 'clock_rc.spice'),
                        'pdk_top_level_library_sha256': sha(library), 'baseline_review_metrics_sha256': sha(REVIEW / 'review_metrics.json')},
              'routing': {'variant': 'stage_local', 'placement': 'Unchanged',
                          'baseline_tracks_um': json.loads((BASE / 'tracks.json').read_text()),
                          'variant_tracks_um': json.loads((PHYSICAL / 'tracks.json').read_text()),
                          'timing_MIM_C1_escape_y_um': {'baseline':55, 'variant':30},
                          'unavoidable_under_fixed_placement': 'raw feedback still spans stage 5, stage 1 and the first output buffer'},
              'area': {name: extent(path / 'microrobot_clock.mag') for name, path in [('baseline', BASE), ('stage_local', PHYSICAL)]},
              'capacitance': caps, 'cases': cases,
              'assumptions': 'Exact reviewed tt/26.85 C PV cold-start deck: three fitted cells at assumed 150 um^2/cell, 1 us dark then 100 us ramp, 2 pF storage, 2 fF load, real SKY130 DFF+feedback, Gear2, reltol1e-6, abstol1e-15, no UIC/seed',
              'limitations': ['One 4 ms/25 ns variant; single timestep, not convergence-qualified',
                             'Incident explicit parasitic C is a diagnostic sum, not ground-equivalent load; excludes intentional MIM and model capacitance and ignores coupling correlation',
                             'Finite PV rail changes with the circuit; no additive causal attribution from capacitance accounting',
                             'No PVT, mismatch, remaining divider, POR, drivers or footprint closure',
                             'Separate internal bias power unavailable; analog macro and first-FF/feedback measured',
                             'Full clock.dat stays local; no raw transient or local PDF exported']}
    if all(case.get('full_completion') for case in cases.values()):
        freq = {name: case['edges']['steady_clock_frequency_Hz'] for name, case in cases.items()}
        result['comparison'] = {'frequency_Hz':freq, 'stage_local_over_baseline_RC_frequency_ratio':freq['stage_local_25ns']/freq['extracted_25ns'],
                                'stage_local_over_schematic_frequency_ratio':freq['stage_local_25ns']/freq['schematic_25ns']}
    dump(DEST / 'metrics.json', result)
    dump(DEST / 'sha256.json', {str(p.relative_to(DEST)): sha(p) for p in sorted(DEST.rglob('*')) if p.is_file() and p.name != 'sha256.json' and '__pycache__' not in p.parts})
    print(json.dumps({'completion':{name: case.get('full_completion') for name,case in cases.items()}, 'comparison':result.get('comparison'),
                      'incident_C_fF':{name:{net:value['total_incident_parasitic_fF'] for net,value in cap['logical_nets'].items()} for name,cap in caps.items()}}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if not args.audit_only:
        execute()
    audit()
