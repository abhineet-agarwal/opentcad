"""
Phase 2a transient DC — pn diode turn-on ramp.

Qualitative checks on the `transient_sweep` API:
  * Sweep returns (times, {contact: I_history}) of matching length.
  * A monotone 0.1 → 0.7 V forward-bias ramp over 10 ns drives the
    diode current up through turn-on (|I_final| / |I_initial| ≫ 1e6).
  * Bad input shapes raise the expected validation errors.
  * A callable schedule equals an array of the same evaluations.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure


pytest.importorskip("devsim")


def _pn():
    return (Structure(width_um=1.0, name="pn_tr")
            .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
            .add_layer   ("n", 0.5, Material.SI, doping_Nd=1e17)
            .add_contact ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact ("cathode", 0.0, 1.0, "n", surface="top")
            .to_meshfield(mesh_size_um=0.03))


def _fresh_solver():
    import devsim as ds
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material
    return DeviceSolver(_pn(), {"Silicon": load_material("Si")})


@pytest.mark.requires_devsim
@pytest.mark.slow
def test_transient_ramp_drives_diode_through_turn_on():
    """0.1 V → 0.7 V linear ramp over 10 ns must produce the ~1e9×
    forward-current rise characteristic of a Si pn diode."""
    import devsim as ds
    solver = _fresh_solver()
    times = np.linspace(0, 10e-9, 51)
    V = np.interp(times, [0, 10e-9], [0.1, 0.7])
    t, I = solver.transient_sweep({"anode": V}, times,
                                    measure_contacts=["anode"])

    assert len(t) == len(times)
    assert "anode" in I
    assert len(I["anode"]) == len(times)

    I_init = abs(I["anode"][0])
    I_final = abs(I["anode"][-1])
    assert I_final / max(I_init, 1e-20) > 1e6, (
        f"Ramp should drive turn-on: |I0|={I_init:.2e}, "
        f"|I_end|={I_final:.2e}")
    assert I_final > 1e-3, (
        f"At V=0.7 the diode should deliver >1 mA/cm, got "
        f"{I_final:.2e}")

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass


@pytest.mark.requires_devsim
def test_transient_callable_schedule_matches_array():
    """Callable waveforms and array waveforms with the same samples
    must produce identical current traces."""
    import devsim as ds
    times = np.linspace(0, 2e-9, 11)

    # Callable schedule
    s1 = _fresh_solver()
    t1, I1 = s1.transient_sweep({"anode": lambda tt: 0.3 + 0.1 * tt / 2e-9},
                                  times, measure_contacts=["anode"])
    # Equivalent array
    s2 = _fresh_solver()
    V = 0.3 + 0.1 * times / 2e-9
    t2, I2 = s2.transient_sweep({"anode": V}, times,
                                  measure_contacts=["anode"])

    assert len(I1["anode"]) == len(I2["anode"])
    for a, b in zip(I1["anode"], I2["anode"]):
        rel = abs(a - b) / max(abs(a), abs(b), 1e-20)
        assert rel < 1e-6, f"callable vs array disagree: {a} vs {b}"

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass


@pytest.mark.requires_devsim
def test_transient_rejects_bad_inputs():
    """Validation: non-monotone times, mismatched array shapes, and
    unknown integrator must each raise ValueError up front."""
    solver = _fresh_solver()

    with pytest.raises(ValueError, match="strictly increasing"):
        solver.transient_sweep({"anode": lambda t: 0.1},
                                 np.array([0.0, 1e-9, 5e-10, 2e-9]))

    with pytest.raises(ValueError, match="at least 2 points"):
        solver.transient_sweep({}, np.array([0.0]))

    with pytest.raises(ValueError, match="expected"):
        solver.transient_sweep({"anode": np.array([0.1, 0.2])},
                                 np.array([0.0, 1e-9, 2e-9]))

    with pytest.raises(ValueError, match="integrator"):
        solver.transient_sweep({"anode": lambda t: 0.1},
                                 np.array([0.0, 1e-9]),
                                 integrator="rk4")

    import devsim as ds
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
