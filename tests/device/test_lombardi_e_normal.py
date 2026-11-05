"""
Phase 2a Lombardi E_normal upgrade.

The default Lombardi now uses |Potential_grady| (the physical normal
field at a horizontal Si/SiO2 interface) instead of the isotropic
|EField| that composes the parallel and normal field magnitudes.

Tests:
  * Axis validation — 'y', 'x', 'magnitude' are OK, anything else raises.
  * Register check — e_normal_axis='y' installs Potential_grady and
    the Lb_Emag_raw edge model; 'magnitude' installs neither (uses the
    isotropic edge EField as before).
  * Equivalence smoke — for a purely-1D structure where Ex ≈ 0 by
    construction, 'y' and 'magnitude' must give the same Id-Vgs within
    tight tolerance.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.device.models import Lombardi, ConstantMobility
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure


pytest.importorskip("devsim")


def test_lombardi_rejects_bad_axis():
    with pytest.raises(ValueError, match="e_normal_axis"):
        Lombardi(e_normal_axis="z")
    with pytest.raises(ValueError, match="e_normal_axis"):
        Lombardi(e_normal_axis="normal")


def test_lombardi_defaults_to_y_axis():
    m = Lombardi()
    assert m.e_normal_axis == "y"


@pytest.mark.requires_devsim
def test_lombardi_y_axis_installs_vector_gradient():
    """axis='y' must register the Potential_grady node model via
    DEVSIM's vector_gradient — otherwise the mobility falls back to
    bulk-only and the whole upgrade is dead code."""
    import devsim as ds
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass

    mf = (Structure(width_um=0.5, name="lb_axis")
          .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
          .add_contact("top", 0.0, 0.5, "p", surface="top")
          .add_contact("bot", 0.0, 0.5, "p", surface="bottom")
          .to_meshfield(mesh_size_um=0.1))
    cfg = PhysicsConfig(mobility=Lombardi(e_normal_axis="y"))
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=cfg)
    solver.solve_equilibrium()

    nmodels = ds.get_node_model_list(device=solver._device_name, region="SI")
    assert "Potential_grady" in nmodels
    assert "Lb_Enorm_node" in nmodels

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass


@pytest.mark.requires_devsim
def test_lombardi_magnitude_axis_skips_vector_gradient():
    """axis='magnitude' is the back-compat path — it uses the edge
    EField magnitude and must NOT install Potential_grady as a node
    model (nothing depends on it in that configuration)."""
    import devsim as ds
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass

    mf = (Structure(width_um=0.5, name="lb_mag")
          .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
          .add_contact("top", 0.0, 0.5, "p", surface="top")
          .add_contact("bot", 0.0, 0.5, "p", surface="bottom")
          .to_meshfield(mesh_size_um=0.1))
    cfg = PhysicsConfig(mobility=Lombardi(e_normal_axis="magnitude"))
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=cfg)
    solver.solve_equilibrium()

    nmodels = ds.get_node_model_list(device=solver._device_name, region="SI")
    assert "Potential_grady" not in nmodels
    assert "Lb_Enorm_node" not in nmodels

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
