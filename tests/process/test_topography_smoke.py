"""
Milestone 1.1a smoke test — a Recipe drives ViennaLS to advance the
topography, and the mesh bridge produces a MeshField the device layer
would accept.

We build a bare Si substrate, deposit a 50 nm SiO2 conformal film,
isotropically etch 20 nm off the top, then check:

  * the recipe DSL round-trips as expected
  * the level-set stack has two materials, at the right heights
  * the resulting MeshField has both material tags with cell counts
    consistent with the physical layer areas
  * MeshField satisfies its own invariants (material_id present) — so it
    can be handed to any downstream module without further massage.
"""
import numpy as np
import pytest

from opentcad.geometry.formats import Material, MeshField
from opentcad.geometry.structure import Structure


pytest.importorskip("viennals")

from opentcad.process.topography import (
    Recipe, simulate, topography_to_meshfield, extract_surface_polyline,
)


def _build_recipe():
    struct = (Structure(width_um=1.0, name="topo_smoke")
              .add_substrate("body", 0.5, Material.SI))
    recipe = (Recipe("deposit_then_etch")
              .deposit(Material.SIO2, 0.05)
              .etch(0.02))
    return struct, recipe


def test_recipe_dsl_records_steps_in_order():
    """The Recipe is pure data — steps are appended in call order and
    the summary is stable across runs."""
    _, recipe = _build_recipe()
    assert len(recipe) == 2
    steps = list(recipe)
    assert steps[0].material == Material.SIO2
    assert steps[0].thickness_um == pytest.approx(0.05)
    assert steps[0].model == "conformal"
    assert steps[1].depth_um == pytest.approx(0.02)
    assert steps[1].model == "isotropic"
    # summary is human-readable
    lines = recipe.summary().splitlines()
    assert "deposit 50.0 nm of SIO2" in lines[1]
    assert "etch 20.0 nm" in lines[2]


def test_topography_stack_heights_match_process_arithmetic():
    """Si top stays at 0.5 um; SiO2 top ends at 0.5 + 0.05 - 0.02 =
    0.53 um. Level-sets must sit at those y values everywhere across x
    (planar deposit + planar etch, no masking)."""
    struct, recipe = _build_recipe()
    state = simulate(struct, recipe, grid_delta_um=0.01)

    assert len(state.layers) == 2
    assert state.layers[0].material == Material.SI
    assert state.layers[1].material == Material.SIO2

    # Extract each layer's top polyline and check y is constant + right.
    nodes_si, _ = extract_surface_polyline(state.layers[0].level_set)
    ys_si = np.array([n[1] for n in nodes_si])
    assert np.allclose(ys_si, 0.5, atol=1e-3), \
        f"Si top expected at 0.5 um, got y range "\
        f"{ys_si.min():.4f}..{ys_si.max():.4f}"

    nodes_ox, _ = extract_surface_polyline(state.layers[1].level_set)
    ys_ox = np.array([n[1] for n in nodes_ox])
    assert np.allclose(ys_ox, 0.53, atol=1e-3), \
        f"SiO2 top expected at 0.53 um, got y range "\
        f"{ys_ox.min():.4f}..{ys_ox.max():.4f}"


def test_meshfield_has_both_materials_and_expected_areas():
    """Sum of triangle areas per material should match the physical
    layer area exactly (this doesn't depend on how gmsh chooses to
    refine — thin layers get more, smaller triangles but the total
    area stays the same)."""
    struct, recipe = _build_recipe()
    state = simulate(struct, recipe, grid_delta_um=0.01)
    mf = topography_to_meshfield(state, mesh_size_um=0.05)

    assert isinstance(mf, MeshField)
    assert mf.n_cells > 0
    assert "material_id" in mf.grid.cell_data

    si_cells = int((mf.material_ids == int(Material.SI)).sum())
    ox_cells = int((mf.material_ids == int(Material.SIO2)).sum())
    assert si_cells > 0, "no Si cells in mesh"
    assert ox_cells > 0, "no SiO2 cells in mesh"

    # Physical layer areas [um^2] over the 1-um-wide window.
    exp_si = 1.0 * 0.5              # Si: 0.5 um thick
    exp_ox = 1.0 * (0.05 - 0.02)    # SiO2: 30 nm after etch

    areas = mf.grid.compute_cell_sizes(length=False, area=True,
                                       volume=False).cell_data["Area"]
    got_si = float(areas[mf.material_ids == int(Material.SI)].sum())
    got_ox = float(areas[mf.material_ids == int(Material.SIO2)].sum())
    assert got_si == pytest.approx(exp_si, rel=1e-3), (
        f"Si area {got_si:.4f} vs expected {exp_si:.4f} um^2")
    assert got_ox == pytest.approx(exp_ox, rel=1e-2), (
        f"SiO2 area {got_ox:.4f} vs expected {exp_ox:.4f} um^2")


def test_meshfield_bounds_align_with_substrate_top_and_deposit_thickness():
    """Domain floor should be at y=0 (substrate bottom) and domain
    ceiling at y=0.53 (post-etch SiO2 top). Any drift means we've
    silently thickened or shrunk a material somewhere in the pipeline."""
    struct, recipe = _build_recipe()
    state = simulate(struct, recipe, grid_delta_um=0.01)
    mf = topography_to_meshfield(state, mesh_size_um=0.05)

    xmin, xmax, ymin, ymax, _, _ = mf.bounds
    assert xmin == pytest.approx(0.0, abs=1e-4)
    assert xmax == pytest.approx(1.0, abs=1e-4)
    assert ymin == pytest.approx(0.0, abs=1e-4)
    assert ymax == pytest.approx(0.53, abs=2e-3), \
        f"Post-etch top at y={ymax:.4f}, expected 0.530 um"
