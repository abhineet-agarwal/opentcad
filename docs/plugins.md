# Extending OpenTCAD with plugins

New process steps, device analyses, materials and dopant tables can be
added without editing OpenTCAD. Everything goes through
`opentcad.plugins`, the same registry the built-ins use.

## Process steps

A step is any class, usually a frozen dataclass. Register a handler for it
with the stage it runs in:

- `stage="topography"` runs `apply(state, step)` on the level-set
  `TopographyState`, before meshing. It needs ViennaLS.
- `stage="doping"` runs `apply(meshfield, step)` on the meshed device, after
  topography. Whatever it returns is recorded in
  `RecipeRunResult.doping_result.steps`.

```python
from dataclasses import dataclass
from opentcad.plugins import register_step
from opentcad.process import run_recipe
from opentcad.process.topography import Recipe

@dataclass(frozen=True)
class UniformAcceptor:
    conc_cm3: float

def apply_uniform_acceptor(mf, step):
    mf.Na = mf.Na + step.conc_cm3
    return {"added_cm3": step.conc_cm3}

register_step(UniformAcceptor, stage="doping", apply=apply_uniform_acceptor,
              describe=lambda s: f"uniform Na +{s.conc_cm3:.1e} cm⁻³")

recipe = Recipe("demo").add(UniformAcceptor(1e16)).implant("As", 30, 1e15)
out = run_recipe(structure, recipe)
```

`Recipe.add` refuses a step class with no registered handler. Steps run in
recipe order within their stage, but every topography step runs before every
doping step, because doping is applied to the final mesh.

In [simulation files](simulation_files.md) a step is written by name,
`{step: uniform_acceptor, conc_cm3: 1e16}`. The name defaults to the class
name in snake_case; pass `name=` to `register_step` to choose another. Only
dataclass steps can be read from and written to files; their fields are
converted using the type hints (numbers, text, materials, tuples).

## Physics models

`register_model(category, name, cls)` makes a model class usable by name in
simulation files. The categories are `mobility`, `recombination`, `bgn` and
`statistics`. The class's constructor arguments become its options, and each
must be stored on the instance under the same name so the model can be
written back out. An option called `base` is read as a nested model of the
same category:
`{model: lombardi, base: klaassen}`.

## Device analyses

An analysis is a function `fn(solver, **kwargs)`. Run it with
`DeviceSolver.run(name, **kwargs)`. The built-ins `"iv"`, `"cv"`,
`"transient"` and `"ac"` are registered the same way. Use the solver's
public building blocks: `solve_equilibrium()`, `set_contact_voltage()`,
`solve_dc()` and `contact_current_A_per_cm()`.

```python
from opentcad.plugins import register_analysis

def forward_current(solver, *, contact, volts):
    out = []
    for v in volts:
        solver.set_contact_voltage(contact, v)
        solver.solve_dc()
        out.append(solver.contact_current_A_per_cm(contact))
    return out

register_analysis("forward_current", forward_current)

solver.solve_equilibrium()
currents = solver.run("forward_current", contact="anode", volts=[0.1, 0.2])
```

Built-in analyses start by bringing every contact back to 0 V. The first
analysis runs the equilibrium solve; later ones ramp the biases down from the
previous operating point. So analyses can be chained on one solver.

## Metrics

A metric turns one analysis result into one number for a
[sweep](simulation_files.md#parameter-sweeps) table:
`register_metric("name", fn)`, where `fn(result, **options) -> float`.
For `iv` and `cv`, `result` is `(x_values, y_values)`. The options in a
sweep file are checked against `fn`'s signature.

## Data folders

```python
from opentcad.plugins import register_data_dir

register_data_dir("dopants", "my_tables/")     # <Sym>_in_Si.yaml, <Sym>_diffusion.yaml
register_data_dir("materials", "my_materials/")  # <Symbol>.yaml, <process>/<Symbol>.yaml
```

- **Dopants:** the implant tables define the species. Each `*_in_Si.yaml`
  needs `species`, `symbol`, `dopant_kind` and a `moments` list, in the same
  format as `opentcad/process/doping/data/B_in_Si.yaml`. Its species name and
  symbol become accepted names in `Recipe.implant`. A matching
  `<Sym>_diffusion.yaml` (with `intrinsic: {D0_cm2s, Ea_eV}`, plus `fair:`
  coefficients for the Fair model) makes it annealable.
- **Materials:** YAMLs follow `opentcad/materials/params/Si.yaml`.
  - Every file needs `permittivity_relative`.
  - A semiconductor (anything without `is_insulator: true`) also needs
    the band structure (`bandgap.Eg_eV_300K`, `electron_affinity_eV`,
    `Nc_cm3_300K`, `Nv_cm3_300K`, `ni_cm3_300K`), the constant mobilities
    and the SRH lifetimes. A missing one is an error, never filled with
    silicon's value.
  - Model-specific blocks (`mobility_klaassen`, `velocity_saturation`,
    the Auger/radiative coefficients, `avalanche`) may be left out. Then
    the models that need them refuse to run on that material, telling you
    what to add. (`MaterialParams.defaulted` lists what was left out;
    model classes declare their needs with `required_params()`.)
  - A new material can only be used for a region if the `Material` enum
    in `opentcad/geometry/formats.py` already has it; adding enum members
    from a plugin is not supported yet.
- **Clashes:** a species, alias or file name defined in two folders raises
  an error. A plugin cannot silently replace built-in data.

## Packaging a plugin

Declare an entry point in the `opentcad.plugins` group. Its target is called
once, with no arguments, the first time OpenTCAD consults a registry:

```toml
# pyproject.toml of your package
[project.entry-points."opentcad.plugins"]
my_plugin = "my_package.opentcad_plugin:register"
```

```python
# my_package/opentcad_plugin.py
from opentcad.plugins import register_step, register_analysis, register_data_dir

def register():
    register_step(...)
    register_analysis(...)
    register_data_dir("dopants", Path(__file__).parent / "data")
```

A plugin that raises while loading produces a `RuntimeWarning`, and OpenTCAD
carries on without it. `opentcad.plugins.plugin_status()` lists every plugin
seen and whether it loaded. Set `OPENTCAD_DISABLE_PLUGINS=1` to skip
entry-point discovery, for example to reproduce a result with the core alone.
