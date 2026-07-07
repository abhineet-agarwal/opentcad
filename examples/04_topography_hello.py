"""
Example 04 — Topography "hello world".

Runs a two-step process recipe against a bare Si substrate:
    1. blanket etch 30 nm (isotropic uniform)
    2. window etch 150 nm through a 300-nm mask opening (curved trench
       with quarter-circle undercuts at the mask edges)

The window step is what showcases the level-set solver: the trench
floor is flat inside the window, the sidewalls curl under the mask
edges (undercut), and the profile is smoothly single-valued in y(x).

and produces two artifacts:
    * examples/04_topography_recipe.png — the material stack at each
      step of the recipe, overlaid.
    * examples/04_topography_mesh.png   — the final MeshField shown with
      per-material shading, ready to be handed to the device solver.

Run:
    python examples/04_topography_hello.py
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import Material, MATERIAL_NAMES
from opentcad.geometry.structure import Structure
from opentcad.process.topography import (
    Recipe, extract_surface_polyline,
    initial_state_from_structure, simulate,
    topography_to_meshfield,
)
from opentcad.process.topography.simulator import _apply_deposit, _apply_etch


def _stack_polylines(state):
    """Extract the (material, xs, ys) top-surface polylines for the
    given state, at a single point in time. Returns a plain list of
    numpy arrays that survives further mutations of state."""
    out = []
    xmin, xmax, _, _ = state.bounds_um
    for L in state.layers:
        nodes, _ = extract_surface_polyline(L.level_set)
        pts = np.asarray(nodes)
        xs = pts[:, 0]; ys = pts[:, 1]
        keep = (xs >= xmin - 1e-7) & (xs <= xmax + 1e-7)
        order = np.argsort(xs[keep])
        out.append((L.material, xs[keep][order].copy(), ys[keep][order].copy()))
    return out


def _run_snapshots(struct, recipe, grid_delta_um: float):
    """Return list of (label, bounds, polylines) at each step. Polylines
    are extracted immediately so mutations to state after the snapshot
    is taken don't affect earlier entries."""
    state = initial_state_from_structure(struct, grid_delta_um)
    frames = [("initial", state.bounds_um, _stack_polylines(state))]
    for i, step in enumerate(recipe, 1):
        if hasattr(step, "thickness_um"):
            _apply_deposit(state, step)
            label = (f"step {i}: deposit {step.thickness_um*1000:.0f} nm "
                     f"{step.material.name}")
        else:
            _apply_etch(state, step)
            label = f"step {i}: etch {step.depth_um*1000:.0f} nm"
        frames.append((label, state.bounds_um, _stack_polylines(state)))
    return frames


def main():
    struct = (Structure(width_um=1.0, name="topo_hello")
              .add_substrate("body", 0.5, Material.SI))
    recipe = (Recipe("blanket_then_curved_trench")
              .etch(0.03)
              .etch(0.15, window_x_um=(0.35, 0.65)))
    print(recipe.summary())
    print()

    print("Simulating each step for the recipe plot...")
    frames = _run_snapshots(struct, recipe, grid_delta_um=0.005)
    for label, _, polylines in frames:
        heights = [f"{m.name}@{ys.mean():.4f}" for m, _, ys in polylines]
        print(f"  {label:36s} → {heights}")

    print("\nRunning full simulation and building MeshField...")
    final_state = simulate(struct, recipe, grid_delta_um=0.005)
    mf = topography_to_meshfield(final_state, mesh_size_um=0.03)
    print("\n" + mf.summary())

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plots)")
        return

    palette = {
        Material.SI:   "#c9a66b",
        Material.SIO2: "#7fb8d9",
    }

    # --- Recipe progression plot ---
    fig, axes = plt.subplots(1, len(frames), figsize=(4 * len(frames), 3),
                             sharey=True)
    if len(frames) == 1:
        axes = [axes]
    for ax, (label, bounds, polylines) in zip(axes, frames):
        xmin, xmax, ymin, _ = bounds
        prev_y = np.full(2, ymin)
        prev_x = np.array([xmin, xmax])
        for material, xs, ys in polylines:
            n = max(int(xs.size), 2)
            xi = np.linspace(xmin, xmax, n)
            yi = np.interp(xi, xs, ys) if xs.size >= 2 else np.full_like(xi, ys[0])
            yb = np.interp(xi, prev_x, prev_y)
            color = palette.get(material, "#bbbbbb")
            ax.fill_between(xi, yb, yi, color=color,
                            label=MATERIAL_NAMES.get(material, material.name),
                            edgecolor="k", linewidth=0.4)
            prev_x, prev_y = xi, yi
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, max(0.6, float(prev_y.max()) * 1.05))
        ax.set_xlabel("x [um]")
        ax.set_title(label, fontsize=9)
        ax.grid(True, alpha=0.2)
    axes[0].set_ylabel("y [um]")
    axes[-1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/04_topography_recipe.png", dpi=120)
    print("  → examples/04_topography_recipe.png")

    # --- MeshField cell-by-material plot ---
    tri = mf.grid.extract_surface().triangulate()
    pts = np.asarray(mf.grid.points)[:, :2]
    tris = mf.grid.cells_dict[5]  # VTK triangle

    fig, ax = plt.subplots(figsize=(6, 4))
    for material_id in np.unique(mf.material_ids):
        try:
            mat = Material(int(material_id))
        except ValueError:
            continue
        mask = mf.material_ids == material_id
        triples = tris[mask]
        color = palette.get(mat, "#bbbbbb")
        for a, b, c in triples:
            xs = [pts[a, 0], pts[b, 0], pts[c, 0], pts[a, 0]]
            ys = [pts[a, 1], pts[b, 1], pts[c, 1], pts[a, 1]]
            ax.fill(xs, ys, color=color, edgecolor="k", linewidth=0.15)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_title(f"Post-process MeshField — {mf.n_cells} triangles")
    ax.set_aspect("equal")
    ax.set_xlim(0, struct.width_um)
    ax.set_ylim(0, mf.bounds[3] * 1.05)
    handles = [plt.Rectangle((0, 0), 1, 1, color=palette[m]) for m in palette]
    labels = [MATERIAL_NAMES.get(m, m.name) for m in palette]
    ax.legend(handles, labels, loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/04_topography_mesh.png", dpi=120)
    print("  → examples/04_topography_mesh.png")


if __name__ == "__main__":
    main()
