"""Focused evidence/default-compatibility checks; never starts a simulator."""
import hashlib
import json
from pathlib import Path
import sys

DEST = Path(__file__).resolve().parent
REPO = DEST.parents[3]
sys.path.insert(0, str(REPO))
from examples.microrobot.clock_layout import physical_source, routing_script, specs


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = json.loads((DEST / 'metrics.json').read_text())
    base = REPO / 'examples/microrobot/local_runs/clock_layout/contact_escape_v2'
    pins = json.loads((base / 'instance_pins.json').read_text())
    entries = specs(physical_source()[1])
    script, tracks = routing_script(entries, pins)
    expected = script + '\nputs "OPENTCAD_FLOW_DONE"\nquit -noprompt\n'
    assert expected == (base / 'route_extract.tcl').read_text()
    assert tracks == json.loads((base / 'tracks.json').read_text())
    assert routing_script(entries, pins, routing='baseline') == (script, tracks)
    try:
        routing_script(entries, pins, routing='invalid')
    except ValueError:
        pass
    else:
        raise AssertionError('Unknown routing accepted')
    for name in ['native_drc_pass', 'native_lvs_pass', 'negative_control_rejected', 'roundtrip_drc_pass', 'roundtrip_lvs_pass']:
        assert report['physical_gates'][name]
    assert report['execution']['simulator_invocations'] == 1
    assert report['execution']['returncode'] == 0
    for case in report['cases'].values():
        assert case['full_completion'] and case['columns'] == 8 and case['all_finite']
        assert case['first_time_s'] == 0 and case['actual_stop_s'] == .004
        assert case['nondecreasing_time'] and not case['log_abort_markers']
    variant = report['cases']['stage_local_25ns']
    assert variant['edges']['steady_q_rise_count'] >= 3
    assert set(variant['edges']['clock_rises_between_successive_sustained_q_rises']) == {2}
    assert variant['existing_bench_criterion_evaluation']['passed']
    assert report['area']['baseline'] == report['area']['stage_local']
    assert not list(DEST.rglob('clock.dat')) and not list(DEST.rglob('*.pdf'))
    assert (DEST / 'clock_layout.py.snapshot').read_bytes() == (REPO / 'examples/microrobot/clock_layout.py').read_bytes()
    manifest = json.loads((DEST / 'sha256.json').read_text())
    for name, expected_sha in manifest.items():
        assert sha(DEST / name) == expected_sha, name
    result = {'default_routing_script_byte_identical_to_baseline': True,
              'explicit_baseline_identical_to_default': True, 'unknown_variant_rejected': True,
              'physical_gates_pass': True, 'full_transients_complete': True,
              'new_variant_steady_q_count': variant['edges']['steady_q_rise_count'],
              'new_variant_exact_two_clock_rises_per_sustained_Q_period': True,
              'paint_extent_unchanged': True, 'generator_snapshot_matches': True,
              'previous_manifest_verified': True, 'raw_transient_and_PDF_not_exported': True,
              'baseline_script_sha256': hashlib.sha256(expected.encode()).hexdigest()}
    (DEST / 'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    manifest = {str(p.relative_to(DEST)): sha(p) for p in sorted(DEST.rglob('*'))
                if p.is_file() and p.name != 'sha256.json' and '__pycache__' not in p.parts}
    (DEST / 'sha256.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
