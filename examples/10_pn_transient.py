"""
Example 10 — Transient DC: pn diode turn-on ramp.

Demonstrates Phase 2a's new `DeviceSolver.transient_sweep`:
drive the anode of a Si p-n junction through a 0.1 → 0.7 V linear
ramp and record the current at each time step with BDF1 integration.

The result traces the exponential I(V) turn-on characteristic
dynamically, showing ~10 decades of current rise over the 10 ns
ramp as the junction crosses the Shockley knee. Captures both the
DC I-V shape and the (modest) capacitive/transit delay inherent to
the drift-diffusion response.

Run:
    python examples/10_pn_transient.py
"""
from __future__ import annotations

import numpy as np

from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def build_diode():
    return (Structure(width_um=1.0, name="pn_transient")
            .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
            .add_layer   ("n", 0.5, Material.SI, doping_Nd=1e17)
            .add_contact ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact ("cathode", 0.0, 1.0, "n", surface="top"))


def main():
    print("Building pn diode...")
    mf = build_diode().to_meshfield(mesh_size_um=0.04)
    print(f"  mesh: {mf.n_cells} triangles, {mf.n_points} nodes")

    solver = DeviceSolver(mf, {"Silicon": load_material("Si")})

    # 0.1 → 0.7 V linear ramp over 10 ns, 50 time points.
    times = np.linspace(0.0, 10e-9, 51)
    V = np.interp(times, [0.0, 10e-9], [0.1, 0.7])

    print("\nRunning transient_sweep (BDF1)...")
    t, I = solver.transient_sweep({"anode": V}, times,
                                    measure_contacts=["anode"])

    I_anode = np.asarray(I["anode"])
    print(f"\n  {'t (ns)':>7}  {'V (V)':>6}  {'I (A/cm)':>12}")
    for k in range(0, len(t), 10):
        print(f"  {t[k]*1e9:7.2f}  {V[k]:6.3f}  {I_anode[k]:12.3e}")
    print(f"  (final: V={V[-1]}, I={I_anode[-1]:.3e})")

    I_rise = abs(I_anode[-1]) / max(abs(I_anode[0]), 1e-30)
    print(f"\n  current rise over ramp: {I_rise:.2e}x")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    t_ns = np.asarray(t) * 1e9
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))

    axes[0].plot(t_ns, V, "o-")
    axes[0].set_xlabel("t (ns)"); axes[0].set_ylabel("V_anode (V)")
    axes[0].set_title("Applied waveform")
    axes[0].grid(True, alpha=0.3)

    ok = np.abs(I_anode) > 0
    axes[1].semilogy(t_ns[ok], np.abs(I_anode[ok]), "o-")
    axes[1].set_xlabel("t (ns)"); axes[1].set_ylabel("|I_anode| (A/cm)")
    axes[1].set_title("Transient current response")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    out = "examples/10_pn_transient.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
