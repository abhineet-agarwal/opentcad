"""
Example 05 — LOCOS field isolation (Phase 1 exit demo).

Classic LOCOS flow on a bare Si wafer:

    1. thin pad oxide (200 nm dry O2 at 900 °C) so the field oxide
       doesn't strain the Si below its edges too aggressively.
    2. field oxidation (wet H2O at 1000 °C for 60 min) inside a
       photolith-style window, with a small (30 nm) bird's-beak
       feathering length that stands in for lateral O2 diffusion
       under a would-be nitride mask edge.

The overall shape — thick field oxide inside the window, a smooth
"beak" tail feathering out onto the pad-oxide plateau, and unetched
Si below — is the visual signature of LOCOS. The Phase 1 exit
criterion is a gate-oxide thickness within 5 % of the analytic Deal-
Grove prediction; the accompanying tests
(`tests/process/test_oxidation.py`) verify this on bare Si across dry
+ wet ambients at multiple temperatures.

Run:
    python examples/05_locos.py

Produces:
    examples/05_locos_profile.png   — before / pad oxide / field oxide
                                       stack profiles, side by side.
    examples/05_locos_mesh.png      — the final MeshField ready for
                                       DeviceSolver, shaded per
                                       material with the bird's beak
                                       visible in the triangulation.
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import MATERIAL_NAMES, Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography import (
    Recipe, extract_surface_polyline,
    initial_state_from_structure, simulate, topography_to_meshfield,
)
from opentcad.process.topography.oxidation import (
    oxide_thickness, temperature_celsius_to_kelvin,
)
from opentcad.process.topography.simulator import _apply_oxidize


WIDTH_UM = 2.0
BODY_UM = 0.5
FIELD_WINDOW = (0.7, 1.3)
BIRD_BEAK_UM = 0.03


def _polylines(state):
    """Snapshot (material, xs, ys) polylines for the current state."""
    out = []
    xmin, xmax, _, _ = state.bounds_um
    for L in state.layers:
        nodes, _ = extract_surface_polyline(L.level_set)
        pts = np.asarray(nodes, dtype=float)
        xs, ys = pts[:, 0], pts[:, 1]
        keep = (xs >= xmin - 1e-7) & (xs <= xmax + 1e-7)
        order = np.argsort(xs[keep])
        out.append((L.material,
                    xs[keep][order].copy(),
                    ys[keep][order].copy()))
    return out


def _snapshots(struct, recipe, grid_delta_um: float):
    """Advance step by step so we can plot the intermediate state."""
    state = initial_state_from_structure(struct, grid_delta_um)
    frames = [("bare Si", state.bounds_um, _polylines(state))]
    for i, step in enumerate(recipe, 1):
        _apply_oxidize(state, step)
        label = (f"step {i}: oxidize "
                 f"{step.temperature_C:.0f}°C {step.time_s/60:.0f}min "
                 f"{step.ambient}")
        if step.window_x_um is not None:
            label += f"\nwindow [{step.window_x_um[0]:.2f},"\
                     f"{step.window_x_um[1]:.2f}] µm"
        frames.append((label, state.bounds_um, _polylines(state)))
    return frames


def _plot_stack(ax, label, bounds, polylines, palette):
    xmin, xmax, ymin, _ = bounds
    prev_y = np.full(2, ymin)
    prev_x = np.array([xmin, xmax])
    for material, xs, ys in polylines:
        n = max(int(xs.size), 2)
        xi = np.linspace(xmin, xmax, n)
        yi = np.interp(xi, xs, ys) if xs.size >= 2 else np.full_like(xi, ys[0])
        yb = np.interp(xi, prev_x, prev_y)
        ax.fill_between(xi, yb, yi, color=palette.get(material, "#bbbbbb"),
                        label=MATERIAL_NAMES.get(material, material.name),
                        edgecolor="k", linewidth=0.3)
        prev_x, prev_y = xi, yi
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(0.30, 0.85)
    ax.set_xlabel("x [µm]")
    ax.set_title(label, fontsize=9)
    ax.grid(True, alpha=0.2)


def main():
    struct = (Structure(width_um=WIDTH_UM, name="locos")
              .add_substrate("body", BODY_UM, Material.SI))

    # Classic LOCOS: thin pad oxide everywhere, then a *masked* wet
    # field oxidation over the active area. The bird's beak length is
    # a heuristic for lateral O2 diffusion under the nitride edge.
    recipe = (Recipe("locos_flow")
              .oxidize(temperature_C=900,  time_s=15 * 60, ambient="dry")
              .oxidize(temperature_C=1000, time_s=60 * 60, ambient="wet",
                       window_x_um=FIELD_WINDOW,
                       bird_beak_length_um=BIRD_BEAK_UM))
    print(recipe.summary())
    print()

    print("Simulating step-by-step for the plot...")
    frames = _snapshots(struct, recipe, grid_delta_um=0.005)
    for label, _, polylines in frames:
        heights = [f"{m.name}@{ys.mean():.4f}" for m, _, ys in polylines]
        print(f"  {label.splitlines()[0]:<40s} → {heights}")

    T = temperature_celsius_to_kelvin(1000)
    x_analytic = oxide_thickness(0.005, 60 * 60, T, "wet")
    print(f"\nanalytic Deal-Grove: wet 1000°C 60min on top of 5 nm pad → "
          f"x_ox = {x_analytic*1000:.0f} nm")

    print("\nBuilding MeshField from final state...")
    final_state = simulate(struct, recipe, grid_delta_um=0.005)
    mf = topography_to_meshfield(final_state, mesh_size_um=0.03)
    print(mf.summary())

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plots)")
        return

    palette = {Material.SI: "#c9a66b", Material.SIO2: "#7fb8d9"}

    # --- Step-by-step profile ---
    fig, axes = plt.subplots(1, len(frames), figsize=(4.2 * len(frames), 3.6),
                              sharey=True)
    for ax, (label, bounds, polylines) in zip(axes, frames):
        _plot_stack(ax, label, bounds, polylines, palette)
    axes[0].set_ylabel("y [µm]")
    axes[-1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/05_locos_profile.png", dpi=120)
    print("  → examples/05_locos_profile.png")

    # --- Final triangulated MeshField ---
    pts = np.asarray(mf.grid.points)[:, :2]
    tris = mf.grid.cells_dict[5]
    fig, ax = plt.subplots(figsize=(7, 4))
    for material_id in np.unique(mf.material_ids):
        try:
            mat = Material(int(material_id))
        except ValueError:
            continue
        mask = mf.material_ids == material_id
        color = palette.get(mat, "#bbbbbb")
        for a, b, c in tris[mask]:
            xs = [pts[a, 0], pts[b, 0], pts[c, 0], pts[a, 0]]
            ys = [pts[a, 1], pts[b, 1], pts[c, 1], pts[a, 1]]
            ax.fill(xs, ys, color=color, edgecolor="k", linewidth=0.12)
    ax.set_xlabel("x [µm]")
    ax.set_ylabel("y [µm]")
    ax.set_title(f"LOCOS MeshField — {mf.n_cells} triangles")
    ax.set_aspect("equal")
    ax.set_xlim(0, WIDTH_UM)
    ax.set_ylim(0, mf.bounds[3] * 1.05)
    handles = [plt.Rectangle((0, 0), 1, 1, color=palette[m]) for m in palette]
    labels = [MATERIAL_NAMES.get(m, m.name) for m in palette]
    ax.legend(handles, labels, loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/05_locos_mesh.png", dpi=120)
    print("  → examples/05_locos_mesh.png")


if __name__ == "__main__":
    main()
