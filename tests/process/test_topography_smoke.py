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


# ---------------------------------------------------------------------------
# Windowed isotropic etch — the "curved trench" case.
#
# A single etch step with a window in [x0, x1] on a bare Si substrate.
# Expectation: the level-set drops to (initial - depth) inside the
# window, stays at the initial height far outside the window, and
# rounds smoothly (undercut) at the edges.
# ---------------------------------------------------------------------------

TRENCH_DEPTH_UM = 0.15
TRENCH_X0, TRENCH_X1 = 0.35, 0.65
TRENCH_INITIAL_Y_UM = 0.5


def _build_trench():
    struct = (Structure(width_um=1.0, name="curved_trench")
              .add_substrate("body", TRENCH_INITIAL_Y_UM, Material.SI))
    recipe = (Recipe("mask_and_etch")
              .etch(depth_um=TRENCH_DEPTH_UM,
                    window_x_um=(TRENCH_X0, TRENCH_X1)))
    return struct, recipe


def _sample_top(level_set, xmin=0.0, xmax=1.0):
    """Return (xs, ys) — the extracted polyline sorted by x, with
    the lower y kept at multi-valued x (matches mesh_bridge policy)."""
    nodes, _ = extract_surface_polyline(level_set)
    pts = np.asarray(nodes)
    x, y = pts[:, 0], pts[:, 1]
    keep = (x >= xmin - 1e-6) & (x <= xmax + 1e-6)
    x, y = x[keep], y[keep]
    order = np.argsort(x, kind="stable")
    return x[order], y[order]


def test_windowed_etch_floor_and_pristine_regions():
    """Inside the window, y sits at initial - depth (etch bottoms out).
    Well outside the window, y stays at the initial mask level."""
    struct, recipe = _build_trench()
    state = simulate(struct, recipe, grid_delta_um=0.005)
    xs, ys = _sample_top(state.layers[0].level_set)

    y_expected_floor = TRENCH_INITIAL_Y_UM - TRENCH_DEPTH_UM
    center_mask = (xs > TRENCH_X0 + 0.05) & (xs < TRENCH_X1 - 0.05)
    assert center_mask.any(), "no polyline nodes inside the window center"
    assert np.all(np.abs(ys[center_mask] - y_expected_floor) < 5e-3), (
        f"trench floor should sit at y={y_expected_floor}, got "
        f"y in [{ys[center_mask].min():.4f}, {ys[center_mask].max():.4f}]")

    # Far outside the undercut zone the mask must hold.
    pristine = xs < 0.10
    assert pristine.any()
    assert np.all(np.abs(ys[pristine] - TRENCH_INITIAL_Y_UM) < 1e-3), (
        f"unmasked regions should stay at y={TRENCH_INITIAL_Y_UM}, got "
        f"y in [{ys[pristine].min():.4f}, {ys[pristine].max():.4f}]")


def test_windowed_etch_produces_curved_undercut():
    """Between the pristine mask level and the etched floor there is a
    non-trivial transition zone — the classic isotropic-etch undercut.
    Verify that the profile *varies* (curvature) rather than being a
    step function, and that the undercut extends beyond the mask edge
    (i.e. eats sideways into the material)."""
    struct, recipe = _build_trench()
    state = simulate(struct, recipe, grid_delta_um=0.005)
    xs, ys = _sample_top(state.layers[0].level_set)

    y_floor = TRENCH_INITIAL_Y_UM - TRENCH_DEPTH_UM

    # Any x-node with y strictly between floor and initial is a
    # transition-zone point — count them on each side.
    transition = (ys > y_floor + 1e-3) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)
    assert transition.sum() >= 4, (
        f"expected >=4 profile points in the curved-undercut zone, got "
        f"{transition.sum()}. Profile is essentially a step function.")

    # Undercut extent: nodes with y below the mask level that sit past
    # the nominal window edge on each side.
    left_undercut  = xs[(xs < TRENCH_X0) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
    right_undercut = xs[(xs > TRENCH_X1) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
    assert left_undercut.size >= 3, "no undercut past the left mask edge"
    assert right_undercut.size >= 3, "no undercut past the right mask edge"

    # Undercut depth (lateral) — the etch is depth d, isotropic, so we
    # expect ~d of undercut at the deep end (quarter-circle). Require
    # at least half of that to survive discretization + boundary tol.
    lat_left  = TRENCH_X0 - left_undercut.min()
    lat_right = right_undercut.max() - TRENCH_X1
    assert lat_left  > 0.5 * TRENCH_DEPTH_UM, (
        f"left undercut only {lat_left*1000:.1f} nm — expected "
        f">{TRENCH_DEPTH_UM*1000*0.5:.0f} nm")
    assert lat_right > 0.5 * TRENCH_DEPTH_UM, (
        f"right undercut only {lat_right*1000:.1f} nm — expected "
        f">{TRENCH_DEPTH_UM*1000*0.5:.0f} nm")


def test_windowed_etch_profile_is_symmetric():
    """A window centered in the domain should give a mirror-symmetric
    trench profile — this catches numerical asymmetries in the Lax-
    Friedrichs advection or bugs in the VF's x-bounds check."""
    struct, recipe = _build_trench()
    state = simulate(struct, recipe, grid_delta_um=0.005)
    xs, ys = _sample_top(state.layers[0].level_set)

    x_center = 0.5 * (TRENCH_X0 + TRENCH_X1)

    # Sample the profile at ±dx around the center and compare y.
    dxs = np.linspace(0.05, 0.35, 12)
    ys_left  = np.interp(x_center - dxs, xs, ys)
    ys_right = np.interp(x_center + dxs, xs, ys)
    max_delta = float(np.max(np.abs(ys_left - ys_right)))
    assert max_delta < 8e-3, (
        f"trench profile is asymmetric: max |y(x)-y(-x)| = "
        f"{max_delta*1000:.1f} nm across the window center")


def _build_directional_trench(sidewall_ratio: float = 0.0):
    struct = (Structure(width_um=1.0, name="rie_trench")
              .add_substrate("body", TRENCH_INITIAL_Y_UM, Material.SI))
    recipe = (Recipe("rie_trench")
              .etch(depth_um=TRENCH_DEPTH_UM, model="directional",
                    window_x_um=(TRENCH_X0, TRENCH_X1),
                    sidewall_ratio=sidewall_ratio))
    return struct, recipe


def test_directional_trench_floor_and_no_undercut():
    """A pure directional etch (sidewall_ratio=0) reaches the same
    floor depth as the isotropic version but has essentially zero
    lateral undercut past the mask edges — the sidewalls stay vertical."""
    struct, recipe = _build_directional_trench(sidewall_ratio=0.0)
    state = simulate(struct, recipe, grid_delta_um=0.005)
    xs, ys = _sample_top(state.layers[0].level_set)

    y_floor = TRENCH_INITIAL_Y_UM - TRENCH_DEPTH_UM
    center = (xs > TRENCH_X0 + 0.05) & (xs < TRENCH_X1 - 0.05)
    assert np.all(np.abs(ys[center] - y_floor) < 5e-3), (
        f"RIE floor should be at y={y_floor}, got range "
        f"{ys[center].min():.4f}..{ys[center].max():.4f}")

    # Lateral undercut past each mask edge — RIE limit ⇒ essentially 0.
    left_undercut  = xs[(xs < TRENCH_X0) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
    right_undercut = xs[(xs > TRENCH_X1) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
    lat_left  = TRENCH_X0 - left_undercut.min()  if left_undercut.size else 0.0
    lat_right = right_undercut.max() - TRENCH_X1 if right_undercut.size else 0.0
    # Should be a small numerical smear from Lax-Friedrichs dissipation
    # at the sharp mask corner — well under the ~150 nm quarter-circle
    # the isotropic case gives at the same depth.
    assert lat_left  < 0.03, (
        f"Left undercut {lat_left*1000:.1f} nm — too large for a pure "
        "directional etch.")
    assert lat_right < 0.03, (
        f"Right undercut {lat_right*1000:.1f} nm — too large for a "
        "pure directional etch.")


def test_directional_undercut_below_isotropic_at_same_depth():
    """At the same window and depth, the isotropic quarter-circle
    should extend much further past the mask edge than the directional
    (RIE) profile — this is the qualitative difference between wet and
    dry etches. Ratio > 5× is a generous safety margin."""
    _, iso_recipe = _build_trench()
    struct_iso, _ = _build_trench()
    iso_state = simulate(struct_iso, iso_recipe, grid_delta_um=0.005)
    xs_i, ys_i = _sample_top(iso_state.layers[0].level_set)

    struct_dir, dir_recipe = _build_directional_trench(sidewall_ratio=0.0)
    dir_state = simulate(struct_dir, dir_recipe, grid_delta_um=0.005)
    xs_d, ys_d = _sample_top(dir_state.layers[0].level_set)

    def right_undercut(xs, ys):
        past = xs[(xs > TRENCH_X1) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
        return float(past.max() - TRENCH_X1) if past.size else 0.0

    u_iso = right_undercut(xs_i, ys_i)
    u_dir = right_undercut(xs_d, ys_d)
    assert u_iso > 5.0 * u_dir + 0.01, (
        f"Isotropic undercut {u_iso*1000:.1f} nm should be >>5× the "
        f"directional undercut {u_dir*1000:.1f} nm")


def test_directional_with_sidewall_ratio_gives_partial_undercut():
    """Setting sidewall_ratio between 0 and 1 mixes some chemical
    isotropy into the directional flux — the sidewalls now recede
    at a fraction of the top rate, so the undercut lands between the
    two limits."""
    struct, recipe = _build_directional_trench(sidewall_ratio=0.4)
    state = simulate(struct, recipe, grid_delta_um=0.005)
    xs, ys = _sample_top(state.layers[0].level_set)

    right_past = xs[(xs > TRENCH_X1) & (ys < TRENCH_INITIAL_Y_UM - 1e-3)]
    u = float(right_past.max() - TRENCH_X1) if right_past.size else 0.0
    # 40% sidewall etch at depth 150 nm ⇒ expect ~60 nm undercut,
    # bracketed to catch both "no undercut" (bug: iso term dropped) and
    # "full quarter-circle" (bug: directional term dropped).
    assert 0.02 < u < 0.12, (
        f"Undercut with sidewall_ratio=0.4 should sit between 20 and "
        f"120 nm, got {u*1000:.1f} nm")


def test_windowed_etch_meshfield_area_matches_removed_material():
    """The MeshField's Si area should equal (initial substrate area)
    minus the area of material removed by the etch. We can compute the
    removed area directly from the extracted top-surface polyline."""
    struct, recipe = _build_trench()
    state = simulate(struct, recipe, grid_delta_um=0.005)

    xs, ys = _sample_top(state.layers[0].level_set)
    # Area under the etched top surface = trapezoidal integral of y(x).
    # Removed area = (initial_top * width) - integral y(x) dx.
    initial_area = TRENCH_INITIAL_Y_UM * (xs[-1] - xs[0])
    remaining_area = float(np.trapezoid(ys, xs))
    expected_si_area = remaining_area
    assert 0.3 < expected_si_area < initial_area, (
        f"sanity: expected_si_area={expected_si_area:.4f}, "
        f"initial_area={initial_area:.4f}")

    mf = topography_to_meshfield(state, mesh_size_um=0.02)
    areas = mf.grid.compute_cell_sizes(length=False, area=True,
                                       volume=False).cell_data["Area"]
    got_si = float(areas[mf.material_ids == int(Material.SI)].sum())
    # Allow ~2% mesh discretization slop.
    assert got_si == pytest.approx(expected_si_area, rel=2e-2), (
        f"MeshField Si area {got_si:.4f} vs expected {expected_si_area:.4f} um^2")
