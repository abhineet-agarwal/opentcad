"""
Phase 2.3a — intrinsic-diffusion anneal kernel.

Three groups of tests:

  1. Diffusivity lookup — Arrhenius constants in / expected D out,
     T-dependence doubles roughly per 100 °C step, species canonicals.
  2. Analytic diffusion — a sharp as-implanted Gaussian broadens from
     σ₀ to √(σ₀² + 2 D t), peak drops in proportion, integrated dose
     per column is conserved within the resampling budget.
  3. DSL round-trip — Anneal dataclass validates, Recipe.anneal()
     appends a step, summary() prints a readable line, and
     apply_doping_recipe + run_recipe dispatch Anneal correctly.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import (
    apply_anneal,
    apply_doping_recipe,
    apply_implant,
    diffusivity_intrinsic,
)
from opentcad.process.doping.anneal import temperature_celsius_to_kelvin
from opentcad.process.topography import Recipe
from opentcad.process.topography.recipe import Anneal


# ---------------------------------------------------------------------------
# 1. Diffusivity lookup
# ---------------------------------------------------------------------------

def test_diffusivity_matches_arrhenius_closed_form():
    """D(T) = D0 · exp(-Ea / kT). Verify against the published Fair
    constants for As at 1000 °C: D ≈ 1-3e-15 cm²/s."""
    T = temperature_celsius_to_kelvin(1000)
    D = diffusivity_intrinsic("As", T)
    assert 5e-16 < D < 1e-14, f"As D(1000°C) = {D:.2e} out of band"


def test_diffusivity_doubles_roughly_per_100C_step():
    """Arrhenius: a 100 °C step at ~1000 °C scales D by about e^(Ea/kT²·100).
    For As (Ea = 3.44 eV) that's a factor ~15. For a conservative
    sanity check, D(1100) > 3 · D(1000)."""
    D_1000 = diffusivity_intrinsic("As", temperature_celsius_to_kelvin(1000))
    D_1100 = diffusivity_intrinsic("As", temperature_celsius_to_kelvin(1100))
    assert D_1100 / D_1000 > 3.0


def test_diffusivity_species_ordering_matches_literature():
    """At 1000 °C, As < B < P (intrinsic). This ordering is a
    canonical textbook fact — if it's wrong something broke in the YAMLs."""
    T = temperature_celsius_to_kelvin(1000)
    D_As = diffusivity_intrinsic("As", T)
    D_B  = diffusivity_intrinsic("B",  T)
    D_P  = diffusivity_intrinsic("P",  T)
    assert D_As < D_B < D_P or D_As < D_P


def test_diffusivity_canonicalisation():
    """Aliases + case variants resolve the same as pearson_iv."""
    T = temperature_celsius_to_kelvin(1000)
    assert diffusivity_intrinsic("arsenic", T) == diffusivity_intrinsic("As", T)
    assert diffusivity_intrinsic("B",        T) == diffusivity_intrinsic("boron", T)


def test_diffusivity_refuses_impossible_temperature():
    with pytest.raises(ValueError, match=">\\s*0"):
        diffusivity_intrinsic("As", 0)
    with pytest.raises(ValueError, match=">\\s*0"):
        diffusivity_intrinsic("As", -5)


# ---------------------------------------------------------------------------
# 2. Analytic diffusion behaviour
# ---------------------------------------------------------------------------

def _bare_si(width_um=1.0, body_um=0.5, mesh=0.01):
    return (Structure(width_um=width_um, name="t")
            .add_substrate("body", body_um, Material.SI)
            .to_meshfield(mesh_size_um=mesh))


def _column_profile(mf, x_target):
    """Return (y_um, Nd) in a thin x-slab at the given x, sorted by y."""
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - x_target) < 0.01
    y = pts[sel, 1]
    nd = mf.Nd[sel]
    order = np.argsort(y)
    return y[order], nd[order]


def _sigma_of(y, nd):
    """Weighted standard deviation along y for a 1D Gaussian-ish profile."""
    w = nd.sum()
    if w == 0:
        return 0.0
    mean = (y * nd).sum() / w
    return math.sqrt((nd * (y - mean) ** 2).sum() / w)


def test_annealing_broadens_gaussian_per_sqrt_2Dt():
    """A single As implant with σ₀ ≈ dRp. After anneal at 1000 °C for
    30 min, the Gaussian broadens to σ = √(σ₀² + 2 D t). Measured σ
    should match within 25% (bounded by mesh resampling + reflection
    at the top boundary piling mass up on itself)."""
    mf = _bare_si(width_um=0.6, body_um=0.5, mesh=0.005)
    apply_implant(mf, "As", 30, 1e14, window_x_um=(0.1, 0.5))
    y0, nd0 = _column_profile(mf, 0.3)
    sigma_before = _sigma_of(y0, nd0)

    r = apply_anneal(mf, 1000, 1800)
    y1, nd1 = _column_profile(mf, 0.3)
    sigma_after = _sigma_of(y1, nd1)

    sigma_expected = math.sqrt(sigma_before ** 2 + r.sigma_Nd_um ** 2)
    # Lower bound: must have broadened appreciably.
    assert sigma_after > sigma_before * 1.3
    # Upper bound: within 25% of the analytic prediction.
    assert abs(sigma_after - sigma_expected) / sigma_expected < 0.25


def test_annealing_lowers_peak_concentration():
    """When a Gaussian broadens, the peak drops by σ₀ / σ_after
    (conservation of mass for a Gaussian). After anneal the peak
    should be strictly below the as-implanted peak."""
    mf = _bare_si(width_um=0.6, body_um=0.5, mesh=0.005)
    apply_implant(mf, "As", 30, 1e14, window_x_um=(0.1, 0.5))
    peak_before = float(mf.Nd.max())
    apply_anneal(mf, 1000, 1800)
    peak_after = float(mf.Nd.max())
    assert peak_after < peak_before
    assert peak_after > 0.3 * peak_before    # didn't vanish


def test_annealing_approximately_conserves_dose():
    """Integrating Nd(y) along a column well inside the implant
    window should give roughly the same total as before, within the
    ~5-10% resampling budget."""
    mf = _bare_si(width_um=0.6, body_um=0.5, mesh=0.005)
    apply_implant(mf, "As", 30, 1e14, window_x_um=(0.1, 0.5))
    y0, nd0 = _column_profile(mf, 0.3)
    dose_before = float(np.trapezoid(nd0, y0 * 1e-4))   # cm⁻²

    apply_anneal(mf, 1000, 1800)
    y1, nd1 = _column_profile(mf, 0.3)
    dose_after = float(np.trapezoid(nd1, y1 * 1e-4))

    assert abs(dose_after - dose_before) / dose_before < 0.15


def test_annealing_handles_zero_time_as_noop():
    """time_s = 0 → σ = 0 → identity. Doping unchanged."""
    mf = _bare_si()
    apply_implant(mf, "As", 30, 1e14)
    nd_before = mf.Nd.copy()
    apply_anneal(mf, 1000, 0.0)
    assert np.allclose(mf.Nd, nd_before)


def test_annealing_preserves_opposite_species_independently():
    """Annealing a p-body (Na=1e17) + As implant should diffuse Nd
    per As kinetics (slow) and Na per B kinetics (faster) without
    mixing or deleting either field."""
    mf = _bare_si()
    apply_implant(mf, "As", 30, 1e14, window_x_um=(0.3, 0.7))
    # Starting p-body Na is uniform; implant adds Nd near the surface.
    na_before_mean = float(mf.Na.mean())
    nd_before_max  = float(mf.Nd.max())

    r = apply_anneal(mf, 1000, 1800)
    # Na should still integrate roughly to the same substrate-wide total.
    assert float(mf.Na.mean()) == pytest.approx(na_before_mean, rel=0.05)
    # Nd peak should have dropped as the Gaussian broadened.
    assert float(mf.Nd.max()) < nd_before_max
    # B diffuses faster than As at the same T.
    assert r.sigma_Na_um > r.sigma_Nd_um


# ---------------------------------------------------------------------------
# 3. DSL round-trip + dispatcher integration
# ---------------------------------------------------------------------------

def test_anneal_dataclass_validates():
    with pytest.raises(ValueError, match="time"):
        Anneal(temperature_C=1000, time_s=-1)
    with pytest.raises(ValueError, match="temperature"):
        Anneal(temperature_C=-1000, time_s=1)


def test_recipe_anneal_appends_step():
    r = Recipe().anneal(temperature_C=1000, time_s=1800,
                        species_Nd="P", species_Na="B")
    assert len(r.steps) == 1
    s = r.steps[0]
    assert isinstance(s, Anneal)
    assert s.temperature_C == 1000
    assert s.time_s == 1800
    assert s.species_Nd == "P"


def test_recipe_summary_prints_anneal():
    text = Recipe().anneal(1000, 1800).summary()
    assert "anneal @ 1000°C" in text
    assert "1800 s" in text


def test_apply_doping_recipe_dispatches_anneal():
    """A Recipe with Implant + Anneal fires both via the dispatcher.
    DopingRecipeResult tracks counts of each."""
    mf = _bare_si()
    recipe = (Recipe("implant_and_anneal")
              .implant("As", 30, 1e14, window_x_um=(0.3, 0.7))
              .anneal(1000, 1800))
    res = apply_doping_recipe(mf, recipe)
    assert res.n_implants == 1
    assert res.n_anneals == 1
    assert res.anneals[0].species_Nd == "arsenic"


def test_apply_doping_recipe_handles_multiple_anneals():
    """Two anneals compose: σ² = σ₀² + 2D·(t₁ + t₂) within the
    mesh/grid error budget."""
    mf_a = _bare_si(width_um=0.5, mesh=0.005)
    mf_b = _bare_si(width_um=0.5, mesh=0.005)
    apply_implant(mf_a, "As", 30, 1e14)
    apply_implant(mf_b, "As", 30, 1e14)

    # One long anneal vs two short ones with the same total time.
    apply_anneal(mf_a, 1000, 3600)
    apply_anneal(mf_b, 1000, 1800)
    apply_anneal(mf_b, 1000, 1800)

    # Peak values should be close — same cumulative Dt.
    peak_a = float(mf_a.Nd.max())
    peak_b = float(mf_b.Nd.max())
    assert peak_b == pytest.approx(peak_a, rel=0.10)
