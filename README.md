# OpenTCAD

**An open, honest and extensible TCAD framework: semiconductor process and
device simulation in one Python pipeline.**

OpenTCAD takes a device from a description of how it is made (layers,
deposition, etching, oxidation, ion implantation, annealing) to how it
behaves (I–V, C–V, transient and small-signal response, and maps of the
potential, carriers and electric field). It is built on mature open
libraries ([Gmsh](https://gmsh.info), [ViennaLS](https://viennatools.github.io/),
[DEVSIM](https://devsim.org), [PyVista](https://pyvista.org)) and joins them
through one data contract, so each stage can be inspected, replaced or extended.

## The vision

Commercial TCAD (Synopsys Sentaurus and its peers) is powerful but closed,
expensive and hard to reproduce outside the lab that ran it. OpenTCAD aims to be
the open alternative, built on four commitments:

- **Reproducible.** A whole simulation is a plain-text file (structure, process
  recipe, mesh, physics, analyses) that anyone can check, rerun and diff. Sweeps
  are files too.
- **Honest about what it knows.** Every number is either given by you, taken from
  a cited source, or flagged as an assumption. Missing information is an error or
  a question, never a silent default. Physics features land with a quantitative
  check against an analytic result or a published reference.
- **Extensible.** New process steps, device analyses, physics models, metrics,
  materials and dopant tables plug in from outside the core, through the same
  registries the built-ins use.
- **Open and local-first.** Apache-2.0. Nothing leaves your machine unless you
  configure it to. The assistant runs on a local open-weights model, and the
  process catalog is private by default.

Longer term, the [open materials platform proposal](docs/open_materials_platform.md)
describes a shared, reviewable catalog of materials, equipment and process
knowledge, with simulation contracts that state exactly what is supported. Its
first slice, a [private local catalog](docs/catalog.md), already exists.

## What works today

| Capability | Status | Evidence |
|---|---|---|
| 2-D structures, meshing, Poisson + drift–diffusion (DEVSIM) | Working | p-n junction within 5 % of Shockley; MOS-cap regimes; NMOS on/off > 10¹⁰ |
| Topography: deposit, isotropic/directional etch, selectivity, Deal–Grove oxidation | Working (geometric models) | Oxide thickness within 5 % of Deal–Grove at 1000–1100 °C; LOCOS demo |
| Doping: Pearson implants (tilt, BF₂, masks), intrinsic and Fair anneal | Working | Tabulated R_p, ΔR_p reproduced to 0.1 %; dose conserved; junction depth mesh-converged |
| Process → device in one call (`run_recipe`) | Working | Deposited MOS cap C–V matches the layered one within 10 % |
| Device physics: Klaassen, Canali, Lombardi, SRH, Auger, avalanche, BGN, Fermi–Dirac, fixed charge | Working; avalanche qualitative | Unit and analytic tests per model |
| Analyses: I–V, C–V, transient, small-signal AC, field snapshots | Working | Equilibrium snapshot matches pn analytics to 1 mV |
| SKY130 NMOS threshold check | Passes (Phase 2 exit) | Vth +14.8 % (max-gm), +7.5 % (100 nA·W/L) vs SkyWater's model card |
| Simulation files, CLI, parameter sweeps | Working | Every point checked before running |
| Plugins (steps, analyses, models, metrics, data) | Working | Entry-point discovery; clashes are errors |
| GUI with a local open-weights assistant | Working | Drafts are checked, repaired and every assumed value flagged |
| Private process catalog | First slice | Import, check, pinned export, runsheets |
| Calibration against PDKs (Phase 3) | Not started | Targets extracted; optimizer pending |

The full record, with numbers and the tests behind them, is in
[docs/validation.md](docs/validation.md). The roadmap is in [PHASES.md](PHASES.md).

## Quick start

```bash
git clone https://github.com/abhineet-agarwal/opentcad.git && cd opentcad
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                 # core: geometry, doping, device solver
pip install -e ".[topography]"          # optional: ViennaLS for deposit / etch / oxidize
pip install -e ".[gui]"                 # optional: Streamlit + Plotly GUI

opentcad check examples/decks/nmos_implanted.yaml     # validate a simulation file
opentcad run   examples/decks/nmos_implanted.yaml     # run it → results JSON (+ field .vtu)
opentcad sweep examples/decks/nmos_tox_sweep.yaml     # Vth and Id vs oxide → table.csv
streamlit run opentcad/gui/app.py                     # GUI; "assistant" page in the sidebar
```

Or from Python:

```python
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.device.solver import DeviceSolver
from opentcad.materials.database import load_material

diode = (Structure(width_um=1.0, name="pn")
         .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
         .add_layer("n", 0.5, Material.SI, doping_Nd=1e17)
         .add_contact("anode", 0.0, 1.0, "p", surface="bottom")
         .add_contact("cathode", 0.0, 1.0, "n", surface="top"))
solver = DeviceSolver(diode.to_meshfield(mesh_size_um=0.05), {"Silicon": load_material("Si")})
V, I = solver.iv_sweep("anode", "cathode", v_start=0.0, v_end=0.7, v_step=0.05)
```

The [quickstart](docs/getting_started.md) runs this diode three ways, and the
[tutorials](docs/tutorials/README.md) go from it to an implanted NMOS and a LOCOS
isolation flow.

## How it fits together

```
 Structure (layers, regions, contacts) ──┐
                                          ├─ run_recipe ──► MeshField ──► DeviceSolver ──► I–V, C–V, AC,
 Recipe (deposit, etch, oxidize,         │   topography     (materials,     (DEVSIM:        transient,
         implant, anneal, plugins…) ─────┘   + meshing      doping, species, Poisson + DD)  field maps
                                             + doping        contacts,
                                                             provenance)
 Simulation file (YAML) = Structure + Recipe + mesh + physics + analyses  →  opentcad check / run / sweep
```

Every module boundary passes a **`MeshField`**: a triangle mesh with per-cell
materials, per-node doping (and per-species concentrations), named contacts and a
process history. Units are fixed everywhere: µm, cm⁻³, K, eV, V.
[docs/architecture.md](docs/architecture.md) covers the design and the extension
points.

## Documentation

The documentation is in [`docs/`](docs/README.md), laid out as a standard library
manual and published with GitBook:

| Section | Pages |
|---|---|
| Getting started | [Installation](docs/installation.md), [Quickstart](docs/getting_started.md) |
| Tutorials | [Five tutorials](docs/tutorials/README.md), from a p-n junction to LOCOS, and an [example gallery](docs/tutorials/examples.md) |
| User guide | [Concepts](docs/concepts.md), [Simulation files](docs/simulation_files.md), [Process](docs/process.md), [Device physics](docs/device_physics.md), [Visualization](docs/visualization.md), [Assistant](docs/assistant.md), [Process catalog](docs/catalog.md) |
| API reference | [Every public class and function](docs/api/README.md), generated from the docstrings |
| Development | [Contributing](docs/contributing.md), [Architecture](docs/architecture.md), [Plugins](docs/plugins.md), [Validation](docs/validation.md), [Releasing](docs/releasing.md) |

## Contributing

OpenTCAD is meant to be continued by others: new materials with citations, physics
models with tests, process steps, analyses, examples, documentation and
calibration data are all welcome. Read the [contributing guide](docs/contributing.md) first. It
covers the development setup, the ground rules (units, the MeshField contract, no
silent defaults, evidence for physics), how to add each kind of extension, and a
list of open problems that make good starting points.

## Applications

[`examples/microrobot/`](examples/microrobot/README.md) is a separate application
built on OpenTCAD: a PV-powered microrobot controller study combining conceptual
device physics, paper-derived terminal fits, SKY130 circuit blocks and physical
verification of a bias macro. Its scope, evidence and limits are documented there.
The [executed notebook](submission.ipynb) embeds the full demonstration, and its
[scope and limitations](examples/microrobot/SUBMISSION_STATUS.md) record what
remains unresolved.
The reusable pieces it needed (optical generation and compact PV models) live in
the core ([docs/optical_generation.md](docs/optical_generation.md),
[docs/photovoltaic_compact.md](docs/photovoltaic_compact.md)).

## License

Apache License 2.0; see [LICENSE](LICENSE). OpenTCAD uses several open projects,
each under its own license:
- Gmsh: GPL v2 with a linking exception.
- DEVSIM: Apache 2.0.
- PyVista: MIT.
- ViennaLS: its current wheels (5.8.3, 5.9.0) ship a GPL v3 license file. That's
  why ViennaLS is an optional extra, needed only for topography steps.

## Citation

If you use OpenTCAD in academic work, please cite this repository and the
upstream tools it builds on (DEVSIM, Gmsh, ViennaLS).
