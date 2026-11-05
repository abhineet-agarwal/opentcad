"""
Example 11 — HF-CV MOS capacitor via small-signal AC sweep.

Demonstrates Phase 2a's new `DeviceSolver.ac_sweep` on the canonical
MOS-cap high-frequency CV measurement. For each gate bias in a
sweep, we solve DC then call `ac_sweep` at f = 1 MHz and recover
C_hf(V_g) = Im(Y)/ω.

On a p-substrate device the HF-CV curve shows the three classical
regimes:
  * accumulation (V_g ≪ V_fb):  C → C_ox
  * depletion (V_fb ≲ V_g ≲ V_T): C < C_ox, falling with V_g
  * HF inversion (V_g ≫ V_T):   C flattens at C_min — minority
    carriers can't follow, so the inversion-layer response is
    blocked.

Compare against example 03 (LF CV via quasi-static dQ/dV) to see
the characteristic HF/LF split in inversion.

Run:
    python examples/11_mos_hfcv.py
"""
from __future__ import annotations

import numpy as np

from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def build_mos(width_um=1.0, tox_um=0.01, tsi_um=0.5):
    return (Structure(width_um=width_um, name="mos_hfcv")
            .add_substrate("sub", tsi_um, Material.SI, doping_Na=1e17)
            .add_layer("ox", tox_um, Material.SIO2)
            .add_contact("gate", 0.0, width_um, "ox",  surface="top")
            .add_contact("body", 0.0, width_um, "sub", surface="bottom"))


def main():
    print("Building MOS cap...")
    mf = build_mos().to_meshfield(mesh_size_um=0.02)
    mat = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    s = DeviceSolver(mf, mat, ac_terminals=["gate"])

    # Sweep gate from accumulation (-2 V) to inversion (+2 V).
    Vg_sweep = np.linspace(-2.0, 2.0, 21)
    freq = 1e6   # 1 MHz small-signal probe

    print(f"\nSmall-signal AC sweep at f = {freq:.0e} Hz, {len(Vg_sweep)} bias points")
    C_hf = np.zeros_like(Vg_sweep)
    for i, Vg in enumerate(Vg_sweep):
        _, Y = s.ac_sweep("gate", "body", [freq], dc_bias=float(Vg))
        C_hf[i] = Y[0].imag / (2 * np.pi * freq)
        if i % 5 == 0:
            print(f"  V_g = {Vg:+5.2f} V  →  C_hf = {C_hf[i]:.3e} F/cm")

    # Analytic C_ox for parallel plates
    eps_ox = 3.9 * 8.8541878128e-14         # F/cm
    Cox_per_cm = eps_ox / 10e-7 * (1.0 * 1e-4)  # 10 nm tox, 1 um gate
    C_min = C_hf.min()
    print(f"\n  C_ox (parallel-plate, 10 nm)   = {Cox_per_cm:.3e} F/cm")
    print(f"  C_hf(deep accumulation V=-2 V) = {C_hf[0]:.3e} F/cm")
    print(f"  C_hf(deep inversion    V=+2 V) = {C_hf[-1]:.3e} F/cm  (HF floor)")
    print(f"  ratio C_ox / C_min             = {Cox_per_cm / C_min:.2f}x")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    fig, ax = plt.subplots(1, 1, figsize=(6, 4))
    ax.plot(Vg_sweep, C_hf * 1e12, "o-", label=f"C_hf @ {freq:.0e} Hz")
    ax.axhline(Cox_per_cm * 1e12, ls="--", color="k", alpha=0.4,
                label=f"C_ox (parallel plate)")
    ax.set_xlabel("V_g (V)")
    ax.set_ylabel("Capacitance (pF/cm)")
    ax.set_title(f"MOS-cap HF CV (p-sub, 1e17, t_ox = 10 nm)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    out = "examples/11_mos_hfcv.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
