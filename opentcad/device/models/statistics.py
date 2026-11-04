"""
opentcad/device/models/statistics.py — Carrier statistics models.

Wraps the Boltzmann-form n(potential) / p(potential) expressions with a
statistics-specific correction. Boltzmann is the Phase 0 default:

    n_boltz = n_i * exp(Potential / V_t)

FermiDirac (Blakemore approximation) applies the correction:

    n_FD = n_boltz / (1 + xi * n_boltz / N_c)         xi = 0.27

which saturates smoothly at N_c/xi ~ 3.7*N_c as the classical
n → infty limit — capturing the degeneracy of heavy doping without
solving the exact Fermi-Dirac integral F_{1/2}.

References:
  Blakemore, Solid-State Electron. 25, 1067 (1982) — approximation.
  Joyce, Dixon, APL 31, 354 (1977) — inverse-F_{1/2} series expansion.
  Sze, Ng, Physics of Semiconductor Devices, 3rd ed., ch. 1.
"""
from __future__ import annotations
from ..physics import StatisticsModel


class Boltzmann(StatisticsModel):
    """Boltzmann (Maxwell-Boltzmann) statistics — the Phase 0 default.

    n = N_c * exp((E_F - E_c) / kT) — valid when E_F is at least a few
    kT below E_c. Breaks down at doping > ~1e19 cm^-3 in Si where
    degeneracy becomes important."""

    def wrap_electron_density(self, expr, params): return expr
    def wrap_hole_density(self, expr, params): return expr

    def electron_potential_offset(self, n_expr, n_i_expr, params):
        return f"V_t*log(({n_expr})/({n_i_expr}))"

    def hole_potential_offset(self, p_expr, n_i_expr, params):
        return f"V_t*log(({p_expr})/({n_i_expr}))"


class FermiDirac(StatisticsModel):
    """Fermi-Dirac statistics via the Blakemore approximation.

    F_{1/2}(eta) ≈ 1 / (exp(-eta) + xi) with xi = 0.27 in the standard
    Blakemore fit. Rearranging in terms of the Boltzmann-form n:

        n_FD = n_boltz / (1 + xi * n_boltz / N_c)

    Valid for n/N_c up to ~ 1/xi = 3.7 (Blakemore ceiling). Above this
    the more accurate Joyce-Dixon inverse expansion is needed — noted
    as follow-up.

    Impact:
      - Light doping (n << N_c): reduces to Boltzmann (n_FD ≈ n_boltz).
      - Heavy doping (n ~ N_c): softens the exp() growth of n vs. E_F,
        so the built-in potential and Vth extraction shift by 10-100 mV
        compared to Boltzmann.
    """

    #: Blakemore fit coefficient (dimensionless).
    xi: float = 0.27

    def attach(self, ds, device, region, params, T_K):
        ds.set_parameter(device=device, region=region, name="N_c",
                         value=float(params.band_structure.Nc_cm3_300K))
        ds.set_parameter(device=device, region=region, name="N_v",
                         value=float(params.band_structure.Nv_cm3_300K))
        ds.set_parameter(device=device, region=region, name="FD_xi",
                         value=float(self.xi))

    def wrap_electron_density(self, expr, params):
        return f"({expr}) / (1 + FD_xi * ({expr}) / N_c)"

    def wrap_hole_density(self, expr, params):
        return f"({expr}) / (1 + FD_xi * ({expr}) / N_v)"

    def electron_potential_offset(self, n_expr, n_i_expr, params):
        # Blakemore inverse: given n, E_F - E_i satisfies
        # n = n_i * exp((E_F-E_i)/kT) / (1 + xi*n_i*exp((E_F-E_i)/kT)/N_c)
        # -> (E_F-E_i)/kT = log(n / (n_i * (1 - xi*n/N_c)))
        # Floor (1 - xi*n/Nc) at 1e-3 so log stays real when n approaches
        # the Blakemore ceiling N_c/xi ≈ 3.7 N_c.
        return (f"V_t*log(({n_expr})/(({n_i_expr})*"
                f"max(1 - FD_xi*({n_expr})/N_c, 1e-3)))")

    def hole_potential_offset(self, p_expr, n_i_expr, params):
        return (f"V_t*log(({p_expr})/(({n_i_expr})*"
                f"max(1 - FD_xi*({p_expr})/N_v, 1e-3)))")


class JoyceDixon(FermiDirac):
    """Joyce-Dixon series inverse of F_{1/2} for heavy-doping statistics.

    The Blakemore approximation that the parent FermiDirac class uses
    saturates (and the inverse's log denominator vanishes) at n = N_c/ξ
    ≈ 3.7·N_c — making it unreliable for S/D wells doped above ~1e20
    cm⁻³ in Si. Joyce & Dixon (APL 31, 354, 1977) derived an explicit
    series for the inverse Fermi-Dirac integral:

        η(u) = ln(u) + a_1·u + a_2·u² + a_3·u³ + a_4·u⁴ + …

    with a_1 = 1/√8 ≈ 0.3536, a_2 ≈ -4.950e-3, a_3 ≈ 1.483e-4,
    a_4 ≈ -4.426e-6. The first two terms are accurate to <1 % for
    u ≤ 10 (i.e., n ≤ ~3e20 in Si at 300 K).

    What this class changes vs. the parent FermiDirac:
      * `electron_potential_offset` and `hole_potential_offset` are
        replaced by the explicit Joyce-Dixon form. No more Blakemore
        ceiling in the ohmic-contact BC: as n/N_c grows past 4 the
        parent's `log(n / (n_i*(1 - ξn/Nc)))` floors at 1e-3 and loses
        physical meaning; this form keeps running.
      * `wrap_electron_density` / `wrap_hole_density` keep the Blakemore
        forward expressions. Replacing those symbolically with a true
        F_{1/2} inverse-of-inverse isn't straightforwardly expressible
        in DEVSIM's symbolic engine, and the forward form matters less
        in practice since Newton iterates in the carrier variables.

    Use case: this is the right class to pick for Si sources/drains at
    1e20+ doping where Blakemore distorts the contact BC noticeably.
    """
    # Series coefficients (Joyce & Dixon 1977). Include through 2nd
    # order — accurate to < 1 % for u ≤ 10 which covers all practical
    # Si doping ranges. Register as DEVSIM parameters alongside N_c / N_v.
    jd_a1: float = 0.3535533905932738   # 1/sqrt(8)
    jd_a2: float = -4.950e-3

    def attach(self, ds, device, region, params, T_K):
        super().attach(ds, device, region, params, T_K)
        ds.set_parameter(device=device, region=region, name="JD_a1",
                         value=float(self.jd_a1))
        ds.set_parameter(device=device, region=region, name="JD_a2",
                         value=float(self.jd_a2))

    def electron_potential_offset(self, n_expr, n_i_expr, params):
        # (E_F - E_i)/kT = ln(n/n_i) + a_1·(n/N_c) + a_2·(n/N_c)²
        # Derived from η(u) = ln(u) + Σ a_k u^k with u = n/N_c and the
        # Boltzmann anchor (E_F-E_i)/kT = ln(n/n_i) for u→0.
        n = f"({n_expr})"
        ni = f"({n_i_expr})"
        u = f"({n}/N_c)"
        return (f"V_t*(log({n}/{ni}) + JD_a1*{u} + JD_a2*{u}*{u})")

    def hole_potential_offset(self, p_expr, n_i_expr, params):
        p = f"({p_expr})"
        ni = f"({n_i_expr})"
        u = f"({p}/N_v)"
        return (f"V_t*(log({p}/{ni}) + JD_a1*{u} + JD_a2*{u}*{u})")
