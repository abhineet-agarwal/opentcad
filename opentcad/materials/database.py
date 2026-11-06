"""
opentcad/materials/database.py — Material parameter loader.

Loads YAML parameter files from opentcad/materials/params/.
Returns pydantic-validated parameter objects for use in device simulation.

Usage:
    from opentcad.materials.database import load_material
    si = load_material("Si")
    print(si.mobility_constant.electron_cm2_Vs)   # 1350.0
    print(si.recombination.tau_n_s)                # 1e-5
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel

PARAMS_DIR = Path(__file__).parent / "params"


class MobilityConstant(BaseModel):
    electron_cm2_Vs: float = 1350.0
    hole_cm2_Vs: float = 480.0
    uncertainty_percent: float = 5.0


class MobilityKlaassen(BaseModel):
    """Klaassen unified low-field bulk mobility coefficients.

    Reference: Klaassen, Solid-State Electron. 35, 953 (1992).
    Default values are the published Si fit. If the YAML omits this
    block, these defaults are used."""
    mu_min_e: float = 52.2
    mu_max_e: float = 1417.0
    theta1_e: float = 2.285
    m_e: float = 1.0
    Nref_1_e: float = 9.68e16
    alpha_1_e: float = 0.68

    mu_min_h: float = 44.9
    mu_max_h: float = 470.5
    theta1_h: float = 2.247
    m_h: float = 1.258
    Nref_1_h: float = 2.2e17
    alpha_1_h: float = 0.719

    f_BH: float = 3.828
    f_CW: float = 2.459
    c_D: float = 0.21
    c_A: float = 0.50
    Nref_D: float = 4.0e20
    Nref_A: float = 7.2e20

    r1: float = 0.7643; r2: float = 2.2999; r3: float = 6.5502
    r4: float = 2.3670; r5: float = -0.01552; r6: float = 0.6478

    s1: float = 0.892333; s2: float = 0.41372; s3: float = 0.19778
    s4: float = 0.28227;  s5: float = 0.005978; s6: float = 1.80618
    s7: float = 0.72169


class Recombination(BaseModel):
    tau_n_s: float = 1e-5       # [s] electron SRH lifetime
    tau_p_s: float = 1e-5       # [s] hole SRH lifetime
    Et_eV: float = 0.0          # trap energy re mid-gap [eV]
    Cn_cm6_per_s: float = 2.8e-31  # Auger electron
    Cp_cm6_per_s: float = 9.9e-32  # Auger hole
    B_rad_cm3_per_s: float = 9.5e-15  # Radiative


class BandStructure(BaseModel):
    Eg_eV_300K: float = 1.124
    electron_affinity_eV: float = 4.05
    Nc_cm3_300K: float = 2.86e19
    Nv_cm3_300K: float = 3.10e19
    ni_cm3_300K: float = 9.65e9
    permittivity_relative: float = 11.7


class VelocitySaturation(BaseModel):
    vsat_e_cm_s: float = 1.02e7
    vsat_h_cm_s: float = 0.72e7
    beta_e: float = 2.0
    beta_h: float = 1.0


class Avalanche(BaseModel):
    """Impact-ionisation Chynoweth coefficients, Si defaults are the
    van Overstraeten-de Man single-regime fit."""
    a_n_per_cm: float = 7.03e5
    b_n_V_per_cm: float = 1.231e6
    a_p_per_cm: float = 1.582e6
    b_p_V_per_cm: float = 2.036e6


class MaterialParams(BaseModel):
    """Validated material parameter set for one material."""
    material: str
    symbol: str
    is_insulator: bool = False   # True for SiO2/Si3N4 (Poisson only, no carriers)
    band_structure: BandStructure = BandStructure()
    mobility_constant: MobilityConstant = MobilityConstant()
    mobility_klaassen: MobilityKlaassen = MobilityKlaassen()
    recombination: Recombination = Recombination()
    velocity_saturation: VelocitySaturation = VelocitySaturation()
    avalanche: Avalanche = Avalanche()
    raw: dict = {}   # full YAML dict for advanced access
    #: Fields the file did not give, filled with the code defaults (the
    #: silicon values), as dotted names: "mobility_klaassen" for a whole
    #: missing block, "recombination.Et_eV" for one key. Physics models
    #: check this so they never run on silicon numbers by accident.
    defaulted: list[str] = []
    source: str = ""  # the YAML file it came from


class MaterialFileError(ValueError):
    """A material file lacks fields every simulation needs."""


#: Needed for every material.
REQUIRED_ALL = ("permittivity_relative",)
#: Needed for every semiconductor (insulators run Poisson only).
REQUIRED_SEMICONDUCTOR = (
    "bandgap.Eg_eV_300K", "electron_affinity_eV", "Nc_cm3_300K",
    "Nv_cm3_300K", "ni_cm3_300K", "mobility_constant.electron_cm2_Vs",
    "mobility_constant.hole_cm2_Vs", "recombination.tau_n_s",
    "recombination.tau_p_s")


def load_material(symbol: str, process: Optional[str] = None) -> MaterialParams:
    """Load material parameters by symbol.

    Args:
        symbol: Material symbol, e.g. "Si", "SiO2", "GaN".
        process: Optional process variant, e.g. "hackerfab". If given, loads
                 {process}/{symbol}.yaml with fallback to {symbol}.yaml.

    Files are looked up in the built-in params/ folder and in any folder
    added with ``opentcad.plugins.register_data_dir("materials", path)``.
    A file present in two folders raises ValueError.

    Returns:
        MaterialParams pydantic object.

    Raises:
        FileNotFoundError: If no YAML file found for the given symbol.
    """
    from opentcad.plugins import data_dirs, find_data_file

    # Built-in params/ first, then folders added with
    # opentcad.plugins.register_data_dir("materials", ...). A file name
    # provided by two folders is an error rather than a silent override.
    yaml_path = None
    if process:
        yaml_path = find_data_file("materials", f"{process}/{symbol}.yaml")
    if yaml_path is None:
        yaml_path = find_data_file("materials", f"{symbol}.yaml")

    if yaml_path is None:
        dirs = data_dirs("materials")
        available = sorted({f.stem for d in dirs for f in d.glob("*.yaml")})
        raise FileNotFoundError(
            f"No parameter file found for '{symbol}'"
            f"{f' (process {process!r})' if process else ''}. "
            f"Available: {available}. "
            f"Searched: {[str(d) for d in dirs]}"
        )

    raw = yaml.safe_load(yaml_path.read_text()) or {}
    return params_from_dict(raw, symbol, source=str(yaml_path))


def _has(raw: dict, dotted: str) -> bool:
    node = raw
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def params_from_dict(raw: dict, symbol: str = "", *, source: str = "") -> MaterialParams:
    """Build MaterialParams from a parsed material file.

    Fields every simulation needs (REQUIRED_ALL, plus REQUIRED_SEMICONDUCTOR
    unless ``is_insulator: true``) must be present: a missing one raises
    MaterialFileError instead of silently taking silicon's value. Optional
    model blocks (Klaassen, velocity saturation, Auger/radiative, avalanche)
    fall back to the code defaults, which are silicon's; every field filled
    that way is listed in ``MaterialParams.defaulted`` so the models that
    need it can refuse to run.
    """
    is_insulator = bool(raw.get("is_insulator", False))
    required = REQUIRED_ALL + (() if is_insulator else REQUIRED_SEMICONDUCTOR)
    missing = [k for k in required if not _has(raw, k)]
    if missing:
        where = f" ({source})" if source else ""
        raise MaterialFileError(
            f"material {raw.get('symbol', symbol)!r}{where} is missing "
            f"required field(s) {missing}; give them in the file (OpenTCAD "
            f"does not fill them with silicon's values)")

    defaulted: list[str] = []

    def block(name: str, model):
        """The YAML block ``name`` as ``model``, recording what was filled."""
        given = raw.get(name)
        if not isinstance(given, dict):
            defaulted.append(name)
            return model()
        known = {k: v for k, v in given.items() if k in model.model_fields}
        defaulted.extend(f"{name}.{k}" for k in model.model_fields
                         if k not in known and k != "uncertainty_percent")
        return model(**known)

    def top(key: str, default):
        if key in raw:
            return raw[key]
        defaulted.append(key)
        return default

    bandgap = raw.get("bandgap") if isinstance(raw.get("bandgap"), dict) else {}
    band = BandStructure(
        Eg_eV_300K=bandgap.get("Eg_eV_300K", BandStructure().Eg_eV_300K),
        electron_affinity_eV=top("electron_affinity_eV", 4.05),
        Nc_cm3_300K=top("Nc_cm3_300K", 2.86e19),
        Nv_cm3_300K=top("Nv_cm3_300K", 3.10e19),
        ni_cm3_300K=top("ni_cm3_300K", 9.65e9),
        permittivity_relative=raw["permittivity_relative"],
    )
    if "Eg_eV_300K" not in bandgap:
        defaulted.append("bandgap.Eg_eV_300K")

    return MaterialParams(
        material=raw.get("material", symbol),
        symbol=raw.get("symbol", symbol),
        is_insulator=is_insulator,
        band_structure=band,
        mobility_constant=block("mobility_constant", MobilityConstant),
        mobility_klaassen=block("mobility_klaassen", MobilityKlaassen),
        recombination=block("recombination", Recombination),
        velocity_saturation=block("velocity_saturation", VelocitySaturation),
        avalanche=block("avalanche", Avalanche),
        raw=raw,
        defaulted=defaulted,
        source=source,
    )
