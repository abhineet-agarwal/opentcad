"""
Example 06 — NMOS source/drain by ion implantation, in one Recipe.

The Phase 2.1 + 2.2 narrative: express a fab-style flow in a single
chainable `Recipe` object and hand it, together with a Structure
scaffold, to `run_recipe` — one call does the topography half
(empty here), meshes the result, and plays the implant chain into
the device-ready MeshField.

Why Example 06 doesn't yet drive DEVSIM:
    The raw as-implanted Gaussian spans 4 decades in Nd with sharp
    gradients, which Newton's equilibrium Poisson solve can't settle
    on without an initial guess. In a real fab the implant is
    immediately followed by an anneal at ~1000 °C that smears the
    Gaussian into a flatter, Erf-like profile DEVSIM eats happily.
    That anneal step is Unit C (Phase 2.3). Once it ships, the
    `.anneal(...)` call appended to this Recipe produces an Id-Vgs
    curve matching examples/02_nmos_idvg.py.

For now, this example shows:
    * The one-call pipeline API: `run_recipe(struct, recipe)` →
      doped MeshField, plus a diagnostic record of every implant.
    * A real two-species, two-energy S/D implant chain expressed as
      four `Recipe.implant` calls.
    * The depth-profile and 2D cross-section plots showing the
      resulting dopant distribution.

Run:
    python examples/06_nmos_implanted.py
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
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

IMPLANT_SPECIES = "As"
SOURCE_WINDOW = (0.0, W_SD_UM)
DRAIN_WINDOW = (WIDTH_UM - W_SD_UM, WIDTH_UM)


def build_scaffold():
    """Substrate + gate oxide + S/D contact windows (material-only
    overrides). No doping is set on the Structure — every n+ carrier
    in the output MeshField will come from a `Recipe.implant` call."""
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
    """The whole 'fab flow' in one DSL object. Two-energy As implant
    chain into both source and drain through separate photolith masks.
    Real fabs shoot both windows in a single pass; splitting them
    here lets the Recipe be read as a document of what happened."""
    return (Recipe("nmos_sd_implant")
            # shallow As to pin the surface Nd high
            .implant(IMPLANT_SPECIES,  30, 1e15, window_x_um=SOURCE_WINDOW)
            .implant(IMPLANT_SPECIES,  30, 1e15, window_x_um=DRAIN_WINDOW)
            # deep As to extend the junction below the gate oxide
            .implant(IMPLANT_SPECIES, 100, 1e15, window_x_um=SOURCE_WINDOW)
            .implant(IMPLANT_SPECIES, 100, 1e15, window_x_um=DRAIN_WINDOW))


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

    print("Running recipe end-to-end (topography + mesh + doping)...")
    out = run_recipe(struct, recipe, mesh_size_um=0.015)
    mf = out.meshfield

    print(f"\n  MeshField: {mf.n_cells} triangles, {mf.n_points} nodes")
    print(f"  topography_state = {out.topography_state!r} "
          "(None → doping-only recipe, shortcut path taken)")
    print()
    print(f"  Implants fired ({out.doping_result.n_implants}):")
    for i, r in enumerate(out.doping_result.implants, 1):
        x0, x1 = r.window_x_um
        print(f"    {i}. {r.species:11s} @ {r.energy_keV:3.0f} keV, "
              f"{r.dose_cm2:.1e} cm⁻², window [{x0:.2f}..{x1:.2f}] µm "
              f"→ Rp = {r.moments.Rp_um*1000:5.1f} nm, "
              f"→ {r.added_to}")

    print()
    print(f"  Nd_max = {mf.Nd.max():.2e} cm⁻³   "
          f"Na_max = {mf.Na.max():.2e} cm⁻³")
    net = mf.net_doping
    print(f"  net doping range: [{net.min():+.2e}, {net.max():+.2e}]")

    out_vtu = "examples/06_nmos_implanted.vtu"
    mf.save(out_vtu)
    print(f"\n  doped MeshField saved to {out_vtu}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plots)")
        return

    # Depth profile at source-well centre.
    pts = np.asarray(mf.grid.points)[:, :2]
    centre = np.abs(pts[:, 0] - W_SD_UM / 2) < 0.02
    y_centre = pts[centre, 1]
    order = np.argsort(y_centre)[::-1]
    y_srt = y_centre[order]
    depth_nm = (y_srt.max() - y_srt) * 1000

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    ax1.semilogy(depth_nm, np.clip(mf.Nd[centre][order], 1e14, None),
                  "o-", color="tab:red", markersize=3, label="As (implant)")
    ax1.axhline(N_A, ls="--", color="tab:blue", lw=1,
                 label=f"p-body Na = {N_A:.0e}")
    for e in (30, 100):
        m = moments_for(IMPLANT_SPECIES, e)
        ax1.axvline(m.Rp_um * 1000, ls=":", color="gray", lw=0.7)
        ax1.text(m.Rp_um * 1000, 3e20, f" Rp\n{e} keV",
                  fontsize=7, color="gray", va="top")
    ax1.set_xlabel("depth below Si surface [nm]")
    ax1.set_ylabel("Nd [cm⁻³]")
    ax1.set_title("As implant chain — depth profile @ S well centre")
    ax1.set_xlim(0, 200); ax1.set_ylim(1e14, 1e21)
    ax1.grid(True, alpha=0.3, which="both")
    ax1.legend(fontsize=8, loc="lower left")

    sc = ax2.scatter(pts[:, 0], pts[:, 1],
                      c=np.sign(net) * np.log10(np.clip(np.abs(net),
                                                         1e14, None)),
                      cmap="RdBu_r", s=4, vmin=-21, vmax=21)
    ax2.set_xlabel("x [µm]"); ax2.set_ylabel("y [µm]")
    ax2.set_title("net doping (red = n, blue = p)")
    ax2.set_aspect("equal")
    plt.colorbar(sc, ax=ax2, label="sign(net) · log₁₀|net| [cm⁻³]",
                  shrink=0.8)

    fig.tight_layout()
    out = "examples/06_nmos_implanted.png"
    fig.savefig(out, dpi=120)
    print(f"  depth-profile plot saved to {out}")

    print()
    print("Next piece (Phase 2.3 / Unit C): append")
    print("  .anneal(temperature_C=1000, time_s=1800)")
    print("to the Recipe to broaden the Gaussian into a flat-top S/D")
    print("profile DEVSIM can equilibrate on.")


if __name__ == "__main__":
    main()
