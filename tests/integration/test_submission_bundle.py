"""Portability and immutable-input checks for the curated submission."""
import hashlib
import json
import subprocess
import sys

import pytest

from tools.build_microrobot_submission import build, seal_execution


def test_export_imports_only_bundled_project_source(tmp_path):
    folder = build(tmp_path / 'standalone')
    assert not (folder / '.git').exists()
    assert not list(folder.rglob('*.pdf'))
    assert not list(folder.rglob('*.dat'))
    assert not list(folder.rglob('s2e_digitized.csv'))
    assert not (folder / 'examples/microrobot/local_references').exists()
    manifest = json.loads((folder / 'submission.json').read_text())
    for name, checksum in manifest['files_sha256'].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == checksum
    script = '''
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import bootstrap
root, app = bootstrap.activate()
import opentcad
from examples.microrobot import tcad_demo
assert Path(opentcad.__file__).resolve().is_relative_to(root)
assert Path(tcad_demo.__file__).resolve().is_relative_to(root)
assert (app/'results/pv.json').is_file()
assert (app/'results/clock_final/summary.json').is_file()
assert not (app/'data/s2e_digitized.csv').exists()
print('standalone imports verified')
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(folder)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'standalone imports verified' in result.stdout


def test_sealing_rejects_reference_drift(tmp_path):
    folder = build(tmp_path / 'drift')
    reference = folder / 'examples/microrobot/results/pv.json'
    reference.write_text(reference.read_text() + '\n')
    (folder / 'execution_validation.json').write_text(json.dumps({
        'archive_files_changed': [], 'source_files_changed': []}))
    with pytest.raises(AssertionError, match='Unapproved package drift'):
        seal_execution(folder)
