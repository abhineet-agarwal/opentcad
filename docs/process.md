# Process simulation

A **`Recipe`** is an ordered list of process steps. It is pure data: it can be
printed, pickled, written to a [simulation file](simulation_files.md) and checked
without any backend. `run_recipe(structure, recipe)` executes it:

1. Topography steps (deposit, etch, oxidize) run on ViennaLS level sets.
2. The result is meshed with Gmsh, and the structure's doping, contacts and
   metadata are carried onto it.
3. Doping steps (implant, anneal) run on that device mesh.

```python
from opentcad.process import run_recipe
from opentcad.process.topography import Recipe

recipe = (Recipe("flow")
    .deposit(Material.SIO2, 0.01)
    .etch(0.15, model="directional", window_x_um=(0.35, 0.65))
    .oxidize(1000, 600, ambient="dry")
    .implant("As", 30, 1e15, window_x_um=(0.0, 0.5))
    .anneal(1000, 10, model="fair"))
out = run_recipe(structure, recipe, mesh_size_um=0.03)
out.meshfield            # ready for DeviceSolver
out.topography_state     # the level-set stack (None for doping-only recipes)
out.doping_result        # what each implant/anneal did
```

All topography steps run before all doping steps, because doping is applied to the
final mesh. A well implant followed by an oxidation is therefore not modelled in
that order (see [Limits](#limits)). Plugin steps join either stage
([plugins.md](plugins.md)).

## Topography

| Step | Model |
|---|---|
| `deposit(material, thickness_um)` | Conformal: Minkowski dilation of the surface (ViennaLS `GeometricAdvect`) |
| `etch(depth_um)` | Blanket isotropic erosion |
| `etch(depth_um, window_x_um=(x0, x1))` | Masked isotropic etch: the quarter-circle undercut, by Lax–Friedrichs advection |
| `etch(depth_um, model="directional", direction=…, sidewall_ratio=…)` | RIE-style: the rate follows how squarely the surface faces the beam; near-vertical walls at `sidewall_ratio=0` |
| `etch(…, rates={Material.SI3N4: 1.0, Material.SIO2: 0.02})` | Per-material selectivity, e.g. a nitride etch that stops on oxide |
| `oxidize(T_C, t_s, ambient="dry"/"wet", window_x_um=…, bird_beak_length_um=…)` | Deal–Grove linear-parabolic growth with Arrhenius A, B on ⟨100⟩ Si; per-column moving boundary (Si consumed by 0.44·Δx, oxide grows up 0.56·Δx); optional mask with an exponential bird's beak |

A deep masked etch through a stacked structure punches through the top layer and
continues into the one beneath, using multi-level-set advection.

The etch and deposition models are **geometric**: they describe shape evolution,
not plasma chemistry or flux. ViennaPS would add physical models (plasma etch,
ion-beam etch, flux-based deposition) as an optional backend. That is on the
roadmap but blocked on macOS: ViennaPS 4.6.1 and 4.7.0 segfault when loaded, as
both packages bundle their own VTK and OpenMP. The Recipe and mesh-bridge
boundaries are designed so it can slot in.

## Doping

### Implant

`Recipe.implant(species, energy_keV, dose_cm2, window_x_um=None, tilt_deg=0, profile="pearson")`

- **Depth profile:** the Pearson curve matched to all four tabulated moments
  (R_p, ΔR_p, γ, β), from the Pearson equation directly. Several table rows are
  type I or VI, not IV; boron above ~30 keV, for example, is type I. Tables for
  B, P and As in Si cover 10–200 keV, log-interpolated in energy, with no
  extrapolation. `profile="gaussian"` keeps only R_p and ΔR_p.
- **Lateral straggle and masks:** Gaussian lateral straggle (σ_lat = 0.7·ΔR_p),
  integrated over the beam geometry. Mask windows get the erf edge blur, and dose
  per unit wafer area is conserved at any tilt (|tilt| < 89°).
- **Surface:** depth is measured from the local top of the meshed stack, column
  by column, so implants into trenches and over LOCOS land where they should.
- **BF₂:** treated as boron at the mass-scaled energy, E·11/49. Co-implanted
  fluorine isn't modelled.
- **Checked early:** an unknown species, or an energy outside its table, is an
  error when the step is created, before anything runs.

Each implant writes a per-species field `C_<species>` (e.g. `C_arsenic`) as well as
the `Nd`/`Na` totals the device solver reads. More species are added by dropping
`<Sym>_in_Si.yaml` and `<Sym>_diffusion.yaml` into a data folder
([plugins.md](plugins.md#data-folders)).

### Anneal

`Recipe.anneal(temperature_C, time_s, model="intrinsic" | "fair")`. Every tracked
species diffuses with its own coefficients.

- **`intrinsic`:** diffusion with the Arrhenius D_i(T). It is exact while the
  doping stays below n_i(T).
- **`fair`:** Fair's concentration-coupled diffusivity,
  D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)² for donors (D⁺, D⁺⁺ with p/n_i for
  acceptors). n and p are the total donor and acceptor concentrations. It
  captures the concentration-enhanced spreading at S/D-level doping.
- **Where dopants move:** only in silicon, the one material with diffusion
  data. Every other material, and empty space such as an etched trench, is a
  no-flux wall, and doping there is left as it is. Segregation into the oxide
  is not modelled.
- **How:** when silicon fills the mesh's bounding box, the intrinsic model is a
  Gaussian convolution on a Cartesian grid and Fair is stepped explicitly on
  it. Otherwise, as in any MOS structure, both diffuse on the mesh's silicon
  triangles with linear finite elements (backward Euler), so the walls sit
  exactly on the silicon boundary.
- **Dose:** both kernels conserve each species' dose in the silicon.

## From structure to processed device

`topography_to_meshfield` meshes the level-set stack and knows only materials.
`run_recipe` then carries the `Structure` over (`opentcad.process.structure_transfer`):

- **Doping:** a node takes a layer's or region's doping only where that layer or
  region contains it *and* one of the node's cells still has its material.
  Silicon left after an etch or oxidation keeps its doping. Oxide grown where
  silicon was consumed, and deposited material, get none. Regions override layers.
- **Contacts:**
  - A `top` contact sits on the final top surface over its x-range, since a
    deposit may now cover the layer it was declared on.
  - A `bottom` contact sits on the wafer floor.
  - If the material under a contact changed between semiconductor and insulator,
    a warning says so. An ohmic contact becomes a gate, or the reverse.
  - The material found under each contact is recorded in
    `meshfield.metadata["contact_materials"]`.
- **Regions:** the level-set stack has layers only, so a region's *material*
  override can't apply after topography. A warning says so; its doping still
  applies where its material matches. On the doping-only path (no topography
  steps), regions work fully.
- **Meshing:** neighbouring materials share their interface nodes, so the device
  solver couples them.

## Limits

These are not modelled yet. Each is a known, documented gap rather than something
silently approximated:

- **Oxidation physics:**
  - Oxidation-enhanced diffusion (needs interstitial injection from oxidation).
  - Transient-enhanced diffusion (needs an implant-damage model).
  - Dopant segregation at Si/SiO₂ (needs cited segregation coefficients).
- **Screen oxides:** material above the silicon is crossed with silicon stopping
  data, since no SiO₂ range tables are shipped.
- **Step order:** doping interleaved with later topography (implants run after
  meshing).
- **Etch geometry:**
  - Angled directional etches.
  - Re-entrant (overhanging) profiles; the mesh bridge needs a polygon walker.
- **LOCOS:** 2-D coupled O₂ diffusion; the bird's beak is a heuristic
  exponential.
- **Physical etch and deposition models** (the ViennaPS backend).
- **Channeling.**

The [contributing guide](contributing.md#good-places-to-start) lists the ones that
make good contributions.
