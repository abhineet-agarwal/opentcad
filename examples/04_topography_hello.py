"""
Example 04 — Topography "hello world": isotropic vs directional trench.

Runs two parallel recipes against a bare Si substrate. Both mask the
same 300 nm window and etch 150 nm:

    * isotropic  — quarter-circle undercut curls under the mask edges,
                   classic wet-etch profile.
    * directional (RIE, sidewall_ratio=0) — the ion beam only sees the
                   horizontal top, so the trench walls stay vertical.

Produces three artifacts:
    * examples/04_topography_recipe.png — recipe progression per step
      for both recipes, in a 2×3 grid.
    * examples/04_topography_profile.png — the two final profiles
      overlaid on a single axis, so you can read undercut off directly.
    * examples/04_topography_mesh.png — the isotropic result meshed
      and ready to hand to the device solver.

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


TRENCH_DEPTH_UM = 0.15
TRENCH_WINDOW = (0.35, 0.65)
INITIAL_Y_UM = 0.5


def _stack_polylines(state):
    """Extract (material, xs, ys) top-surface polylines at a single
    point in time; returns arrays that survive later state mutation."""
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
    state = initial_state_from_structure(struct, grid_delta_um)
    frames = [("initial", state.bounds_um, _stack_polylines(state))]
    for i, step in enumerate(recipe, 1):
        if hasattr(step, "thickness_um"):
            _apply_deposit(state, step)
            label = (f"step {i}: deposit {step.thickness_um*1000:.0f} nm "
                     f"{step.material.name}")
        else:
            _apply_etch(state, step)
            model_suffix = ("" if step.model == "isotropic"
                            else f" ({step.model})")
            label = f"step {i}: etch {step.depth_um*1000:.0f} nm{model_suffix}"
        frames.append((label, state.bounds_um, _stack_polylines(state)))
    return frames


def _build(model: str) -> tuple[Structure, Recipe]:
    struct = (Structure(width_um=1.0, name=f"trench_{model}")
              .add_substrate("body", INITIAL_Y_UM, Material.SI))
    recipe = (Recipe(f"blanket_then_trench_{model}")
              .etch(0.03)
              .etch(TRENCH_DEPTH_UM, model=model,
                    window_x_um=TRENCH_WINDOW))
    return struct, recipe


def _plot_frame(ax, label, bounds, polylines, palette):
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


def main():
    # Run both recipes and dump the per-step heights so you can see
    # what happened in the terminal too.
    frame_grid = {}
    for tag in ("isotropic", "directional"):
        struct, recipe = _build(tag)
        print(f"=== {tag.upper()} ===")
        print(recipe.summary())
        frames = _run_snapshots(struct, recipe, grid_delta_um=0.005)
        for label, _, polylines in frames:
            heights = [f"{m.name}@{ys.mean():.4f}" for m, _, ys in polylines]
            print(f"  {label:32s} → {heights}")
        frame_grid[tag] = frames
        print()

    # Mesh only the isotropic case for the mesh figure — the directional
    # case has a vertical wall which the current mesh bridge simplifies
    # by keeping the deeper point, so its meshed picture is nearly the
    # same as a rectangular trench.
    struct_i, recipe_i = _build("isotropic")
    final_state = simulate(struct_i, recipe_i, grid_delta_um=0.005)
    mf = topography_to_meshfield(final_state, mesh_size_um=0.03)
    print("MeshField (isotropic trench):")
    print(mf.summary())

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed - skipping plots)")
        return

    palette = {Material.SI: "#c9a66b", Material.SIO2: "#7fb8d9"}

    # --- 2 x n recipe progression grid ---
    n_steps = max(len(frames) for frames in frame_grid.values())
    fig, axes = plt.subplots(2, n_steps, figsize=(4 * n_steps, 5.5),
                             sharey=True)
    for row, tag in enumerate(("isotropic", "directional")):
        frames = frame_grid[tag]
        for col, (label, bounds, polylines) in enumerate(frames):
            _plot_frame(axes[row][col],
                        f"[{tag}] {label}", bounds, polylines, palette)
        axes[row][0].set_ylabel("y [um]")
        axes[row][-1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/04_topography_recipe.png", dpi=120)
    print("  → examples/04_topography_recipe.png")

    # --- Overlay of final profiles ---
    fig, ax = plt.subplots(figsize=(7, 3.5))
    colors = {"isotropic": "#d94a4a", "directional": "#2d6cba"}
    for tag in ("isotropic", "directional"):
        _, _, polylines = frame_grid[tag][-1]
        _, xs, ys = polylines[0]
        ax.plot(xs, ys, color=colors[tag], lw=2, label=tag)
    ax.axhline(INITIAL_Y_UM, color="k", ls="--", lw=0.7, alpha=0.5,
               label="initial surface")
    ax.axhline(INITIAL_Y_UM - TRENCH_DEPTH_UM, color="k", ls=":", lw=0.7,
               alpha=0.5, label="target trench floor")
    for xw in TRENCH_WINDOW:
        ax.axvline(xw, color="k", ls=":", lw=0.5, alpha=0.4)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_title(f"Trench profile @ 150 nm depth, window "
                 f"[{TRENCH_WINDOW[0]:.2f}, {TRENCH_WINDOW[1]:.2f}] um")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig("examples/04_topography_profile.png", dpi=120)
    print("  → examples/04_topography_profile.png")

    # --- MeshField cell-by-material plot (isotropic) ---
    pts = np.asarray(mf.grid.points)[:, :2]
    tris = mf.grid.cells_dict[5]
    fig, ax = plt.subplots(figsize=(6, 4))
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
            ax.fill(xs, ys, color=color, edgecolor="k", linewidth=0.15)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_title(f"MeshField (isotropic trench) — {mf.n_cells} triangles")
    ax.set_aspect("equal")
    ax.set_xlim(0, struct_i.width_um)
    ax.set_ylim(0, mf.bounds[3] * 1.05)
    handles = [plt.Rectangle((0, 0), 1, 1, color=palette[m]) for m in palette]
    labels = [MATERIAL_NAMES.get(m, m.name) for m in palette]
    ax.legend(handles, labels, loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig("examples/04_topography_mesh.png", dpi=120)
    print("  → examples/04_topography_mesh.png")


if __name__ == "__main__":
    main()
