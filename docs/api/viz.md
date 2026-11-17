# Visualization

Figure data on the mesh, interactive Plotly figures and the colour palette.

For an introduction, see the [user guide](../visualization.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.viz.fields`: `sample_on_grid`, `GridField`, `cells_on_grid`, `cell_values_on_grid`, `cell_gradient`, `electric_field_V_per_cm`, `net_doping`, `signed_log10`, `zero_contour`, `material_edges`, `material_labels`, `vertical_cut`, `points_um`, `triangles`.

## sample_on_grid

```python
opentcad.viz.fields.sample_on_grid(
    mf: MeshField,
    values,
    *,
    nx: int = 400,
    ny: Optional[int] = None,
    materials: Optional[Iterable[Material]] = None,
) -> GridField
```

Sample nodal ``values`` on a regular grid by linear interpolation
inside each mesh triangle. ``materials`` restricts to those cells.
``ny`` defaults to keep square pixels.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L61)

## GridField

```python
class opentcad.viz.fields.GridField(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> None
```

Values on a regular grid: ``z[j, i]`` at ``(x[i], y[j])``; NaN where
there is no (selected) mesh.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L52)

## cells_on_grid

```python
opentcad.viz.fields.cells_on_grid(
    mf: MeshField,
    x: np.ndarray,
    y: np.ndarray,
) -> np.ndarray
```

Index of the mesh cell containing each grid point ``(x[i], y[j])``,
shape (len(y), len(x)); −1 outside the mesh.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L84)

## cell_values_on_grid

```python
opentcad.viz.fields.cell_values_on_grid(mf: MeshField, cell_values, x, y) -> np.ndarray
```

Per-cell values on a grid (NaN outside the mesh), shape (len(y), len(x)).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L117)

## cell_gradient

```python
opentcad.viz.fields.cell_gradient(mf: MeshField, values) -> np.ndarray
```

Gradient of nodal ``values`` on each triangle, (n_cells, 2), in
[value]/µm. Exact for the piecewise-linear field.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L94)

## electric_field_V_per_cm

```python
opentcad.viz.fields.electric_field_V_per_cm(mf: MeshField, potential=None) -> np.ndarray
```

|E| = |∇ψ| on each triangle [V/cm], from the ``Potential`` point
data of a solver snapshot (or ``potential`` given explicitly).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L109)

## net_doping

```python
opentcad.viz.fields.net_doping(mf: MeshField) -> np.ndarray
```

Nd − Na [cm⁻³]: positive n-type, negative p-type.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L124)

## signed_log10

```python
opentcad.viz.fields.signed_log10(values, floor: float = 1e14) -> np.ndarray
```

sign(v)·log10(|v|/floor), and 0 for |v| ≤ floor. Keeps the n/p sign
on a log scale; ±1 corresponds to ±10·floor, and so on.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L129)

## zero_contour

```python
opentcad.viz.fields.zero_contour(
    mf: MeshField,
    values,
    *,
    materials: Optional[Iterable[Material]] = frozenset({Material.SI, Material.POLY_SI, Material.SIGE, Material.GAN, Material.SIC, Material.SUBSTRATE}),
) -> np.ndarray
```

Line segments where nodal ``values`` cross zero, by linear
interpolation inside each triangle (exact for the mesh field).
Returns an (n, 2, 2) array of ((x0, y0), (x1, y1)). With the net doping
this is the metallurgical p-n junction.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L137)

## material_edges

```python
opentcad.viz.fields.material_edges(mf: MeshField) -> np.ndarray
```

Segments between cells of different material, plus the outer
boundary. (n, 2, 2) array, for outlining regions.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L162)

## material_labels

```python
opentcad.viz.fields.material_labels(
    mf: MeshField,
    *,
    min_thickness_frac: float = 0.0,
) -> dict[Material, tuple[float, float]]
```

A label position inside each material: the centroid of the
material's triangle closest to its area-weighted centroid. Materials
whose typical thickness (area / longest bounding-box side) is below
``min_thickness_frac`` of the device height are left out — too thin
to hold a label.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L189)

## vertical_cut

```python
opentcad.viz.fields.vertical_cut(
    mf: MeshField,
    x_um: float,
    fields: dict,
    *,
    n: int = 600,
    materials: Optional[Iterable[Material]] = frozenset({Material.SI, Material.POLY_SI, Material.SIGE, Material.GAN, Material.SIC, Material.SUBSTRATE}),
) -> dict[str, np.ndarray]
```

Sample ``fields`` ({name: nodal values}) down the line x = x_um.
Returns {"y_um": ..., name: ...}; NaN where the line is outside the
selected cells.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L217)

## points_um

```python
opentcad.viz.fields.points_um(mf: MeshField) -> np.ndarray
```

Node coordinates as an (n_points, 2) array of (x, y) in µm.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L30)

## triangles

```python
opentcad.viz.fields.triangles(mf: MeshField) -> np.ndarray
```

Triangle connectivity as an (n_cells, 3) array of node indices, in
cell order. Raises ValueError if the mesh is not all triangles.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/fields.py#L35)

Import from `opentcad.viz.interactive`: `structure_map`, `doping_map`, `doping_profile`, `field_map`, `iv_figures`, `metric_figure`.

## structure_map

```python
opentcad.viz.interactive.structure_map(
    mf: MeshField,
    *,
    theme: str = 'light',
    nx: int = 500,
    show_mesh: bool = False,
    title: str = 'Structure',
)
```

Materials (fixed colour per material, labelled on the regions) and
contacts (thick labelled lines). ``show_mesh`` draws triangle edges.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L250)

## doping_map

```python
opentcad.viz.interactive.doping_map(
    mf: MeshField,
    *,
    theme: str = 'light',
    nx: int = 500,
    floor: float = 1e14,
    title: str = 'Net doping',
)
```

Net doping Nd − Na on a signed log scale: p-type blue, n-type red,
gray within ±floor. Non-semiconductor regions are shown flat and
labelled; material edges as hairlines; the p-n junction as a line.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L87)

## doping_profile

```python
opentcad.viz.interactive.doping_profile(
    mf: MeshField,
    x_um: float,
    *,
    theme: str = 'light',
    floor: float = 1e13,
    title: Optional[str] = None,
)
```

Concentration of each tracked species (and any untracked doping)
against depth below the semiconductor top at x = x_um; junction
depths marked.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L332)

## field_map

```python
opentcad.viz.interactive.field_map(
    mf: MeshField,
    quantity: str,
    *,
    theme: str = 'light',
    nx: int = 500,
    title: Optional[str] = None,
)
```

A solution field from a solver snapshot (``DeviceSolver.snapshot`` or
the ``fields`` analysis):

  * ``Potential`` — ψ [V], diverging around 0 (n-like +, p-like −), all regions
  * ``Electrons`` / ``Holes`` — log10 density [cm⁻³], semiconductors only
  * ``ElectricField`` — |E| [V/cm] per triangle, all regions

Material edges and the p-n junction are drawn on top.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L164)

## iv_figures

```python
opentcad.viz.interactive.iv_figures(
    v: Sequence[float],
    i: Sequence[float],
    *,
    theme: str = 'light',
    x_label: str = 'V [V]',
    y_label: str = 'I [A/cm]',
    title: str = '',
    vth: Optional[float] = None,
)
```

Two figures for one sweep: linear current, and |current| on a log
axis. Separate charts rather than one chart with two y-axes.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L383)

## metric_figure

```python
opentcad.viz.interactive.metric_figure(
    xs: Sequence[float],
    ys: Sequence[Optional[float]],
    *,
    theme: str = 'light',
    x_label: str = '',
    y_label: str = '',
    title: str = '',
)
```

One sweep metric against the swept value (points joined by a line;
missing values leave a gap).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/interactive.py#L417)

Import from `opentcad.viz.palette`: `material_color`, `species_color`, `diverging_colorscale`, `sequential_colorscale`, `oklch`.

## material_color

```python
opentcad.viz.palette.material_color(material: Material, theme: str = 'light') -> str
```

Fill colour for a material; materials past the 8 slots share muted ink.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/palette.py#L68)

## species_color

```python
opentcad.viz.palette.species_color(
    species: str,
    theme: str = 'light',
    known: list[str] | None = None,
) -> str
```

Line colour for a dopant species, fixed per species.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/palette.py#L76)

## diverging_colorscale

```python
opentcad.viz.palette.diverging_colorscale(theme: str = 'light') -> list
```

Plotly colorscale for signed data: p/negative = blue, n/positive =
red, gray at zero. In dark mode the arms brighten away from the
(dark) midpoint so near-zero recedes into the surface.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/palette.py#L86)

## sequential_colorscale

```python
opentcad.viz.palette.sequential_colorscale(theme: str = 'light') -> list
```

Plotly colorscale for magnitude: light→dark blue on a light surface,
dark→light on a dark one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/palette.py#L100)

## oklch

```python
opentcad.viz.palette.oklch(hex_color: str) -> tuple[float, float, float]
```

(L, C, h°) of an sRGB hex colour in OKLCH.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/viz/palette.py#L120)
