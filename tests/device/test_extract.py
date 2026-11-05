"""Threshold-voltage extraction on curves with known answers."""
import numpy as np
import pytest

from opentcad.device.extract import vth_constant_current, vth_max_gm


def test_max_gm_on_tanh_curve():
    # Id = 1 + tanh((V - 1)/0.2): gm peaks at V = 1 with Id* = 1 and
    # gm* = 5, so the tangent meets Id = 0 at V = 0.8.
    v = np.linspace(0.0, 2.0, 2001)
    i = 1.0 + np.tanh((v - 1.0) / 0.2)
    assert vth_max_gm(v, i, vds=0.05) == pytest.approx(0.8 - 0.025, abs=1e-5)


def test_max_gm_ignores_current_sign():
    v = np.linspace(0.0, 2.0, 401)
    i = 1.0 + np.tanh((v - 1.0) / 0.2)
    assert vth_max_gm(v, -i, 0.0) == pytest.approx(vth_max_gm(v, i, 0.0))


def test_max_gm_handles_uneven_steps():
    v = np.sort(np.concatenate([np.linspace(0, 2, 801), [0.9995, 1.0005]]))
    i = 1.0 + np.tanh((v - 1.0) / 0.2)
    assert vth_max_gm(v, i, 0.0) == pytest.approx(0.8, abs=1e-4)


def test_max_gm_rejects_peak_at_sweep_end():
    v = np.linspace(0.0, 1.0, 51)
    with pytest.raises(ValueError, match="last bias point"):
        vth_max_gm(v, np.exp(v), 0.05)


def test_constant_current_exact_for_exponential():
    # 80 mV/decade from 1 nA at 0.3 V: reaches 100 nA at 0.46 V. Log-linear
    # interpolation is exact for an exponential.
    v = np.linspace(0.0, 1.0, 37)
    i = 1e-9 * 10.0 ** ((v - 0.3) / 0.08)
    assert vth_constant_current(v, i, 1e-7) == pytest.approx(0.46, abs=1e-12)


def test_constant_current_bracketing_errors():
    v = np.linspace(0.0, 1.0, 11)
    i = 1e-9 * 10.0 ** v
    with pytest.raises(ValueError, match="never reaches"):
        vth_constant_current(v, i, 1.0)
    with pytest.raises(ValueError, match="first bias point"):
        vth_constant_current(v, i, 1e-12)


@pytest.mark.parametrize("vgs,ids", [
    ([0.0, 0.2, 0.1, 0.3], [1, 2, 3, 4]),     # not increasing
    ([0.0, 0.1], [1, 2]),                     # too short
    ([0.0, 0.1, 0.2], [1, 2]),                # length mismatch
])
def test_input_validation(vgs, ids):
    with pytest.raises(ValueError):
        vth_max_gm(vgs, ids, 0.05)
