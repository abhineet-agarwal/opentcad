# Simulation files and the `opentcad` command

A simulation file is one YAML (or JSON) document describing a whole run:
structure, process recipe, mesh, device physics and analyses. It's what the
command line runs, and what a front end such as the GUI produces.

```bash
opentcad check examples/decks/nmos_implanted.yaml        # list every problem, or OK
opentcad run   examples/decks/nmos_implanted.yaml        # → nmos_implanted.results.json
opentcad run   deck.yaml -o out.json --vtu mesh.vtu      # also save the final MeshField
opentcad plugins                                         # what steps/analyses/models exist
```

`python -m opentcad ...` works the same; `pip install -e .` installs the
`opentcad` command. Exit status: 0 success, 1 the file has problems, 2 the
run failed. DEVSIM's per-iteration output is hidden unless `--verbose`.

From Python:

```python
from opentcad.io import load_deck, run_deck, save_deck
deck = load_deck("examples/decks/pn_diode.yaml")
result = run_deck(deck)
voltages, currents = result.analyses["forward"]
```

## Format (version 1)

Units are OpenTCAD's everywhere: µm, cm⁻³, K, eV, V. Two complete
examples are in [`examples/decks/`](../examples/decks/).

```yaml
version: 1
name: nmos_demo
description: free text                     # optional
structure:
  width_um: 2.0
  layers:                                  # bottom first; the first is the substrate
    - {name: body, thickness_um: 0.5, material: Si, doping_Na: 1e17}
    - {name: oxide, thickness_um: 0.005, material: SiO2}
  regions:                                 # optional rectangular overrides
    - {name: src, x_um: [0, 0.5], y_um: [0.4, 0.505], material: Si, doping_Nd: 1e20}
  contacts:                                # surface: top|bottom; type: ohmic|schottky
    - {name: gate, x_um: [0.5, 1.5], layer: oxide, surface: top, flat_band_shift_V: 0}
recipe:                                    # optional; steps run as in run_recipe
  - {step: implant, species: As, energy_keV: 30, dose_cm2: 1e15, window_x_um: [0, 0.5]}
  - {step: anneal, temperature_C: 1000, time_s: 10, model: fair}
mesh: {size_um: 0.03, grid_delta_um: 0.005}   # optional (these are the defaults)
device:                                    # optional; without it the run stops after meshing
  temperature_K: 300
  physics:
    mobility: {model: lombardi, base: {model: canali, base: klaassen}}
    recombination: [srh, auger]
    bgn: slotboom
    statistics: boltzmann
  material_process: {Si: hackerfab}        # optional parameter-file variants
  interface_Qf: [{region: SI, Qf_C_per_cm2: 1e-8, y_um: 0.5}]
analyses:                                  # run in order on one solver
  - {name: idvg, type: iv, anode_contact: gate, cathode_contact: src,
     v_start: 0, v_end: 1.5, v_step: 0.1, hold_contacts: {drain: 0.05},
     measure_contact: drain}
```

- **Materials:** `Si`, `SiO2`, `Si3N4`, `PolySi`, `Al`, `Photoresist`,
  `SiGe`, `GaN`, `SiC`, `Substrate` (case, spaces and underscores
  ignored). The device solver loads `<material>.yaml` parameters for every
  material in the mesh, so a material without a parameter file fails at run
  time.
- **Recipe steps:** any registered step by name. Built-ins are `deposit`,
  `etch`, `oxidize`, `implant` and `anneal`, whose fields are the arguments of
  `Recipe.deposit()` and so on. Plugin steps work too if they are
  dataclasses (see [plugins.md](plugins.md)). Species and energies are checked
  against the implant tables when the file is read.
- **Physics:** a model name, or `{model: name, option: value}`; `base:`
  nests a model. Names: mobility `constant`, `klaassen`, `canali`,
  `lombardi`; recombination `srh`, `auger`, `radiative`, `avalanche`; bgn
  `none`, `slotboom`; statistics `boltzmann`, `fermi_dirac`, `joyce_dixon`.
- **Analyses:** `type` is a registered analysis (`iv`, `cv`, `transient`,
  `ac`, or a plugin's), and the other keys are its arguments: those of
  `DeviceSolver.iv_sweep` and so on. They are checked against the function's
  signature, and contact names against the structure, before anything runs.
  `ac` terminals are wired automatically. Results go to the JSON under each
  analysis's `name`, with complex values written as `[re, im]`.

## Checking

Every problem is collected and reported with its location, not just the
first:

```
bad.yaml: 4 problem(s)
  structure.layers[0].material: unknown material 'Silcon'; use one of [...]
  recipe[0]: Unknown implant species 'Sb'. Known: ['arsenic', 'boron', 'phosphorus']
  recipe[1]: Energy 500.0 keV outside tabulated range for boron in Si [10 … 200] keV.
  recipe[2]: Unknown implant species 'Ga'. Known: ['arsenic', 'boron', 'phosphorus']
```

Unknown keys are errors, never ignored, so a misspelt field can't silently
fall back to a default. `1e15` is read as a number (plain YAML reads it as
text). `opentcad.io.dumps_deck(deck)` writes a deck back out, and loading
the result gives the same deck.
