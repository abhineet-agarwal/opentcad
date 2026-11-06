"""
opentcad.viz.fields — figure data from a MeshField, independent of any
plotting library.

Everything works on the mesh's own triangles (no re-triangulation), so
grid samples, contours and cuts use exactly the piecewise-linear field
the solver and the doping kernels see.

    sample_on_grid(mf, values)      values on a regular grid (NaN outside)
    net_doping(mf), signed_log10    Nd − Na, and a log scale that keeps sign
    zero_contour(mf, values)        segments where a field changes sign (p-n junction)
    material_edges(mf)              segments on material boundaries and the outline
    material_labels(mf)             one (x, y) label position per material
    vertical_cut(mf, x, fields)     profiles down a vertical line
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from opentcad.geometry.formats import Material, MeshField

#: Materials whose doping means something (shown on doping maps).
SEMICONDUCTORS = frozenset({Material.SI, Material.POLY_SI, Material.SIGE,
                            Material.GAN, Material.SIC, Material.SUBSTRATE})


def points_um(mf: MeshField) -> np.ndarray:
    return np.asarray(mf.grid.points, dtype=float)[:, :2]


def triangles(mf: MeshField) -> np.ndarray:
    tris = mf.grid.cells_dict.get(5)          # VTK_TRIANGLE
    if tris is None or len(tris) != mf.n_cells:
        raise ValueError("MeshField must consist of triangles only")
    return np.asarray(tris, dtype=np.int64)


def _cell_mask(mf: MeshField, materials: Optional[Iterable[Material]]) -> np.ndarray:
    """True for cells to drop (matplotlib's mask convention)."""
    if materials is None:
        return np.zeros(mf.n_cells, dtype=bool)
    keep = {int(m) for m in materials}
    return ~np.isin(np.asarray(mf.material_ids), list(keep))


@dataclass
class GridField:
    """Values on a regular grid: ``z[j, i]`` at ``(x[i], y[j])``; NaN where
    there is no (selected) mesh."""
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray


def sample_on_grid(mf: MeshField, values, *, nx: int = 400,
                   ny: Optional[int] = None,
                   materials: Optional[Iterable[Material]] = None) -> GridField:
    """Sample nodal ``values`` on a regular grid by linear interpolation
    inside each mesh triangle. ``materials`` restricts to those cells.
    ``ny`` defaults to keep square pixels."""
    import matplotlib.tri as mtri
    values = np.asarray(values, dtype=float)
    if values.shape != (mf.n_points,):
        raise ValueError(f"values must have shape ({mf.n_points},)")
    pts = points_um(mf)
    tri = mtri.Triangulation(pts[:, 0], pts[:, 1], triangles(mf),
                             mask=_cell_mask(mf, materials))
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    if ny is None:
        ny = max(2, int(round(nx * (ymax - ymin) / max(xmax - xmin, 1e-12))))
    x = np.linspace(xmin, xmax, nx)
    y = np.linspace(ymin, ymax, ny)
    xx, yy = np.meshgrid(x, y)
    z = mtri.LinearTriInterpolator(tri, values)(xx, yy)
    return GridField(x, y, np.ma.filled(z.astype(float), np.nan))


def cells_on_grid(mf: MeshField, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Index of the mesh cell containing each grid point ``(x[i], y[j])``,
    shape (len(y), len(x)); −1 outside the mesh."""
    import matplotlib.tri as mtri
    pts = points_um(mf)
    tri = mtri.Triangulation(pts[:, 0], pts[:, 1], triangles(mf))
    xx, yy = np.meshgrid(x, y)
    return np.asarray(tri.get_trifinder()(xx, yy), dtype=np.int64)


def cell_gradient(mf: MeshField, values) -> np.ndarray:
    """Gradient of nodal ``values`` on each triangle, (n_cells, 2), in
    [value]/µm. Exact for the piecewise-linear field."""
    v = np.asarray(values, dtype=float)
    pts = points_um(mf)
    t = triangles(mf)
    p0, p1, p2 = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
    d1, d2 = p1 - p0, p2 - p0
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    f1, f2 = v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]
    gx = (f1 * d2[:, 1] - f2 * d1[:, 1]) / det
    gy = (f2 * d1[:, 0] - f1 * d2[:, 0]) / det
    return np.column_stack([gx, gy])


def electric_field_V_per_cm(mf: MeshField, potential=None) -> np.ndarray:
    """|E| = |∇ψ| on each triangle [V/cm], from the ``Potential`` point
    data of a solver snapshot (or ``potential`` given explicitly)."""
    psi = mf.grid.point_data["Potential"] if potential is None else potential
    g = cell_gradient(mf, psi)                    # V/µm
    return np.hypot(g[:, 0], g[:, 1]) * 1e4


def cell_values_on_grid(mf: MeshField, cell_values, x, y) -> np.ndarray:
    """Per-cell values on a grid (NaN outside the mesh), shape (len(y), len(x))."""
    cells = cells_on_grid(mf, x, y)
    vals = np.asarray(cell_values, dtype=float)
    return np.where(cells >= 0, vals[np.clip(cells, 0, None)], np.nan)


def net_doping(mf: MeshField) -> np.ndarray:
    """Nd − Na [cm⁻³]: positive n-type, negative p-type."""
    return np.asarray(mf.Nd, dtype=float) - np.asarray(mf.Na, dtype=float)


def signed_log10(values, floor: float = 1e14) -> np.ndarray:
    """sign(v)·log10(|v|/floor), and 0 for |v| ≤ floor. Keeps the n/p sign
    on a log scale; ±1 corresponds to ±10·floor, and so on."""
    v = np.asarray(values, dtype=float)
    mag = np.log10(np.maximum(np.abs(v) / floor, 1.0))
    return np.sign(v) * mag


def zero_contour(mf: MeshField, values, *,
                 materials: Optional[Iterable[Material]] = SEMICONDUCTORS
                 ) -> np.ndarray:
    """Line segments where nodal ``values`` cross zero, by linear
    interpolation inside each triangle (exact for the mesh field).
    Returns an (n, 2, 2) array of ((x0, y0), (x1, y1)). With the net doping
    this is the metallurgical p-n junction."""
    v = np.asarray(values, dtype=float)
    pts = points_um(mf)
    tris = triangles(mf)[~_cell_mask(mf, materials)]
    pos = v[tris] >= 0.0
    mixed = pos.any(axis=1) & ~pos.all(axis=1)
    segs = []
    for tri in tris[mixed]:
        crossings = []
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            va, vb = v[a], v[b]
            if (va >= 0.0) != (vb >= 0.0):
                t = va / (va - vb)
                crossings.append(pts[a] + t * (pts[b] - pts[a]))
        if len(crossings) == 2:
            segs.append(crossings)
    return np.asarray(segs, dtype=float).reshape(-1, 2, 2)


def material_edges(mf: MeshField) -> np.ndarray:
    """Segments between cells of different material, plus the outer
    boundary. (n, 2, 2) array, for outlining regions."""
    tris = triangles(mf)
    mats = np.asarray(mf.material_ids)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    owner = np.tile(np.arange(len(tris)), 3)
    key = np.sort(edges, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner = key[order], owner[order]
    same_as_next = np.all(key[1:] == key[:-1], axis=1)
    keep = []
    i = 0
    n = len(key)
    while i < n:
        if i + 1 < n and same_as_next[i]:
            if mats[owner[i]] != mats[owner[i + 1]]:
                keep.append(key[i])
            i += 2
        else:
            keep.append(key[i])                  # boundary edge
            i += 1
    pts = points_um(mf)
    keep = np.asarray(keep, dtype=np.int64).reshape(-1, 2)
    return np.stack([pts[keep[:, 0]], pts[keep[:, 1]]], axis=1)


def material_labels(mf: MeshField, *, min_thickness_frac: float = 0.0
                    ) -> dict[Material, tuple[float, float]]:
    """A label position inside each material: the centroid of the
    material's triangle closest to its area-weighted centroid. Materials
    whose typical thickness (area / longest bounding-box side) is below
    ``min_thickness_frac`` of the device height are left out — too thin
    to hold a label."""
    pts = points_um(mf)
    tris = triangles(mf)
    cent = pts[tris].mean(axis=1)
    a, b, c = pts[tris[:, 0]], pts[tris[:, 1]], pts[tris[:, 2]]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    out = {}
    mats = np.asarray(mf.material_ids)
    height = mf.bounds[3] - mf.bounds[2]
    for mid in np.unique(mats):
        sel = mats == mid
        corners = pts[tris[sel]].reshape(-1, 2)
        span = max(np.ptp(corners[:, 0]), np.ptp(corners[:, 1]), 1e-12)
        if area[sel].sum() / span < min_thickness_frac * height:
            continue
        target = (cent[sel] * area[sel, None]).sum(axis=0) / area[sel].sum()
        k = np.argmin(np.sum((cent[sel] - target) ** 2, axis=1))
        out[Material(int(mid))] = tuple(float(v) for v in cent[sel][k])
    return out


def vertical_cut(mf: MeshField, x_um: float, fields: dict, *, n: int = 600,
                 materials: Optional[Iterable[Material]] = SEMICONDUCTORS
                 ) -> dict[str, np.ndarray]:
    """Sample ``fields`` ({name: nodal values}) down the line x = x_um.
    Returns {"y_um": ..., name: ...}; NaN where the line is outside the
    selected cells."""
    import matplotlib.tri as mtri
    pts = points_um(mf)
    tri = mtri.Triangulation(pts[:, 0], pts[:, 1], triangles(mf),
                             mask=_cell_mask(mf, materials))
    _, _, ymin, ymax = mf.bounds[:4]
    y = np.linspace(ymin, ymax, n)
    x = np.full_like(y, float(x_um))
    out = {"y_um": y}
    for name, vals in fields.items():
        z = mtri.LinearTriInterpolator(tri, np.asarray(vals, dtype=float))(x, y)
        out[name] = np.ma.filled(z.astype(float), np.nan)
    return out
