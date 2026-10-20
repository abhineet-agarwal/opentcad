"""
Phase 2 orchestrator — apply_doping_recipe + run_recipe.

Two groups of tests:

  1. apply_doping_recipe — walks the Implant steps of a Recipe over an
     already-meshed MeshField. Covers empty / single / multi-implant
     recipes, mixed recipes (topography steps ignored), and verifies
     the diagnostic result object.

  2. run_recipe — top-level orchestrator that stitches
     simulate + topography_to_meshfield + apply_doping_recipe for the
     three canonical paths (doping-only shortcut, topography-only
     passthrough, mixed full pipeline).
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process import (
    RecipeRunResult,
    apply_doping_recipe,
    run_recipe,
)
from opentcad.process.doping import DopingRecipeResult
from opentcad.process.topography import Recipe


# ---------------------------------------------------------------------------
# apply_doping_recipe
# ---------------------------------------------------------------------------

def _bare_si(width_um=2.0, body_um=0.5, mesh=0.015):
    return (Structure(width_um=width_um, name="t")
            .add_substrate("body", body_um, Material.SI, doping_Na=1e17)
            .to_meshfield(mesh_size_um=mesh))


def test_dispatch_empty_recipe_is_noop():
    """An empty recipe leaves the MeshField's doping untouched."""
    mf = _bare_si()
    nd_before = float(mf.Nd.max())
    na_before = float(mf.Na.max())
    res = apply_doping_recipe(mf, Recipe("empty"))
    assert isinstance(res, DopingRecipeResult)
    assert res.n_implants == 0
    assert float(mf.Nd.max()) == nd_before
    assert float(mf.Na.max()) == na_before


def test_dispatch_topography_only_recipe_is_noop_for_doping():
    """A recipe with only topography steps touches no doping."""
    mf = _bare_si()
    nd_before = float(mf.Nd.max())
    res = apply_doping_recipe(
        mf, Recipe().deposit(Material.SIO2, 0.01).etch(0.005))
    # Implants fired: 0. Doping unchanged.
    assert res.n_implants == 0
    assert float(mf.Nd.max()) == nd_before


def test_dispatch_single_implant_matches_direct_call():
    """apply_doping_recipe with one implant is equivalent to calling
    apply_implant directly."""
    from opentcad.process.doping import apply_implant
    mf_dispatch = _bare_si()
    mf_direct   = _bare_si()

    recipe = Recipe().implant("As", 30, 1e15, window_x_um=(0.0, 0.5))
    res = apply_doping_recipe(mf_dispatch, recipe)
    assert res.n_implants == 1

    apply_implant(mf_direct, "As", 30, 1e15, window_x_um=(0.0, 0.5))
    assert float(mf_dispatch.Nd.max()) == pytest.approx(
        float(mf_direct.Nd.max()), rel=1e-9)


def test_dispatch_multi_implant_accumulates_in_order():
    """Three implants in order: As-shallow, As-deep, B-counter.
    Both species end up in the right field, implants compose."""
    mf = _bare_si()
    recipe = (Recipe("chain")
              .implant("As", 30,  1e15, window_x_um=(0.0, 0.5))
              .implant("As", 100, 1e15, window_x_um=(0.0, 0.5))
              .implant("B",  30,  2e14, window_x_um=(0.0, 0.5)))
    res = apply_doping_recipe(mf, recipe)
    assert res.n_implants == 3

    # As implants add to Nd, B adds to Na. Pre-existing p-body Na=1e17
    # is still there plus the B contribution.
    assert float(mf.Nd.max()) > 1e20                   # degenerate n+ peak
    assert float(mf.Na.max()) > 1e17 + 1e18            # B tail above p-body
    # Species → correct field is also recorded in the diagnostic:
    assert [r.added_to for r in res.implants] == ["Nd", "Nd", "Na"]
    assert [r.species for r in res.implants] == [
        "arsenic", "arsenic", "boron"]


def test_dispatch_mixed_recipe_skips_topography_cleanly():
    """A mixed recipe with topography interleaved applies only its
    Implant steps; topography steps pass through silently."""
    mf = _bare_si()
    recipe = (Recipe("mixed")
              .deposit(Material.SIO2, 0.005)
              .implant("As", 30, 1e15)
              .etch(0.002)
              .implant("B", 30, 1e13))
    res = apply_doping_recipe(mf, recipe)
    assert res.n_implants == 2
    assert float(mf.Nd.max()) > 0
    assert float(mf.Na.max()) > 1e17


# ---------------------------------------------------------------------------
# run_recipe orchestrator
# ---------------------------------------------------------------------------

def _two_layer_si():
    """A substrate + oxide stack used for the orchestrator tests."""
    return (Structure(width_um=1.0, name="rr")
            .add_substrate("p", 0.3, Material.SI, doping_Na=1e17)
            .add_layer("oxide", 0.01, Material.SIO2))


def test_run_recipe_doping_only_uses_structure_meshfield_shortcut():
    """A recipe with no topography steps should skip simulate() and
    go straight from Structure.to_meshfield; topography_state is None."""
    struct = _two_layer_si()
    out = run_recipe(struct, Recipe().implant("As", 30, 1e14),
                     mesh_size_um=0.03)
    assert isinstance(out, RecipeRunResult)
    assert out.topography_state is None            # shortcut path taken
    assert out.doping_result.n_implants == 1
    assert float(out.meshfield.Nd.max()) > 0
    # Materials preserved from the Structure.
    materials = {int(m) for m in out.meshfield.material_ids}
    assert int(Material.SI)   in materials
    assert int(Material.SIO2) in materials


def test_run_recipe_topography_only_populates_state_but_no_doping():
    """A topography-only recipe runs the level-set path; no implants."""
    struct = (Structure(width_um=1.0, name="rr")
              .add_substrate("si", 0.3, Material.SI))
    out = run_recipe(struct, Recipe().oxidize(1000, 600, "dry"),
                     grid_delta_um=0.01, mesh_size_um=0.03)
    assert out.topography_state is not None
    assert out.doping_result.n_implants == 0
    assert float(out.meshfield.Nd.max()) == 0.0
    assert float(out.meshfield.Na.max()) == 0.0
    # Oxidation added an SiO2 layer.
    materials = {int(m) for m in out.meshfield.material_ids}
    assert int(Material.SI)   in materials
    assert int(Material.SIO2) in materials


def test_run_recipe_mixed_pipeline_closes_the_loop():
    """Full pipeline: topography step + implant chain. Verify both
    the TopographyState and the MeshField doping were produced."""
    struct = (Structure(width_um=1.0, name="rr")
              .add_substrate("p", 0.3, Material.SI, doping_Na=1e17)
              .add_region("sw", 0.0, 0.5, 0.2, 0.3, Material.SI))
    recipe = (Recipe("mixed")
              .oxidize(900, 600, "dry")
              .implant("As", 30,  1e15, window_x_um=(0.0, 0.5))
              .implant("As", 100, 1e15, window_x_um=(0.0, 0.5)))
    out = run_recipe(struct, recipe, grid_delta_um=0.01, mesh_size_um=0.03)
    assert out.topography_state is not None
    assert out.doping_result.n_implants == 2

    mf = out.meshfield
    # Materials: Si (substrate) + SiO2 (grown).
    materials = {int(m) for m in mf.material_ids}
    assert int(Material.SI)   in materials
    assert int(Material.SIO2) in materials
    # Doping: Na preserved for p-body, Nd populated inside the S/D window.
    assert float(mf.Nd.max()) > 1e19
    pts = np.asarray(mf.grid.points)[:, :2]
    in_window = (pts[:, 0] < 0.5) & (pts[:, 1] > 0.1)
    assert float(mf.Nd[in_window].max()) > 1e19
    far_outside = pts[:, 0] > 0.9
    assert float(mf.Nd[far_outside].max()) < 1e17   # mask holding


def test_run_recipe_defaults_are_sensible():
    """Running without any kwarg overrides should produce a usable
    MeshField for a trivial doping-only recipe."""
    struct = (Structure(width_um=0.5, name="rr")
              .add_substrate("si", 0.3, Material.SI, doping_Na=1e16))
    out = run_recipe(struct, Recipe().implant("P", 30, 1e13))
    assert out.meshfield.n_cells > 0
    assert float(out.meshfield.Nd.max()) > 0
