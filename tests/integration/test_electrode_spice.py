"""Independent analytical checks for the optional SPICE electrode interface."""

from pathlib import Path
import shutil

import numpy as np
import pytest

from examples.microrobot.electrical import run_deck

pytestmark = pytest.mark.skipif(not shutil.which("ngspice"), reason="optional ngspice")
MODEL = Path(__file__).resolve().parents[2] / "examples/microrobot/circuits/electrochemical.spice"


def test_double_layer_rc_limit_without_adsorption(tmp_path):
    deck = (
        "* Analytical electrode RC limit\n"
        + MODEL.read_text()
        + """
Vmetal metal 0 PWL(0 0 1u 0 1.01u 0.1)
Xinterface metal solution theta micro_electrode cdl=40p qmax=0 rf=10g
Rsolution solution 0 1meg
.options reltol=1e-6 abstol=1e-16 method=gear maxord=2
.control
set wr_vecnames
set wr_singlescale
tran 0.2u 400u 0 0.2u
wrdata result.dat v(metal,solution)
quit
.endc
.end
"""
    )
    run_deck(tmp_path, deck)
    t, eta = np.loadtxt(tmp_path / "result.dat", skiprows=1).T
    select = t > 2e-6
    tau = 40e-12 / (1 / 1e6 + 1 / 10e9)
    expected = 0.1 * 10e9 / (1e6 + 10e9) * (1 - np.exp(-(t - 1.005e-6) / tau))
    assert np.max(abs(eta[select] - expected[select])) < 5e-5


def test_adsorption_kinetics_and_terminal_charge_balance(tmp_path):
    deck = (
        "* Independently check adsorption relaxation and delivered charge\n"
        + MODEL.read_text()
        + """
Vmetal metal 0 PWL(0 0 1m 0 1.001m 0.2)
Xinterface metal 0 theta micro_electrode cdl=40p qmax=260p tau=20m rf=1e20
.options reltol=1e-6 abstol=1e-16 method=gear maxord=2
.control
set wr_vecnames
set wr_singlescale
tran 10u 101m 0 10u
wrdata result.dat v(theta) i(Vmetal)
quit
.endc
.end
"""
    )
    run_deck(tmp_path, deck)
    t, theta, current = np.loadtxt(tmp_path / "result.dat", skiprows=1).T
    equilibrium = 1 / (1 + np.exp(-0.2 / 0.08))
    expected = equilibrium + (0.5 - equilibrium) * np.exp(-(t - 1.0005e-3) / 0.02)
    assert np.max(abs(theta[t > 0.002] - expected[t > 0.002])) < 2e-5
    terminal_charge = -np.trapezoid(current, t)
    stored_charge = 40e-12 * 0.2 + 260e-12 * (theta[-1] - 0.5)
    assert terminal_charge == pytest.approx(stored_charge, rel=2e-3)
