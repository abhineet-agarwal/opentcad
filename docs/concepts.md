# Concepts

OpenTCAD has a few building blocks. Once you know them, the rest of the
documentation is detail.

```
Structure ──┐
            ├── run_recipe ──► MeshField ──► DeviceSolver ──► I–V, C–V, AC, transient, field maps
Recipe ─────┘
```

- A **Structure** describes the starting cross-section.
- A **Recipe** lists the process steps applied to it.
- **`run_recipe`** carries out the steps and returns a **MeshField**: the meshed
  device with its materials, doping and contacts.
- A **DeviceSolver** simulates the MeshField electrically.
- A **simulation file** records all of this as text.

## Units

Units are fixed throughout and are never inferred. Names carry the unit where it
could be ambiguous.

| Quantity | Unit | Example name |
|---|---|---|
| Length, position | µm | `thickness_um`, `x_um`, `mesh_size_um` |
| Concentration | cm⁻³ | `doping_Nd`, `Nd`, `C_arsenic` |
| Implant dose | cm⁻² | `dose_cm2` |
| Implant energy | keV | `energy_keV` |
| Process temperature | °C | `temperature_C` |
| Device temperature | K | `temperature_K` |
| Time | s | `time_s` |
| Voltage | V | `v_start`, `flat_band_shift_V` |
| Energy, work function | eV | `work_function_eV` |
| Current, capacitance (2-D) | A/cm, F/cm (per unit width out of the plane) | results of `iv_sweep`, `cv_sweep` |

## Structure

A `Structure` is a 2-D cross-section of a given width, x from 0 to `width_um`.
Layers stack upward from y = 0, the bottom of the substrate.

| Method | Adds |
|---|---|
| `add_substrate(name, thickness_um, material, doping_Na=, doping_Nd=)` | The bottom layer (exactly once, first) |
| `add_layer(name, thickness_um, material, …)` | A layer on top of the stack |
| `add_region(name, x_start, x_end, y_start, y_end, material, …)` | A rectangle that replaces the material *and* doping beneath it; later regions win |
| `add_contact(name, x_start, x_end, layer_name, surface="top" or "bottom", …)` | A named contact on a surface of a layer |
| `to_meshfield(mesh_size_um=…)` | Mesh it (Gmsh, refined at material interfaces) |

A contact is a metal gate if it sits on an insulator. Otherwise it is ohmic by
default, or Schottky with `contact_type="schottky"` and a `work_function_eV`.

## Recipe

A `Recipe` is an ordered list of steps. It is data only: you can print it with
`recipe.summary()`, save it in a simulation file and check it without running
anything.

| Step | Stage | What it does |
|---|---|---|
| `deposit(material, thickness_um)` | topography | Conformal deposition |
| `etch(depth_um, model=…, window_x_um=…, rates=…)` | topography | Isotropic or directional etch, masked or blanket, with per-material rates |
| `oxidize(temperature_C, time_s, ambient=…, window_x_um=…)` | topography | Deal–Grove thermal oxidation, optionally masked |
| `implant(species, energy_keV, dose_cm2, window_x_um=…, tilt_deg=…)` | doping | Pearson-profile ion implant |
| `anneal(temperature_C, time_s, model="intrinsic" or "fair")` | doping | Dopant diffusion |
| `add(step)` | either | Any step registered by a [plugin](plugins.md) |

`run_recipe(structure, recipe)` runs the topography steps on ViennaLS level sets,
meshes the result, carries the structure's doping and contacts across, and then
applies the doping steps to the mesh. With no topography steps, it meshes the
structure directly. [Process simulation](process.md) has the details and limits.

## MeshField

Every stage hands the next a `MeshField`: a triangle mesh plus the fields a
device needs.

```python
mf.material_ids             # Material of each cell
mf.Nd, mf.Na                # total donors / acceptors at each node [cm⁻³]
mf.net_doping               # Nd − Na
mf.species_names()          # implanted species, e.g. ["arsenic", "boron"]
mf.get_species("boron")     # one species [cm⁻³]
mf.get_contact("gate")      # a ContactTag: nodes, type, work function, flat-band shift
mf.process_history          # the steps that made it
mf.save("device")           # device.vtu (mesh, fields) + device.json (contacts, history, metadata)
MeshField.load("device")
```

The `.vtu` file opens in ParaView and other VTK tools.

## Materials

Material parameters live in YAML files, each value with its source.
`load_material("Si")` reads one. The solver takes a mapping from material name to
parameters, covering every material in the mesh:

```python
{"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
```

A missing required parameter is an error, never a silent default.
[Device physics](device_physics.md#materials) says what a file must contain.

## Device solver and analyses

`DeviceSolver(meshfield, materials, temperature_K=300, physics=PhysicsConfig(…))`
solves Poisson and drift–diffusion with DEVSIM. Its analyses are:
- `iv_sweep`, `cv_sweep`, `transient_sweep` and `ac_sweep`;
- `field_snapshot`, which returns the potential and carrier densities as a
  MeshField.

`solver.run(name, **kwargs)` calls any of them, plugin analyses included, by name.
[Device physics](device_physics.md) lists the physics models.

## Simulation files

A YAML or JSON file can describe a whole run: structure, recipe, mesh, device
physics and analyses. Run it with `opentcad run`. Sweep files vary any field and
extract metrics into a table. Every problem in a file is reported, with its
location, before anything runs. See [Simulation files](simulation_files.md).

## Plugins

Steps, analyses, physics models, metrics, materials and dopant tables can all be
added from outside the package, through the registries the built-ins use. See
[Plugins](plugins.md).
