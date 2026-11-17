# Materials

Material parameter files and the objects they load into.

For an introduction, see the [user guide](../device_physics.md#materials). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.materials.database`: `load_material`, `MaterialParams`, `MaterialFileError`, `params_from_dict`, `BandStructure`, `MobilityConstant`, `MobilityKlaassen`, `VelocitySaturation`, `Recombination`, `Avalanche`.

## load_material

```python
opentcad.materials.database.load_material(
    symbol: str,
    process: Optional[str] = None,
) -> MaterialParams
```

Load material parameters by symbol.

**Parameters**

- `symbol`: Material symbol, e.g. "Si", "SiO2", "GaN".
- `process`: Optional process variant, e.g. "mylab". If given, ``{process}/{symbol}.yaml`` must exist: a missing variant is an error listing the variants that do exist, never a silent fallback to ``{symbol}.yaml``.

Files are looked up in the built-in params/ folder and in any folder
added with ``opentcad.plugins.register_data_dir("materials", path)``.
A file present in two folders raises ValueError.

**Returns**

MaterialParams pydantic object.

**Raises**

- `FileNotFoundError`: If no YAML file found for the given symbol.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L150)

## MaterialParams

```python
class opentcad.materials.database.MaterialParams(
    *,
    material: str,
    symbol: str,
    is_insulator: bool = False,
    band_structure: BandStructure = BandStructure(Eg_eV_300K=1.124, electron_affinity_eV=4.05, Nc_cm3_300K=2.86e+19, Nv_cm3_300K=3.1e+19, ni_cm3_300K=9650000000.0, permittivity_relative=11.7),
    mobility_constant: MobilityConstant = MobilityConstant(electron_cm2_Vs=1350.0, hole_cm2_Vs=480.0, uncertainty_percent=5.0),
    mobility_klaassen: MobilityKlaassen = MobilityKlaassen(mu_min_e=52.2, mu_max_e=1417.0, theta1_e=2.285, m_e=1.0, Nref_1_e=9.68e+16, alpha_1_e=0.68, mu_min_h=44.9, mu_max_h=470.5, theta1_h=2.247, m_h=1.258, Nref_1_h=2.2e+17, alpha_1_h=0.719, f_BH=3.828, f_CW=2.459, c_D=0.21, c_A=0.5, Nref_D=4e+20, Nref_A=7.2e+20, r1=0.7643, r2=2.2999, r3=6.5502, r4=2.367, r5=-0.01552, r6=0.6478, s1=0.892333, s2=0.41372, s3=0.19778, s4=0.28227, s5=0.005978, s6=1.80618, s7=0.72169),
    recombination: Recombination = Recombination(tau_n_s=1e-05, tau_p_s=1e-05, Et_eV=0.0, Cn_cm6_per_s=2.8e-31, Cp_cm6_per_s=9.9e-32, B_rad_cm3_per_s=9.5e-15),
    velocity_saturation: VelocitySaturation = VelocitySaturation(vsat_e_cm_s=10200000.0, vsat_h_cm_s=7200000.0, beta_e=2.0, beta_h=1.0),
    avalanche: Avalanche = Avalanche(a_n_per_cm=703000.0, b_n_V_per_cm=1231000.0, a_p_per_cm=1582000.0, b_p_V_per_cm=2036000.0),
    raw: dict = {},
    defaulted: list[str] = [],
    source: str = '',
) -> None
```

Validated material parameter set for one material.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L116)

## MaterialFileError

```python
class opentcad.materials.database.MaterialFileError
```

A material file lacks fields every simulation needs.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L136)

## params_from_dict

```python
opentcad.materials.database.params_from_dict(
    raw: dict,
    symbol: str = '',
    *,
    source: str = '',
) -> MaterialParams
```

Build MaterialParams from a parsed material file.

Fields every simulation needs (REQUIRED_ALL, plus REQUIRED_SEMICONDUCTOR
unless ``is_insulator: true``) must be present: a missing one raises
MaterialFileError instead of silently taking silicon's value. Optional
model blocks (Klaassen, velocity saturation, Auger/radiative, avalanche)
fall back to the code defaults, which are silicon's; every field filled
that way is listed in ``MaterialParams.defaulted`` so the models that
need it can refuse to run.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L211)

## BandStructure

```python
class opentcad.materials.database.BandStructure(
    *,
    Eg_eV_300K: float = 1.124,
    electron_affinity_eV: float = 4.05,
    Nc_cm3_300K: float = 2.86e19,
    Nv_cm3_300K: float = 3.1e19,
    ni_cm3_300K: float = 9.65e09,
    permittivity_relative: float = 11.7,
) -> None
```

Band gap [eV], electron affinity [eV], effective densities of states
and intrinsic density at 300 K [cm⁻³], and relative permittivity.

Field defaults are silicon's values; the required fields (see
``load_material``) must still be given in a material file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L81)

## MobilityConstant

```python
class opentcad.materials.database.MobilityConstant(
    *,
    electron_cm2_Vs: float = 1350.0,
    hole_cm2_Vs: float = 480.0,
    uncertainty_percent: float = 5.0,
) -> None
```

Constant low-field mobilities [cm²/V/s] and their uncertainty [%].

Field defaults are silicon's values; the required fields (see
``load_material``) must still be given in a material file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L22)

## MobilityKlaassen

```python
class opentcad.materials.database.MobilityKlaassen(
    *,
    mu_min_e: float = 52.2,
    mu_max_e: float = 1417.0,
    theta1_e: float = 2.285,
    m_e: float = 1.0,
    Nref_1_e: float = 9.68e16,
    alpha_1_e: float = 0.68,
    mu_min_h: float = 44.9,
    mu_max_h: float = 470.5,
    theta1_h: float = 2.247,
    m_h: float = 1.258,
    Nref_1_h: float = 2.2e17,
    alpha_1_h: float = 0.719,
    f_BH: float = 3.828,
    f_CW: float = 2.459,
    c_D: float = 0.21,
    c_A: float = 0.5,
    Nref_D: float = 4e20,
    Nref_A: float = 7.2e20,
    r1: float = 0.7643,
    r2: float = 2.2999,
    r3: float = 6.5502,
    r4: float = 2.367,
    r5: float = -0.01552,
    r6: float = 0.6478,
    s1: float = 0.892333,
    s2: float = 0.41372,
    s3: float = 0.19778,
    s4: float = 0.28227,
    s5: float = 0.005978,
    s6: float = 1.80618,
    s7: float = 0.72169,
) -> None
```

Klaassen unified low-field bulk mobility coefficients.

Reference: Klaassen, Solid-State Electron. 35, 953 (1992).
Default values are the published Si fit. If the YAML omits this
block, these defaults are used.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L32)

## VelocitySaturation

```python
class opentcad.materials.database.VelocitySaturation(
    *,
    vsat_e_cm_s: float = 1.02e07,
    vsat_h_cm_s: float = 7.2e06,
    beta_e: float = 2.0,
    beta_h: float = 1.0,
) -> None
```

Saturation velocities [cm/s] and Caughey–Thomas exponents β used by
the ``Canali`` high-field model.

Field defaults are silicon's values; the required fields (see
``load_material``) must still be given in a material file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L95)

## Recombination

```python
class opentcad.materials.database.Recombination(
    *,
    tau_n_s: float = 1e-05,
    tau_p_s: float = 1e-05,
    Et_eV: float = 0.0,
    Cn_cm6_per_s: float = 2.8e-31,
    Cp_cm6_per_s: float = 9.9e-32,
    B_rad_cm3_per_s: float = 9.5e-15,
) -> None
```

SRH lifetimes [s], trap energy relative to mid-gap [eV], Auger
coefficients [cm⁶/s] and the radiative coefficient [cm³/s].

Field defaults are silicon's values; the required fields (see
``load_material``) must still be given in a material file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L67)

## Avalanche

```python
class opentcad.materials.database.Avalanche(
    *,
    a_n_per_cm: float = 703000.0,
    b_n_V_per_cm: float = 1.231e06,
    a_p_per_cm: float = 1.582e06,
    b_p_V_per_cm: float = 2.036e06,
) -> None
```

Impact-ionisation Chynoweth coefficients, Si defaults are the
van Overstraeten-de Man single-regime fit.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/materials/database.py#L107)
