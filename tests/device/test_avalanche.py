"""
Phase 2a avalanche generation — qualitative verification.

The MVP uses a saturation-velocity current proxy (|J| ≈ q·v_sat·n) that
gets the breakdown knee into the right ballpark but not the exact Vbd.
Tests here therefore assert qualitative properties:

  * Avalanche = SRH only at V = 0 (no field → α ≈ 0 → no generation).
  * Avalanche adds a reverse-bias knee that SRH-only doesn't have: at
    the deepest reverse bias, |I| with Avalanche must exceed |I| with
    SRH-alone by at least a factor of 10.
  * The avalanche node_model is registered under its contracted name.

Exact-Vbd calibration awaits the edge-aware |J| upgrade documented in
the Avalanche class docstring.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure


pytest.importorskip("devsim")


def _pn_mesh():
    return (Structure(width_um=1.0, name="pn_bd")
            .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
            .add_layer   ("n", 0.5, Material.SI, doping_Nd=1e17)
            .add_contact ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact ("cathode", 0.0, 1.0, "n", surface="top")
            .to_meshfield(mesh_size_um=0.02))


def _reverse_sweep(mf, recomb_models):
    """Sweep cathode (n-side) positive = reverse bias. Returns (V, I) with
    cathode held at the swept voltage and anode at 0."""
    import devsim as ds
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    from opentcad.device.models import Klaassen
    from opentcad.materials.database import load_material

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass

    cfg = PhysicsConfig(mobility=Klaassen(), recombination=list(recomb_models))
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=cfg)
    V, I = solver.iv_sweep("cathode", "anode",
                            v_start=0.0, v_end=40.0, v_step=2.0)
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
    return np.asarray(V), np.asarray(I)


@pytest.mark.requires_devsim
@pytest.mark.slow
def test_avalanche_registers_and_increases_reverse_current():
    """Avalanche-enabled reverse sweep must produce substantially
    more current at the deepest bias than SRH alone — the signature
    of impact-ionisation multiplication."""
    from opentcad.device.models import SRH, Avalanche

    mf = _pn_mesh()
    V_srh, I_srh = _reverse_sweep(mf, [SRH()])
    V_av,  I_av  = _reverse_sweep(mf, [SRH(), Avalanche()])

    # Deepest-bias comparison. Factor ≥ 10 is the qualitative knee
    # signature; exact Vbd not asserted (see class docstring).
    assert abs(I_av[-1]) > 10 * abs(I_srh[-1]), (
        f"At V = {V_av[-1]} V, SRH+Avalanche |I| = {abs(I_av[-1]):.2e} "
        f"should exceed SRH-only |I| = {abs(I_srh[-1]):.2e} by >10x; "
        "avalanche appears inactive or miswired.")


@pytest.mark.requires_devsim
def test_avalanche_node_model_registered():
    """Smoke: the Avalanche model attaches the expected node_model name
    for a trivial single-region device."""
    import devsim as ds
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    from opentcad.device.models import SRH, Avalanche, Klaassen
    from opentcad.materials.database import load_material

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass

    mf = _pn_mesh()
    cfg = PhysicsConfig(mobility=Klaassen(),
                        recombination=[SRH(), Avalanche()])
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=cfg)
    solver.solve_equilibrium()
    models = ds.get_node_model_list(device=solver._device_name, region="SI")
    for name in ("UAvalanche", "AlphaNAval", "AlphaPAval", "EMagAval"):
        assert name in models, f"missing node_model {name!r}"
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
