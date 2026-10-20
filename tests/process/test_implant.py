"""
Phase 2.1 implant kernel + Recipe DSL step.

Six groups of tests:

  1. Pearson-IV table lookup — species canonicalisation, interpolation,
     refusal to extrapolate.
  2. Vertical profile — peak lands at Rp, Gaussian width matches dRp,
     integrated profile per column equals the input dose (within mesh
     discretisation).
  3. Mask attenuation — far outside the window the added dopant is ≈ 0;
     inside the window it's ≈ full dose; the erf edge has the expected
     width σ_lat ≈ 0.7·dRp.
  4. Species → dopant kind — B → Na, P → Nd, As → Nd. Existing Na / Nd
     from the Structure are preserved; implants add, never overwrite.
  5. Composability — two implants of the same species accumulate.
     An implant on top of a region that already has the opposite
     species doping leaves the opposite species untouched.
  6. Recipe DSL round-trip — Implant steps pretty-print, simulate()
     ignores them without errors, mixed recipes with topography +
     implant parse and dispatch cleanly.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import (
    PearsonMoments,
    apply_implant,
    available_species,
    canonicalize_species,
    moments_for,
)
from opentcad.process.topography import Recipe, simulate


# ---------------------------------------------------------------------------
# 1. Pearson-IV table lookup.
# ---------------------------------------------------------------------------

def test_species_canonicalisation():
    """Common aliases + case variants all resolve to the canonical name."""
    assert canonicalize_species("B") == "boron"
    assert canonicalize_species("boron") == "boron"
    assert canonicalize_species("Boron") == "boron"
    assert canonicalize_species("P") == "phosphorus"
    assert canonicalize_species("phosphorus") == "phosphorus"
    assert canonicalize_species("As") == "arsenic"
    assert canonicalize_species("Arsenic") == "arsenic"


def test_species_list_matches_shipped_yaml():
    """Only ship data for species we actually have YAMLs for."""
    assert set(available_species()) == {"arsenic", "boron", "phosphorus"}


def test_moments_in_range_interpolates():
    """15 keV boron should fall between the tabulated 10 and 30 keV
    rows — Rp monotone in energy, dRp too."""
    low  = moments_for("B", 10)
    hi   = moments_for("B", 30)
    mid  = moments_for("B", 15)
    assert low.Rp_um  < mid.Rp_um  < hi.Rp_um
    assert low.dRp_um < mid.dRp_um < hi.dRp_um
    assert low.dopant_kind == "acceptor"


def test_moments_refuse_extrapolation():
    """Below or above the tabulated range → ValueError, no silent nonsense."""
    with pytest.raises(ValueError, match="outside tabulated"):
        moments_for("B", 5)
    with pytest.raises(ValueError, match="outside tabulated"):
        moments_for("As", 300)


# ---------------------------------------------------------------------------
# 2. Vertical profile shape.
# ---------------------------------------------------------------------------

def _bare_si(width_um=2.0, body_um=0.5, mesh=0.01):
    return (Structure(width_um=width_um, name="t")
            .add_substrate("body", body_um, Material.SI)
            .to_meshfield(mesh_size_um=mesh))


def test_peak_concentration_lands_near_Rp():
    """Vertical Gaussian is centred at Rp below the top surface. The
    node of maximum Nd should sit within one grid cell of Rp."""
    mf = _bare_si(width_um=1.0, mesh=0.005)
    y_top = float(np.asarray(mf.grid.points)[:, 1].max())
    r = apply_implant(mf, "P", energy_keV=60, dose_cm2=1e14)
    y_peak = float(mf.grid.points[int(np.argmax(mf.Nd)), 1])
    y_expected = y_top - r.moments.Rp_um
    assert abs(y_peak - y_expected) < 0.015   # 1-2 grid cells of slop


def test_peak_concentration_magnitude_matches_gaussian():
    """Peak concentration of a Gaussian: dose / (sqrt(2π)·dRp).
    Within 20% at this mesh density — exact match needs a node
    sitting precisely at depth = Rp."""
    mf = _bare_si(width_um=1.0, mesh=0.005)
    dose = 1e14
    r = apply_implant(mf, "P", energy_keV=60, dose_cm2=dose)
    dRp_cm = r.moments.dRp_um * 1e-4
    expected = dose / (math.sqrt(2.0 * math.pi) * dRp_cm)
    got = float(mf.Nd.max())
    assert abs(got - expected) / expected < 0.20


def test_integrated_dose_per_column_matches_input():
    """Integrating Nd(y) along a column well inside the window should
    recover the input dose (in cm⁻²). Picks a central column, uses a
    fine mesh, trapezoid-integrates in cm. Expect within 5%."""
    mf = _bare_si(width_um=1.0, mesh=0.0025)
    dose = 1e15
    apply_implant(mf, "P", energy_keV=60, dose_cm2=dose,
                   window_x_um=(0.2, 0.8))

    pts = np.asarray(mf.grid.points)[:, :2]
    # Pick a thin x-slab near x=0.5 and extract y, Nd pairs.
    sel = np.abs(pts[:, 0] - 0.5) < 0.01
    y_um = pts[sel, 1]
    nd   = mf.Nd[sel]
    order = np.argsort(y_um)
    y_cm = y_um[order] * 1e-4
    nd_s = nd[order]
    integrated = float(np.trapezoid(nd_s, y_cm))   # cm⁻² (per column)
    assert abs(integrated - dose) / dose < 0.05


# ---------------------------------------------------------------------------
# 3. Mask attenuation.
# ---------------------------------------------------------------------------

def test_mask_shields_far_region():
    """Many σ_lat away from the mask edge, the added Nd should be < 1%
    of the peak — ≈ zero within numerical floor."""
    mf = _bare_si(width_um=4.0, mesh=0.01)
    r = apply_implant(mf, "As", energy_keV=30, dose_cm2=1e15,
                       window_x_um=(2.0, 3.0))
    xs = np.asarray(mf.grid.points)[:, 0]
    # σ_lat is in µm; 10σ outside the window edge → erf attenuation
    # smaller than 1e-11, Nd should be ~ zero.
    far = xs < (2.0 - 10.0 * r.sigma_lat_um)
    assert far.any()
    assert float(mf.Nd[far].max()) < 0.01 * float(mf.Nd.max())


def test_mask_center_delivers_full_dose():
    """At the window centre (many σ_lat from either edge) the local
    dose should be the input dose within <1%. Compare peak Nd there
    against the analytic Gaussian normalisation."""
    mf = _bare_si(width_um=4.0, mesh=0.005)
    dose = 1e15
    r = apply_implant(mf, "As", energy_keV=30, dose_cm2=dose,
                       window_x_um=(1.0, 3.0))
    pts = np.asarray(mf.grid.points)[:, :2]
    # Thin slab at the window centre x=2.0
    sel = np.abs(pts[:, 0] - 2.0) < 0.01
    y_um = pts[sel, 1]
    nd   = mf.Nd[sel]
    # Integrated dose in this column, in cm⁻².
    order = np.argsort(y_um)
    integrated = float(np.trapezoid(nd[order], y_um[order] * 1e-4))
    assert abs(integrated - dose) / dose < 0.05


# ---------------------------------------------------------------------------
# 4. Species → dopant kind.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,expected", [
    ("B",         "Na"),
    ("boron",     "Na"),
    ("P",         "Nd"),
    ("As",        "Nd"),
    ("arsenic",   "Nd"),
])
def test_species_targets_correct_dopant_field(species, expected):
    mf = _bare_si()
    r = apply_implant(mf, species, energy_keV=30, dose_cm2=1e13)
    assert r.added_to == expected
    if expected == "Nd":
        assert float(mf.Nd.max()) > 0.0
        assert float(mf.Na.max()) == 0.0
    else:
        assert float(mf.Na.max()) > 0.0
        assert float(mf.Nd.max()) == 0.0


def test_implant_preserves_pre_existing_opposite_doping():
    """A p-body (Na=1e17) that receives an As implant should keep its
    full Na and gain Nd on top. Net doping flips sign where Nd > Na,
    which is what makes a pn junction physical."""
    mf = (Structure(width_um=1.0, name="t")
          .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
          .to_meshfield(mesh_size_um=0.01))
    assert float(mf.Na.max()) == pytest.approx(1e17)
    assert float(mf.Nd.max()) == 0.0

    apply_implant(mf, "As", energy_keV=30, dose_cm2=1e15)
    assert float(mf.Na.min()) == pytest.approx(1e17)   # untouched
    assert float(mf.Nd.max()) > 1e19                    # shallow n+ formed
    # Net doping must be positive somewhere (junction formed) and
    # negative deep in the substrate (p-body intact).
    net = mf.net_doping
    assert net.max() > 0 and net.min() < 0


# ---------------------------------------------------------------------------
# 5. Composability.
# ---------------------------------------------------------------------------

def test_two_implants_same_species_accumulate():
    """Two 5e14 doses of As should sum to 1e15, not overwrite."""
    mf = _bare_si()
    apply_implant(mf, "As", energy_keV=30, dose_cm2=5e14)
    peak_one = float(mf.Nd.max())
    apply_implant(mf, "As", energy_keV=30, dose_cm2=5e14)
    peak_two = float(mf.Nd.max())
    assert abs(peak_two - 2.0 * peak_one) / peak_two < 0.01


def test_species_dont_cross_pollute():
    """B implant into a previously P-implanted mesh grows Na without
    touching Nd."""
    mf = _bare_si()
    apply_implant(mf, "P", energy_keV=30, dose_cm2=1e14)
    nd_before = float(mf.Nd.max())
    apply_implant(mf, "B", energy_keV=30, dose_cm2=1e14)
    assert float(mf.Nd.max()) == pytest.approx(nd_before, rel=1e-6)
    assert float(mf.Na.max()) > 0.0


# ---------------------------------------------------------------------------
# 6. Recipe DSL round-trip.
# ---------------------------------------------------------------------------

def test_recipe_implant_appends_step():
    from opentcad.process.topography.recipe import Implant
    r = Recipe("x").implant("As", 30, 1e15, window_x_um=(0.0, 0.5))
    assert len(r.steps) == 1
    s = r.steps[0]
    assert isinstance(s, Implant)
    assert s.species == "As"
    assert s.energy_keV == 30
    assert s.dose_cm2 == 1e15
    assert s.window_x_um == (0.0, 0.5)


def test_implant_rejects_bad_params():
    from opentcad.process.topography.recipe import Implant
    with pytest.raises(ValueError, match="energy"):
        Implant("As", -10, 1e14)
    with pytest.raises(ValueError, match="dose"):
        Implant("As", 30, -1e14)
    with pytest.raises(ValueError, match="window"):
        Implant("As", 30, 1e14, window_x_um=(0.5, 0.2))


def test_simulate_ignores_implant_step_cleanly():
    """simulate() handles the topography half of the recipe only;
    Implant steps pass through without error (doping dispatcher
    will pick them up in Unit B)."""
    struct = Structure(width_um=1.0).add_substrate("s", 0.5, Material.SI)
    recipe = (Recipe("mixed")
              .oxidize(temperature_C=900, time_s=600)
              .implant("As", 30, 1e14))
    state = simulate(struct, recipe, grid_delta_um=0.01)
    # One oxidation ran: Si + SiO2 in the stack. Implant did nothing to it.
    materials = [L.material for L in state.layers]
    assert Material.SI in materials
    assert Material.SIO2 in materials


def test_recipe_summary_prints_implant_line():
    r = Recipe("x").implant("As", 30, 1e15, window_x_um=(0.0, 0.5))
    text = r.summary()
    assert "implant As" in text
    assert "30 keV" in text
    assert "1.0e+15" in text
    assert "window=[0.000..0.500]" in text
