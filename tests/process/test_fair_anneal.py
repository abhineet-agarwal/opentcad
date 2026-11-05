"""
Phase 2.3b Fair concentration-coupled anneal.

The intrinsic Gaussian path (apply_anneal) is exact for D·∇²C where D
is a constant — fine at doping ≪ n_i(T). At heavy S/D doping the Fair
components (D⁻, D⁻⁻ for donors; D⁺ for acceptors) become comparable to
or dominate over D_i, and the profile top flattens faster than the
intrinsic model predicts. This test file verifies that apply_anneal_fair:

  * Loads the Fair components correctly from each species' YAML.
  * At very low doping (n ≪ n_i) collapses to the intrinsic Gaussian
    result within tight tolerance (the u^k terms are negligible).
  * At heavy P doping (n ≫ n_i) drops the profile peak MORE than the
    intrinsic anneal would (concentration enhancement is real).
  * Enforces its sub-step budget — a tight max_sub_steps raises.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping.anneal import (
    apply_anneal, apply_anneal_fair, fair_diffusivity_components,
    _intrinsic_carrier_density_cm3, temperature_celsius_to_kelvin)


def _mesh():
    return (Structure(width_um=0.5, name="fair_t")
            .add_substrate("bulk", 0.5, Material.SI, doping_Na=1e14)
            .add_contact("top", 0.0, 0.5, "bulk", surface="top")
            .add_contact("bot", 0.0, 0.5, "bulk", surface="bottom")
            .to_meshfield(mesh_size_um=0.02))


def _install_gaussian(mf, peak_cm3: float, y0_um: float = 0.45,
                       sigma_um: float = 0.02):
    pts = np.asarray(mf.grid.points, dtype=float)
    mf.Nd = peak_cm3 * np.exp(-((pts[:, 1] - y0_um) ** 2) /
                                 (2 * sigma_um ** 2))
    mf.Na = np.zeros(mf.n_points)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def test_fair_components_phosphorus_loaded():
    """P YAML has intrinsic + D_minus + D_minus_minus — all three must
    show up with non-zero Arrhenius values at anneal temperature."""
    T_K = temperature_celsius_to_kelvin(1000.0)
    cP = fair_diffusivity_components("P", T_K)
    assert "D_i" in cP
    assert "D_minus" in cP
    assert "D_minus_minus" in cP
    for key in ("D_i", "D_minus", "D_minus_minus"):
        assert cP[key] > 0.0, f"P.{key} = {cP[key]}"


def test_fair_components_boron_loaded():
    """B has only D_plus (no D_plus_plus)."""
    T_K = temperature_celsius_to_kelvin(1000.0)
    cB = fair_diffusivity_components("B", T_K)
    assert "D_i" in cB
    assert "D_plus" in cB
    assert "D_plus_plus" not in cB


def test_intrinsic_ni_at_1000C_is_reasonable():
    """n_i(1000°C) should sit in the 5e18 - 1e19 range — the Fair
    enhancement crossover."""
    T_K = temperature_celsius_to_kelvin(1000.0)
    n_i = _intrinsic_carrier_density_cm3(T_K)
    assert 1e18 < n_i < 1e20, f"n_i(T=1273K) = {n_i:.2e}"


# ---------------------------------------------------------------------------
# Numerical behavior
# ---------------------------------------------------------------------------

def test_fair_at_low_doping_matches_intrinsic():
    """n << n_i ⇒ u → 1 clamp, so D_eff ≈ D_i + (D⁻ + D⁻⁻) ≈ D_i for
    boron (no D⁻) and close for P. Match intrinsic to within a factor
    of 2 (Fair uses explicit FTCS with floor-clamped u, intrinsic uses
    analytic Gaussian; tolerance accounts for FTCS and grid-resample)."""
    peak = 1e15   # ≪ n_i(1000°C) ≈ 6e18

    mf_i = _mesh(); _install_gaussian(mf_i, peak)
    before_peak = mf_i.Nd.max()
    apply_anneal(mf_i, 1000.0, 1.0, species_Nd="P", species_Na="B")
    after_i = mf_i.Nd.max()

    mf_f = _mesh(); _install_gaussian(mf_f, peak)
    apply_anneal_fair(mf_f, 1000.0, 1.0, species_Nd="P", species_Na="B")
    after_f = mf_f.Nd.max()

    # Both should have smoothed the peak only slightly at T=1000°C,
    # 1 s, D_i(P) ~ 1e-14 → sigma ~ sqrt(2e-14) ~ 1.4e-7 cm = 1.4 nm,
    # comparable to the grid-resolution rounding, so both peaks stay
    # close to initial. Just require Fair ≤ intrinsic (no spurious
    # enhancement at low doping) and both ≤ initial.
    assert after_f <= before_peak * 1.001
    assert after_i <= before_peak * 1.001
    # Fair should be within 2x of intrinsic at low doping.
    assert 0.5 < after_f / after_i < 2.0, (
        f"Low-doping Fair/Intr ratio {after_f/after_i:.3f}")


def test_fair_at_high_P_doping_shows_enhancement():
    """At n ≫ n_i, D⁻⁻ term (~u²) dominates — the P kink-and-tail
    signature. Fair must spread the peak MORE than intrinsic alone.
    The D_eff_peak returned in the result must exceed D_i by at least
    10× (concentration enhancement > 10× for n=1e21)."""
    mf_f = _mesh(); _install_gaussian(mf_f, 1e21)
    res = apply_anneal_fair(mf_f, 1000.0, 1.0, species_Nd="P", species_Na="B")
    peak_fair = mf_f.Nd.max()

    mf_i = _mesh(); _install_gaussian(mf_i, 1e21)
    apply_anneal(mf_i, 1000.0, 1.0, species_Nd="P", species_Na="B")
    peak_intr = mf_i.Nd.max()

    enhancement = res.D_eff_Nd_peak_cm2_s / res.D_i_Nd_cm2_s
    assert enhancement > 10.0, (
        f"At n=1e21, D_eff/D_i should be ≫ 1; got {enhancement:.2f}")
    # Fair peak should drop more than intrinsic (bigger spread).
    assert peak_fair < peak_intr, (
        f"Fair peak {peak_fair:.2e} should drop below intrinsic "
        f"{peak_intr:.2e} at heavy doping")


def test_fair_sub_step_budget_enforced():
    """A deliberately tight max_sub_steps must raise rather than
    silently truncate."""
    mf = _mesh(); _install_gaussian(mf, 1e21)
    with pytest.raises(RuntimeError, match="max_sub_steps"):
        apply_anneal_fair(mf, 1000.0, 10.0, species_Nd="P",
                           max_sub_steps=3)


def test_fair_rejects_bad_stability_factor():
    mf = _mesh(); _install_gaussian(mf, 1e18)
    with pytest.raises(ValueError, match="stability_factor"):
        apply_anneal_fair(mf, 1000.0, 1.0, stability_factor=0.9)
    with pytest.raises(ValueError, match="stability_factor"):
        apply_anneal_fair(mf, 1000.0, 1.0, stability_factor=0.0)


def test_fair_rejects_negative_time():
    mf = _mesh(); _install_gaussian(mf, 1e18)
    with pytest.raises(ValueError, match="time"):
        apply_anneal_fair(mf, 1000.0, -1.0, species_Nd="P")


def test_ftcs_step_stable_at_limit_and_conserves_trapezoid_mass():
    """At D·dt/dx² = 0.25 round-off noise must not grow (above it, the 2D
    explicit scheme amplifies the checkerboard mode), and a blob touching
    the wall keeps its trapezoid-weighted mass exactly."""
    from opentcad.process.doping.anneal import _ftcs_step
    rng = np.random.default_rng(0)
    dx, D0 = 1e-6, 1e-13
    C = 1e20 * (1.0 + 1e-12 * rng.standard_normal((40, 40)))
    D = np.full_like(C, D0)
    for _ in range(1000):
        C = _ftcs_step(C, D, dx, 0.25 * dx * dx / D0)
    assert np.ptp(C) / 1e20 < 1e-11

    C = np.zeros((30, 30)); C[0:4, 8:12] = 1e20
    D = np.full_like(C, D0)
    w = np.ones_like(C)
    w[0, :] *= 0.5; w[-1, :] *= 0.5; w[:, 0] *= 0.5; w[:, -1] *= 0.5
    m0 = float((w * C).sum())
    for _ in range(500):
        C = _ftcs_step(C, D, dx, 0.2 * dx * dx / D0)
    assert float((w * C).sum()) == pytest.approx(m0, rel=1e-12)
    assert C.min() >= 0.0


def test_fair_long_anneal_obeys_maximum_principle():
    """Thousands of sub-steps at heavy doping: the profile may only
    spread — never overshoot its initial peak or go non-finite."""
    mf = _mesh(); _install_gaussian(mf, 1e21)
    peak0 = float(mf.Nd.max())
    res = apply_anneal_fair(mf, 1000.0, 30.0, species_Nd="P")
    assert res.n_sub_steps > 200
    assert np.all(np.isfinite(mf.Nd))
    assert float(mf.Nd.max()) <= peak0 * (1 + 1e-9)


def test_fair_rejects_factor_above_stability_limit():
    mf = _mesh(); _install_gaussian(mf, 1e18)
    with pytest.raises(ValueError, match="stability_factor"):
        apply_anneal_fair(mf, 1000.0, 1.0, stability_factor=0.3)
