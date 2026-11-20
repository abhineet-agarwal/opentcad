# OpenTCAD

**Open-source process and device simulation for semiconductors, in Python.**

OpenTCAD takes a device from how it is made (layers, deposition, etching,
oxidation, ion implantation, annealing) to how it behaves (I–V, C–V, transient and
small-signal response, and maps of potential, carriers and electric field). It
joins established open tools ([Gmsh](https://gmsh.info),
[ViennaLS](https://viennatools.github.io/), [DEVSIM](https://devsim.org)) through
one data contract, the `MeshField`. Every stage can be inspected, replaced or
extended.

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

## Where to start

| If you want to… | Read |
|---|---|
| Install it | [Installation](installation.md) |
| Run something in five minutes | [Quickstart](getting_started.md) |
| Learn by building devices | [Tutorials](tutorials/README.md) |
| Understand the building blocks | [Concepts](concepts.md) |
| Look up a class or function | [API reference](api/README.md) |
| Contribute | [Contributing](contributing.md) |

## What it does

- **Process:**
  - Conformal deposition; isotropic and directional etching with masks and
    per-material selectivity; Deal–Grove oxidation, including LOCOS.
  - Pearson-profile implants with tilt and mask edges; intrinsic and Fair
    diffusion.
- **Device:**
  - Poisson and drift–diffusion with Klaassen, Canali and Lombardi mobility;
    SRH, Auger, radiative and avalanche terms; bandgap narrowing;
    Fermi–Dirac statistics; Schottky contacts and fixed oxide charge.
  - Analyses: I–V, C–V, transient, small-signal AC and field snapshots.
- **Workflow:**
  - Plain-text simulation files that are checked before they run; parameter
    sweeps with extracted metrics; a bounded design search that meets metric
    targets by varying existing fields of a file.
  - A plugin system; a browser GUI; a drafting assistant on a local open-weights
    model; a private process catalog.

## Principles

- **Reproducible.** A whole simulation is a text file anyone can rerun and diff.
- **Honest.** Every run lists each number it used and the source its file or
  code cites for it; a value without one is listed as such
  ([Sources and provenance](provenance.md)). Missing information is an error, not
  a silent default. Physics is checked against analytic results and published
  references ([Validation](validation.md)).
- **Extensible.** Built-in steps, analyses and models use the same registries
  that plugins do.
- **Local and open.** Apache-2.0. Nothing leaves your machine unless you
  configure it to.

## Status

OpenTCAD is pre-release (0.1.0.dev0) and not yet on PyPI. Phases 0–2 of the
[roadmap](https://github.com/abhineet-agarwal/opentcad/blob/main/PHASES.md) are complete:
- device simulation;
- process topography;
- doping, checked against SkyWater SKY130's NMOS threshold.

Phase 3, calibration against PDK data, is in progress: the calibrated SKY130
NMOS matches the model card's threshold, swing and on-current within 10 %.
[Validation](validation.md) lists what is checked and what is not.
