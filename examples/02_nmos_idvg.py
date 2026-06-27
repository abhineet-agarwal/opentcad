"""
Example 02 — 2D NMOS Id-Vgs (Phase 0 exit demonstration).

Geometry (cross-section, units um):

    y=0.505 ┌────┬──── gate ────┬────┐   ← top, oxide surface
    y=0.500 │ n+ │  SiO2 (5nm)  │ n+ │
            │----│--------------│----│   ← Si surface (y=0.5)
            │ n+ │              │ n+ │
    y=0.400 │ n+ │   p-body     │ n+ │
            │    │ (Na = 1e17)  │    │
    y=0.000 └────┴──────────────┴────┘   ← body contact
            0   0.5            1.5  2.0

Source/drain are added via Structure.add_region — the material override
replaces the gate-oxide cells in the S/D windows with n+ Si, so the
contacts sit on real silicon.

Sweeps Vgs from 0 V to 1.5 V at Vds = 50 mV and produces:
  - tabular Id-Vgs on stdout
  - examples/02_nmos_idvg.png (linear + semilog plots)

Run:
    python examples/02_nmos_idvg.py
"""
from __future__ import annotations
import numpy as np
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17       # [cm^-3] p-body doping
N_D = 1e20       # [cm^-3] n+ source/drain doping
T_OX_UM = 0.005  # 5 nm gate oxide
L_GATE_UM = 1.0
W_SD_UM = 0.5
H_BODY_UM = 0.5
SD_DEPTH_UM = 0.1
VDS = 0.05


def build_nmos():
    w = 2 * W_SD_UM + L_GATE_UM
    return (Structure(width_um=w, name="nmos")
            .add_substrate("p_body", H_BODY_UM, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
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


def main():
    print("Building structure + mesh...")
    mf = build_nmos().to_meshfield(mesh_size_um=0.03)
    print(f"  mesh: {mf.n_cells} triangles, {mf.n_points} nodes")

    print("\nSolving equilibrium + DC sweep...")
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2"   : load_material("SiO2")})
    solver.solve_equilibrium()

    # Ramp Vds from 0 to 50 mV before turning the gate.
    for vd in np.linspace(0.0, VDS, 6)[1:]:
        solver._set_contact_voltage("drain", float(vd))
        solver._solve_dc()

    Vgs = np.linspace(0.0, 1.5, 16)
    Id = []
    for vg in Vgs:
        solver._set_contact_voltage("gate", float(vg))
        solver._solve_dc()
        Id.append(abs(solver._get_contact_current("drain")))
    Id = np.asarray(Id)

    print(f"\n  Vds = {VDS*1000:.0f} mV   L_gate = {L_GATE_UM} um")
    print(f"  {'Vgs (V)':>8}  {'Id (A/cm)':>14}")
    for vg, i in zip(Vgs, Id):
        print(f"  {vg:8.3f}  {i:14.3e}")

    on_off = Id[-1] / max(Id[0], 1e-30)
    print(f"\n  on/off ratio: {on_off:.2e}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(Vgs, Id * 1e3, "o-")
    axes[0].set_xlabel("Vgs (V)")
    axes[0].set_ylabel("Id (mA/cm)")
    axes[0].set_title(f"NMOS Id-Vgs (linear), Vds = {VDS*1000:.0f} mV")
    axes[0].grid(True, alpha=0.3)

    axes[1].semilogy(Vgs, np.clip(Id, 1e-15, None), "o-")
    axes[1].set_xlabel("Vgs (V)")
    axes[1].set_ylabel("|Id| (A/cm)")
    axes[1].set_title("NMOS Id-Vgs (semilog) — subthreshold + on-state")
    axes[1].grid(True, alpha=0.3, which="both")

    fig.tight_layout()
    out = "examples/02_nmos_idvg.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
