# Process recipes and topography

Recipes, topography steps on ViennaLS, meshing the result, and run_recipe.

For an introduction, see the [user guide](../process.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.process`: `run_recipe`, `RecipeRunResult`.

## run_recipe

```python
opentcad.process.run_recipe(
    structure,
    recipe: Recipe,
    *,
    grid_delta_um: float = 0.005,
    mesh_size_um: float = 0.03,
) -> RecipeRunResult
```

Run *recipe* against *structure*, end to end. Returns a
MeshField with material_id, Nd, Na, and contacts all populated.

**Parameters**

- `structure`: initial geometry (substrate + layers + regions + contacts). Any `doping_Na` / `doping_Nd` on substrates or regions is honoured as the starting doping; implants in the recipe add on top.
- `recipe`: ordered process-flow DSL. Topography steps are played through ViennaLS; doping steps are deferred to the meshed device.
- `grid_delta_um`: level-set grid spacing for topography steps. Default 5 nm — fine enough for Phase 1 LOCOS, cheap enough for interactive use.
- `mesh_size_um`: Gmsh characteristic element size for the device mesh. Default 30 nm — matches Phase 0 exit-criterion MOSFET.

**Returns**

`RecipeRunResult` carrying the finished MeshField plus the
intermediate TopographyState (if any) and the DopingRecipeResult.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/__init__.py#L56)

## RecipeRunResult

```python
class opentcad.process.RecipeRunResult(
    meshfield: MeshField,
    topography_state: Optional[TopographyState] = None,
    doping_result: DopingRecipeResult = DopingRecipeResult(),
) -> None
```

Everything the orchestrator produced, in one object. The
MeshField is the main artefact; the rest is diagnostic.

`topography_state` is None when the recipe is doping-only (in
which case the MeshField came straight from Structure.to_meshfield
instead of from the level-set stack).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/__init__.py#L37)

Import from `opentcad.process.topography`: `Recipe`, `Deposit`, `Etch`, `Oxidize`, `simulate`, `topography_to_meshfield`, `TopographyState`, `Layer`, `initial_state_from_structure`, `extract_surface_polyline`.

## Recipe

```python
class opentcad.process.topography.Recipe(
    name: str = 'recipe',
    steps: List[Step] = list(),
) -> None
```

Ordered process flow. Chainable; each method returns self.

**Example**

```python
recipe = (Recipe("locos_lite")
          .deposit(Material.SIO2, 0.05)
          .etch(0.02))
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L274)

### Recipe.deposit

```python
Recipe.deposit(
    material: Material,
    thickness_um: float,
    model: str = 'conformal',
) -> Recipe
```

Append a ``Deposit`` step: ``thickness_um`` of ``material`` over the
current surface. Returns the recipe.

### Recipe.etch

```python
Recipe.etch(
    depth_um: float,
    model: str = 'isotropic',
    window_x_um: Optional[Tuple[float, float]] = None,
    mask_material: Optional[Material] = None,
    direction: Tuple[float, float] = (0.0, -1.0),
    sidewall_ratio: float = 0.0,
    rates: Optional[Dict[Material, float]] = None,
    default_rate: float = 0.0,
) -> Recipe
```

Append an ``Etch`` step; the models, masks and selectivity options
are described under ``Etch``. Returns the recipe.

### Recipe.oxidize

```python
Recipe.oxidize(
    temperature_C: float,
    time_s: float,
    ambient: str = 'dry',
    window_x_um: Optional[Tuple[float, float]] = None,
    bird_beak_length_um: float = 0.0,
) -> Recipe
```

Append a Deal–Grove ``Oxidize`` step. Returns the recipe.

### Recipe.implant

```python
Recipe.implant(
    species: str,
    energy_keV: float,
    dose_cm2: float,
    window_x_um: Optional[Tuple[float, float]] = None,
    tilt_deg: float = 0.0,
    profile: str = 'pearson',
) -> Recipe
```

Append an ``Implant`` step. The species and energy are checked
now, so an unknown species or an energy outside its table raises
ValueError here rather than at run time. Returns the recipe.

### Recipe.anneal

```python
Recipe.anneal(
    temperature_C: float,
    time_s: float,
    species_Nd: str = 'As',
    species_Na: str = 'B',
    model: str = 'intrinsic',
) -> Recipe
```

Append an ``Anneal`` step (``model`` is ``"intrinsic"`` or
``"fair"``). Returns the recipe.

### Recipe.add

```python
Recipe.add(step) -> Recipe
```

Append any registered step — the way to use plugin steps
(see ``opentcad.plugins.register_step``). Raises TypeError for a
step class with no registered handler.

### Recipe.summary

```python
Recipe.summary() -> str
```

The recipe as text: a header line, then one numbered line per step.

## Deposit

```python
class opentcad.process.topography.Deposit(
    material: Material,
    thickness_um: float,
    model: str = 'conformal',
) -> None
```

Grow *thickness_um* of *material* on top of the current surface.

The `model` selects the deposition physics:
  - "conformal": Minkowski-dilation of the surface by *thickness*.

```
Textbook isotropic CVD / ALD.
```

The DSL keeps the door open for "directional" (PVD-style, follows a
supplied direction vector) and "selective" (only on a subset of the
exposed materials) — those will be added when we wire the ViennaPS
process models.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L21)

## Etch

```python
class opentcad.process.topography.Etch(
    depth_um: float,
    model: str = 'isotropic',
    window_x_um: Optional[Tuple[float, float]] = None,
    mask_material: Optional[Material] = None,
    direction: Tuple[float, float] = (0.0, -1.0),
    sidewall_ratio: float = 0.0,
    rates: Optional[Dict[Material, float]] = None,
    default_rate: float = 0.0,
) -> None
```

Remove *depth_um* of the top material.

Models:
  - "isotropic": recedes along the local surface normal (wet etch,

```
downstream plasma). With `window_x_um=None` this is a uniform
Minkowski erosion; with a window it becomes a curved-under-mask
profile solved by the ViennaLS Lax-Friedrichs advection scheme.
```

  - "directional": RIE-style. Rate scales with how strongly the

```
local surface normal faces the incoming ion beam, so horizontal
tops recede at full rate and sidewalls barely move — giving
near-vertical trench walls. `direction` is the beam propagation
direction (etch travels along it); default is straight down.
```

  - `sidewall_ratio`: fraction of the full etch rate that a purely-

```
lateral surface still receives (models chemical isotropy on top
of the directional ion flux). 0.0 = pure directional.
```

Mask forms:
  * `window_x_um=(x0, x1)`: photolithography-style opening.
  * `mask_material`: reserved for a hardmask level-set (multi-layer

```
initial stack). Not yet honored.
```

Material selectivity:
  * `rates`: optional {Material: relative_rate} map. When set, each

```
material in the stack is etched at `rates[material] * depth_um`
and materials absent from the map are etched at
`default_rate * depth_um`. Default = 0.0 → "stop on anything
not listed" semantics. Classic use: strip nitride, stop on
oxide, with `rates={Material.SI3N4: 1.0, Material.SIO2: 0.02}`.
```

  * When `rates is None` every material etches at the same rate

```
(backward-compat for Phase 1 scripts).
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L48)

## Oxidize

```python
class opentcad.process.topography.Oxidize(
    temperature_C: float,
    time_s: float,
    ambient: str = 'dry',
    window_x_um: Optional[Tuple[float, float]] = None,
    bird_beak_length_um: float = 0.0,
) -> None
```

Deal-Grove thermal oxidation of the exposed Si-SiO2 stack.

Grows SiO2 on top of every exposed Si column following the linear-
parabolic law x_ox^2 + A x_ox = B (t + tau). The Si-SiO2 boundary
moves down by 0.44*dx_grown; the SiO2 top moves up by 0.56*dx_grown.

**Parameters**

- `temperature_C`: oxidation temperature in °C.
- `time_s`: oxidation duration in seconds.
- `ambient`: 'dry' (O2) or 'wet' (H2O). Sets Deal-Grove coefficients per Plummer/Deal fits for <100> Si.
- `window_x_um`: optional (x0, x1). Only columns inside the window oxidize at full rate. Modelling a nitride hardmask over the rest of the wafer for LOCOS.
- `bird_beak_length_um`: characteristic feathering length outside the window (heuristic stand-in for lateral O2 diffusion under the nitride edge). 0.0 = perfectly sharp mask; typical LOCOS value ≈ pad-oxide thickness (30-100 nm).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L129)

## simulate

```python
opentcad.process.topography.simulate(
    structure,
    recipe: Recipe,
    grid_delta_um: float = 0.01,
) -> TopographyState
```

Run *recipe* on *structure*, returning the final TopographyState.

**Parameters**

- `structure`: opentcad Structure — provides the substrate + width.
- `recipe`: opentcad Recipe — ordered process steps.
- `grid_delta_um`: level-set grid spacing.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/simulator.py#L561)

## topography_to_meshfield

```python
opentcad.process.topography.topography_to_meshfield(
    state: TopographyState,
    mesh_size_um: float = 0.05,
    n_samples: int = 64,
) -> MeshField
```

Convert a TopographyState into a MeshField that the device layer
can consume directly.

**Parameters**

- `state`: final topography stack from simulate().
- `mesh_size_um`: gmsh characteristic element size [um].
- `n_samples`: number of samples per material-top polyline. 64 is enough for smooth curved surfaces at MVP resolution — bumped up automatically if a layer polyline has more raw nodes.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/mesh_bridge.py#L113)

## TopographyState

```python
class opentcad.process.topography.TopographyState(
    bounds_um: tuple,
    grid_delta_um: float,
    layers: List[Layer] = list(),
) -> None
```

Full topography stack — bottom material first.

**Attributes**

- `bounds_um`: (xmin, xmax, ymin, ymax) simulation window in um.
- `grid_delta_um`: level-set grid spacing in um.
- `layers`: material layers, bottom-to-top.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/simulator.py#L66)

### TopographyState.top

```python
property TopographyState.top: Layer
```

The uppermost layer. Raises RuntimeError if there are none.

## Layer

```python
class opentcad.process.topography.Layer(
    material: Material,
    level_set: viennals.d2.Domain,
) -> None
```

One material layer in the topography stack.

**Attributes**

- `material`: opentcad Material enum for the layer.
- `level_set`: viennals 2D Domain whose implicit surface marks the *top* of this material.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/simulator.py#L53)

## initial_state_from_structure

```python
opentcad.process.topography.initial_state_from_structure(
    structure,
    grid_delta_um: float = 0.01,
) -> TopographyState
```

Build the starting TopographyState from an opentcad Structure.

Supports both single-substrate (add_substrate) and stacked initial
conditions (add_substrate + add_layer). Layers are iterated in
bottom-to-top order — matching Structure's storage — so state.layers
ends up bottom-first, which is also the order ViennaLS expects when
the stack is handed to Advect for multi-material simulation.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/simulator.py#L131)

## extract_surface_polyline

```python
opentcad.process.topography.extract_surface_polyline(
    level_set: viennals.d2.Domain,
) -> tuple[list, list]
```

Extract the (nodes, lines) representation of a 2D level-set's
surface. Returns the raw viennals Mesh contents:
  nodes: list of [x, y, z] (z always 0 in 2D)
  lines: list of [i, j] node indices forming the polyline segments.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/simulator.py#L582)

Import from `opentcad.process.topography.oxidation`: `oxide_thickness`.

## oxide_thickness

```python
opentcad.process.topography.oxidation.oxide_thickness(
    x0_um: float,
    t_s: float,
    T_K: float,
    ambient: str = 'dry',
) -> float
```

Solve Deal-Grove for x_ox(t) given prior thickness x0 [μm].

Returns thickness in μm.

Closed form:

```
x(t) = -A/2 + sqrt( (A/2 + x0)² + B·t )
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/oxidation.py#L136)

Import from `opentcad.process.structure_transfer`: `carry_structure`.

## carry_structure

```python
opentcad.process.structure_transfer.carry_structure(
    structure,
    mf: MeshField,
) -> MeshField
```

Write ``structure``'s doping, contacts and metadata onto ``mf`` (the
mesh of the processed topography) in place, and return it.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/structure_transfer.py#L54)
