"""
opentcad/device/models/mobility.py — Bulk + high-field mobility models.

Each model implements `attach(ds, device, region, params, T_K)` and
exposes `mu_n_expr()` / `mu_p_expr()` returning the DEVSIM expression
the solver should inline into the Scharfetter-Gummel current density.

Carrier-dependent models (Klaassen) must register :Electrons@n0/@n1 /
:Holes@n0/@n1 derivatives on any edge model they name so DEVSIM's
diff() picks them up via the chain rule.

Composition:
  Canali(base=Klaassen())  # doping + carrier + high-field
  Canali(base=ConstantMobility())  # simple + high-field
"""
from __future__ import annotations
from typing import Optional
from ..physics import MobilityModel


class ConstantMobility(MobilityModel):
    """Constant mobility from MaterialParams.mobility_constant.

    No doping or carrier dependence. This is the Phase 0 default and
    reproduces the original DeviceSolver behavior exactly."""

    requires_carriers = False

    def attach(self, ds, device, region, params, T_K):
        mu_n = params.mobility_constant.electron_cm2_Vs
        mu_p = params.mobility_constant.hole_cm2_Vs
        ds.set_parameter(device=device, region=region, name="mu_n",
                         value=float(mu_n))
        ds.set_parameter(device=device, region=region, name="mu_p",
                         value=float(mu_p))

    def mu_n_expr(self): return "mu_n"
    def mu_p_expr(self): return "mu_p"


class Klaassen(MobilityModel):
    """Klaassen unified low-field bulk mobility.

    Reference: Klaassen, *A unified mobility model for device simulation*,
    Solid-State Electronics 35, 953 (1992). The implementation follows
    DEVSIM's reference Klaassen.py.

    Captures:
      - lattice scattering (mu_L ~ T^-theta)
      - donor / acceptor ionized impurity scattering with clustering (Z_D, Z_A)
      - carrier–carrier scattering (mu_e_c, mu_h_c)
      - majority/minority partitioning via the F_P, G_P factors

    Output edge models `ElectronMobilityEdge` / `HoleMobilityEdge` are
    geometric means of node values; carrier derivatives are registered
    so Newton on the continuity equations converges.
    """

    requires_carriers = True

    def attach(self, ds, device, region, params, T_K):
        self._set_parameters(ds, device, region, params, T_K)
        self._build_node_models(ds, device, region)
        self._build_edge_models(ds, device, region)

    def mu_n_expr(self): return "ElectronMobilityEdge"
    def mu_p_expr(self): return "HoleMobilityEdge"

    def _set_parameters(self, ds, device, region, params, T_K):
        k = params.mobility_klaassen
        for name, value in vars(k).items():
            ds.set_parameter(device=device, region=region, name=name,
                             value=float(value))
        ds.set_parameter(device=device, region=region, name="T",
                         value=float(T_K))

    def _build_node_models(self, ds, device, region):
        # Constants: lattice + carrier-carrier terms (no carrier derivatives).
        scalar_models = {
            "mu_L_e": "(mu_max_e * (300 / T)^theta1_e)",
            "mu_L_h": "(mu_max_h * (300 / T)^theta1_h)",
            "mu_e_N": "(mu_max_e * mu_max_e / (mu_max_e - mu_min_e) * "
                      "(T/300)^(3*alpha_1_e - 1.5))",
            "mu_h_N": "(mu_max_h * mu_max_h / (mu_max_h - mu_min_h) * "
                      "(T/300)^(3*alpha_1_h - 1.5))",
            "mu_e_c": "(mu_min_e * mu_max_e / (mu_max_e - mu_min_e)) * "
                      "(300/T)^(0.5)",
            "mu_h_c": "(mu_min_h * mu_max_h / (mu_max_h - mu_min_h)) * "
                      "(300/T)^(0.5)",
            # max(.,1) floor prevents divide-by-zero when the region is
            # pure n-type (Acceptors=0) or pure p-type (Donors=0).
            # Adding 1 cm^-3 background has no effect on real device fields
            # (which start at >= 1e10) but keeps the formula evaluable.
            "Z_D": "(1 + 1 / (c_D + (Nref_D / max(Donors, 1))^2))",
            "Z_A": "(1 + 1 / (c_A + (Nref_A / max(Acceptors, 1))^2))",
            "N_D_K": "(Z_D * max(Donors, 1))",
            "N_A_K": "(Z_A * max(Acceptors, 1))",
        }
        for name, eq in scalar_models.items():
            ds.node_model(device=device, region=region, name=name, equation=eq)

        # Carrier-dependent intermediates. Each gets diff w.r.t. Electrons & Holes.
        carrier_models = [
            ("PBH_e", "(1.36e20/(Electrons + Holes) * m_e * (T/300)^2)"),
            ("PBH_h", "(1.36e20/(Electrons + Holes) * m_h * (T/300)^2)"),
            ("N_e_sc", "(N_D_K + N_A_K + Holes)"),
            ("N_h_sc", "(N_A_K + N_D_K + Electrons)"),
            ("PCW_e", "(3.97e13 * (1/(Z_D^3 * N_e_sc) * (T/300)^3)^(2/3))"),
            ("PCW_h", "(3.97e13 * (1/(Z_A^3 * N_h_sc) * (T/300)^3)^(2/3))"),
            ("Pe", "(1/(f_CW / PCW_e + f_BH/PBH_e))"),
            ("Ph", "(1/(f_CW / PCW_h + f_BH/PBH_h))"),
            ("G_Pe",
             "(1 - s1/(s2 + (1.0/m_e * T/300)^s4 * Pe)^s3 + "
             "s5/((m_e * 300/T)^s7 * Pe)^s6)"),
            ("G_Ph",
             "(1 - s1/(s2 + (1.0/m_h * T/300)^s4 * Ph)^s3 + "
             "s5/((m_h * 300/T)^s7 * Ph)^s6)"),
            ("F_Pe",
             "((r1 * Pe^r6 + r2 + r3 * m_e/m_h)/"
             "(Pe^r6 + r4 + r5 * m_e/m_h))"),
            ("F_Ph",
             "((r1 * Ph^r6 + r2 + r3 * m_h/m_e)/"
             "(Ph^r6 + r4 + r5 * m_h/m_e))"),
            ("N_e_sc_eff", "(N_D_K + G_Pe * N_A_K + Holes / F_Pe)"),
            ("N_h_sc_eff", "(N_A_K + G_Ph * N_D_K + Electrons / F_Ph)"),
            ("mu_e_D_A_h",
             "mu_e_N * N_e_sc/N_e_sc_eff * (Nref_1_e / N_e_sc)^alpha_1_e + "
             "mu_e_c * ((Electrons + Holes)/N_e_sc_eff)"),
            ("mu_h_D_A_e",
             "mu_h_N * N_h_sc/N_h_sc_eff * (Nref_1_h / N_h_sc)^alpha_1_h + "
             "mu_h_c * ((Electrons + Holes)/N_h_sc_eff)"),
            ("ElectronMobilityNode",
             "mu_e_D_A_h * mu_L_e / (mu_e_D_A_h + mu_L_e)"),
            ("HoleMobilityNode",
             "mu_h_D_A_e * mu_L_h / (mu_h_D_A_e + mu_L_h)"),
        ]
        for name, eq in carrier_models:
            ds.node_model(device=device, region=region, name=name, equation=eq)
            for var in ("Electrons", "Holes"):
                ds.node_model(device=device, region=region,
                              name=f"{name}:{var}",
                              equation=f"simplify(diff({eq}, {var}))")

    def _build_edge_models(self, ds, device, region):
        # Geometric mean of node mobilities onto edges, with derivatives.
        # DEVSIM's edge_average_model handles the @n0/@n1 indirection and
        # auto-registers the four derivative entries per variable.
        for kind, node_name in (("ElectronMobilityEdge", "ElectronMobilityNode"),
                                ("HoleMobilityEdge",    "HoleMobilityNode")):
            ds.edge_average_model(device=device, region=region,
                                  edge_model=kind, node_model=node_name,
                                  average_type="geometric")
            for var in ("Electrons", "Holes"):
                ds.edge_average_model(device=device, region=region,
                                      edge_model=kind, node_model=node_name,
                                      derivative=var,
                                      average_type="geometric")


class Canali(MobilityModel):
    """Canali high-field velocity-saturation mobility (1975).

    Wraps an underlying low-field bulk model:

        mu_eff = mu_bulk / (1 + (mu_bulk*|E| / vsat)^beta)^(1/beta)

    where |E| is the field magnitude along the edge. In the low-field
    limit mu_eff -> mu_bulk; at high field the drift velocity saturates
    at vsat regardless of mu_bulk. Reference: Canali, Majni, Minder,
    Ottaviani, IEEE TED 22, 1045 (1975).

    Composes with any MobilityModel:
        Canali(base=Klaassen())       — full CMOS mobility
        Canali(base=ConstantMobility()) — simple high-field
    """

    def __init__(self, base: Optional[MobilityModel] = None):
        self.base = base if base is not None else ConstantMobility()

    @property
    def requires_carriers(self) -> bool:
        return self.base.requires_carriers

    def attach(self, ds, device, region, params, T_K):
        self.base.attach(ds, device, region, params, T_K)
        vs = params.velocity_saturation
        for name, val in (("vsat_e", vs.vsat_e_cm_s),
                          ("vsat_h", vs.vsat_h_cm_s),
                          ("beta_e", vs.beta_e),
                          ("beta_h", vs.beta_h)):
            ds.set_parameter(device=device, region=region, name=name,
                             value=float(val))

        # |EField| as sqrt(EField^2 + eps^2) — a smoothed magnitude so
        # the derivative doesn't have a kink at E=0 (which would break
        # Newton during the initial ramp when the field is small). eps=1
        # V/cm is negligible compared to any field of physical interest
        # (typical relevant fields are 1e3 - 1e6 V/cm).
        mu_bulk_e = self.base.mu_n_expr()
        mu_bulk_h = self.base.mu_p_expr()
        e_mag = "((EField*EField) + 1)^(0.5)"

        mu_e = (f"({mu_bulk_e}) / "
                f"(1 + ((({mu_bulk_e})*{e_mag}) / vsat_e)^beta_e)^(1/beta_e)")
        mu_h = (f"({mu_bulk_h}) / "
                f"(1 + ((({mu_bulk_h})*{e_mag}) / vsat_h)^beta_h)^(1/beta_h)")

        ds.edge_model(device=device, region=region,
                      name="ElectronMobilityCanali", equation=mu_e)
        ds.edge_model(device=device, region=region,
                      name="HoleMobilityCanali", equation=mu_h)

        # Field-derivative always needed (Potential appears via EField).
        for var in ("Potential@n0", "Potential@n1"):
            ds.edge_model(device=device, region=region,
                          name=f"ElectronMobilityCanali:{var}",
                          equation=f"simplify(diff({mu_e}, {var}))")
            ds.edge_model(device=device, region=region,
                          name=f"HoleMobilityCanali:{var}",
                          equation=f"simplify(diff({mu_h}, {var}))")

        # If the base model depends on carriers (Klaassen), the wrapped
        # expression does too — expose those derivatives to Newton.
        if self.requires_carriers:
            for var in ("Electrons@n0", "Electrons@n1",
                        "Holes@n0",     "Holes@n1"):
                ds.edge_model(device=device, region=region,
                              name=f"ElectronMobilityCanali:{var}",
                              equation=f"simplify(diff({mu_e}, {var}))")
                ds.edge_model(device=device, region=region,
                              name=f"HoleMobilityCanali:{var}",
                              equation=f"simplify(diff({mu_h}, {var}))")

    def mu_n_expr(self): return "ElectronMobilityCanali"
    def mu_p_expr(self): return "HoleMobilityCanali"
