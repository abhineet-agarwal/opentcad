"""
Phase 0 exit criterion (MOSFET half): a full 2D NMOS must show correct
threshold behavior — subthreshold off-state with exponential turn-on,
clear on-state above Vth, monotonic Id(Vgs).

Geometry (cross-section, units um):

    y=0.505 ┌────┬──── gate ────┬────┐   ← top, oxide surface
    y=0.500 │ n+ │  SiO2 (5nm)  │ n+ │
            │----│--------------│----│   ← Si surface (y=0.5)
            │ n+ │              │ n+ │
    y=0.400 │ n+ │   p-body     │ n+ │
            │    │ (Na = 1e17)  │    │
    y=0.000 └────┴──────────────┴────┘   ← body contact
            0   0.5            1.5  2.0

- Source/drain are added via Structure.add_region(material=Material.SI,
  Nd=1e20), extending from y=0.4 up through the top of the oxide layer.
  Doping override puts the n+ everywhere in the rectangle; the new
  material-override path in mesh.py replaces the oxide cells in that
  rectangle with Si, so S/D contacts land on actual silicon.

- We sweep Vgs at low Vds = 50 mV (linear region) and check:
    * Id at Vgs=0 V (off) ≪ Id at Vgs=1.5 V (on): on/off > 1e3.
    * Id(Vgs) monotonic non-decreasing.
    * Some Vgs in (0.5, 1.2) gives a tenfold Id jump per ~250 mV
      (loose subthreshold-slope sanity check — well above the 60 mV/dec
      thermal limit, but constant-mobility / no-trap models won't get
      that close).
"""
import numpy as np
import pytest
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17     # [cm^-3] p-body doping
N_D = 1e20     # [cm^-3] n+ source/drain doping
T_OX_UM = 0.005
L_GATE_UM = 1.0
W_SD_UM = 0.5
H_BODY_UM = 0.5
SD_DEPTH_UM = 0.1   # n+ junction depth into the body
VDS = 0.05


@pytest.fixture
def nmos_mf():
    w = 2 * W_SD_UM + L_GATE_UM
    s = (Structure(width_um=w, name="nmos")
         .add_substrate("p_body", H_BODY_UM, Material.SI, doping_Na=N_A)
         .add_layer("oxide", T_OX_UM, Material.SIO2)
         # n+ source: from y=0.4 up to top of oxide, doping + material override.
         .add_region("source", 0.0, W_SD_UM,
                     H_BODY_UM - SD_DEPTH_UM, H_BODY_UM + T_OX_UM,
                     Material.SI, doping_Nd=N_D)
         .add_region("drain", w - W_SD_UM, w,
                     H_BODY_UM - SD_DEPTH_UM, H_BODY_UM + T_OX_UM,
                     Material.SI, doping_Nd=N_D)
         .add_contact("source", 0.0, W_SD_UM, "oxide", surface="top")
         .add_contact("drain",  w - W_SD_UM, w, "oxide", surface="top")
         .add_contact("gate",   W_SD_UM, W_SD_UM + L_GATE_UM,
                      "oxide", surface="top")
         .add_contact("body",   0.0, w, "p_body", surface="bottom"))
    return s.to_meshfield(mesh_size_um=0.03)


@pytest.mark.requires_devsim
@pytest.mark.slow
def test_nmos_idvg_threshold_behavior(nmos_mf):
    si = load_material("Si"); ox = load_material("SiO2")
    solver = DeviceSolver(nmos_mf, {"Silicon": si, "SiO2": ox})
    solver.solve_equilibrium()

    # Source + body grounded (already 0 from equilibrium); ramp Vds and Vgs.
    solver._set_contact_voltage("source", 0.0)
    solver._set_contact_voltage("body",   0.0)
    for vd in np.linspace(0.0, VDS, 6)[1:]:
        solver._set_contact_voltage("drain", float(vd))
        solver._solve_dc()

    Vgs = np.linspace(0.0, 1.5, 11)
    Id = []
    for vg in Vgs:
        solver._set_contact_voltage("gate", float(vg))
        solver._solve_dc()
        Id.append(abs(solver._get_contact_current("drain")))

    Id = np.asarray(Id)
    print("\nNMOS Id-Vgs (Vds = %.3f V):" % VDS)
    for vg, i in zip(Vgs, Id):
        print(f"  Vgs={vg:5.2f} V   Id={i:.3e} A/cm")

    # On/off ratio: turning the gate on must move Id by >1000x.
    on  = Id[-1]
    off = Id[0]
    assert on > 1e-7, f"On-state Id too small: {on:.3e} (gate not turning on)"
    assert off < on / 1e3, (
        f"On/off ratio too low: on={on:.3e}, off={off:.3e} (ratio {on/off:.2e})")

    # Monotonic-non-decreasing (allow ~5% numerical wiggle).
    diffs = np.diff(Id)
    assert np.all(diffs > -0.05 * Id[:-1]), (
        f"Id should rise monotonically with Vgs, got steps {diffs}")

    # Subthreshold-slope sanity check: somewhere in the sweep, the current
    # should jump by 10x within ~250 mV.
    log_Id = np.log10(np.clip(Id, 1e-30, None))
    decade_steps = []
    for i in range(len(Vgs)):
        for j in range(i + 1, len(Vgs)):
            if log_Id[j] - log_Id[i] >= 1.0:
                decade_steps.append(Vgs[j] - Vgs[i])
                break
    assert decade_steps, "Never saw a 1-decade rise in Id across the sweep"
    assert min(decade_steps) < 0.25, (
        f"Steepest 1-decade rise took {min(decade_steps)*1000:.0f} mV; "
        f"expected < 250 mV (typical of subthreshold turn-on)")
