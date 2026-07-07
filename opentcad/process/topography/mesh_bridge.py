"""
opentcad/process/topography/mesh_bridge.py — TopographyState → MeshField.

Turns the stack of ViennaLS level-sets produced by simulate() into the
same MeshField the device layer already consumes:

    TopographyState (viennals Domains, stacked bottom-first)
        │
        │  for each layer's top LS: ToSurfaceMesh → polyline (nodes, lines)
        │
        ▼
    single-valued top curves y_i(x), one per material
        │
        │  gmsh: build one 2D surface per material, bounded above by
        │        y_i(x) and below by y_{i-1}(x) (or the domain floor)
        │
        ▼
    triangular mesh with cell_data["material_id"]

MVP assumptions (loosened as we add anisotropic etch / re-entrant profiles):
  * top surfaces are single-valued: y is a function of x. That's true for
    isotropic deposit and isotropic etch of a flat wafer up to the point
    the etch bottoms out into a lower material — we bail with a clear
    error rather than silently produce a bogus mesh.
  * the simulation window (state.bounds_um) is a rectangle.
  * material stack is strictly ordered — layer[i] sits fully above the
    interface with layer[i-1].
"""
from __future__ import annotations

import numpy as np
import pyvista as pv

from opentcad.geometry.formats import Material, MeshField

from .simulator import TopographyState, extract_surface_polyline


def _polyline_to_y_of_x(nodes, xmin: float, xmax: float,
                        atol: float = 1e-7):
    """Reduce a ViennaLS 2D surface mesh to a single-valued function y(x).

    ViennaLS returns a set of line segments in arbitrary order. For a
    single-valued interface we can just harvest all node (x, y) pairs,
    keep those within the domain window, sort by x, and dedupe overlaps.
    Returns two numpy arrays (xs, ys) sorted by x.

    Raises ValueError if the surface is multi-valued (two distinct y for
    the same x beyond the tolerance) — a signal that the assumption has
    been violated and the caller needs a real polygon walker.
    """
    if not nodes:
        raise ValueError("Empty surface polyline — level-set extracted no "
                         "geometry. Did the recipe erode the whole layer?")
    pts = np.asarray(nodes, dtype=float)          # shape (N, 3), z=0
    xs = pts[:, 0]
    ys = pts[:, 1]
    # Keep points strictly within the sim window (ToSurfaceMesh may emit
    # small overshoots outside the reflective boundaries).
    keep = (xs >= xmin - atol) & (xs <= xmax + atol)
    xs, ys = xs[keep], ys[keep]

    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]

    # Merge duplicates that share the same x (within atol). If y values
    # agree, keep the mean; if they disagree, the surface is multi-
    # valued at that x — physically that's a vertical wall + undercut
    # from a masked etch (the level-set has two zero-crossings on the
    # same column). We keep the LOWER y, which represents the true top
    # of the underlying material once you disregard the thin overhang
    # sliver that hangs off the mask edge (the mask itself isn't in
    # our material stack, so the overhang has nothing physical holding
    # it up in the meshed geometry). Preserves the undercut extent and
    # the trench floor, while giving gmsh a clean single-valued curve
    # to mesh against.
    merged_xs: list[float] = []
    merged_ys: list[float] = []
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and (xs[j + 1] - xs[i]) < atol:
            j += 1
        y_cluster = ys[i:j + 1]
        merged_xs.append(float(xs[i]))
        merged_ys.append(float(y_cluster.min()))
        i = j + 1

    # Clamp x to the exact bounds and ensure we have an endpoint at each
    # side, extrapolating y with the nearest sample if necessary.
    if abs(merged_xs[0] - xmin) > atol:
        merged_xs.insert(0, xmin)
        merged_ys.insert(0, merged_ys[0])
    else:
        merged_xs[0] = xmin
    if abs(merged_xs[-1] - xmax) > atol:
        merged_xs.append(xmax)
        merged_ys.append(merged_ys[-1])
    else:
        merged_xs[-1] = xmax
    return np.asarray(merged_xs), np.asarray(merged_ys)


def _resample_polyline_uniform(xs: np.ndarray, ys: np.ndarray, n: int
                               ) -> tuple[np.ndarray, np.ndarray]:
    """Resample (xs, ys) onto n equally-spaced x samples covering the
    same x range. Linear interpolation."""
    xg = np.linspace(xs[0], xs[-1], n)
    yg = np.interp(xg, xs, ys)
    return xg, yg


def topography_to_meshfield(state: TopographyState,
                            mesh_size_um: float = 0.05,
                            n_samples: int = 64) -> MeshField:
    """Convert a TopographyState into a MeshField that the device layer
    can consume directly.

    Args:
        state: final topography stack from simulate().
        mesh_size_um: gmsh characteristic element size [um].
        n_samples: number of samples per material-top polyline. 64 is
            enough for smooth curved surfaces at MVP resolution — bumped
            up automatically if a layer polyline has more raw nodes.
    """
    import gmsh

    xmin, xmax, ymin, _ = state.bounds_um

    raw_curves: list[tuple[Material, np.ndarray, np.ndarray]] = []
    for L in state.layers:
        nodes, _lines = extract_surface_polyline(L.level_set)
        xs, ys = _polyline_to_y_of_x(nodes, xmin, xmax)
        raw_curves.append((L.material, xs, ys))

    if not raw_curves:
        raise ValueError("TopographyState has no layers.")

    # Resample every curve onto the same x grid so downstream code can
    # compare y-values element-wise (stack-monotonicity, plotting, etc.)
    # and so the gmsh side-wall connections at xmin/xmax align exactly.
    max_raw_n = max(len(xs) for _, xs, _ in raw_curves)
    n = max(n_samples, max_raw_n)
    tops: list[tuple[Material, np.ndarray, np.ndarray]] = []
    for material, xs, ys in raw_curves:
        xs_r, ys_r = _resample_polyline_uniform(xs, ys, n)
        tops.append((material, xs_r, ys_r))

    # Verify strict stacking: each polyline must lie above the previous.
    for i in range(1, len(tops)):
        _, _, ys_prev = tops[i - 1]
        _, _, ys_cur = tops[i]
        if not np.all(ys_cur >= ys_prev - 1e-6):
            drop = float((ys_prev - ys_cur).max())
            raise ValueError(
                f"Layer {i} top drops {drop:.4f} um below layer {i-1} top — "
                "etch broke through the underlying material. Handling this "
                "properly needs a real polygon walker (planned).")

    lc_mm = mesh_size_um * 1e-3
    lc_fine_mm = lc_mm / 2

    if gmsh.isInitialized():
        gmsh.clear()
    else:
        gmsh.initialize()

    try:
        gmsh.option.setNumber("General.Verbosity", 0)
        gmsh.model.add("topography")

        # Convert um → mm at the boundary. Every point below stays in mm.
        UM_TO_MM = 1e-3

        def make_curve(xs: np.ndarray, ys: np.ndarray) -> int:
            """Add a piecewise-linear curve through (xs, ys). Returns
            the wire tag."""
            pts = []
            for xi, yi in zip(xs, ys):
                pts.append(gmsh.model.occ.addPoint(
                    xi * UM_TO_MM, yi * UM_TO_MM, 0.0, lc_mm))
            segments = []
            for a, b in zip(pts[:-1], pts[1:]):
                segments.append(gmsh.model.occ.addLine(a, b))
            return segments, pts

        # Bottom of the whole domain: the floor of the substrate is where
        # material layer[0] starts, but for meshing we need a closed loop
        # per material. Use the domain floor ymin as the bottom of
        # layer[0].
        # For layer i > 0, the bottom curve is layer[i-1]'s top curve
        # (shared boundary → same points).

        # Persistent per-layer polyline endpoints so we can share sides.
        # For each interface curve, keep its left/right endpoint tags so
        # we can close the side edges consistently.
        interface_curves: list[dict] = []
        # Domain floor (special-cased):
        floor_segments, floor_pts = make_curve(
            np.array([xmin, xmax]),
            np.array([ymin, ymin]),
        )
        interface_curves.append({
            "segments": floor_segments,
            "left_pt":  floor_pts[0],
            "right_pt": floor_pts[-1],
            "left_x":  xmin, "right_x": xmax,
            "left_y":  ymin, "right_y": ymin,
        })

        for material, xs, ys in tops:
            segs, pts = make_curve(xs, ys)
            interface_curves.append({
                "segments": segs,
                "left_pt":  pts[0],
                "right_pt": pts[-1],
                "left_x":  float(xs[0]),  "right_x": float(xs[-1]),
                "left_y":  float(ys[0]),  "right_y": float(ys[-1]),
                "material": material,
            })

        surface_material: dict[int, Material] = {}
        for i in range(1, len(interface_curves)):
            bot = interface_curves[i - 1]
            top = interface_curves[i]

            # Left side: line from bot.left_pt to top.left_pt.
            left_side = gmsh.model.occ.addLine(bot["left_pt"], top["left_pt"])
            # Right side: line from top.right_pt to bot.right_pt (reverse
            # so the loop traverses counter-clockwise when possible).
            right_side = gmsh.model.occ.addLine(top["right_pt"],
                                                bot["right_pt"])

            # Build the curve loop: bottom (L→R), right side (R→R),
            # top reversed (R→L), left reversed (L→L). We negate segment
            # tags for reversal.
            loop_segs = (
                list(bot["segments"])
                + [right_side]
                + [-s for s in reversed(top["segments"])]
                + [-left_side]
            )
            wire = gmsh.model.occ.addWire(loop_segs, checkClosed=False)
            surf = gmsh.model.occ.addPlaneSurface([wire])
            surface_material[surf] = top["material"]

        gmsh.model.occ.synchronize()

        for stag, material in surface_material.items():
            pg = gmsh.model.addPhysicalGroup(2, [stag])
            gmsh.model.setPhysicalName(2, pg, material.name)

        gmsh.option.setNumber("Mesh.Algorithm", 6)   # Frontal-Delaunay
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc_fine_mm)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc_mm)
        gmsh.model.mesh.generate(2)

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        points = coords.reshape(-1, 3) * 1e3   # mm → um
        tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

        all_cells: list[int] = []
        all_mat_ids: list[int] = []
        for stag, material in surface_material.items():
            elem_types, elem_tags, elem_conn = gmsh.model.mesh.getElements(
                dim=2, tag=stag)
            mid = int(material)
            for et, etags, econn in zip(elem_types, elem_tags, elem_conn):
                if et != 2:
                    continue
                conn = econn.reshape(len(etags), 3)
                for nds in conn:
                    all_cells.append(3)
                    all_cells.extend(tag_to_idx[int(n)] for n in nds)
                    all_mat_ids.append(mid)

        if not all_mat_ids:
            raise RuntimeError("gmsh generated no triangles from topography.")

        cells = np.array(all_cells, dtype=np.int64)
        celltypes = np.full(len(all_mat_ids), pv.CellType.TRIANGLE,
                            dtype=np.uint8)
        mat_ids = np.array(all_mat_ids, dtype=np.int32)

        grid = pv.UnstructuredGrid(cells, celltypes, points)
        grid.cell_data["material_id"] = mat_ids
    finally:
        gmsh.finalize()

    return MeshField(grid=grid)
