"""
run_recipe with topography steps: the structure's doping, contacts and
metadata are carried onto the processed mesh (structure_transfer), and the
mesh is conformal at material interfaces (one node shared, not two).
"""
import warnings

import numpy as np
import pytest

pytest.importorskip("viennals")      # every test here runs topography

from scipy.spatial import cKDTree  # noqa: E402

from opentcad.geometry.formats import Material  # noqa: E402
from opentcad.geometry.structure import Structure  # noqa: E402
from opentcad.process import run_recipe  # noqa: E402
from opentcad.process.topography import Recipe  # noqa: E402


def _wafer(name="w"):
    return (Structure(width_um=1.0, name=name)
            .add_substrate("body", 0.5, Material.SI, doping_Na=1e17)
            .add_contact("gate", 0.2, 0.8, "body", surface="top")
            .add_contact("sub", 0.0, 1.0, "body", surface="bottom"))


def _run(structure, recipe):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = run_recipe(structure, recipe, mesh_size_um=0.03)
    return out.meshfield, [str(w.message) for w in caught]


def test_deposit_keeps_doping_places_contacts_and_shares_interface_nodes():
    mf, msgs = _run(_wafer("dep"), Recipe().deposit(Material.SIO2, 0.01))
    pts = np.asarray(mf.points)[:, :2]
    mats = np.asarray(mf.material_ids)
    tris = np.asarray(mf.grid.cells_dict[5])
    si = np.unique(tris[mats == int(Material.SI)])
    ox_only = np.setdiff1d(np.unique(tris[mats == int(Material.SIO2)]), si)
    assert np.allclose(mf.Na[si], 1e17)                  # silicon keeps its doping
    assert np.all(mf.Na[ox_only] == 0)                   # deposited oxide gets none
    # Conformal: no coincident duplicates; Si and SiO2 share the interface.
    assert not cKDTree(pts).query_pairs(1e-9)
    assert len(np.intersect1d(si, np.unique(tris[mats == int(Material.SIO2)]))) > 0
    # Contacts: gate on the final top (oxide), substrate on the floor.
    names = {c.name: c for c in mf.contacts}
    assert np.allclose(pts[names["gate"].boundary_nodes, 1], 0.51, atol=1e-6)
    assert np.allclose(pts[names["sub"].boundary_nodes, 1], 0.0, atol=1e-9)
    assert mf.metadata["contact_materials"] == {"gate": ["SiO2"], "sub": ["Silicon"]}
    assert mf.metadata["structure_name"] == "dep"
    assert any("Contact 'gate'" in m and "insulator" in m for m in msgs)


def test_oxidation_consumed_silicon_does_not_lend_doping_to_the_oxide():
    mf, _ = _run(_wafer("ox"), Recipe().oxidize(1000, 1800, ambient="wet"))
    mats = np.asarray(mf.material_ids)
    tris = np.asarray(mf.grid.cells_dict[5])
    si = np.unique(tris[mats == int(Material.SI)])
    ox_only = np.setdiff1d(np.unique(tris[mats == int(Material.SIO2)]), si)
    pts = np.asarray(mf.points)
    assert pts[ox_only, 1].min() < 0.5                   # oxide grew into the old Si
    assert np.all(mf.Na[ox_only] == 0)
    assert np.allclose(mf.Na[si], 1e17)


def test_regions_on_the_topography_path_warn():
    s = _wafer("reg").add_region("well", 0.0, 0.5, 0.3, 0.5, Material.SI, doping_Nd=1e18)
    mf, msgs = _run(s, Recipe().deposit(Material.SIO2, 0.01))
    assert any("regions (well)" in m for m in msgs)
    pts = np.asarray(mf.points)
    inside = (pts[:, 0] < 0.45) & (pts[:, 1] > 0.35) & (pts[:, 1] < 0.45)
    assert np.allclose(mf.Nd[inside], 1e18)             # Si region doping still applies


@pytest.mark.requires_devsim
def test_deposited_mos_capacitor_matches_the_layered_one():
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material
    params = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    mf, _ = _run(_wafer("mosdep"), Recipe().deposit(Material.SIO2, 0.01))
    dep = DeviceSolver(mf, params)
    _, c_dep = dep.cv_sweep("gate", "sub", -1.0, 1.0, 0.5)
    dep.close()      # DEVSIM solves every live device: drop this one first
    ref = (Structure(width_um=1.0, name="mosref")
           .add_substrate("body", 0.5, Material.SI, doping_Na=1e17)
           .add_layer("ox", 0.01, Material.SIO2)
           .add_contact("gate", 0.2, 0.8, "ox", surface="top")
           .add_contact("sub", 0.0, 1.0, "body", surface="bottom")).to_meshfield(0.03)
    _, c_ref = DeviceSolver(ref, params).cv_sweep("gate", "sub", -1.0, 1.0, 0.5)
    assert min(c_dep) > 0                       # the oxide couples (was 0 before)
    assert np.allclose(c_dep, c_ref, rtol=0.1)
