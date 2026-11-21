"""
opentcad/device/models/bgn.py — Bandgap-narrowing models.

BGN reduces the effective bandgap in heavily-doped regions, raising the
effective intrinsic density:

    n_i_eff = n_i * exp(dEg(N) / (2*V_t))

Every place the solver used `n_i` (Poisson, contact BCs, recombination)
substitutes `n_i_expr()` from the active BGN model. NoBGN is the default
and is a no-op — the expression is just the parameter `n_i`.

Models:
  NoBGN     — no bandgap narrowing (Phase 0 baseline)
  Slotboom  — Slotboom (1976) empirical fit for Si, standard workhorse
"""
from __future__ import annotations
from opentcad.provenance import Source

from ..physics import BandgapNarrowingModel
from .references import SLOTBOOM_DE_GRAAFF_1976

#: Where Slotboom & de Graaff's fitted parameters were read.
KLAASSEN_1991 = Source(
    "D. B. M. Klaassen, Physical modelling for bipolar device simulation, in Simulation "
    "of Semiconductor Devices and Processes 4 (SISDEP), W. Fichtner, D. Aemmer (eds.), "
    "Hartung-Gorre (1991), p. 23",
    url="https://in4.iue.tuwien.ac.at/pdfs/sisdep1991/pdfs/Klaassen_2.pdf",
    note="eq. (22) and the text after it quote Slotboom & de Graaff's p-type fit as "
         "V_ref = 9 mV, N_ref = 1e17 cm^-3, c = 0.5; checked on the scanned paper")


class NoBGN(BandgapNarrowingModel):
    """No bandgap narrowing. n_i stays constant. Used as the default so
    existing callers get identical behavior to Phase 0."""

    def attach(self, ds, device, region, params, T_K):
        # Nothing to register — the solver falls back to the plain n_i
        # parameter that _set_region_parameters already writes.
        pass

    def n_i_expr(self): return "n_i"


class Slotboom(BandgapNarrowingModel):
    """Slotboom empirical bandgap narrowing (1976, updated fit).

        dEg(N) = E_ref * ( ln(N / N_ref)
                          + sqrt(ln(N / N_ref)^2 + 0.5) )   [eV]

    where N is |NetDoping|, N_ref = 1e17 cm^-3 and E_ref = 6.92 meV. Below
    N_ref, dEg is essentially 0. Slotboom & de Graaff's own fit uses
    E_ref = 9 mV with the same N_ref and 0.5 (as Klaassen 1991, eq. 22,
    quotes it); no paper is recorded for 6.92 meV with N_ref = 1e17.

    n_i_eff = n_i * exp(dEg / (2*V_t))

    Reference: Slotboom & de Graaff, Solid-State Electron. 19, 857 (1976).
    """

    references = (SLOTBOOM_DE_GRAAFF_1976,)

    #: Reference bandgap-narrowing prefactor [eV]. Slotboom & de Graaff's
    #: fit uses 9 meV; the source of 6.92 meV is not recorded.
    E_ref_eV: float = 6.92e-3
    #: Reference doping at which dEg starts to activate [cm^-3].
    N_ref_cm3: float = 1.0e17

    def attach(self, ds, device, region, params, T_K):
        from opentcad.provenance import note_value
        group = "Model: Slotboom bandgap narrowing"
        e_src, e_note = (), ("set in the model code; Slotboom & de Graaff's fit uses "
                             "9 meV and no paper is recorded for 6.92 meV")
        if self.E_ref_eV == 9e-3:
            e_src, e_note = (SLOTBOOM_DE_GRAAFF_1976, KLAASSEN_1991), None
        note_value(group, "E_ref_eV", float(self.E_ref_eV), e_src, file=__file__,
                   note=e_note)
        note_value(group, "N_ref_cm3", float(self.N_ref_cm3),
                   (SLOTBOOM_DE_GRAAFF_1976, KLAASSEN_1991)
                   if self.N_ref_cm3 == 1e17 else (), file=__file__)
        ds.set_parameter(device=device, region=region, name="BGN_Eref",
                         value=float(self.E_ref_eV))
        ds.set_parameter(device=device, region=region, name="BGN_Nref",
                         value=float(self.N_ref_cm3))
        # Total ionised dopant. Use max(., 1) to keep log() finite when
        # a region has literally zero doping.
        ds.node_model(device=device, region=region, name="BGN_N",
                      equation="max((Donors + Acceptors), 1)")
        # ln(N/N_ref). Slotboom formula.
        ds.node_model(device=device, region=region, name="BGN_ln",
                      equation="log(BGN_N / BGN_Nref)")
        # dEg [eV]. Slotboom sqrt() form is always >= 0 for any real ln.
        ds.node_model(
            device=device, region=region, name="BGN_dEg",
            equation="BGN_Eref * (BGN_ln + (BGN_ln*BGN_ln + 0.5)^(0.5))")
        # n_i_eff = n_i * exp(dEg / (2*V_t)). n_i and V_t are parameters
        # already set on the region by DeviceSolver.
        ds.node_model(device=device, region=region, name="n_i_eff",
                      equation="n_i * exp(BGN_dEg / (2*V_t))")

    def n_i_expr(self): return "n_i_eff"
