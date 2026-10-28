"""Verify emitted waveform invariants with the actual Verilog simulator."""
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="optional Icarus Verilog tools")
def test_phase_period_duty_lag_and_asynchronous_restart(tmp_path):
    rtl = Path(__file__).resolve().parents[2] / "examples/microrobot/rtl"
    compile_result = subprocess.run(["iverilog", "-g2012", "-s", "phase_generator_tb",
        "-o", str(tmp_path / "phase"), str(rtl / "phase_generator.v"),
        str(rtl / "phase_generator_tb.v")], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run(["vvp", str(tmp_path / "phase")], capture_output=True, text=True)
    assert run.returncode == 0 and "PASS" in run.stdout, run.stdout + run.stderr
    samples = np.array([[int(x) for x in line.split()[1:]] for line in run.stdout.splitlines()
                        if line.startswith("SAMPLE ")])
    a, b, valid = samples[:, 1:].T
    assert np.all(valid == 1)
    assert np.mean(a) == np.mean(b) == 0.5
    ra = np.flatnonzero(np.diff(a) == 1) + 1
    rb = np.flatnonzero(np.diff(b) == 1) + 1
    assert np.all(np.diff(ra) == 16) and np.all(np.diff(rb) == 16)
    lags = [rise - ra[ra < rise][-1] for rise in rb if np.any(ra < rise)]
    assert len(lags) >= 4 and np.all(np.array(lags) == 4)
