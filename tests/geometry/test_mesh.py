"""Smoke tests for gmsh-based 2D mesh generation."""
import numpy as np
import pytest
import pyvista as pv

from opentcad.geometry.formats import Material, MeshField
from opentcad.geometry.structure import Structure


def test_single_layer_smoke():
    mf = Structure(1.0).add_substrate("body", 0.5, Material.SI).to_meshfield(0.05)
    assert isinstance(mf, MeshField)
    assert mf.n_cells > 0
    assert mf.n_points > 0
    assert np.all(mf.material_ids == int(Material.SI))
    xmin, xmax, ymin, ymax, _, _ = mf.bounds
    assert xmin == pytest.approx(0.0, abs=1e-6)
    assert xmax == pytest.approx(1.0, abs=1e-6)
    assert ymin == pytest.approx(0.0, abs=1e-6)
    assert ymax == pytest.approx(0.5, abs=1e-6)


def test_multilayer_assigns_correct_materials():
    mf = (Structure(1.0, name="stack")
          .add_substrate("body", 0.3, Material.SI, doping_Na=1e15)
          .add_layer("oxide", 0.05, Material.SIO2)
          .add_layer("poly", 0.1, Material.POLY_SI, doping_Nd=1e20)
          .to_meshfield(0.04))
    ids = set(int(m) for m in mf.material_ids)
    assert ids == {int(Material.SI), int(Material.SIO2), int(Material.POLY_SI)}
    # Triangles only
    assert all(ct == pv.CellType.TRIANGLE for ct in mf.grid.celltypes)
    # Doping propagated from layer specs
    assert mf.Na.max() == pytest.approx(1e15)
    assert mf.Nd.max() == pytest.approx(1e20)


def test_region_overrides_material():
    """add_region with a different material should change cell material_id
    inside the override rectangle (used for source/drain n+ in NMOS)."""
    mf = (Structure(2.0, name="sd_override")
          .add_substrate("body", 0.5, Material.SI, doping_Na=1e17)
          .add_layer("oxide", 0.05, Material.SIO2)
          .add_region("source", 0.0, 0.5, 0.4, 0.55, Material.SI, doping_Nd=1e20)
          .to_meshfield(0.04))

    pts   = mf.points
    cells = mf.grid.cells.reshape(-1, 4)[:, 1:]
    cx = pts[cells, 0].mean(axis=1)
    cy = pts[cells, 1].mean(axis=1)
    mids = mf.material_ids

    # Cells inside the override rectangle must all be SI (not SIO2).
    inside = (cx <= 0.5) & (cy >= 0.4) & (cy <= 0.55)
    assert inside.sum() > 0
    assert np.all(mids[inside] == int(Material.SI)), (
        "Region with Material.SI should override SiO2 cells")

    # Cells in the oxide layer outside the override stay SiO2.
    oxide_outside = (cx > 0.6) & (cy > 0.5)
    assert oxide_outside.sum() > 0
    assert np.all(mids[oxide_outside] == int(Material.SIO2))

    # Doping override is also active inside the rectangle.
    in_node = (pts[:, 0] <= 0.5) & (pts[:, 1] >= 0.4) & (pts[:, 1] <= 0.55)
    assert mf.Nd[in_node].max() == pytest.approx(1e20)


def test_interface_refinement_increases_density_near_interface():
    """Cells touching the interface should be smaller than bulk cells."""
    mf = (Structure(1.0)
          .add_substrate("body", 0.5, Material.SI)
          .add_layer("top", 0.5, Material.SIO2)
          .to_meshfield(0.1))
    pts = mf.points
    # Triangle cell size (edge-length proxy): distance from first two vertices
    # per cell. Cells near y=0.5 should on average be smaller than cells far
    # from the interface.
    cells = mf.grid.cells.reshape(-1, 4)   # [3, n0, n1, n2]
    centroids_y = pts[cells[:, 1:], 1].mean(axis=1)
    edge = np.linalg.norm(pts[cells[:, 1]] - pts[cells[:, 2]], axis=1)
    near = edge[np.abs(centroids_y - 0.5) < 0.05]
    far = edge[np.abs(centroids_y - 0.5) > 0.2]
    assert near.mean() < far.mean()
