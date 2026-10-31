"""Build a curated portable folder; never publishes or submits it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'examples/microrobot'
EVIDENCE = ('clock_layout_review', 'clock_compact_placement',
            'clock_compact_convergence', 'clock_compact_hot85', 'tcad_demo')
EXCLUDED_NAMES = {'__pycache__', '.DS_Store', '.spiceinit'}
EXCLUDED_SUFFIXES = {'.pyc', '.pdf', '.dat'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_files(folder):
    return {str(p.relative_to(folder)): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and not any(part in EXCLUDED_NAMES or part in
              {'local_runs', '.pytest_cache', '.venv'} for part in p.relative_to(folder).parts)
            and p.suffix != '.pyc' and p.name != 'submission.json'}


def seal_execution(folder):
    """Accept only declared execution outputs; fail on every reference/source drift."""
    folder = Path(folder).resolve()
    path = folder / 'submission.json'
    manifest = json.loads(path.read_text())
    old = manifest['files_sha256']
    current = payload_files(folder)
    allowed = {'submission.ipynb', 'execution_validation.json'}
    changed = sorted(name for name in old.keys() | current.keys()
                     if old.get(name) != current.get(name) and name not in allowed)
    if changed:
        raise AssertionError(f'Unapproved package drift: {changed}')
    report = json.loads((folder / 'execution_validation.json').read_text())
    if report['archive_files_changed'] or report['source_files_changed']:
        raise AssertionError('Execution changed packaged inputs')
    manifest['execution_note'] = 'Front notebook executed in this folder; see execution_validation.json'
    manifest['execution_validation_sha256'] = digest(folder / 'execution_validation.json')
    manifest['files_sha256'] = current
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def build(destination):
    dest = Path(destination).resolve()
    if dest.exists():
        raise FileExistsError('Choose a new export directory; existing work is preserved')
    dest.mkdir(parents=True)
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store')
    shutil.copytree(ROOT / 'opentcad', dest / 'opentcad', ignore=ignore)
    shutil.copytree(ROOT / 'docs', dest / 'docs', ignore=ignore)
    target = dest / 'examples/microrobot'
    target.mkdir(parents=True)
    (dest / 'examples/__init__.py').write_text('')
    application_files = ('__init__.py', 'bootstrap.py', 'runtime.py', 'pv.py',
                         'system.py', 'published.py', 'digitize.py', 'clock.py',
                         'electrical.py', 'controller.py', 'run.py', 'tcad_demo.py',
                         'README.md', 'SETUP.md', 'ATTRIBUTION.md', 'references.md',
                         'SUBMISSION_STATUS.md', 'PHYSICAL_VALIDATION.md',
                         'M4_STARTUP_STATUS.md', 'requirements-notebook.txt',
                         'requirements-notebook.in')
    for name in application_files:
        shutil.copy2(APP / name, target / name)
    (target / 'data').mkdir()
    for name in ('README.md', 'reynolds2022_AUDIT.md', 'reynolds2022_inventory.json'):
        shutil.copy2(APP / 'data' / name, target / 'data' / name)
    for name in ('circuits', 'rtl'):
        shutil.copytree(APP / name, target / name, ignore=ignore)
    archive = target / 'results'
    archive.mkdir()
    for name in ('pv.json', 'validation.json'):
        shutil.copy2(APP / 'results' / name, archive / name)
    (archive / 'published').mkdir()
    shutil.copy2(APP / 'results/published/pv_fit.json', archive / 'published/pv_fit.json')
    (archive / 'clock_final').mkdir()
    shutil.copy2(APP / 'results/clock_final/summary.json', archive / 'clock_final/summary.json')
    # Curated evidence has no full transient or local reference material.
    # Historical manifests retain original source hashes; export hashes below
    # identify the portable copies after explicitly recorded path redaction.
    transformed = {}
    for name in EVIDENCE:
        source = APP / 'results' / name
        if not source.is_dir():
            if name == 'tcad_demo':
                raise FileNotFoundError('Run and review tcad_demo before building the submission')
            raise FileNotFoundError(source)
        for p in sorted(source.rglob('*')):
            if not p.is_file() or p.suffix in EXCLUDED_SUFFIXES or any(
                    part in EXCLUDED_NAMES for part in p.relative_to(source).parts):
                continue
            output = archive / name / p.relative_to(source)
            output.parent.mkdir(parents=True, exist_ok=True)
            content = p.read_bytes()
            try:
                original = content.decode('utf-8')
            except UnicodeDecodeError:
                original = None
            if original is not None:
                portable = original.replace(str(ROOT), '<PROJECT_ROOT>')
                portable = re.sub(r'/Users/[^/\s"\']+', '<USER_HOME>', portable)
                if portable != original:
                    transformed[str(output.relative_to(dest))] = {
                        'source_sha256': hashlib.sha256(content).hexdigest(),
                        'change': 'local absolute user/check-out paths redacted; numerical data unchanged'}
                    content = portable.encode('utf-8')
            output.write_bytes(content)
    compact_records = {
        'clock_local_routes': ('README.md', 'metrics.json', 'prototype_layout.png'),
        'pv_calibration_feasibility': ('README.md', 'metrics.json', 'dd_curves.json',
            'execution_checks.json', 'dd_comparison.png', 'throughput_feasibility.png'),
        'electrical_v2': ('summary.json', 'drivers.png'),
    }
    for investigation in ('tcad_controller', 'tcad_logic_isolation',
            'tcad_actuator_startup', 'tcad_passive_clamps', 'tcad_charge_adsorption',
            'tcad_passive_adsorption', 'tcad_stable_adsorption', 'tcad_linear_bads',
            'tcad_adsorption_source_audit', 'tcad_actuator_feedback_replay',
            'tcad_feedback_fix'):
        compact_records[investigation] = ('README.md', 'status.json', 'metrics.json')
    for group, names in compact_records.items():
        for name in names:
            source = APP / 'results' / group / name
            if not source.is_file():
                if name == 'README.md':
                    continue
                raise FileNotFoundError(source)
            output = archive / group / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
    for name in ('LICENSE', 'CHANGELOG.md'):
        shutil.copy2(ROOT / name, dest / name)
    for name in ('bootstrap.py', 'SETUP.md', 'ATTRIBUTION.md', 'requirements-notebook.txt'):
        shutil.copy2(APP / name, dest / name)
    shutil.copy2(ROOT / 'tools/execute_microrobot_bundle.py', dest / 'execute_notebooks.py')
    shutil.copy2(APP / 'submission.ipynb', dest / 'submission.ipynb')
    tests = ['conftest.py', 'device/test_optical.py', 'device/test_compact_pv.py',
             'integration/test_microrobot.py', 'integration/test_controller_events.py',
             'integration/test_tcad_demo.py']
    for name in tests:
        output = dest / 'tests' / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'tests' / name, output)
    (dest / 'pytest.ini').write_text('[pytest]\ntestpaths = tests\naddopts = -ra\n')
    (dest / '.gitignore').write_text('__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\nexamples/microrobot/local_runs/\n')
    (dest / 'README.md').write_text('''# OpenTCAD microrobot: portable educational notebook

SPDX-License-Identifier: Apache-2.0

Team: Abhineet Agarwal, IIT Bombay. IEEE member: No. SSCS member: No.

Open **submission.ipynb** after following SETUP.md. This is an executable
end-to-end mixed-abstraction model with separately validated transistor blocks:
archived actual drift-diffusion PV tables, characterized schematic clock/first
DFF, behavioral divider/reset and finite-resistance drivers, nonlinear
finite-return electrochemistry and assumed mechanical bending.

**Full transistor-coupled controller startup failed and remains unresolved.**
The conceptual TCAD PV is uncalibrated, mechanics are assumed, no walking is
simulated, and the complete controller has no physical layout verification.
Read examples/microrobot/SUBMISSION_STATUS.md before interpreting plots.
Compact-clock DRC/LVS/PEX, pre/post comparison, timestep and hot-electronics
sensitivity are separate archived evidence, not coupled-controller acceptance.

All imported project source is bundled. No parent checkout or network access
is needed to run the notebook after dependencies are installed. Python 3.12
packages are pinned; native requirements are in SETUP.md. Colab is untested.
Run `python execute_notebooks.py .` to execute into fresh local_runs and verify
that reference/source inputs did not change. Run `python -m pytest -ra` for
the included focused tests. Source provenance and SHA256 are in submission.json.

Local PDFs, raw SPICE transients, and externally supplied measurement CSVs of
unverified redistribution rights are excluded. Attribution is in ATTRIBUTION.md.
Historical evidence manifests may refer to omitted raw data or original local
paths; submission.json records portable path redactions and final file hashes.

Intended path: ISSCC27/submitted_notebooks/opentcad_microrobot/.
The October 31, 2026, 11:59 AM Pacific deadline has passed. No eligibility or
late-submission promise is made. This local export has not been submitted,
published or pushed, and does not authorize fabrication.
''')
    for output in dest.rglob('*'):
        if not output.is_file():
            continue
        try:
            original = output.read_text()
        except UnicodeDecodeError:
            continue
        portable = original.replace(str(ROOT), '<PROJECT_ROOT>')
        portable = re.sub(r'/Users/[^/\s"\']+', '<USER_HOME>', portable)
        if portable != original:
            transformed.setdefault(str(output.relative_to(dest)), {
                'source_sha256': digest(output),
                'change': 'local absolute user/check-out paths redacted; numerical data unchanged'})
            output.write_text(portable)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = {'project': 'opentcad_microrobot', 'format': 2,
                'source_base_commit': revision,
                'source_note': 'Current working-tree source; per-file hashes identify actual content',
                'execution_note': 'Unexecuted fresh export; front notebook execution is a separate step',
                'source_notebook_sha256': digest(dest / 'submission.ipynb'),
                'upstream_path': 'ISSCC27/submitted_notebooks/opentcad_microrobot',
                'colab_tested': False,
                'controller_status': 'Executable mixed-abstraction system; full transistor-coupled startup failed and unresolved',
                'excluded': ['local reference PDFs', 'raw SPICE transients',
                             'externally supplied measurement CSVs', 'runtime local_runs and caches'],
                'portable_path_redactions': transformed,
                'files_sha256': payload_files(dest)}
    (dest / 'submission.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return dest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seal-execution', type=Path)
    args = parser.parse_args()
    if args.seal_execution:
        seal_execution(args.seal_execution)
        print(args.seal_execution)
    elif args.output:
        print(build(args.output))
    else:
        parser.error('Specify --output or --seal-execution')
