# Tutorials

Each tutorial builds one device from scratch and says how to check the result.
They go in order: each one adds one idea to the last.

| Tutorial | You'll learn | Needs |
|---|---|---|
| [1. A p-n junction](01_pn_junction.md) | Structures, meshing, the solver, an I–V sweep, field snapshots | Core |
| [2. A MOS capacitor](02_mos_capacitor.md) | Insulators, gate contacts, C–V | Core |
| [3. An NMOS from a process recipe](03_nmos_from_recipe.md) | Recipes, implants, anneals, `run_recipe`, three-terminal sweeps | Core |
| [4. A trench from a masked etch](04_masked_etch.md) | Topography steps, etch models, the processed mesh | `topography` extra |
| [5. LOCOS field isolation](05_locos.md) | Deal–Grove oxidation, masked oxidation | `topography` extra |

The code on these pages runs as part of the test suite
(`tests/docs/test_docs.py`), so it stays correct as OpenTCAD changes. For more
complete scripts with plots, see the [example gallery](examples.md).
