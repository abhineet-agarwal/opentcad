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
from .references import CANALI_1975, KLAASSEN_1992, LOMBARDI_1988


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

    references = (KLAASSEN_1992,)

    requires_carriers = True

    def required_params(self) -> tuple[str, ...]:
        return ("mobility_klaassen",)

    def attach(self, ds, device, region, params, T_K):
        self._set_parameters(ds, device, region, params, T_K)
        self._build_node_models(ds, device, region)
        self._build_edge_models(ds, device, region)

    def mu_n_expr(self): return "ElectronMobilityEdge"
    def mu_p_expr(self): return "HoleMobilityEdge"

    def _set_parameters(self, ds, device, region, params, T_K):
        k = params.mobility_klaassen
        for name, value in k.items():
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

        mu_eff = mu_bulk / (1 + (mu_bulk*F / vsat)^beta)^(1/beta)

    In the low-field limit mu_eff -> mu_bulk; at high driving force F the
    drift velocity saturates at vsat regardless of mu_bulk. Reference:
    Canali, Majni, Minder, Ottaviani, IEEE TED 22, 1045 (1975).

    The driving force F on each mesh edge is one of:

    * ``"quasi_fermi"`` (default): the gradient of the carrier's quasi-Fermi
      potential along the edge, phi_n = psi - V_t*ln(n/n_i) (the Boltzmann
      form). Only the field that drives the current counts: across an
      inversion layer the quasi-Fermi level is flat, so the gate field
      doesn't slow carriers moving along the channel.
    * ``"efield"``: the electric field along the edge (the earlier
      default). On a mesh whose edges are not aligned with the current, oblique
      edges in a MOSFET channel pick up the vertical gate field, so
      saturation is overstated: in the SKY130 NMOS check Ion is 38 % low
      with it and 3.6 % low with ``"quasi_fermi"``.

    For ``"quasi_fermi"`` both densities in the logarithm are offset by
    ``density_ref_cm3``. Where the carrier density is well above it the
    force is the quasi-Fermi gradient; well below, it tends to the electric
    field. Without the offset, minority carriers that drop by orders of
    magnitude over the last mesh edge before an ohmic contact see a large
    quasi-Fermi step there, and their diffusion is throttled (a forward p-n
    diode's current halves). The offset is a numerical choice, not a
    material parameter. In the Jacobian the force's density dependence is
    left out (its potential dependence is kept): with it, Newton's first
    update after a bias step diverges. The converged solution is unchanged.

    In a uniform resistor the two forces are the same.

    Composes with any MobilityModel:
        Canali(base=Klaassen())       — full CMOS mobility
        Canali(base=ConstantMobility()) — simple high-field
    """

    references = (CANALI_1975,)

    DRIVING_FORCES = ("quasi_fermi", "efield")

    def required_params(self) -> tuple[str, ...]:
        return ("velocity_saturation",) + self.base.required_params()

    def __init__(self, base: Optional[MobilityModel] = None,
                 driving_force: str = "quasi_fermi", density_ref_cm3: float = 1e15):
        if driving_force not in self.DRIVING_FORCES:
            raise ValueError(f"driving_force must be one of {self.DRIVING_FORCES}, "
                             f"not {driving_force!r}")
        if not density_ref_cm3 > 0:
            raise ValueError("density_ref_cm3 must be positive")
        self.base = base if base is not None else ConstantMobility()
        self.driving_force = driving_force
        self.density_ref_cm3 = float(density_ref_cm3)

    @property
    def requires_carriers(self) -> bool:
        # Cross-carrier coupling comes only from the base: the quasi-Fermi
        # force's own density dependence is left out of the Jacobian (attach).
        return self.base.requires_carriers

    def _forces(self, ni: str) -> tuple[str, str]:
        """Smoothed edge driving force for electrons and holes, in V/cm.

        sqrt(F^2 + 1): a smoothed magnitude so the derivative has no kink at
        F = 0 (which would break Newton during the initial ramp). 1 V/cm is
        negligible next to any field of interest (1e3 - 1e6 V/cm).
        """
        if self.driving_force == "efield":
            e_mag = "((EField*EField) + 1)^(0.5)"
            return e_mag, e_mag
        # phi_n@n0 - phi_n@n1 = dpsi - V_t*ln(n0/n1) + V_t*ln(ni0/ni1), and
        # phi_p@n0 - phi_p@n1 = dpsi + V_t*ln(p0/p1) - V_t*ln(ni0/ni1).
        dpsi = "(Potential@n0 - Potential@n1)"
        dni = "" if ni == "n_i" else f" + V_t*log({ni}@n0/{ni}@n1)"
        nf = f"{self.density_ref_cm3:.6g}"
        dphi_n = (f"({dpsi} - V_t*log((Electrons@n0 + {nf})/(Electrons@n1 + {nf}))"
                  f"{dni})")
        dphi_p = (f"({dpsi} + V_t*log((Holes@n0 + {nf})/(Holes@n1 + {nf}))"
                  f"{dni.replace(' + ', ' - ', 1)})")
        return tuple(f"((({d})*EdgeInverseLength)^2 + 1)^(0.5)" for d in (dphi_n, dphi_p))

    def attach(self, ds, device, region, params, T_K):
        self.base.attach(ds, device, region, params, T_K)
        # Bandgap narrowing (attached before mobility) registers n_i_eff.
        ni = ("n_i_eff" if "n_i_eff" in ds.get_node_model_list(device=device, region=region)
              else "n_i")
        if (ni == "n_i_eff" and self.driving_force == "quasi_fermi"
                and "n_i_eff@n0" not in ds.get_edge_model_list(device=device, region=region)):
            # The quasi-Fermi force reads n_i_eff at both edge ends.
            ds.edge_from_node_model(device=device, region=region, node_model="n_i_eff")
        vs = params.velocity_saturation
        for name, val in (("vsat_e", vs.vsat_e_cm_s),
                          ("vsat_h", vs.vsat_h_cm_s),
                          ("beta_e", vs.beta_e),
                          ("beta_h", vs.beta_h)):
            ds.set_parameter(device=device, region=region, name=name,
                             value=float(val))

        mu_bulk_e = self.base.mu_n_expr()
        mu_bulk_h = self.base.mu_p_expr()
        f_e, f_h = self._forces(ni)
        if self.driving_force == "quasi_fermi":
            # The force is its own edge model with only its potential
            # derivatives. Newton then treats its density dependence as
            # frozen within an iteration: with the exact density derivatives
            # (~V_t/n on edges where n spans orders of magnitude) the first
            # update after a bias step diverges, even on a reverse-biased
            # p-n diode. The converged solution is the same; only the
            # Jacobian is approximate.
            for name, eq in (("CanaliForceElectrons", f_e), ("CanaliForceHoles", f_h)):
                ds.edge_model(device=device, region=region, name=name, equation=eq)
                for var in ("Potential@n0", "Potential@n1"):
                    ds.edge_model(device=device, region=region, name=f"{name}:{var}",
                                  equation=f"simplify(diff({eq}, {var}))")
            f_e, f_h = "CanaliForceElectrons", "CanaliForceHoles"

        mu_e = (f"({mu_bulk_e}) / "
                f"(1 + ((({mu_bulk_e})*{f_e}) / vsat_e)^beta_e)^(1/beta_e)")
        mu_h = (f"({mu_bulk_h}) / "
                f"(1 + ((({mu_bulk_h})*{f_h}) / vsat_h)^beta_h)^(1/beta_h)")

        ds.edge_model(device=device, region=region,
                      name="ElectronMobilityCanali", equation=mu_e)
        ds.edge_model(device=device, region=region,
                      name="HoleMobilityCanali", equation=mu_h)

        # Potential always appears (EField or the quasi-Fermi difference).
        variables = ["Potential@n0", "Potential@n1"]
        if self.requires_carriers:
            # Klaassen-type bases depend on both carriers; expose those
            # derivatives to Newton.
            variables += ["Electrons@n0", "Electrons@n1", "Holes@n0", "Holes@n1"]
        for var in variables:
            ds.edge_model(device=device, region=region,
                          name=f"ElectronMobilityCanali:{var}",
                          equation=f"simplify(diff({mu_e}, {var}))")
            ds.edge_model(device=device, region=region,
                          name=f"HoleMobilityCanali:{var}",
                          equation=f"simplify(diff({mu_h}, {var}))")

    def mu_n_expr(self): return "ElectronMobilityCanali"
    def mu_p_expr(self): return "HoleMobilityCanali"


class Lombardi(MobilityModel):
    """Lombardi surface mobility model.

    Combines a bulk mobility with acoustic-phonon and surface-roughness
    scattering via Matthiessen's rule:

        1/mu_surf = 1/mu_bulk + 1/mu_ac + 1/mu_sr

    where mu_ac and mu_sr depend on the normal field at the Si/SiO2
    interface:

        mu_ac(E_norm) = B/E_norm + C*NI^tau / (E_norm^(1/3) * (T/300)^kappa)
        mu_sr(E_norm) = delta / E_norm^gamma
        gamma        = A + alpha*(n+p) / NI^eta

    NI = |Donors| + |Acceptors| is the total ionised impurity density.
    Reference: Lombardi, Manzini, Saporito, Vanzi, IEEE TCAD 7, 1164 (1988).
    The coefficients come from the material file's ``mobility_lombardi``
    block (Si.yaml carries Darwish 1997's values, as in DEVSIM's Klaassen.py
    ``Philips_Surface_Mobility``); a file without the block is refused.

    Composes with any bulk model. Typical MOS use:

        Lombardi(base=Canali(base=Klaassen()))

    E_normal selection via the ``e_normal_axis`` kwarg:
      * ``"y"`` (default) — use ``|Potential_grady|`` via DEVSIM
        ``vector_gradient``. This is the physical normal field for a
        horizontal Si/SiO2 interface (the layered-DSL case), so it is
        the right default for planar MOSFETs. Averaging node→edge
        matches what ``Lb_NI`` already does.
      * ``"x"`` — use ``|Potential_gradx|`` for vertical-sidewall
        interfaces (FinFET fin side, trench MOS).
      * ``"magnitude"`` — the earlier behavior: the edge ``EField``
        magnitude, isotropic and independent of the interface
        orientation. Use for comparison or for devices without a
        well-defined interface normal.

    Caveats:
      * The axis toggle is global per region — a device whose Si/SiO2
        interface genuinely changes orientation (curved birds-beak,
        45-degree sidewalls) still needs a per-element projection, which
        requires element-aware models and is documented as follow-up.
      * ``Potential_grady`` depends on ``Potential`` only — its
        derivative wrt ``Potential`` at each node is finite but
        averaging to edges smooths out the step; Newton converges.
    """

    references = (LOMBARDI_1988,)

    def required_params(self) -> tuple[str, ...]:
        return ("mobility_lombardi",) + self.base.required_params()

    def __init__(self, base: Optional[MobilityModel] = None,
                 e_normal_axis: str = "y"):
        self.base = base if base is not None else ConstantMobility()
        if e_normal_axis not in {"y", "x", "magnitude"}:
            raise ValueError(
                f"e_normal_axis must be 'y', 'x' or 'magnitude' "
                f"(got {e_normal_axis!r})")
        self.e_normal_axis = e_normal_axis

    @property
    def requires_carriers(self) -> bool:
        return True   # Lombardi mu_sr's gamma depends on (n+p)

    def attach(self, ds, device, region, params, T_K):
        self.base.attach(ds, device, region, params, T_K)
        for name, val in params.mobility_lombardi.items():
            ds.set_parameter(device=device, region=region, name=f"Lb_{name}",
                             value=float(val))
        ds.set_parameter(device=device, region=region, name="T",
                         value=float(T_K))

        # NI = |Donors| + |Acceptors| as a node model, projected to edge
        # via geometric mean (matches Klaassen.py Philips_Surface_Mobility).
        ds.node_model(device=device, region=region, name="Lb_NI_node",
                      equation="max(Donors + Acceptors, 1)")
        ds.edge_average_model(device=device, region=region,
                              edge_model="Lb_NI",
                              node_model="Lb_NI_node",
                              average_type="geometric")

        # E_normal source depends on the configured axis. 1 V/cm floor
        # keeps mu_ac / mu_sr denominators away from zero; far below any
        # real MOSFET inversion-layer field (1e4 - 1e6 V/cm typical).
        if self.e_normal_axis == "magnitude":
            # Isotropic back-compat path: use smoothed edge |EField|.
            e_mag = "((EField*EField) + 1)^(0.5)"
            ds.edge_model(device=device, region=region, name="Lb_Emag",
                          equation=f"max({e_mag}, 1)")
        else:
            # Interface-normal path: use vector_gradient's y- or x-
            # component, averaged node→edge via arithmetic edge_average.
            ds.vector_gradient(device=device, region=region,
                               node_model="Potential", calc_type="default")
            comp = "Potential_grady" if self.e_normal_axis == "y" \
                else "Potential_gradx"
            ds.node_model(device=device, region=region,
                          name="Lb_Enorm_node",
                          equation=f"((({comp})*({comp})) + 1)^(0.5)")
            ds.edge_average_model(
                device=device, region=region,
                edge_model="Lb_Emag_raw",
                node_model="Lb_Enorm_node",
                average_type="arithmetic")
            ds.edge_model(device=device, region=region, name="Lb_Emag",
                          equation="max(Lb_Emag_raw, 1)")

        # Acoustic-phonon-limited surface mobility (edge)
        for k in ("e", "h"):
            ds.edge_model(
                device=device, region=region, name=f"Lb_mu_ac_{k}",
                equation=(
                    f"Lb_B_{k}/Lb_Emag "
                    f"+ (Lb_C_{k} * Lb_NI^Lb_tau_{k}) "
                    f"/ (Lb_Emag^(1.0/3.0) * (T/300)^Lb_kappa_{k})"))

        # Surface-roughness mobility (edge). gamma_x depends on (n+p),
        # so it needs carrier derivatives — use edge_average of a node model.
        for k in ("e", "h"):
            ds.node_model(device=device, region=region,
                          name=f"Lb_gamma_{k}_node",
                          equation=(
                              f"Lb_A_{k} + Lb_alpha_{k} * "
                              f"(Electrons + Holes) / Lb_NI_node^Lb_eta_{k}"))
            for var in ("Electrons", "Holes"):
                ds.node_model(
                    device=device, region=region,
                    name=f"Lb_gamma_{k}_node:{var}",
                    equation=(
                        f"simplify(diff("
                        f"Lb_A_{k} + Lb_alpha_{k} * "
                        f"(Electrons + Holes) / Lb_NI_node^Lb_eta_{k}, {var}))"))
            ds.edge_average_model(
                device=device, region=region,
                edge_model=f"Lb_gamma_{k}",
                node_model=f"Lb_gamma_{k}_node",
                average_type="arithmetic")
            for var in ("Electrons", "Holes"):
                ds.edge_average_model(
                    device=device, region=region,
                    edge_model=f"Lb_gamma_{k}",
                    node_model=f"Lb_gamma_{k}_node",
                    derivative=var,
                    average_type="arithmetic")
            ds.edge_model(
                device=device, region=region, name=f"Lb_mu_sr_{k}",
                equation=f"Lb_delta_{k} / Lb_Emag^Lb_gamma_{k}")

        # Matthiessen composition: mu_surf = mu_b*mu_ac*mu_sr / (sum products)
        mu_bulk_e = self.base.mu_n_expr()
        mu_bulk_h = self.base.mu_p_expr()

        mu_e = (f"({mu_bulk_e}) * Lb_mu_ac_e * Lb_mu_sr_e / "
                f"(({mu_bulk_e})*Lb_mu_ac_e + ({mu_bulk_e})*Lb_mu_sr_e + "
                f"Lb_mu_ac_e*Lb_mu_sr_e)")
        mu_h = (f"({mu_bulk_h}) * Lb_mu_ac_h * Lb_mu_sr_h / "
                f"(({mu_bulk_h})*Lb_mu_ac_h + ({mu_bulk_h})*Lb_mu_sr_h + "
                f"Lb_mu_ac_h*Lb_mu_sr_h)")

        ds.edge_model(device=device, region=region,
                      name="ElectronMobilityLombardi", equation=mu_e)
        ds.edge_model(device=device, region=region,
                      name="HoleMobilityLombardi", equation=mu_h)

        # All derivatives that Newton needs. The dependencies come from
        # (a) the base bulk mobility (via chain rule), (b) Lb_Emag which
        # depends on Potential, and (c) Lb_gamma_x which depends on carriers.
        for var in ("Potential@n0", "Potential@n1",
                    "Electrons@n0", "Electrons@n1",
                    "Holes@n0",     "Holes@n1"):
            ds.edge_model(device=device, region=region,
                          name=f"ElectronMobilityLombardi:{var}",
                          equation=f"simplify(diff({mu_e}, {var}))")
            ds.edge_model(device=device, region=region,
                          name=f"HoleMobilityLombardi:{var}",
                          equation=f"simplify(diff({mu_h}, {var}))")

    def mu_n_expr(self): return "ElectronMobilityLombardi"
    def mu_p_expr(self): return "HoleMobilityLombardi"
