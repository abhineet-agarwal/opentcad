# Quickstart

This page runs one device three ways: from a simulation file, in the GUI and from
Python. Install OpenTCAD first ([Installation](installation.md)).

## 1. Run a simulation file

A simulation file holds everything about a run: structure, process recipe, mesh,
physics and analyses. Here is the bundled p-n diode,
[`examples/decks/pn_diode.yaml`](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/decks/pn_diode.yaml):

```yaml
version: 1
name: pn_diode
structure:
  width_um: 1.0
  layers:
    - {name: p_body, thickness_um: 0.5, material: Si, doping_Na: 1e17}
    - {name: n_well, thickness_um: 0.5, material: Si, doping_Nd: 1e17}
  contacts:
    - {name: anode, x_um: [0, 1], layer: p_body, surface: bottom}
    - {name: cathode, x_um: [0, 1], layer: n_well, surface: top}
mesh: {size_um: 0.05}
device:
  temperature_K: 300
  physics: {mobility: klaassen, recombination: [srh]}
analyses:
  - {name: forward, type: iv, anode_contact: anode, cathode_contact: cathode,
     v_start: 0.0, v_end: 0.6, v_step: 0.1}
  - {name: equilibrium, type: fields}
```

Check it, then run it:

```bash
opentcad check examples/decks/pn_diode.yaml
opentcad run   examples/decks/pn_diode.yaml
```

```
pn_diode.yaml: OK — pn_diode: 2 layer(s), 0 recipe step(s), 2 analysis/es
[   0.2 s] analysis forward (iv)
[   1.4 s] analysis equilibrium (fields)
results → pn_diode.results.json
fields equilibrium → pn_diode.equilibrium.vtu
```

- **Results:** `pn_diode.results.json` holds the I–V curve.
- **Fields:** `pn_diode.equilibrium.vtu` holds the potential and carrier
  densities. It opens in ParaView, or with `MeshField.load`.

`opentcad check` reports every problem in a file at once, each with its location:
unknown keys, impossible values, contacts on layers that don't exist,
out-of-table implant energies. Nothing runs until the file is clean.

[Simulation files](simulation_files.md) documents the format and sweeps.

## 2. Use the GUI

```bash
pip install -e ".[gui]"
streamlit run opentcad/gui/app.py
```

The GUI opens at `http://localhost:8501` and has two pages:

- **Main page:** builds a structure and recipe step by step, with a preview at
  each stage, then runs I–V or C–V.
- **Assistant page** (in the sidebar): you describe a device or a change in plain
  language, and a model on your own machine drafts the simulation file. OpenTCAD
  checks the draft, flags every value you didn't state, and shows the structure,
  doping, curves and field maps when it runs. See [Assistant](assistant.md).

## 3. Use Python

The same diode in Python:

```python
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material

diode = (Structure(width_um=1.0, name="pn_diode")
         .add_substrate("p_body", 0.5, Material.SI, doping_Na=1e17)
         .add_layer("n_well", 0.5, Material.SI, doping_Nd=1e17)
         .add_contact("anode", 0.0, 1.0, "p_body", surface="bottom")
         .add_contact("cathode", 0.0, 1.0, "n_well", surface="top"))

mesh = diode.to_meshfield(mesh_size_um=0.05)
solver = DeviceSolver(mesh, {"Silicon": load_material("Si")})
V, I = solver.iv_sweep("anode", "cathode", v_start=0.0, v_end=0.6, v_step=0.1)
fields = solver.run("fields")          # a MeshField carrying Potential, Electrons, Holes
solver.close()
```

{% hint style="info" %}
DEVSIM keeps every device in one global state and solves all live devices
together. Call `solver.close()` when you're done with a solver, before building
another one in the same process.
{% endhint %}

## Next steps

- **Learn the building blocks:** [Concepts](concepts.md).
- **Build devices step by step:** the [tutorials](tutorials/README.md).
- **Look up a function:** the [API reference](api/README.md).
