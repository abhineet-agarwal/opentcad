"""
Example 06 — NMOS source/drain by ion implantation (Phase 2.1 milestone).

Shows the Phase 2 **implant** half of the process → device loop. Same
NMOS geometry as examples/02_nmos_idvg.py, but the n+ source and drain
wells are formed by actual As implants (Pearson-IV depth profile with
Gaussian lateral straggle around a photolith-style mask opening) rather
than hand-written `add_region(doping_Nd=1e20)` overrides.

What this script demonstrates:
    1. Build the geometry only — substrate + oxide + S/D contact windows
       (material overrides to open the oxide, NO hand-doping).
    2. Mesh.
    3. Apply an As implant chain (30 keV + 100 keV, 1e15 cm⁻² each)
       through the source + drain mask windows. Pearson-IV moments are
       looked up from the shipped tables.
    4. Plot the Nd(depth) profile in the S/D column — the signature
       Gaussian peaks at Rp = 22 nm and Rp = 70 nm from the surface.
    5. Save the doped MeshField to VTU for inspection and for the
       downstream (post-anneal) device solve.

What this script does NOT yet do:
    * Run DEVSIM. The raw as-implanted Gaussian spans ~4 orders of
      magnitude in Nd with sharp gradients and non-monotonic depth
      dependence; Newton's method for equilibrium Poisson diverges on
      that profile without a good initial guess. In a real fab the
      implant is immediately followed by an anneal at ~1000 °C that
      spreads the Gaussian into a smoother, flat-topped Erf-like
      profile — precisely the shape device solvers were designed for.
      That anneal step is Unit C of the Phase 2 plan (Fair diffusion
      model on FiPy); once it lands, this example gains three more
      lines and produces the Id-Vgs curve.

Run:
    python examples/06_nmos_implanted.py
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import apply_implant


# Geometry — matched to examples/02 so the two can be compared directly.
N_A = 1e17            # p-body doping (hand-specified in Structure)
T_OX_UM = 0.005       # 5 nm gate oxide
L_GATE_UM = 1.0
W_SD_UM = 0.5
H_BODY_UM = 0.5
SD_DEPTH_UM = 0.1
WIDTH_UM = 2 * W_SD_UM + L_GATE_UM     # 2.0 µm

# S/D implant chain: shallow + deep for ~100 nm total doped depth.
IMPLANT_SPECIES = "As"
IMPLANT_CHAIN = [
    {"energy_keV":  30, "dose_cm2": 1e15},
    {"energy_keV": 100, "dose_cm2": 1e15},
]
SOURCE_WINDOW = (0.0, W_SD_UM)
DRAIN_WINDOW = (WIDTH_UM - W_SD_UM, WIDTH_UM)


def build_geometry_only():
    """Substrate + gate oxide + S/D contact *windows* (material only,
    no doping) + four contacts. In a real fab the S/D contact windows
    are opened in the oxide before metal lands; we mirror that with a
    material override that says "this slab is Si" and let the implant
    deposit the dopants."""
    top_of_oxide = H_BODY_UM + T_OX_UM
    return (Structure(width_um=WIDTH_UM, name="nmos_implanted")
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


def main():
    print("Building geometry (no S/D overrides)...")
    struct = build_geometry_only()
    mf = struct.to_meshfield(mesh_size_um=0.015)
    print(f"  mesh: {mf.n_cells} triangles, {mf.n_points} nodes")
    print(f"  before implant:  Nd_max = {mf.Nd.max():.2e}  "
          f"Na_max = {mf.Na.max():.2e}  (uniform p-body)")

    print(f"\nImplanting {IMPLANT_SPECIES} chain through S + D windows:")
    for step in IMPLANT_CHAIN:
        r = apply_implant(mf, IMPLANT_SPECIES, step["energy_keV"],
                           step["dose_cm2"], window_x_um=SOURCE_WINDOW)
        apply_implant(mf, IMPLANT_SPECIES, step["energy_keV"],
                       step["dose_cm2"], window_x_um=DRAIN_WINDOW)
        print(f"  @ {step['energy_keV']:3d} keV, "
              f"{step['dose_cm2']:.1e} cm⁻²  →  "
              f"Rp = {r.moments.Rp_um*1000:.1f} nm, "
              f"dRp = {r.moments.dRp_um*1000:.1f} nm, "
              f"σ_lat = {r.sigma_lat_um*1000:.1f} nm")

    print(f"\n  after implant chain:")
    print(f"    Nd_max     = {mf.Nd.max():.2e}  cm⁻³")
    print(f"    Na_max     = {mf.Na.max():.2e}  cm⁻³  (p-body, untouched)")
    net = mf.net_doping
    print(f"    net doping = [{net.min():+.2e}, {net.max():+.2e}]")

    # ------------------------------------------------------------
    # Nd(y) depth profile at the source-well centre.
    # ------------------------------------------------------------
    pts = np.asarray(mf.grid.points)[:, :2]
    centre = np.abs(pts[:, 0] - W_SD_UM / 2) < 0.02
    y = pts[centre, 1]
    nd = mf.Nd[centre]
    na = mf.Na[centre]
    order = np.argsort(y)[::-1]
    y_srt = y[order]
    nd_srt = nd[order]
    na_srt = na[order]
    depth_nm = (y_srt.max() - y_srt) * 1000

    out_vtu = "examples/06_nmos_implanted.vtu"
    mf.save(out_vtu)
    print(f"\n  doped MeshField saved to {out_vtu}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plots)")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    # Panel 1: Nd(depth) semilog — the signature implant profile.
    ax1.semilogy(depth_nm, np.clip(nd_srt, 1e14, None), "o-",
                 color="tab:red", markersize=3, label="As (implant)")
    ax1.axhline(N_A, ls="--", color="tab:blue", lw=1,
                label=f"p-body Na = {N_A:.0e}")
    for step in IMPLANT_CHAIN:
        from opentcad.process.doping import moments_for
        m = moments_for(IMPLANT_SPECIES, step["energy_keV"])
        ax1.axvline(m.Rp_um * 1000, ls=":", color="gray", lw=0.7)
        ax1.text(m.Rp_um * 1000, 3e20,
                 f" Rp\n{step['energy_keV']} keV",
                 fontsize=7, color="gray", va="top")
    ax1.set_xlabel("depth below Si surface [nm]")
    ax1.set_ylabel("Nd [cm⁻³]")
    ax1.set_title("As implant chain — depth profile @ S well centre")
    ax1.set_xlim(0, 200)
    ax1.set_ylim(1e14, 1e21)
    ax1.grid(True, alpha=0.3, which="both")
    ax1.legend(fontsize=8, loc="lower left")

    # Panel 2: net-doping cross-section as a 2D scatter.
    sc = ax2.scatter(pts[:, 0], pts[:, 1], c=np.sign(net) * np.log10(
        np.clip(np.abs(net), 1e14, None)),
                     cmap="RdBu_r", s=4, vmin=-21, vmax=21)
    ax2.set_xlabel("x [µm]")
    ax2.set_ylabel("y [µm]")
    ax2.set_title("net doping (log₁₀|N|, red = n, blue = p)")
    ax2.set_aspect("equal")
    plt.colorbar(sc, ax=ax2, label="sign(net) · log₁₀|net| [cm⁻³]",
                 shrink=0.8)

    fig.tight_layout()
    out = "examples/06_nmos_implanted.png"
    fig.savefig(out, dpi=120)
    print(f"  depth-profile plot saved to {out}")

    print("\nNext step (Phase 2.3): apply_anneal(mf, T=1000, t=30*60)")
    print("would broaden the Gaussian into an Erf-like S/D profile that")
    print("DEVSIM can equilibrate on.  Then the Id-Vgs sweep runs")
    print("identically to examples/02_nmos_idvg.py.")


if __name__ == "__main__":
    main()
