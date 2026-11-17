# Visualization

OpenTCAD's figures work on the mesh itself:
- maps are sampled exactly, triangle by triangle, with no smoothing;
- junctions are found where net doping crosses zero inside each triangle;
- material edges come from the cells.

Three layers build on that:

| Layer | Module | For |
|---|---|---|
| Figure data | `opentcad.viz.fields` | NumPy arrays: grids, cut lines, contours, \|E\|. Plot them with anything |
| Interactive figures | `opentcad.viz.interactive` | Plotly figures (needs the `gui` extra) |
| GUI | `opentcad/gui/app.py` | The same figures in the browser, for files you build or the assistant drafts |

## Interactive figures

The examples use the diode from the [quickstart](getting_started.md):

```python
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material

mf = (Structure(width_um=1.0, name="pn_diode")
      .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
      .add_layer("n", 0.5, Material.SI, doping_Nd=1e17)
      .add_contact("anode", 0.0, 1.0, "p", surface="bottom")
      .add_contact("cathode", 0.0, 1.0, "n", surface="top")).to_meshfield(mesh_size_um=0.05)
solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
V, I = solver.iv_sweep("anode", "cathode", v_start=0.0, v_end=0.6, v_step=0.1)
```

```python
from opentcad.viz import interactive as vi

vi.structure_map(mf).show()                # materials
vi.doping_map(mf).show()                   # signed log net doping, with the p-n junction
vi.doping_profile(mf, x_um=0.25).show()    # each species vs depth at x, junction depths marked

snap = solver.run("fields", biases={"anode": 0.4})
for quantity in ("Potential", "Electrons", "Holes", "ElectricField"):
    vi.field_map(snap, quantity).show()

lin, log = vi.iv_figures(V, I, vth=0.62)    # linear and log current for one sweep
```

All figures take `theme="light"` or `"dark"`. Colours come from
`opentcad.viz.palette`, a palette checked for colour-vision deficiency and for
legibility in both themes. Materials and dopant species keep fixed colours across
figures.

## Figure data for your own plots

```python
import matplotlib.pyplot as plt
from opentcad.viz import fields as F

grid = F.sample_on_grid(mf, F.signed_log10(F.net_doping(mf)), nx=400)
plt.pcolormesh(grid.x, grid.y, grid.z, cmap="RdBu_r", shading="auto")   # z[j, i] at (x[i], y[j])
for (x0, y0), (x1, y1) in F.zero_contour(mf, F.net_doping(mf)):
    plt.plot([x0, x1], [y0, y1], "k-", lw=0.8)        # the metallurgical junction
plt.xlabel("x [µm]"); plt.ylabel("y [µm]")

cut = F.vertical_cut(mf, 0.25, {"Nd": mf.Nd, "Na": mf.Na})   # 1-D profiles
E = F.electric_field_V_per_cm(snap)                            # |E| per triangle
solver.close()
```

The [API reference](api/viz.md) lists every function.

## ParaView and other VTK tools

`MeshField.save("device")` writes `device.vtu`, and `opentcad run` writes one
`.vtu` per `fields` analysis. Both hold the materials, doping, species and (for
snapshots) `Potential`, `Electrons` and `Holes`. They open directly in ParaView.
