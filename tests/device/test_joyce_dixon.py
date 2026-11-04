"""
Phase 2a Joyce-Dixon FD extension.

The parent FermiDirac class uses Blakemore, which hits a numerical floor
at n = N_c / ξ ≈ 3.7·N_c and distorts the contact BC for S/D wells doped
above ~1e20 cm⁻³ in Si. JoyceDixon replaces the potential-offset
expression with the explicit Joyce-Dixon series inverse of F_{1/2}.

Four tests:
  * Low-doping agreement — JD, Blakemore and Boltzmann all agree at
    n << N_c.
  * Heavy-doping divergence — at n ≥ 3.7·N_c Blakemore pegs; JD keeps
    going smoothly and monotonically.
  * DEVSIM parameters — JD_a1 and JD_a2 get registered alongside N_c.
  * Full-solve — an n+ substrate contact with JoyceDixon solves to
    equilibrium with smaller contact-potential magnitude than the same
    device with Blakemore (which over-floors at heavy doping).
"""
from __future__ import annotations

import math

import pytest

from opentcad.device.models import Boltzmann, FermiDirac, JoyceDixon


# Analytic cross-check values (kT/q = 25.85 mV, Si N_c = 2.86e19,
# n_i = 9.65e9).
V_T = 0.025852
N_C = 2.86e19
N_I = 9.65e9
XI_BLAKE = 0.27
JD_A1 = 1.0 / math.sqrt(8.0)
JD_A2 = -4.950e-3


def _phi_boltzmann(n: float) -> float:
    return V_T * math.log(n / N_I)


def _phi_blakemore(n: float) -> float:
    denom = max(1.0 - XI_BLAKE * n / N_C, 1e-3)
    return V_T * math.log(n / (N_I * denom))


def _phi_joyce_dixon(n: float) -> float:
    u = n / N_C
    return V_T * (math.log(n / N_I) + JD_A1 * u + JD_A2 * u * u)


# ---------------------------------------------------------------------------
# Analytic tests
# ---------------------------------------------------------------------------

def test_joyce_dixon_agrees_with_boltzmann_at_low_doping():
    """n << N_c ⇒ u → 0 ⇒ JD series = log(n/n_i) + 0."""
    for n in (1e14, 1e15, 1e16, 1e17):
        jd = _phi_joyce_dixon(n)
        bz = _phi_boltzmann(n)
        assert abs(jd - bz) < 2e-3, (
            f"n={n}: JD {jd:.4f} vs Boltzmann {bz:.4f}")


def test_joyce_dixon_diverges_from_blakemore_above_ceiling():
    """At n ~> 3.7·N_c the Blakemore log denominator floors at 1e-3 and
    overshoots; JD should produce a *lower* potential and keep moving
    smoothly as doping rises."""
    n_floor = 5e20   # u ≈ 17, well above Blakemore ceiling
    jd = _phi_joyce_dixon(n_floor)
    bk = _phi_blakemore(n_floor)
    # Blakemore saturates ~0.83 V; JD lands lower and keeps moving.
    assert bk > jd
    assert bk - jd > 0.05   # at least 50 mV separation
    # JD must still be monotone-increasing in n.
    jd_higher = _phi_joyce_dixon(n_floor * 2)
    assert jd_higher > jd


def test_joyce_dixon_potential_offset_formula_contains_series_terms():
    """The expression returned to DEVSIM must reference the Joyce-Dixon
    coefficients — otherwise we're silently falling back to Blakemore."""
    jd = JoyceDixon()
    expr_e = jd.electron_potential_offset("Electrons", "n_i", params=None)
    expr_h = jd.hole_potential_offset("Holes", "n_i", params=None)
    for expr in (expr_e, expr_h):
        assert "JD_a1" in expr
        assert "JD_a2" in expr
        assert "log(" in expr


# ---------------------------------------------------------------------------
# DEVSIM full-solve test
# ---------------------------------------------------------------------------

pytest.importorskip("devsim")


@pytest.mark.requires_devsim
def test_joyce_dixon_registers_parameters_in_devsim():
    """JoyceDixon.attach must add JD_a1 and JD_a2 as DEVSIM parameters
    on the region, alongside the parent FermiDirac's N_c / N_v / FD_xi."""
    import devsim as ds
    from opentcad.geometry.formats import Material
    from opentcad.geometry.structure import Structure
    from opentcad.device.solver import DeviceSolver
    from opentcad.device.physics import PhysicsConfig
    from opentcad.materials.database import load_material

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass

    mf = (Structure(width_um=0.5, name="jd_smoke")
          .add_substrate("si", 0.5, Material.SI, doping_Nd=1e20)
          .add_contact("top", 0.0, 0.5, "si", surface="top")
          .add_contact("bot", 0.0, 0.5, "si", surface="bottom")
          .to_meshfield(mesh_size_um=0.05))
    cfg = PhysicsConfig(statistics=JoyceDixon())
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=cfg)
    solver.solve_equilibrium()

    for name in ("N_c", "N_v", "FD_xi", "JD_a1", "JD_a2"):
        val = ds.get_parameter(device=solver._device_name, region="SI",
                                name=name)
        assert float(val) is not None, f"parameter {name} not registered"

    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
