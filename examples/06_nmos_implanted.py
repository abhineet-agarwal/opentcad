"""
Example 06 — NMOS from a fab recipe, end to end (Phase 2 exit demo).

The full "process recipe in, I-V curve out" story in one script:

    1. Build a device SCAFFOLD — substrate + gate oxide + S/D contact
       windows (material-only overrides, no hand-doping anywhere).
    2. Write a RECIPE of fab steps:
         .implant(As, 30 keV, 1e15, S/D windows)   — shallow surface dope
         .implant(As, 100 keV, 1e15, S/D windows)  — deeper S/D extension
         .anneal(1000 °C, 30 min)                  — Fickian diffusion
    3. run_recipe(struct, recipe) → doped MeshField ready for DEVSIM.
    4. DeviceSolver on that MeshField → Id-Vgs sweep at Vds = 50 mV.

No hand-doped `add_region(doping_Nd=…)` anywhere. The n+ carriers in
the output MeshField all came from the implant Pearson table + the
anneal Fick diffusion.

Compare to examples/02_nmos_idvg.py (same geometry, hand-doped) —
the Id-Vgs curves should match qualitatively (same on/off, same Vth
range), with any differences attributable to the physical implant +
anneal profile vs. the hand-painted 1e20 flat-top region.

Run:
    python examples/06_nmos_implanted.py
"""
from __future__ import annotations

import numpy as np

from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material
from opentcad.process import run_recipe
from opentcad.process.doping import moments_for
from opentcad.process.topography import Recipe


# ---- Device dimensions (matched to examples/02_nmos_idvg.py) --------------
N_A = 1e17
T_OX_UM = 0.005
L_GATE_UM = 1.0
W_SD_UM = 0.5
H_BODY_UM = 0.5
SD_DEPTH_UM = 0.1
WIDTH_UM = 2 * W_SD_UM + L_GATE_UM
VDS = 0.05

IMPLANT_SPECIES = "As"
SOURCE_WINDOW = (0.0, W_SD_UM)
DRAIN_WINDOW  = (WIDTH_UM - W_SD_UM, WIDTH_UM)
ANNEAL_T_C = 1000
ANNEAL_T_S = 30 * 60   # 30 min


def build_scaffold():
    """Substrate + gate oxide + S/D contact windows (material-only).
    Every n+ carrier that ends up in the output MeshField comes from
    the Recipe below — nothing is hand-doped here."""
    top_of_oxide = H_BODY_UM + T_OX_UM
    return (Structure(width_um=WIDTH_UM, name="nmos_from_recipe")
            .add_substrate("p_body", H_BODY_UM, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
            .add_region("source_window",
                        0.0, W_SD_UM,
                        H_BODY_UM - SD_DEPTH_UM, top_of_oxide,
                        Material.SI)
            .add_region("drain_window",
                        WIDTH_UM - W_SD_UM, WIDTH_UM,
                        H_BODY_UM - SD_DEPTH_UM, top_of_oxide,
                        Material.SI)
            .add_contact("source", 0.0,                 W_SD_UM,
                         "oxide", surface="top")
            .add_contact("drain",  WIDTH_UM - W_SD_UM,  WIDTH_UM,
                         "oxide", surface="top")
            .add_contact("gate",   W_SD_UM, W_SD_UM + L_GATE_UM,
                         "oxide", surface="top")
            .add_contact("body",   0.0,                 WIDTH_UM,
                         "p_body", surface="bottom"))


def build_recipe():
    """Full fab recipe — four implants (two energies, two windows)
    + one anneal."""
    return (Recipe("nmos_sd")
            .implant(IMPLANT_SPECIES,  30, 1e15, window_x_um=SOURCE_WINDOW)
            .implant(IMPLANT_SPECIES,  30, 1e15, window_x_um=DRAIN_WINDOW)
            .implant(IMPLANT_SPECIES, 100, 1e15, window_x_um=SOURCE_WINDOW)
            .implant(IMPLANT_SPECIES, 100, 1e15, window_x_um=DRAIN_WINDOW)
            .anneal(ANNEAL_T_C, ANNEAL_T_S))


def main():
    struct = build_scaffold()
    recipe = build_recipe()
    print("Scaffold:")
    print(f"  {WIDTH_UM:.1f} × {H_BODY_UM + T_OX_UM:.3f} µm  "
          f"({len(struct._layers)} layers, {len(struct._regions)} regions, "
          f"{len(struct._contacts)} contacts)")
    print()
    print(recipe.summary())
    print()

    print("Running recipe end-to-end (topography + mesh + doping + anneal)...")
    out = run_recipe(struct, recipe, mesh_size_um=0.015)
    mf = out.meshfield

    print(f"\n  MeshField: {mf.n_cells} triangles, {mf.n_points} nodes")
    print(f"  Implants fired: {out.doping_result.n_implants}")
    print(f"  Anneals fired:  {out.doping_result.n_anneals}")
    for a in out.doping_result.anneals:
        print(f"    {a.temperature_C:.0f}°C · {a.time_s:.0f}s  →  "
              f"σ(Nd)={a.sigma_Nd_um*1000:.1f}nm "
              f"σ(Na)={a.sigma_Na_um*1000:.1f}nm")

    print(f"\n  Nd_max = {mf.Nd.max():.2e} cm⁻³   "
          f"Na_max = {mf.Na.max():.2e} cm⁻³")

    # ---- DEVSIM device solve ----------------------------------------------
    print("\nHanding MeshField to DEVSIM...")
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2"   : load_material("SiO2")})
    V, I = solver.iv_sweep("gate", "source",
                            v_start=0.0, v_end=1.5, v_step=0.1,
                            hold_contacts={"drain": VDS},
                            measure_contact="drain")
    V = np.asarray(V); I = np.asarray(I)
    import devsim as ds
    for d in list(ds.get_device_list()):
        ds.delete_device(device=d)

    print(f"\n  Vds = {VDS*1000:.0f} mV   L_gate = {L_GATE_UM:.1f} µm")
    print(f"  {'Vgs':>8}  {'Id (A/cm)':>14}")
    for v, i in zip(V, I):
        print(f"  {v:8.3f}  {abs(i):14.3e}")

    on_off = abs(I).max() / max(abs(I).min(), 1e-30)
    print(f"\n  on/off ratio: {on_off:.2e}")

    # ---- Plots ------------------------------------------------------------
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plot)")
        return

    pts = np.asarray(mf.grid.points)[:, :2]
    centre = np.abs(pts[:, 0] - W_SD_UM / 2) < 0.02
    y_centre = pts[centre, 1]
    order = np.argsort(y_centre)[::-1]
    y_srt = y_centre[order]
    depth_nm = (y_srt.max() - y_srt) * 1000

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    axes[0].semilogy(depth_nm, np.clip(mf.Nd[centre][order], 1e14, None),
                     "o-", color="tab:red", markersize=3,
                     label=f"As (after {ANNEAL_T_C}°C/{ANNEAL_T_S//60}min)")
    axes[0].axhline(N_A, ls="--", color="tab:blue", lw=1,
                    label=f"p-body Na = {N_A:.0e}")
    for e in (30, 100):
        m = moments_for(IMPLANT_SPECIES, e)
        axes[0].axvline(m.Rp_um * 1000, ls=":", color="gray", lw=0.7)
    axes[0].set_xlabel("depth [nm]")
    axes[0].set_ylabel("Nd [cm⁻³]")
    axes[0].set_title("S/D depth profile (annealed)")
    axes[0].set_xlim(0, 300); axes[0].set_ylim(1e14, 1e21)
    axes[0].grid(True, alpha=0.3, which="both")
    axes[0].legend(fontsize=8, loc="lower left")

    axes[1].plot(V, np.abs(I) * 1e3, "o-", color="tab:red")
    axes[1].set_xlabel("Vgs [V]"); axes[1].set_ylabel("Id [mA/cm]")
    axes[1].set_title(f"Id-Vgs (linear), Vds = {VDS*1000:.0f} mV")
    axes[1].grid(True, alpha=0.3)

    axes[2].semilogy(V, np.clip(np.abs(I), 1e-15, None), "o-",
                     color="tab:red")
    axes[2].set_xlabel("Vgs [V]"); axes[2].set_ylabel("|Id| [A/cm]")
    axes[2].set_title(f"Id-Vgs (semilog), on/off = {on_off:.1e}")
    axes[2].grid(True, alpha=0.3, which="both")

    fig.tight_layout()
    out_path = "examples/06_nmos_implanted.png"
    fig.savefig(out_path, dpi=120)
    print(f"\n  plot saved to {out_path}")


if __name__ == "__main__":
    main()
