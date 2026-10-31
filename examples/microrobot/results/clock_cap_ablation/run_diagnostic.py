"""One artificial 4 ms / 25 ns diagnostic; never reuse/overwrite a local run.

Run once: .venv/bin/python examples/microrobot/results/clock_cap_ablation/run_diagnostic.py
Re-audit only: append --audit-only (does not invoke a simulator).
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

DEST = Path(__file__).resolve().parent
REPO = DEST.parents[3]
REVIEW = DEST.parent / 'clock_layout_review'
LOCAL = REPO / 'examples/microrobot/local_runs/clock_layout'
BASE = LOCAL / 'contact_escape_v2'
RUN = LOCAL / 'clock_cap_ablation_25ns'
SOURCE_SHA = 'f5491783e4294a96d925a4674d76ce188e1333e018c80b41d02dbe212f75b9ea'
START, STOP = .0024, .004


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def counts(text):
    lines = text.splitlines()
    return {'R': sum(bool(re.match(r'^R\S+\s', x)) for x in lines),
            'C': sum(bool(re.match(r'^C\S+\s', x)) for x in lines),
            'FET': sum(' sky130_fd_pr__nfet_' in x or ' sky130_fd_pr__pfet_' in x for x in lines),
            'MIM': sum(' sky130_fd_pr__cap_mim_' in x for x in lines)}


def inputs():
    source = REVIEW / 'provenance/clock_rc.spice'
    assert sha(source) == SOURCE_SHA == sha(BASE / 'clock_rc.spice')
    original = source.read_text()
    removed = [x for x in original.splitlines(keepends=True) if re.match(r'^C\S+\s', x)]
    variant = ''.join(x for x in original.splitlines(keepends=True) if not re.match(r'^C\S+\s', x))
    assert counts(original) == {'R': 851, 'C': 374, 'FET': 29, 'MIM': 7}
    assert counts(variant) == {'R': 851, 'C': 0, 'FET': 29, 'MIM': 7}
    assert len(removed) == 374 and not any(x.lstrip().startswith('+') for x in original.splitlines())
    baseline = REVIEW / 'extracted_25ns/clock.spice'
    deck = baseline.read_text()
    pdk_library = Path(re.search(r'^\.lib "([^"]+)" tt$', deck, re.M)[1])
    reviewed_library_sha = json.loads((REVIEW / 'extracted_25ns/metrics.json').read_text())['library_sha256']
    assert sha(pdk_library) == reviewed_library_sha
    assert deck.count(original) == 1
    changed = deck.replace(original, variant, 1)
    assert changed.replace(variant, original, 1) == deck
    assert [x for x in changed.splitlines() if x.startswith('tran ')] == ['tran 2.5e-08 0.004 0 2.5e-08']
    return source, original, variant, baseline, deck, changed


def execute():
    source, original, variant, baseline, deck, changed = inputs()
    RUN.mkdir(exist_ok=False)
    (RUN / 'clock_rc_no_explicit_c.spice').write_text(variant)
    (RUN / 'clock.spice').write_text(changed)
    for name in ['.spiceinit', 'receiver_cells.spice']:
        shutil.copy2(REVIEW / 'extracted_25ns' / name, RUN / name)
    executable = shutil.which('ngspice')
    if not executable:
        raise FileNotFoundError('ngspice is required')
    command = [executable, '-b', 'clock.spice']
    record = {'command': command, 'cwd': str(RUN.relative_to(REPO)),
              'timeout_s': 180, 'fresh_run_directory': True,
              'simulator_invocations': 1, 'maximum_timestep_s': 25e-9,
              'requested_stop_s': STOP, 'status': 'started'}
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


def crossings(t, signal, rail, rising=True):
    y = signal - rail / 2
    mask = (y[:-1] < 0) & (y[1:] >= 0) if rising else (y[:-1] >= 0) & (y[1:] < 0)
    i = np.flatnonzero(mask)
    return t[i] - y[i] * np.diff(t)[i] / np.diff(y)[i]


def frequency(edges, minimum=2):
    return float(1 / np.mean(np.diff(edges))) if len(edges) >= minimum else None


def audit_case(path):
    record = {'source': str(path.relative_to(REPO)),
              'sha256': {p.name: sha(p) for p in sorted(path.iterdir()) if p.is_file()}}
    log = (path / 'ngspice.log').read_text()
    record['log_abort_markers'] = [s for s in ['simulation(s) aborted', 'doanalyses:', 'timestep too small'] if s in log.lower()]
    record['log_warnings'] = sorted({x.strip() for x in log.splitlines() if 'warning' in x.lower()})
    if not (path / 'clock.dat').is_file():
        return dict(record, full_completion=False, failure='No full transient available')
    data = np.loadtxt(path / 'clock.dat', skiprows=1, ndmin=2)
    t = data[:, 0]
    finite = bool(np.isfinite(data).all())
    record.update(rows=len(data), columns=data.shape[1], all_finite=finite,
                  first_time_s=float(t[0]), actual_stop_s=float(t[-1]),
                  nondecreasing_time=bool(np.all(np.diff(t) >= 0)),
                  max_observed_step_s=float(np.max(np.diff(t))))
    record['full_completion'] = bool(data.shape[1] == 8 and finite and t[0] == 0 and t[-1] == STOP and np.all(np.diff(t) >= 0) and not record['log_abort_markers'])
    if not record['full_completion']:
        return dict(record, failure='Transient did not satisfy the complete-data audit')
    t, vdd, clk, bn, bp, analog, receiver, q = data.T
    # Integrate an exact common 2.4--4 ms window, linearly interpolating its
    # boundary instead of allowing adaptive time samples to set its start.
    inner = (t > START) & (t < STOP)
    wt = np.r_[START, t[inner], STOP]
    window = lambda values: np.r_[np.interp(START, t, values), values[inner], np.interp(STOP, t, values)]
    integrate = lambda values: float(np.trapezoid(window(values), wt))
    average = lambda values: integrate(values) / (STOP - START)
    wvdd = window(vdd)
    record['integration_window_s'] = [START, STOP]
    record['integration_method'] = 'Trapezoidal on full adaptive data; linear boundary interpolation; power interpolates vdd*current'
    record['rail_V'] = {'time_average': average(vdd), 'minimum': float(wvdd.min()), 'maximum': float(wvdd.max())}
    currents = {'analog_clock': analog, 'first_ff_and_feedback': receiver, 'whole_clock_and_first_ff': analog + receiver}
    record['power_W'] = {name: average(vdd * current) for name, current in currents.items()}
    record['energy_J'] = {name: integrate(vdd * current) for name, current in currents.items()}
    cr, qr, qf = crossings(t, clk, vdd), crossings(t, q, vdd), crossings(t, q, vdd, False)
    sr, sqr, sqf = [x[(x > START) & (x <= STOP)] for x in [cr, qr, qf]]
    sustained, sustained_q = [x[x >= .0004] for x in [cr, qr]]
    record['edges'] = {'method': 'Linear interpolation of signal minus instantaneous vdd/2',
                       'all_clock_rises_s': cr.tolist(), 'all_q_rises_s': qr.tolist(), 'all_q_falls_s': qf.tolist(),
                       'steady_clock_rises_s': sr.tolist(), 'steady_q_rises_s': sqr.tolist(), 'steady_q_falls_s': sqf.tolist(),
                       'steady_clock_frequency_Hz': frequency(sr, 5),
                       'bench_q_requires_rise_count': 3, 'steady_q_rise_count': len(sqr),
                       'bench_criterion_q_frequency_Hz': frequency(sqr, 3),
                       'observed_q_frequency_one_or_more_periods_Hz': frequency(sqr),
                       'sustained_audit_start_s': .0004, 'sustained_clock_rises_s': sustained.tolist(),
                       'sustained_q_rises_s': sustained_q.tolist(),
                       'sustained_clock_frequency_Hz': frequency(sustained), 'sustained_q_frequency_Hz': frequency(sustained_q),
                       'sustained_q_to_clock_frequency_ratio': frequency(sustained_q) / frequency(sustained) if len(sustained_q) >= 2 and len(sustained) >= 2 else None,
                       'clock_rises_between_successive_sustained_q_rises': [int(np.sum((sustained > a) & (sustained <= b))) for a, b in zip(sustained_q[:-1], sustained_q[1:])],
                       'startup_limitation': 'Near-zero rail crossings retained but excluded from sustained >=0.4 ms audit; edge timing is not propagation-delay characterization'}
    # Preserve the actual existing bench's sample-index criterion separately
    # from the interpolated edge audit, without executing another simulation.
    select = t > START
    threshold = vdd / 2
    indices = np.flatnonzero((clk[:-1] < threshold[:-1]) & (clk[1:] >= threshold[1:]))
    indices = indices[t[indices] > t[select][0]]
    times = t[indices] + (threshold[indices] - clk[indices]) * np.diff(t)[indices] / np.diff(clk)[indices]
    bench_freq = frequency(times, 5)
    qindices = np.flatnonzero((q[:-1] < threshold[:-1]) & (q[1:] >= threshold[1:]) & select[1:])
    bench_q = frequency(t[qindices], 3)
    rail = float(vdd[select].mean())
    bench_power = float(np.trapezoid((vdd * (analog + receiver))[select], t[select]) / np.ptp(t[select]))
    passed = bool(bench_freq and clk[select].min() < .1 * rail and clk[select].max() > .9 * rail and bench_power > 0)
    passed = bool(passed and bench_q and abs(bench_q / bench_freq - .5) < .025)
    record['existing_bench_criterion_evaluation'] = {'method': 'Offline exact sample-index calculations from existing clock_case; not acceptance',
        'passed': passed, 'clock_requires_rise_count': 5, 'q_requires_rise_count': 3,
        'clock_rise_count': len(indices), 'q_rise_count': len(qindices),
        'frequency_Hz': bench_freq, 'first_divider_output_Hz': bench_q,
        'steady_supply_sample_mean_V': rail, 'mean_power_W': bench_power,
        'clock_min_V': float(clk[select].min()), 'clock_max_V': float(clk[select].max())}
    return record


def audit():
    source, original, variant, baseline, deck, changed = inputs()
    assert (RUN / 'clock.spice').read_text() == changed
    assert (RUN / 'clock_rc_no_explicit_c.spice').read_text() == variant
    for name in ['.spiceinit', 'receiver_cells.spice']:
        assert sha(RUN / name) == sha(REVIEW / 'extracted_25ns' / name)
    for name in ['clock_rc_no_explicit_c.spice', 'clock.spice', '.spiceinit', 'receiver_cells.spice', 'ngspice.log', 'execution.json']:
        shutil.copy2(RUN / name, DEST / name)
    netdiff = ''.join(difflib.unified_diff(original.splitlines(keepends=True), variant.splitlines(keepends=True), fromfile='reviewed/clock_rc.spice', tofile='diagnostic/clock_rc_no_explicit_c.spice'))
    deckdiff = ''.join(difflib.unified_diff(deck.splitlines(keepends=True), changed.splitlines(keepends=True), fromfile='reviewed/extracted_25ns/clock.spice', tofile='diagnostic/clock.spice'))
    (DEST / 'netlist.diff').write_text(netdiff)
    (DEST / 'deck.diff').write_text(deckdiff)
    reviewed = json.loads((REVIEW / 'review_metrics.json').read_text())
    cases = {}
    for name in ['schematic_25ns', 'extracted_25ns']:
        cases[name] = audit_case(BASE / name)
        assert cases[name]['sha256']['clock.dat'] == reviewed['cases'][name]['sha256']['clock.dat']
        assert cases[name]['sha256']['clock.spice'] == reviewed['cases'][name]['sha256']['clock.spice']
        cases[name]['reviewed_original_sample_window_metrics'] = {key: reviewed['cases'][name][key] for key in ['rail_V', 'power_W', 'bench_metrics']}
    cases['no_explicit_c_25ns'] = audit_case(RUN)
    report = {'status': 'ARTIFICIAL DIAGNOSTIC; awaiting Astra evidence review; no physical/electrical acceptance',
              'execution': json.loads((RUN / 'execution.json').read_text()),
              'proof': {'reviewed_rc_source_sha256': sha(source), 'reviewed_extracted_deck_sha256': sha(baseline),
                        'original_counts': counts(original), 'variant_counts': counts(variant),
                        'only_change': 'Delete 374 complete explicit C lines within microrobot_clock; every other byte is preserved',
                        'variant_sha256': sha(DEST / 'clock_rc_no_explicit_c.spice'),
                        'deck_sha256': sha(DEST / 'clock.spice'),
                        'non_C_netlist_lines_identical': True, 'deck_unchanged_outside_replaced_source': True,
                        'pv_fit_sha256': sha(REVIEW / 'provenance/pv_fit.json'),
                        'existing_runner_sha256': sha(LOCAL / 'run_electrical.py'),
                        'clock_case_source_sha256': sha(REPO / 'examples/microrobot/clock.py'),
                        'pdk_top_level_library_sha256': sha(Path(re.search(r'^\.lib "([^"]+)" tt$', deck, re.M)[1])),
                        'baseline_review_metrics_sha256': sha(REVIEW / 'review_metrics.json')},
              'cases': cases,
              'assumptions': 'Exact reviewed tt/26.85 C PV cold-start deck: three S2E-fit cells at assumed 150 um^2/cell, 1 us dark then 100 us optical ramp, 2 pF storage, 2 fF output load, real SKY130 DFF+feedback, Gear2, reltol1e-6, abstol1e-15, no UIC/seed',
              'limitations': ['Artificial netlist retains all extracted resistance, device geometries/connectivity and model capacitance but removes explicit extraction capacitors; it is not a physical design',
                             'Exactly one new 4 ms/25 ns transient; variant is single-timestep and not convergence-qualified',
                             'Coupled finite PV rail changes with the circuit; recovery cannot be interpreted as additive causal contribution of capacitance or resistance',
                             'No PVT, mismatch, storage sweep, layout regeneration, remaining divider, POR or driver qualification',
                             'The >=3 steady Q-rise criterion is preserved; a one-period observation is separately labelled',
                             'Full clock.dat stays local; no raw transient or reference PDF is exported']}
    if all(x.get('full_completion') for x in cases.values()):
        freq = {name: value['edges']['steady_clock_frequency_Hz'] for name, value in cases.items()}
        report['comparison'] = {'frequency_Hz': freq,
                                'diagnostic_over_full_RC_frequency_ratio': freq['no_explicit_c_25ns'] / freq['extracted_25ns'],
                                'diagnostic_over_schematic_frequency_ratio': freq['no_explicit_c_25ns'] / freq['schematic_25ns']}
    dump(DEST / 'metrics.json', report)
    dump(DEST / 'sha256.json', {p.name: sha(p) for p in sorted(DEST.iterdir()) if p.is_file() and p.name != 'sha256.json'})
    print(json.dumps({'completion': {name: case.get('full_completion') for name, case in cases.items()}, 'comparison': report.get('comparison')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if not args.audit_only:
        execute()
    audit()
