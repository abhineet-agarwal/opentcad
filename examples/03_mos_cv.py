"""
Example 03 — MOS capacitor CV sweep (quasi-static / low-frequency).

Baseline geometry: p-Si body (Na = 1e17) / 5 nm SiO2 / metal gate.
Sweeps Vg from -0.5 V to +1.2 V and computes capacitance via DeviceSolver.cv_sweep()
(charge integration + central-difference dQ/dV).

Produces:
  - a Vg vs C table on stdout
  - examples/03_mos_cv.png with (a) linear C-Vg, (b) log-scale C-Vg

Run:
    python examples/03_mos_cv.py
"""
from __future__ import annotations
import numpy as np
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17
T_OX_UM = 0.005          # 5 nm
WIDTH_UM = 1.0
EPS_OX_R = 3.9
EPS_0_F_CM = 8.854e-14
C_OX = EPS_OX_R * EPS_0_F_CM / (T_OX_UM * 1e-4) * (WIDTH_UM * 1e-4)


def build_mos_cap():
    return (Structure(width_um=WIDTH_UM, name="mos_cap_cv")
            .add_substrate("p_body", 0.5, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
            .add_contact("body", 0.0, WIDTH_UM, "p_body", surface="bottom")
            .add_contact("gate", 0.0, WIDTH_UM, "oxide", surface="top"))


def main():
    print("Building structure + mesh...")
    mf = build_mos_cap().to_meshfield(mesh_size_um=0.02)
    print(f"  mesh: {mf.n_cells} triangles, {mf.n_points} nodes")
    print(f"  expected C_ox: {C_OX:.3e} F/cm")

    print("\nRunning quasi-static CV sweep...")
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2":    load_material("SiO2")})
    V, C = solver.cv_sweep("gate", "body", -0.5, +1.2, 0.1)
    V = np.asarray(V); C = np.asarray(C)

    print(f"\n  {'Vg (V)':>8}  {'C (F/cm)':>14}  {'C/C_ox':>7}")
    for v, c in zip(V, C):
        print(f"  {v:+8.3f}  {c:14.3e}  {c/C_OX:7.3f}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    axes[0].plot(V, C / C_OX, "o-", color="tab:blue")
    axes[0].axhline(1.0, color="k", ls="--", lw=0.7, alpha=0.5,
                    label="C_ox (physical ceiling)")
    axes[0].set_xlabel("V$_g$ (V)")
    axes[0].set_ylabel("C / C$_{ox}$")
    axes[0].set_title(f"MOS-cap LF CV (t$_{{ox}}$={T_OX_UM*1000:.0f} nm, "
                       f"N$_A$={N_A:.0e})")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="lower right", fontsize=9)
    axes[0].set_ylim(0, 1.1)

    axes[1].semilogy(V, C, "o-", color="tab:orange")
    axes[1].axhline(C_OX, color="k", ls="--", lw=0.7, alpha=0.5,
                    label=f"C_ox = {C_OX:.2e} F/cm")
    axes[1].set_xlabel("V$_g$ (V)")
    axes[1].set_ylabel("C (F/cm)")
    axes[1].set_title("MOS-cap CV — semilog")
    axes[1].grid(True, alpha=0.3, which="both")
    axes[1].legend(loc="lower right", fontsize=9)

    fig.tight_layout()
    out = "examples/03_mos_cv.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
