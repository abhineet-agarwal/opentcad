"""
Per-species dopant tracking through implant + anneal, and the Fair model
inside Recipe.anneal.

  * Implants write C_<species>; Nd / Na equal untracked + tracked sums.
  * An anneal diffuses each tracked species with its own D: P and As in
    the same Nd spread at their own rates, each conserving its dose.
  * Untracked Nd / Na (Structure-painted) still use species_Nd / Na.
  * Recipe.anneal(model="fair") runs the Fair kernel through the
    dispatcher; Fair enhancement is per species.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import (
    AnnealResult, FairAnnealResult, apply_anneal, apply_anneal_fair,
    apply_doping_recipe, apply_implant, diffusivity_intrinsic,
)
from opentcad.process.doping.anneal import temperature_celsius_to_kelvin
from opentcad.process.topography import Recipe
from opentcad.process.topography.recipe import Anneal


def _si(width_um=0.6, body_um=0.6, mesh=0.006, Na=0.0):
    s = Structure(width_um=width_um, name="t")
    s = s.add_substrate("body", body_um, Material.SI, doping_Na=Na) if Na else \
        s.add_substrate("body", body_um, Material.SI)
    return s.to_meshfield(mesh_size_um=mesh)


def _column(mf, field, x0=0.3, half=0.01):
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - x0) < half
    y, c = pts[sel, 1], np.asarray(field)[sel]
    o = np.argsort(y)
    return y[o], c[o]


def _dose(mf, field):
    y, c = _column(mf, field)
    return float(np.trapezoid(c, y * 1e-4))


def test_totals_stay_consistent_with_species():
    mf = _si(Na=1e16)
    apply_implant(mf, "P", 30, 1e13)
    apply_implant(mf, "As", 30, 1e13)
    apply_implant(mf, "B", 30, 1e13)
    np.testing.assert_allclose(mf.Nd, mf.get_species("phosphorus") + mf.get_species("arsenic"))
    np.testing.assert_allclose(mf.Na, 1e16 + mf.get_species("boron"))
    apply_anneal(mf, 1000, 600)
    np.testing.assert_allclose(mf.Nd, mf.get_species("phosphorus") + mf.get_species("arsenic"),
                               rtol=1e-12, atol=1.0)
    # Untracked 1e16 background is uniform: diffusion leaves it alone.
    np.testing.assert_allclose(mf.Na - mf.get_species("boron"), 1e16, rtol=1e-6)


def _mean_square_depth_um2(mf, field):
    y, c = _column(mf, field)
    d = float(np.asarray(mf.grid.points)[:, 1].max()) - y
    return float(np.trapezoid(d * d * c, y) / np.trapezoid(c, y))


def test_p_and_as_diffuse_at_their_own_rates():
    """With a no-flux surface, d⟨d²⟩/dt = 2D exactly (the wall term
    vanishes), so each species' mean-square depth must grow by its own
    2·D·t — P by ~8× more than As at 1000 °C."""
    mf = _si()
    apply_implant(mf, "P", 30, 1e13)
    apply_implant(mf, "As", 30, 1e13)
    species = ("phosphorus", "arsenic")
    doses0 = {s: _dose(mf, mf.get_species(s)) for s in species}
    msd0 = {s: _mean_square_depth_um2(mf, mf.get_species(s)) for s in species}

    r = apply_anneal(mf, 1000, 1800)
    T = temperature_celsius_to_kelvin(1000)
    for s, sym in zip(species, ("P", "As")):
        D = diffusivity_intrinsic(sym, T)
        assert r.species_D_cm2_s[s] == pytest.approx(D)
        grown = _mean_square_depth_um2(mf, mf.get_species(s)) - msd0[s]
        assert grown == pytest.approx(2 * D * 1800 * 1e8, rel=0.10), s
        assert _dose(mf, mf.get_species(s)) == pytest.approx(doses0[s], rel=0.03), s
    assert r.species_sigma_um["phosphorus"] > 2 * r.species_sigma_um["arsenic"]


def test_untracked_doping_still_uses_species_Nd():
    """A Structure-painted n-region is untracked; it diffuses with
    species_Nd's D while an implanted As species uses arsenic's."""
    mf = (Structure(width_um=0.6, name="t")
          .add_substrate("p", 0.3, Material.SI, doping_Na=1e15)
          .add_layer("n", 0.3, Material.SI, doping_Nd=1e17)
          .to_meshfield(mesh_size_um=0.006))
    apply_implant(mf, "As", 30, 1e13)
    untracked0 = mf.Nd - mf.get_species("arsenic")
    r = apply_anneal(mf, 1000, 1800, species_Nd="P")
    T = temperature_celsius_to_kelvin(1000)
    assert r.D_Nd_cm2_s == pytest.approx(diffusivity_intrinsic("P", T))
    assert r.species_D_cm2_s == {"arsenic": pytest.approx(diffusivity_intrinsic("As", T))}
    untracked1 = mf.Nd - mf.get_species("arsenic")
    # The painted step at y = 0.3 µm smears into the p-region.
    pts = np.asarray(mf.grid.points)[:, :2]
    below = (pts[:, 1] < 0.29) & (pts[:, 1] > 0.25)
    assert untracked0[below].max() == 0.0
    assert untracked1[below].max() > 1e15


def test_recipe_anneal_model_fair_dispatches():
    mf = _si()
    recipe = (Recipe("fair")
              .implant("As", 30, 1e14, window_x_um=(0.2, 0.4))
              .anneal(1000, 60, model="fair"))
    assert "(fair;" in recipe.summary()
    res = apply_doping_recipe(mf, recipe)
    a = res.anneals[0]
    assert isinstance(a, FairAnnealResult) and a.model == "fair"
    assert set(a.species_D_eff_peak_cm2_s) == {"arsenic"}

    res2 = apply_doping_recipe(_si(), Recipe().anneal(1000, 60))
    assert isinstance(res2.anneals[0], AnnealResult) and res2.anneals[0].model == "intrinsic"

    with pytest.raises(ValueError, match="model"):
        Anneal(1000, 60, model="tsuprem")


def test_fair_species_share_the_electron_density():
    """Co-implanted P + As at S/D dose: each species uses its own Fair
    coefficients but the same n (all donors). Back out u = n/n_i from
    arsenic's peak D_eff (D_i + D⁻u) and predict phosphorus' exactly
    (D_i + D⁻u + D⁻⁻u²). If each species saw only its own
    concentration, the two u's would differ by ~2× (As peaks ~2× higher)."""
    from opentcad.process.doping.anneal import fair_diffusivity_components
    mf = _si(width_um=0.4, body_um=0.4, mesh=0.008)
    apply_implant(mf, "P", 30, 1e15)
    apply_implant(mf, "As", 30, 1e15)
    T = temperature_celsius_to_kelvin(1000)
    cP = fair_diffusivity_components("P", T)
    cAs = fair_diffusivity_components("As", T)
    r = apply_anneal_fair(mf, 1000, 10)

    u = (r.species_D_eff_peak_cm2_s["arsenic"] - cAs["D_i"]) / cAs["D_minus"]
    assert u > 10                                   # well into the Fair regime
    predicted_P = cP["D_i"] + cP["D_minus"] * u + cP["D_minus_minus"] * u * u
    assert r.species_D_eff_peak_cm2_s["phosphorus"] == pytest.approx(predicted_P, rel=1e-6)
    assert predicted_P / cP["D_i"] > r.species_D_eff_peak_cm2_s["arsenic"] / cAs["D_i"]
    np.testing.assert_allclose(mf.Nd, mf.get_species("phosphorus") + mf.get_species("arsenic"),
                               rtol=1e-12, atol=1.0)
