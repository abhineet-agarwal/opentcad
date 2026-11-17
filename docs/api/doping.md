# Implant and anneal

Ion implantation, diffusion and the dopant data tables.

For an introduction, see the [user guide](../process.md#doping). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.process.topography.recipe`: `Implant`, `Anneal`.

## Implant

```python
class opentcad.process.topography.recipe.Implant(
    species: str,
    energy_keV: float,
    dose_cm2: float,
    window_x_um: Optional[Tuple[float, float]] = None,
    tilt_deg: float = 0.0,
    profile: str = 'pearson',
) -> None
```

Ion-implant step. Doping, not topography — plays no role in
level-set evolution, picked up by the doping dispatcher after the
topography state has been meshed.

**Parameters**

- `species`: 'boron' / 'B' / 'phosphorus' / 'P' / 'arsenic' / 'As' / 'BF2' (case-insensitive).
- `energy_keV`: ion energy in keV. The dopant energy (for BF₂, ≈ 0.225 × this) must fall inside the tabulated range.
- `dose_cm2`: dose per unit area in cm⁻². Typical S/D is 1e14-1e16.
- `window_x_um`: (x0, x1) mask opening in µm, or None for a blanket implant. Mask edge is softened by the lateral straggle in the kernel.
- `tilt_deg`: beam tilt from the wafer normal in the cross-section plane, |tilt| < 89°. Positive leans toward +x with depth.
- `profile`: "pearson" (all four tabulated moments, default) or "gaussian" (Rp and ΔRp only).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L218)

## Anneal

```python
class opentcad.process.topography.recipe.Anneal(
    temperature_C: float,
    time_s: float,
    species_Nd: str = 'As',
    species_Na: str = 'B',
    model: str = 'intrinsic',
) -> None
```

Thermal anneal — diffusion of every dopant field at the given
temperature for the given time.

Each implanted species (tracked ``C_&lt;species>`` field) diffuses with
its own coefficients; doping that is only in Nd / Na uses
species_Nd / species_Na. See opentcad.process.doping.anneal.

**Parameters**

- `temperature_C`: anneal temperature in °C.
- `time_s`: duration in seconds.
- `species_Nd`: species whose coefficients drive the untracked Nd remainder. Default "As".
- `species_Na`: same for the untracked Na remainder. Default "B".
- `model`: "intrinsic" (Gaussian convolution with D_i; exact below n_i) or "fair" (concentration-coupled Fair model; needed at S/D-level doping).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/topography/recipe.py#L178)

Import from `opentcad.process.doping`: `apply_doping_recipe`, `DopingRecipeResult`, `apply_implant`, `ImplantResult`, `apply_anneal`, `AnnealResult`, `apply_anneal_fair`, `FairAnnealResult`, `moments_for`, `PearsonMoments`, `pearson_density`, `diffusivity_intrinsic`, `available_species`, `canonicalize_species`, `dopant_kind`, `resolve_implant_species`, `surface_height_function`.

## apply_doping_recipe

```python
opentcad.process.doping.apply_doping_recipe(
    mf: MeshField,
    recipe: Recipe,
) -> DopingRecipeResult
```

Walk *recipe* and apply every doping step to *mf* in place.

Topography-stage steps (deposit / etch / oxidize, or plugin steps
registered as topography) are skipped — `simulate()` handled them
upstream and they are already baked into the MeshField's geometry.
Each doping-stage step runs through its registered handler
(``opentcad.plugins``); an unregistered step type raises TypeError.

Returns a `DopingRecipeResult` listing what fired, in order. An empty
recipe or a topography-only recipe returns an empty result; the
MeshField is untouched.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/dispatch.py#L56)

## DopingRecipeResult

```python
class opentcad.process.doping.DopingRecipeResult(
    implants: List[ImplantResult] = list(),
    anneals: List[Union[AnnealResult, FairAnnealResult]] = list(),
    steps: List[Tuple[Any, Any]] = list(),
) -> None
```

What apply_doping_recipe did, in order. Useful for the GUI's
sidebar summary and for debugging a long multi-step recipe.

``implants`` and ``anneals`` hold the built-in results; ``steps``
holds ``(step, result)`` for every doping-stage step in order,
plugin steps included.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/dispatch.py#L33)

### DopingRecipeResult.n_implants

```python
property DopingRecipeResult.n_implants: int
```

Number of implants applied.

### DopingRecipeResult.n_anneals

```python
property DopingRecipeResult.n_anneals: int
```

Number of anneals applied.

## apply_implant

```python
opentcad.process.doping.apply_implant(
    mf: MeshField,
    species: str,
    energy_keV: float,
    dose_cm2: float,
    window_x_um: Optional[Tuple[float, float]] = None,
    *,
    target: Material = Material.SI,
    sigma_lat_frac: float = 0.7,
    tilt_deg: float = 0.0,
    profile: str = 'pearson',
) -> ImplantResult
```

Apply an ion implant to *mf* in place; return a diagnostic record.

**Parameters**

- `mf`: MeshField to dope. Mutated in place — the ``C_&lt;dopant>`` species field and Nd or Na get the implant contribution added.
- `species`: "boron" / "B" / "phosphorus" / "P" / "arsenic" / "As" / "BF2" (case-insensitive).
- `energy_keV`: ion energy in keV. The dopant energy (for BF₂, about 0.225 × this) must lie in the tabulated range — the moment lookup refuses to extrapolate.
- `dose_cm2`: dose per unit wafer area in cm⁻². Typical S/D implants are 1e14-1e16 cm⁻².
- `window_x_um`: optional (x0, x1) mask opening in µm, measured at the surface. None is a blanket implant.
- `target`: substrate material the tables apply to. Only Si is tabulated today.
- `sigma_lat_frac`: σ_lat as a fraction of ΔRp. Default 0.7.
- `tilt_deg`: beam tilt from the wafer normal in the cross-section plane, |tilt| < 89°. Positive leans toward +x with depth.
- `profile`: "pearson" (default; all four moments) or "gaussian" (Rp and ΔRp only).

**Returns**

ImplantResult diagnostic record.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/implant.py#L143)

## ImplantResult

```python
class opentcad.process.doping.ImplantResult(
    species: str,
    energy_keV: float,
    dose_cm2: float,
    moments: PearsonMoments,
    sigma_lat_um: float,
    window_x_um: Optional[Tuple[float, float]],
    added_to: str,
    integrated_added_per_unit_width: float,
    ion: str = '',
    dopant_energy_keV: float = 0.0,
    profile: str = 'pearson',
    tilt_deg: float = 0.0,
) -> None
```

Diagnostic summary returned alongside the in-place mutation.

`species` is the dopant atom written to the mesh; `ion` is what was
implanted (they differ for BF₂). `moments` are looked up at
`dopant_energy_keV`.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/implant.py#L65)

## apply_anneal

```python
opentcad.process.doping.apply_anneal(
    mf: MeshField,
    temperature_C: float,
    time_s: float,
    *,
    species_Nd: str = 'As',
    species_Na: str = 'B',
    grid_resolution_um: float = 0.005,
) -> AnnealResult
```

Diffuse every dopant field in place per intrinsic Fick's law.

Each field is resampled onto a Cartesian grid, convolved with a
Gaussian of σ = √(2 D t) using its own species' D, and resampled back
to the mesh. Mutates the MeshField in place; returns an AnnealResult.

**Parameters**

- `mf`: MeshField with doping to anneal. Nd and Na in cm⁻³.
- `temperature_C`: anneal temperature in °C.
- `time_s`: anneal duration in seconds.
- `species_Nd`: species whose D drives the untracked donor remainder (Nd not covered by ``C_&lt;species>`` fields). Default "As".
- `species_Na`: same for the untracked acceptor remainder. Default "B".
- `grid_resolution_um`: Cartesian-grid cell size for the convolution. Should resolve both the mesh and the Gaussian kernel — default 5 nm matches the ViennaLS grid.

**Returns**

AnnealResult with the diffusivities and σ actually applied.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/anneal.py#L240)

## AnnealResult

```python
class opentcad.process.doping.AnnealResult(
    temperature_C: float,
    time_s: float,
    species_Nd: str,
    species_Na: str,
    D_Nd_cm2_s: float,
    D_Na_cm2_s: float,
    sigma_Nd_um: float,
    sigma_Na_um: float,
    grid_cell_um: float,
    species_D_cm2_s: dict = dict(),
    species_sigma_um: dict = dict(),
    model: str = 'intrinsic',
) -> None
```

Diagnostic record returned alongside the in-place mutation.

`D_Nd_cm2_s` / `sigma_Nd_um` (and the Na pair) describe the untracked
remainder, i.e. all of Nd / Na when no species fields are tracked.
`species_sigma_um` / `species_D_cm2_s` give the same per tracked
species. σ(t) = √(2 D t).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/anneal.py#L132)

## apply_anneal_fair

```python
opentcad.process.doping.apply_anneal_fair(
    mf: MeshField,
    temperature_C: float,
    time_s: float,
    *,
    species_Nd: str = 'P',
    species_Na: str = 'B',
    grid_resolution_um: float = 0.01,
    stability_factor: float = 0.2,
    max_sub_steps: int = 200000,
) -> FairAnnealResult
```

Concentration-coupled Fair anneal via explicit FTCS sub-stepping.

Unlike :func:`apply_anneal` — a single Gaussian convolution, correct
only for constant-D diffusion — this integrates ∂C/∂t = ∇·(D_eff ∇C)
explicitly for every dopant field, with D_eff rebuilt each step from
the current doping and the Fair series:

```
D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)²                (donors)
D_eff = D_i + D⁺·(p/n_i) + D⁺⁺·(p/n_i)²                (acceptors)
```

n is taken as the total donor concentration and p as the total
acceptor concentration, so every donor species feels the electrons
from all of them. This reproduces the phosphorus high-concentration
enhancement (D⁻⁻ dominates at n ≫ n_i) and arsenic's much smaller
one. Coefficients come from
``opentcad/process/doping/data/{P,As,B}_diffusion.yaml``.

Numerical details:
  * Explicit Euler on a Cartesian grid, Neumann (no-flux) walls.
  * Harmonic-mean D at cell faces — preserves flux across sharp

```
concentration gradients where D jumps by orders of magnitude.
```

  * Sub-step dt = ``stability_factor`` · dx² / max(D_eff) over all

```
fields. The 2D explicit scheme is stable only for factors ≤ 0.25
(von Neumann; also the positivity bound here), so the factor is
restricted to (0, 0.25], default 0.2. D_eff is re-evaluated each
sub-step.
```

  * Capped at ``max_sub_steps`` iterations as a runaway guard.

Untracked Nd / Na (not covered by ``C_&lt;species>`` fields) diffuse
with ``species_Nd`` / ``species_Na``'s coefficients. Mutates the
MeshField in place. Use :func:`apply_anneal` when the profile stays
well below n_i at the anneal temperature — it is exact there and
much cheaper.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/anneal.py#L401)

## FairAnnealResult

```python
class opentcad.process.doping.FairAnnealResult(
    temperature_C: float,
    time_s: float,
    species_Nd: str,
    species_Na: str,
    n_sub_steps: int,
    dt_sub_mean_s: float,
    D_i_Nd_cm2_s: float,
    D_eff_Nd_peak_cm2_s: float,
    D_i_Na_cm2_s: float,
    D_eff_Na_peak_cm2_s: float,
    grid_cell_um: float,
    species_D_eff_peak_cm2_s: dict = dict(),
    model: str = 'fair',
) -> None
```

Diagnostic record for a concentration-coupled Fair anneal.

`D_i_Nd` / `D_eff_Nd_peak` (and the Na pair) use species_Nd's /
species_Na's coefficients; `species_D_eff_peak_cm2_s` gives the peak
effective diffusivity per tracked species — the one-number summary of
how much concentration enhancement mattered.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/anneal.py#L320)

## moments_for

```python
opentcad.process.doping.moments_for(
    species: str,
    energy_keV: float,
    target: Material = Material.SI,
) -> PearsonMoments
```

Interpolate Pearson-IV moments for the given species and energy.

Uses log-linear interpolation on energy (implant range vs. energy is
close to a power law across our tabulated range, so log-interp is
accurate to well under 5% between points).

Extrapolation is refused — raise ValueError if energy falls outside
the tabulated range for that species. We'd rather force the caller
to add a data point than silently return nonsense.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L163)

## PearsonMoments

```python
class opentcad.process.doping.PearsonMoments(
    Rp_um: float,
    dRp_um: float,
    gamma: float,
    beta: float,
    dopant_kind: str,
) -> None
```

The four moments of an implant depth distribution.

Rp and dRp are in µm; γ and β are dimensionless. `dopant_kind` is
'donor' or 'acceptor' — set from the YAML per species.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L89)

## pearson_density

```python
opentcad.process.doping.pearson_density(moments: PearsonMoments, n_samples: int = 20001)
```

Sample the Pearson-system depth density for *moments*.

Returns ``(depth_um, density_per_um)``: the curve has mean Rp,
standard deviation ΔRp, skewness γ and kurtosis β, and integrates to
1 over depth (including any part at negative depth — the caller
decides what happens above the surface). Arrays are read-only and
cached per moment set.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L279)

## diffusivity_intrinsic

```python
opentcad.process.doping.diffusivity_intrinsic(
    species: str,
    T_K: float,
    target: Material = Material.SI,
) -> float
```

Intrinsic Fick diffusivity D_i(T) in cm²/s per Arrhenius fit.

Only the intrinsic term; `fair_diffusivity_components` adds the
concentration-dependent ones.

**Parameters**

- `species`: 'B' / 'boron' / 'P' / 'phosphorus' / 'As' / 'arsenic'.
- `T_K`: anneal temperature in Kelvin.
- `target`: substrate material. Only Si has tables today.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/anneal.py#L65)

## available_species

```python
opentcad.process.doping.available_species() -> List[str]
```

Canonical names of every implant species with a range table, from
the built-in data and registered data folders, sorted.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L129)

## canonicalize_species

```python
opentcad.process.doping.canonicalize_species(name: str) -> str
```

Normalize a species name to the canonical lowercase form. Raises
ValueError with a clear message if no implant table defines it.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L117)

## dopant_kind

```python
opentcad.process.doping.dopant_kind(species: str) -> str
```

'donor' or 'acceptor' for an atomic dopant species.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L135)

## resolve_implant_species

```python
opentcad.process.doping.resolve_implant_species(
    name: str,
    energy_keV: float,
) -> Tuple[str, str, float]
```

Map an implanted ion to (ion, dopant, dopant_energy_keV).

Atomic species pass through unchanged. A molecular ion such as BF₂
becomes its dopant atom at the mass-scaled energy. Co-implanted
fluorine (and its effect on diffusion) is not modelled.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/pearson_iv.py#L148)

## surface_height_function

```python
opentcad.process.doping.surface_height_function(
    mf: MeshField,
) -> Callable[[np.ndarray], np.ndarray]
```

Return y_surface(x) [µm]: the top of the meshed stack at each x.

Built from the mesh's boundary edges: on every interval between
boundary-vertex x positions the topmost non-vertical edge is the
surface, so steps and trench floors are exact. Falls back to a flat
max(y) surface for non-triangle meshes.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/process/doping/implant.py#L86)
