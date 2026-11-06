"""
opentcad/device/models/recombination.py — Net recombination contributors.

Each model registers a single node_model expression returning the rate
multiplied by -q (so DEVSIM's continuity equation, which expects an
A/cm^3 source, can sum it directly). The solver builds the total
recombination as the sum of every registered model's term_name.

The sign convention makes avalanche GENERATION fit the same slot:
URec is added to ElectronSource and subtracted from HoleSource, so a
*negative* U contribution adds carriers to both equations — exactly
what pair generation does.

Models implemented:
  SRH       — Shockley-Read-Hall, mid-gap traps (Phase 0 default)
  Auger     — three-particle band-to-band, dominant at >1e18 cm^-3
  Radiative — band-to-band photon emission (negligible in Si, central
              for direct-gap III-V)
  Avalanche — van Overstraeten-de Man impact-ionisation generation
              (unlocks breakdown-voltage extraction)
"""
from __future__ import annotations
from ..physics import RecombinationModel


def _node_with_carrier_derivs(ds, device, region, name, eq):
    """Helper: register a node model and its derivatives w.r.t. Electrons
    and Holes via DEVSIM symbolic diff(). Used by every recombination
    contributor."""
    ds.node_model(device=device, region=region, name=name, equation=eq)
    for var in ("Electrons", "Holes"):
        ds.node_model(device=device, region=region,
                      name=f"{name}:{var}",
                      equation=f"simplify(diff({eq}, {var}))")


class SRH(RecombinationModel):
    """Shockley-Read-Hall recombination with a single mid-gap trap.

    U_SRH = (n*p - n_i^2) / (tau_p*(n + n1) + tau_n*(p + p1))

    Parameters tau_n_s, tau_p_s come from MaterialParams.recombination.
    n1 = p1 = n_i for a mid-gap trap (Et = 0 in the YAML default).
    `n_i_expr` is substituted for the bare n_i wherever BGN is active."""

    term_name = "USRH"

    def attach(self, ds, device, region, params, T_K, n_i_expr="n_i"):
        ds.set_parameter(device=device, region=region, name="taun",
                         value=float(params.recombination.tau_n_s))
        ds.set_parameter(device=device, region=region, name="taup",
                         value=float(params.recombination.tau_p_s))
        ds.set_parameter(device=device, region=region, name="n1",
                         value=float(params.band_structure.ni_cm3_300K))
        ds.set_parameter(device=device, region=region, name="p1",
                         value=float(params.band_structure.ni_cm3_300K))
        eq = (f"-ElectronCharge*(Electrons*Holes - ({n_i_expr})^2)/"
              f"(taup*(Electrons + n1) + taun*(Holes + p1))")
        _node_with_carrier_derivs(ds, device, region, self.term_name, eq)


class Auger(RecombinationModel):
    """Auger recombination — three-particle process where the energy
    released by an electron-hole recombination is given to a third
    carrier instead of a photon.

    U_Auger = (C_n*n + C_p*p) * (n*p - n_i^2)

    Coefficients C_n, C_p for Si: Dziewior & Schmid, APL 31, 346 (1977).
    Auger dominates over SRH for carrier densities > ~1e18 cm^-3, i.e.
    in the n+ emitter / source-drain regions of bipolar and MOS devices.
    """

    term_name = "UAuger"

    def required_params(self) -> tuple[str, ...]:
        return ("recombination.Cn_cm6_per_s", "recombination.Cp_cm6_per_s")

    def attach(self, ds, device, region, params, T_K, n_i_expr="n_i"):
        ds.set_parameter(device=device, region=region, name="Cn_Auger",
                         value=float(params.recombination.Cn_cm6_per_s))
        ds.set_parameter(device=device, region=region, name="Cp_Auger",
                         value=float(params.recombination.Cp_cm6_per_s))
        eq = (f"-ElectronCharge*(Cn_Auger*Electrons + Cp_Auger*Holes)*"
              f"(Electrons*Holes - ({n_i_expr})^2)")
        _node_with_carrier_derivs(ds, device, region, self.term_name, eq)


class Radiative(RecombinationModel):
    """Band-to-band radiative recombination.

    U_rad = B * (n*p - n_i^2)

    Coefficient B from MaterialParams.recombination.B_rad_cm3_per_s.
    Negligible in indirect-gap Si (B ~ 1e-14 cm^3/s); dominant in direct-
    gap GaAs/GaN (B ~ 1e-10)."""

    term_name = "URad"

    def required_params(self) -> tuple[str, ...]:
        return ("recombination.B_rad_cm3_per_s",)

    def attach(self, ds, device, region, params, T_K, n_i_expr="n_i"):
        ds.set_parameter(device=device, region=region, name="B_rad",
                         value=float(params.recombination.B_rad_cm3_per_s))
        eq = (f"-ElectronCharge*B_rad*"
              f"(Electrons*Holes - ({n_i_expr})^2)")
        _node_with_carrier_derivs(ds, device, region, self.term_name, eq)


class Avalanche(RecombinationModel):
    """Impact-ionisation generation (van Overstraeten-de Man, 1970).

    Pair generation rate per unit volume is

        G_avalanche = alpha_n(|E|) * |J_n|/q + alpha_p(|E|) * |J_p|/q

    with Chynoweth-form ionisation coefficients:

        alpha_s(|E|) = a_s * exp(-b_s / |E|)   for s ∈ {n, p}

    We register this as a RecombinationModel with a NEGATIVE value (since
    the sign convention is U = -q*(net recomb)); the solver then adds
    the contribution to both ElectronSource and HoleSource via the
    URec±URec slots that already handle generation terms (optical, etc.).

    MVP approximations (Phase 2a — unblocks breakdown-voltage story,
    does not calibrate exact Vbd):
      * Node-level |E| via DEVSIM's `vector_gradient(Potential)` — the
        gradient magnitude of the Potential at each node. Sharper than
        edge-averaging; coarser than an element-based projection.
      * Current magnitude via the saturation-velocity proxy
            |J_s| ≈ q · v_sat_s · carrier_density
        This is CORRECT in the saturation-drift regime where avalanche
        actually fires (fields of ~3–5e5 V/cm in Si where v_s → v_sat).
        It OVERESTIMATES in the quasi-neutral bulk where n ≈ N_d and
        alpha is near-zero — the alpha factor saves us there, since
        exp(−b/|E|) with |E|≈0 is numerically zero. In the depletion
        region it UNDERESTIMATES because n has dropped by orders. Net:
        the model gets a knee at a higher Vbd than textbook (~2–3× too
        high for Si at N_sub=1e17). Follow-up: replace proxy with the
        real drift-diffusion |J_n|/|J_p| via edge/element-aware models.
      * Alpha derivatives w.r.t. Potential (through EMagAval) are
        omitted from the Newton Jacobian — frozen-field each outer
        iteration. Newton still converges; slower near the knee.
    """

    term_name = "UAvalanche"

    def required_params(self) -> tuple[str, ...]:
        return ("avalanche", "velocity_saturation")

    def attach(self, ds, device, region, params, T_K, n_i_expr="n_i"):
        av = params.avalanche
        vs = params.velocity_saturation
        for name, val in (
            ("a_n_av",  av.a_n_per_cm),
            ("b_n_av",  av.b_n_V_per_cm),
            ("a_p_av",  av.a_p_per_cm),
            ("b_p_av",  av.b_p_V_per_cm),
            ("vsat_n_av", vs.vsat_e_cm_s),
            ("vsat_p_av", vs.vsat_h_cm_s),
        ):
            ds.set_parameter(device=device, region=region, name=name,
                             value=float(val))

        # Node-level Ex, Ey from Potential via DEVSIM's vector_gradient.
        # Registers Potential_gradx and Potential_grady as node models.
        ds.vector_gradient(device=device, region=region,
                           node_model="Potential", calc_type="default")

        # |E|_node with a small floor so exp(-b/|E|) stays finite as
        # the field passes through zero.
        emag_node = ("((Potential_gradx * Potential_gradx) + "
                     "(Potential_grady * Potential_grady) + 1)^(0.5)")
        ds.node_model(device=device, region=region, name="EMagAval",
                      equation=emag_node)

        # Chynoweth ionisation coefficients on nodes. Derivatives w.r.t.
        # Potential (through EMagAval) are intentionally omitted —
        # frozen-field Newton converges but more slowly near breakdown.
        ds.node_model(device=device, region=region, name="AlphaNAval",
                      equation="a_n_av * exp(-b_n_av / EMagAval)")
        ds.node_model(device=device, region=region, name="AlphaPAval",
                      equation="a_p_av * exp(-b_p_av / EMagAval)")

        # U = -q * (alpha_n * vsat_n * n + alpha_p * vsat_p * p)
        # Negative U adds to both ElectronSource and HoleSource (same sign),
        # which is pair generation — the correct avalanche signature.
        eq = ("-ElectronCharge * ("
              "AlphaNAval * vsat_n_av * Electrons"
              " + AlphaPAval * vsat_p_av * Holes)")
        ds.node_model(device=device, region=region, name=self.term_name,
                      equation=eq)
        ds.node_model(device=device, region=region,
                      name=f"{self.term_name}:Electrons",
                      equation="-ElectronCharge * AlphaNAval * vsat_n_av")
        ds.node_model(device=device, region=region,
                      name=f"{self.term_name}:Holes",
                      equation="-ElectronCharge * AlphaPAval * vsat_p_av")
