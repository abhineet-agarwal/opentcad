# API reference

Every public class and function, generated from the docstrings. The
[user guide](../concepts.md) explains how the pieces fit together; this
reference is for looking up exact signatures and behaviour.

| Page | Covers | Main entry points |
|---|---|---|
| [Geometry and the MeshField](geometry.md) | Describe a 2-D cross-section, mesh it, and the MeshField every layer passes. | `Structure`, `LayerSpec`, `RegionSpec`, `ContactSpec` |
| [Process recipes and topography](process.md) | Recipes, topography steps on ViennaLS, meshing the result, and run_recipe. | `run_recipe`, `RecipeRunResult`, `Recipe`, `Deposit` |
| [Implant and anneal](doping.md) | Ion implantation, diffusion and the dopant data tables. | `Implant`, `Anneal`, `apply_doping_recipe`, `DopingRecipeResult` |
| [Device solver](device.md) | The DEVSIM drift–diffusion solver, physics configuration, extraction and optics. | `DeviceSolver`, `PhysicsConfig`, `MobilityModel`, `RecombinationModel` |
| [Physics models](models.md) | Mobility, recombination, bandgap-narrowing and carrier-statistics models. | `ConstantMobility`, `Klaassen`, `Canali`, `Lombardi` |
| [Materials](materials.md) | Material parameter files and the objects they load into. | `load_material`, `MaterialParams`, `MaterialFileError`, `params_from_dict` |
| [Calibration](calibrate.md) | Fitting model parameters to reference data, and writing the result as a material file. | `fit`, `Parameter`, `FitResult`, `Evaluation` |
| [Simulation files and sweeps](io.md) | Loading, checking, running and saving simulation files; parameter sweeps. | `load_deck`, `run_deck`, `save_deck`, `dumps_deck` |
| [Provenance](provenance.md) | Where each value a run used came from: sources in data files and run records. | `recording`, `Record`, `Value`, `Source` |
| [Device design](design.md) | Bounded design search over a fixed simulation file, and model-drafted plans. | `load_design`, `run_design`, `variable_paths`, `Design` |
| [Plugin registries](plugins.md) | Registering and looking up process steps, analyses, models, metrics and data folders. | `register_step`, `StepHandler`, `step_handler`, `step_class` |
| [Visualization](viz.md) | Figure data on the mesh, interactive Plotly figures and the colour palette. | `sample_on_grid`, `GridField`, `cells_on_grid`, `cell_values_on_grid` |
| [Process catalog](catalog.md) | Private records of materials, equipment and process flows. | `Catalog`, `import_file`, `ImportResult`, `check_record` |
| [Assistant](assist.md) | Drafting simulation files and catalog records with a local open-weights model. | `draft_deck`, `Draft`, `Flag`, `unstated_values` |
| [Mesh-to-mesh interpolation](bridge.md) | Moving doping fields between separate meshes. | `interpolate_doping_field` |

Units follow the rest of OpenTCAD: lengths in µm, concentrations in cm⁻³,
device temperature in K, process temperatures in °C, energies in eV, voltages
in V. Names carry their unit where it isn't obvious (`thickness_um`,
`dose_cm2`, `temperature_K`).
