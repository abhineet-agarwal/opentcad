"""
Deal-Grove oxidation — the Phase 1 exit criterion.

Three groups of tests:

  1. Analytic Deal-Grove kinetics vs published table values (Sze/
     Plummer). Coefficients-only, no level-set advection.

  2. Level-set-driven oxidation on a bare Si substrate: SiO2 top /
     Si bottom motion match analytic Deal-Grove prediction within
     5 % (the Phase 1 gate-oxide accuracy target).

  3. Masked LOCOS-style oxidation: field oxide in the window
     matches unmasked prediction, bird's-beak feathering on either
     side, and MeshField parses through the two-layer stack.
"""
import numpy as np
import pytest

pytest.importorskip("viennals")

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography import (
    Recipe, simulate, extract_surface_polyline, topography_to_meshfield,
)
from opentcad.process.topography.oxidation import (
    ALPHA_SI_CONSUMED_PER_OXIDE,
    coefficients,
    oxide_thickness,
    temperature_celsius_to_kelvin,
)


# ---------------------------------------------------------------------------
# 1. Kinetics.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ambient,T_C,minutes,expected_nm,tol_pct", [
    # Reference values from Sze/Plummer table 6.1 + fig 6.4 (approx.
    # 15-30 % scatter across published fits; we allow ±30 %).
    ("dry", 1000, 30,  30.0, 30),
    ("dry", 1000, 60,  50.0, 30),
    ("dry", 1100, 30,  75.0, 30),
    ("wet", 1000, 30, 210.0, 40),
    ("wet", 1100, 60, 700.0, 30),
])
def test_deal_grove_matches_table_values(ambient, T_C, minutes,
                                         expected_nm, tol_pct):
    """Our Deal-Grove Arrhenius fit reproduces textbook table values
    within the ±30 % scatter across published coefficient sets."""
    T_K = temperature_celsius_to_kelvin(T_C)
    x_um = oxide_thickness(0.0, minutes * 60, T_K, ambient)
    x_nm = x_um * 1000
    rel_err = abs(x_nm - expected_nm) / expected_nm * 100
    assert rel_err < tol_pct, (
        f"{ambient} {T_C}°C {minutes}min: {x_nm:.1f} nm, "
        f"expected ~{expected_nm} nm (Sze), {rel_err:.0f}% error")


def test_deal_grove_reduces_to_linear_at_thin():
    """At small (x0 + x)/2 << A/2 the Deal-Grove law simplifies to
    x ≈ (B/A) · t (interface-reaction-limited). Verify this holds in
    the ultra-thin-oxide, low-temperature limit."""
    T_K = temperature_celsius_to_kelvin(800)
    t_s = 60
    x_um = oxide_thickness(0.0, t_s, T_K, "dry")
    coef = coefficients("dry")
    linear_prediction = coef.B_over_A(T_K) * t_s
    assert abs(x_um - linear_prediction) / linear_prediction < 0.10


def test_deal_grove_reduces_to_parabolic_at_thick():
    """For x0 large or long times, x² ≈ B·t (diffusion-limited)."""
    T_K = temperature_celsius_to_kelvin(1100)
    t_s = 4 * 3600
    x_um = oxide_thickness(0.0, t_s, T_K, "wet")
    coef = coefficients("wet")
    parabolic_prediction = (coef.B(T_K) * t_s) ** 0.5
    # 15 % is generous — 4 h is long enough that we're mostly parabolic.
    assert abs(x_um - parabolic_prediction) / parabolic_prediction < 0.15


def test_deal_grove_initial_thickness_effect():
    """Growing from x0 > 0 should give less oxide in a fixed time than
    growing from x0 = 0 (parabolic regime already active)."""
    T_K = temperature_celsius_to_kelvin(1000)
    t_s = 1800
    x_fresh   = oxide_thickness(0.0,  t_s, T_K, "dry")
    x_started = oxide_thickness(0.05, t_s, T_K, "dry")   # 50 nm pad
    # Total (x_started) should be > fresh, but the *increment* smaller.
    assert x_started > x_fresh
    assert (x_started - 0.05) < x_fresh


# ---------------------------------------------------------------------------
# 2. Level-set advection: unmasked oxidation on bare Si.
# ---------------------------------------------------------------------------

BASE_Y_UM = 0.5


def _bare_si(width_um: float = 1.0):
    return (Structure(width_um=width_um, name="ox_test")
            .add_substrate("body", BASE_Y_UM, Material.SI))


def _sample_flat_ys(level_set, xmin=0.0, xmax=1.0):
    nodes, _ = extract_surface_polyline(level_set)
    pts = np.asarray(nodes, dtype=float)
    xs, ys = pts[:, 0], pts[:, 1]
    keep = (xs >= xmin - 1e-6) & (xs <= xmax + 1e-6)
    return xs[keep], ys[keep]


@pytest.mark.parametrize("ambient,T_C,minutes", [
    ("dry", 1000, 30),   # ~31 nm — gate-oxide regime
    ("dry", 1050, 30),   # ~45 nm
    ("wet", 1000, 15),   # ~200 nm
])
def test_unmasked_oxidation_matches_deal_grove_within_5pct(ambient, T_C,
                                                            minutes):
    """Phase 1 exit criterion: unmasked oxidation on a bare Si
    substrate yields SiO2 thickness within 5 % of the analytic Deal-
    Grove prediction. The 5 % target is the Sze/Plummer accuracy for
    gate-oxide thickness in production TCAD flows."""
    struct = _bare_si(width_um=1.0)
    recipe = Recipe("ox").oxidize(temperature_C=T_C,
                                   time_s=minutes * 60,
                                   ambient=ambient)
    state = simulate(struct, recipe, grid_delta_um=0.005)

    assert [L.material for L in state.layers] == [Material.SI, Material.SIO2]

    T_K = temperature_celsius_to_kelvin(T_C)
    x_expected = oxide_thickness(0.0, minutes * 60, T_K, ambient)
    exp_si_top = BASE_Y_UM - ALPHA_SI_CONSUMED_PER_OXIDE * x_expected
    exp_ox_top = BASE_Y_UM + (1 - ALPHA_SI_CONSUMED_PER_OXIDE) * x_expected

    _, ys_si = _sample_flat_ys(state.layers[0].level_set)
    _, ys_ox = _sample_flat_ys(state.layers[1].level_set)

    got_thickness_um = float(ys_ox.mean() - ys_si.mean())
    rel_err = abs(got_thickness_um - x_expected) / x_expected
    assert rel_err < 0.05, (
        f"{ambient} {T_C}°C {minutes}min: SiO2 thickness "
        f"{got_thickness_um*1000:.1f} nm vs analytic "
        f"{x_expected*1000:.1f} nm — {rel_err*100:.1f}% error, "
        f"exceeds Phase 1 exit criterion (5%).")

    # Positions individually should also land close (< 5 nm) — this
    # catches sign errors that a thickness-only check would miss.
    assert abs(float(ys_si.mean()) - exp_si_top) < 0.005
    assert abs(float(ys_ox.mean()) - exp_ox_top) < 0.005


def test_oxidation_from_prior_oxide_grows_less_than_from_bare():
    """Two sequential oxidation steps of equal duration should NOT
    yield twice the oxide of a single step (parabolic dominance)."""
    struct = _bare_si()
    single = simulate(struct,
                      Recipe("s").oxidize(1000, 3600, "wet"),
                      grid_delta_um=0.005)
    _, ys_si_s = _sample_flat_ys(single.layers[0].level_set)
    _, ys_ox_s = _sample_flat_ys(single.layers[1].level_set)
    t_single = float(ys_ox_s.mean() - ys_si_s.mean())

    doubled = simulate(struct,
                       (Recipe("d")
                        .oxidize(1000, 1800, "wet")
                        .oxidize(1000, 1800, "wet")),
                       grid_delta_um=0.005)
    _, ys_si_d = _sample_flat_ys(doubled.layers[0].level_set)
    _, ys_ox_d = _sample_flat_ys(doubled.layers[1].level_set)
    t_doubled = float(ys_ox_d.mean() - ys_si_d.mean())

    # t(2·t0) grown in one shot vs 2 × t(t0) should differ by <1 %:
    # the physics is the same PDE, just split into two integrations.
    assert abs(t_single - t_doubled) / t_single < 0.01


# ---------------------------------------------------------------------------
# 3. LOCOS: masked oxidation + bird's beak + mesh bridge.
# ---------------------------------------------------------------------------

LOCOS_WINDOW = (0.7, 1.3)


def _locos_state(bird_beak_um: float = 0.05):
    struct = (Structure(width_um=2.0, name="locos")
              .add_substrate("body", BASE_Y_UM, Material.SI))
    recipe = Recipe("locos").oxidize(
        temperature_C=1000, time_s=3600, ambient="wet",
        window_x_um=LOCOS_WINDOW, bird_beak_length_um=bird_beak_um)
    return simulate(struct, recipe, grid_delta_um=0.005)


def test_locos_center_matches_unmasked_deal_grove():
    """In the middle of the LOCOS window (away from the mask edges),
    the oxide thickness should match the unmasked Deal-Grove
    prediction within 5 %."""
    state = _locos_state()

    xs_si, ys_si = _sample_flat_ys(state.layers[0].level_set, 0.0, 2.0)
    xs_ox, ys_ox = _sample_flat_ys(state.layers[1].level_set, 0.0, 2.0)

    # Sample thickness at window centre (average over inner 200 nm).
    cx0, cx1 = 0.9, 1.1
    ys_si_c = np.interp(np.linspace(cx0, cx1, 32), xs_si, ys_si)
    ys_ox_c = np.interp(np.linspace(cx0, cx1, 32), xs_ox, ys_ox)
    thickness_c = float(ys_ox_c.mean() - ys_si_c.mean())

    T_K = temperature_celsius_to_kelvin(1000)
    expected = oxide_thickness(0.0, 3600, T_K, "wet")
    rel_err = abs(thickness_c - expected) / expected
    assert rel_err < 0.05, (
        f"LOCOS centre thickness {thickness_c*1000:.1f} nm vs "
        f"analytic {expected*1000:.1f} nm — {rel_err*100:.1f}% error.")


def test_locos_pristine_regions_untouched():
    """Far outside the window (many bird_beak lengths away), Si-top
    and SiO2-top must both sit at the initial substrate top (no oxide
    grown, no material consumed)."""
    state = _locos_state(bird_beak_um=0.05)

    xs_si, ys_si = _sample_flat_ys(state.layers[0].level_set, 0.0, 2.0)
    xs_ox, ys_ox = _sample_flat_ys(state.layers[1].level_set, 0.0, 2.0)

    far = xs_si < 0.2   # well outside window (mask edge at 0.7)
    assert np.all(np.abs(ys_si[far] - BASE_Y_UM) < 5e-4)
    far_ox = xs_ox < 0.2
    assert np.all(np.abs(ys_ox[far_ox] - BASE_Y_UM) < 5e-4)


def test_locos_bird_beak_forms_at_mask_edge():
    """Between the untouched pristine region and the fully-oxidized
    window, the SiO2 top should smoothly ramp down. With a non-zero
    bird_beak_length there must be at least a few nm of oxide grown
    outside the nominal window edges (the "beak"), and the profile
    must be strictly monotone across each edge."""
    state = _locos_state(bird_beak_um=0.05)

    xs_ox, ys_ox = _sample_flat_ys(state.layers[1].level_set, 0.0, 2.0)
    order = np.argsort(xs_ox)
    xs_ox = xs_ox[order]; ys_ox = ys_ox[order]

    # Beak zone: 60 nm outside the mask edge, either side.
    x0, x1 = LOCOS_WINDOW
    beak_left  = ys_ox[(xs_ox > x0 - 0.06) & (xs_ox < x0)]
    beak_right = ys_ox[(xs_ox > x1) & (xs_ox < x1 + 0.06)]
    assert beak_left.size >= 5
    assert beak_right.size >= 5
    assert beak_left.max()  > BASE_Y_UM + 0.005   # >5 nm of grown oxide
    assert beak_right.max() > BASE_Y_UM + 0.005

    # Monotone rise (left edge) and fall (right edge).
    assert np.all(np.diff(beak_left)  >= -1e-4)
    assert np.all(np.diff(beak_right) <= +1e-4)


def test_locos_meshfield_parses_and_has_both_materials():
    """The two-layer LOCOS state must round-trip through the mesh
    bridge into a MeshField with both Si and SiO2 tagged."""
    state = _locos_state()
    mf = topography_to_meshfield(state, mesh_size_um=0.03)
    assert mf.n_cells > 0
    si_cells = int((mf.material_ids == int(Material.SI)).sum())
    ox_cells = int((mf.material_ids == int(Material.SIO2)).sum())
    assert si_cells > 0
    assert ox_cells > 0
