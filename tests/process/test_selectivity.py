"""
Phase 2 Unit D — per-material etch selectivity.

Verifies that `.etch(rates={Material.X: r_X, Material.Y: r_Y})` scales
the etch rate per material, so a nitride etch can stop on an oxide,
or a poly-gate etch can stop on a gate oxide, etc.

Three groups of tests:

  1. Default behaviour (`rates=None`) — every material etches at the
     same rate, matching the Phase 1 regression curves.
  2. Full selectivity (nitride etches, oxide freezes) — the classic
     "stop on oxide" pattern.
  3. Fractional selectivity — a 10:1 rate ratio gives a 10:1 depth
     ratio after the same advection time; a material absent from the
     rate map takes `default_rate`.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography import (
    Recipe, extract_surface_polyline, simulate,
)
from opentcad.process.topography.recipe import Etch


# ---------------------------------------------------------------------------
# DSL round-trip
# ---------------------------------------------------------------------------

def test_etch_dataclass_accepts_rates():
    e = Etch(depth_um=0.1,
             rates={Material.SI3N4: 1.0, Material.SIO2: 0.02},
             default_rate=0.0)
    assert e.rates[Material.SI3N4] == 1.0
    assert e.rates[Material.SIO2] == 0.02


def test_etch_dataclass_rejects_nonMaterial_key():
    with pytest.raises(ValueError, match="Material enum"):
        Etch(depth_um=0.1, rates={"nitride": 1.0})


def test_etch_dataclass_rejects_negative_rate():
    with pytest.raises(ValueError, match="must be ≥ 0"):
        Etch(depth_um=0.1, rates={Material.SI3N4: -0.1})
    with pytest.raises(ValueError, match="default_rate"):
        Etch(depth_um=0.1, default_rate=-0.5)


def test_recipe_etch_wires_rates_through():
    r = Recipe().etch(0.1, rates={Material.SI: 1.0}, default_rate=0.0)
    assert r.steps[0].rates == {Material.SI: 1.0}


def test_recipe_summary_shows_rates():
    r = Recipe().etch(0.05, rates={Material.SI3N4: 1.0, Material.SIO2: 0.02})
    s = r.summary()
    assert "rates=" in s
    assert "SI3N4" in s and "SIO2" in s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _surface_y_of(state, material: Material):
    """Return the mean surface y of the LS belonging to the given
    material in the given TopographyState."""
    for L in state.layers:
        if L.material == material:
            nodes, _ = extract_surface_polyline(L.level_set)
            ys = np.array([n[1] for n in nodes])
            return float(np.mean(ys))
    raise AssertionError(
        f"material {material.name} not found in state")


# ---------------------------------------------------------------------------
# 1. Default (rates=None) — regression: Phase 1 behaviour preserved.
# ---------------------------------------------------------------------------

def test_default_rates_etches_all_materials_at_same_rate():
    """With rates=None, a 50 nm masked directional etch through a
    nitride-on-oxide stack takes 50 nm off whichever material is at
    the surface — same as before Unit D."""
    struct = (Structure(width_um=1.0, name="t")
              .add_substrate("si", 0.5, Material.SI)
              .add_layer("oxide", 0.03, Material.SIO2))
    recipe = Recipe().etch(0.05, model="directional",
                            window_x_um=(0.3, 0.7))
    state = simulate(struct, recipe, grid_delta_um=0.005)
    # The 50 nm etch consumes the 30 nm oxide + 20 nm of Si under it.
    # Si LS should recede ~20 nm in the window centre.
    nodes, _ = extract_surface_polyline(state.layers[0].level_set)
    pts = np.asarray(nodes)
    xs = pts[:, 0]; ys = pts[:, 1]
    centre = (xs > 0.4) & (xs < 0.6)
    assert ys[centre].min() < 0.5 - 0.015      # Si consumed


# ---------------------------------------------------------------------------
# 2. Full selectivity — strip nitride, stop on oxide.
# ---------------------------------------------------------------------------

def test_selectivity_strips_nitride_leaves_oxide_intact():
    """100 nm nitride on 50 nm oxide. Unmasked 150 nm directional etch
    at 100:1 selectivity: nitride clears, oxide barely moves."""
    struct = (Structure(width_um=1.0, name="t")
              .add_substrate("si", 0.5, Material.SI)
              .add_layer("oxide", 0.05, Material.SIO2)
              .add_layer("nitride", 0.1, Material.SI3N4))
    recipe = Recipe().etch(
        0.15, model="directional",
        rates={Material.SI3N4: 1.0, Material.SIO2: 0.01, Material.SI: 0.01})
    state = simulate(struct, recipe, grid_delta_um=0.005)

    y_oxide_before   = 0.55
    y_si_before      = 0.50

    y_oxide_after = _surface_y_of(state, Material.SIO2)
    y_si_after    = _surface_y_of(state, Material.SI)
    y_nitride_after = _surface_y_of(state, Material.SI3N4)

    # Oxide loses ≤ 2 nm (1 % × 150 nm etch).
    assert abs(y_oxide_after - y_oxide_before) < 0.003
    # Si untouched (buried under oxide, stack invariant plus 1 % rate).
    assert abs(y_si_after - y_si_before) < 0.001
    # Nitride clamped onto oxide (nitride LS can't dip below oxide LS
    # once nitride is fully consumed — ViennaLS enforces the stack).
    assert abs(y_nitride_after - y_oxide_after) < 0.003


def test_selectivity_zero_rate_freezes_a_material():
    """Rate exactly 0 for a material should leave it genuinely motionless
    even when the surface above has been stripped."""
    struct = (Structure(width_um=1.0, name="t")
              .add_substrate("si", 0.5, Material.SI)
              .add_layer("oxide", 0.03, Material.SIO2)
              .add_layer("nitride", 0.08, Material.SI3N4))
    recipe = Recipe().etch(
        0.1, model="directional",
        rates={Material.SI3N4: 1.0, Material.SIO2: 0.0, Material.SI: 0.0})
    state = simulate(struct, recipe, grid_delta_um=0.005)
    assert _surface_y_of(state, Material.SIO2) == pytest.approx(0.53,
                                                                  abs=1e-3)
    assert _surface_y_of(state, Material.SI) == pytest.approx(0.50,
                                                                abs=1e-3)


# ---------------------------------------------------------------------------
# 3. Fractional selectivity.
# ---------------------------------------------------------------------------

def test_fractional_rates_scale_recession_proportionally():
    """A 10:1 ratio in rates ⇒ roughly 10:1 ratio in depth loss after
    the same `.etch(depth_um)` call."""
    def recede(rate: float) -> float:
        struct = (Structure(width_um=1.0, name="t")
                  .add_substrate("si", 0.5, Material.SI))
        recipe = Recipe().etch(0.05, model="directional",
                                rates={Material.SI: rate})
        state = simulate(struct, recipe, grid_delta_um=0.005)
        return 0.5 - _surface_y_of(state, Material.SI)

    d_full  = recede(1.0)
    d_tenth = recede(0.1)
    assert d_full > 0.04                   # ~50 nm, close to etch time
    assert d_tenth == pytest.approx(d_full * 0.1, rel=0.1)


def test_default_rate_catches_unlisted_materials():
    """If a material is absent from rates and default_rate=0.5, it
    etches at half rate."""
    struct = (Structure(width_um=1.0, name="t")
              .add_substrate("si", 0.5, Material.SI)
              .add_layer("oxide", 0.08, Material.SIO2))
    recipe = Recipe().etch(0.05, model="directional",
                            rates={Material.SI3N4: 1.0},   # SiO2 absent
                            default_rate=0.5)
    state = simulate(struct, recipe, grid_delta_um=0.005)
    # Oxide etched at 50% rate ⇒ loses ~25 nm from its 80 nm thickness.
    y_oxide = _surface_y_of(state, Material.SIO2)
    recession = 0.58 - y_oxide
    assert recession == pytest.approx(0.025, rel=0.20)


# ---------------------------------------------------------------------------
# 4. Unmasked isotropic selectivity exercises the slow Advect path.
# ---------------------------------------------------------------------------

def test_unmasked_isotropic_with_rates_uses_advect_path():
    """When rates is set, the unmasked isotropic case must route
    through Advect (so each layer sees its own rate), not the fast
    GeometricAdvect shortcut that only touches the top LS."""
    struct = (Structure(width_um=1.0, name="t")
              .add_substrate("si", 0.5, Material.SI)
              .add_layer("oxide", 0.08, Material.SIO2))
    recipe = Recipe().etch(0.05, model="isotropic",
                            rates={Material.SIO2: 1.0, Material.SI: 0.1})
    state = simulate(struct, recipe, grid_delta_um=0.005)
    y_oxide_after = _surface_y_of(state, Material.SIO2)
    y_si_after    = _surface_y_of(state, Material.SI)
    # Oxide should have receded ~50 nm.
    assert (0.58 - y_oxide_after) == pytest.approx(0.05, abs=0.015)
    # Si underneath: still at 0.5 (oxide protects it).
    assert y_si_after == pytest.approx(0.5, abs=0.002)
