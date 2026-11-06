"""
Pearson-system implant profile + BF₂ handling.

  1. pearson_density reproduces the tabulated (Rp, ΔRp, γ, β) for every
     shipped row — including rows that are Pearson type I or VI, not IV.
  2. γ = 0, β = 3 is the Gaussian; impossible moment pairs are refused.
  3. apply_implant(profile="pearson") writes dose × density on the mesh,
     conserves dose, and moves the peak off Rp in the direction of the skew.
  4. BF₂ is boron at the mass-scaled energy.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import yaml

import opentcad
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import (
    PearsonMoments, apply_implant, moments_for, pearson_density,
    resolve_implant_species,
)

# The tables shipped with the package (works for a checkout or an install).
_DATA = Path(opentcad.__file__).resolve().parent / "process" / "doping" / "data"


def _rows():
    out = []
    for sym in ("B", "P", "As"):
        table = yaml.safe_load((_DATA / f"{sym}_in_Si.yaml").read_text())
        out += [(sym, r["energy_keV"]) for r in table["moments"]]
    return out


def _moments(depth, p):
    m = np.trapezoid(depth * p, depth)
    s = math.sqrt(np.trapezoid((depth - m) ** 2 * p, depth))
    g = np.trapezoid((depth - m) ** 3 * p, depth) / s ** 3
    b = np.trapezoid((depth - m) ** 4 * p, depth) / s ** 4
    return m, s, g, b


# ---------------------------------------------------------------------------
# 1-2. The density itself.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sym,energy", _rows())
def test_pearson_density_recovers_tabulated_moments(sym, energy):
    mo = moments_for(sym, energy)
    depth, p = pearson_density(mo)
    assert np.trapezoid(p, depth) == pytest.approx(1.0, rel=1e-6)
    m, s, g, b = _moments(depth, p)
    assert m == pytest.approx(mo.Rp_um, rel=1e-3)
    assert s == pytest.approx(mo.dRp_um, rel=1e-3)
    assert g == pytest.approx(mo.gamma, abs=0.01)
    assert b == pytest.approx(mo.beta, rel=0.01)


def test_pearson_gaussian_limit():
    mo = PearsonMoments(Rp_um=0.1, dRp_um=0.02, gamma=0.0, beta=3.0,
                        dopant_kind="donor")
    depth, p = pearson_density(mo)
    gauss = np.exp(-0.5 * ((depth - 0.1) / 0.02) ** 2) / (math.sqrt(2 * math.pi) * 0.02)
    assert np.max(np.abs(p - gauss)) < 1e-6 * gauss.max()


@pytest.mark.parametrize("gamma,beta", [(1.0, 1.9), (0.0, 1.5)])
def test_pearson_rejects_impossible_or_non_bell_moments(gamma, beta):
    mo = PearsonMoments(Rp_um=0.1, dRp_um=0.02, gamma=gamma, beta=beta,
                        dopant_kind="donor")
    with pytest.raises(ValueError):
        pearson_density(mo)


def test_skew_sign_sets_side_of_peak():
    """Positive γ (P, As) puts the peak shallower than Rp; boron's
    negative γ at 200 keV puts it deeper."""
    for sym, energy, deeper in (("P", 100, False), ("As", 30, False), ("B", 200, True)):
        mo = moments_for(sym, energy)
        depth, p = pearson_density(mo)
        mode = depth[int(np.argmax(p))]
        assert (mode > mo.Rp_um) == deeper, (sym, energy, mode, mo.Rp_um)


# ---------------------------------------------------------------------------
# 3. On the mesh.
# ---------------------------------------------------------------------------

def _bare_si(width_um=0.4, body_um=0.4, mesh=0.004):
    return (Structure(width_um=width_um, name="t")
            .add_substrate("body", body_um, Material.SI)
            .to_meshfield(mesh_size_um=mesh))


def test_implant_writes_dose_times_density():
    mf = _bare_si()
    dose = 1e15
    r = apply_implant(mf, "P", 100, dose)
    assert r.profile == "pearson"
    depth, p = pearson_density(r.moments)
    pts = np.asarray(mf.grid.points)[:, :2]
    d_nodes = pts[:, 1].max() - pts[:, 1]
    expected = dose * np.interp(d_nodes, depth, p / 1e-4, left=0.0, right=0.0)
    np.testing.assert_allclose(mf.Nd, expected, rtol=1e-9, atol=1e-6 * expected.max())


def test_implant_pearson_conserves_dose_and_shifts_peak():
    mf = _bare_si(mesh=0.0025)
    dose = 1e15
    r = apply_implant(mf, "P", 100, dose)
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - 0.2) < 0.005
    y, c = pts[sel, 1], mf.Nd[sel]
    o = np.argsort(y)
    assert np.trapezoid(c[o], y[o] * 1e-4) == pytest.approx(dose, rel=0.02)
    depth, p = pearson_density(r.moments)
    mode = depth[int(np.argmax(p))]
    peak_depth = pts[:, 1].max() - y[int(np.argmax(c))]
    assert abs(peak_depth - mode) < 0.003
    assert r.moments.Rp_um - mode > 0.005   # γ > 0: shallower than Rp


# ---------------------------------------------------------------------------
# 4. BF₂.
# ---------------------------------------------------------------------------

def test_bf2_resolves_to_boron_at_mass_scaled_energy():
    ion, dopant, e = resolve_implant_species("BF2", 100.0)
    assert (ion, dopant) == ("bf2", "boron")
    assert e == pytest.approx(100.0 * 11.009 / 49.005, rel=1e-6)
    assert resolve_implant_species("bf₂", 100.0)[0] == "bf2"
    assert resolve_implant_species("As", 30.0) == ("arsenic", "arsenic", 30.0)


def test_bf2_implant_equals_boron_at_scaled_energy():
    a, b = _bare_si(), _bare_si()
    r = apply_implant(a, "BF2", 100, 1e14)
    apply_implant(b, "B", 100 * 11.009 / 49.005, 1e14)
    assert (r.ion, r.species, r.added_to) == ("bf2", "boron", "Na")
    assert r.energy_keV == 100 and r.dopant_energy_keV == pytest.approx(22.465, rel=1e-3)
    np.testing.assert_allclose(a.Na, b.Na)
    assert a.species_names() == ["boron"]


def test_bf2_out_of_table_names_the_boron_energy():
    with pytest.raises(ValueError, match=r"BF2 at 30 keV puts 6\.74 keV on boron"):
        apply_implant(_bare_si(), "BF2", 30, 1e14)
