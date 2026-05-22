"""
Example 01 — Silicon p-n junction diode IV curve.

Demonstrates the Phase 0 pipeline end-to-end:
  Structure DSL → Gmsh mesh → MeshField → DEVSIM bridge → IV sweep.

Geometry:  1 um x 1 um symmetric pn junction (N_A = N_D = 1e17 cm^-3).
Contacts:  anode on the p-side (bottom), cathode on the n-side (top).
Output:    forward-bias IV from 0 V to 0.7 V on stdout, plus a PNG plot
           if matplotlib is available.

Run:
    python examples/01_pn_junction.py
"""
from __future__ import annotations
import numpy as np
from opentcad.device.solver import DeviceSolver, KB_J, Q_C, T_K_DEFAULT
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def build_diode():
    return (Structure(width_um=1.0, name="pn_diode")
            .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
            .add_layer("n", 0.5, Material.SI, doping_Nd=1e17)
            .add_contact("anode", 0.0, 1.0, "p", surface="bottom")
            .add_contact("cathode", 0.0, 1.0, "n", surface="top"))


def main():
    print("Building structure + mesh...")
    mf = build_diode().to_meshfield(mesh_size_um=0.05)
    print(f"  mesh: {mf.n_cells} triangles, {mf.n_points} nodes")
    print(f"  contacts: "
          f"{[(c.name, len(c.boundary_nodes)) for c in mf.contacts]}")

    print("\nRunning DEVSIM IV sweep...")
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.7, 0.05)

    V_t = KB_J * T_K_DEFAULT / Q_C
    print(f"\n  V_t = {V_t*1000:.2f} mV")
    print(f"  {'V (V)':>8}  {'I (A/cm)':>14}  {'I/I(0.1V)':>12}")
    I0 = next((i for v, i in zip(V, I) if abs(v - 0.1) < 1e-9), None)
    for v, i in zip(V, I):
        ratio = (i / I0) if (I0 and I0 > 0) else float("nan")
        print(f"  {v:8.3f}  {i:14.3e}  {ratio:12.2e}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    Vf = np.array(V); If = np.array(I); ok = If > 0
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(V, I, "o-")
    axes[0].set_xlabel("V (V)"); axes[0].set_ylabel("I (A/cm)")
    axes[0].set_title("Linear IV")
    axes[1].semilogy(Vf[ok], If[ok], "o-")
    axes[1].set_xlabel("V (V)"); axes[1].set_ylabel("|I| (A/cm)")
    axes[1].set_title("Semilog IV (Shockley slope = q/kT)")
    fig.tight_layout()
    out = "examples/01_pn_junction_iv.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
