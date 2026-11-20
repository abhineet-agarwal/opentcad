"""
opentcad/materials/database.py — Material parameter loader.

Loads YAML parameter files from opentcad/materials/params/.
Returns pydantic-validated parameter objects for use in device simulation.

Usage:
    from opentcad.materials.database import load_material
    si = load_material("Si")
    print(si.mobility_constant.electron_cm2_Vs)   # 1350.0
    print(si.recombination.tau_n_s)                # 1e-5
    print(si.sources_of("bandgap.Eg_eV_300K"))     # (Source(cite='M. A. Green…'),)

Each file cites its values in ``sources`` and ``cite`` sections (see
``opentcad.provenance``). While a provenance recording is active, reading a
value from a ``MaterialParams`` notes it with its source, so a run's record
lists the values the solver actually used.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr

from opentcad.provenance import Source, active, note_value, parse_sources, sources_for

PARAMS_DIR = Path(__file__).parent / "params"

#: Top-level keys of a material file that are not parameter values.
META_KEYS = ("material", "symbol", "is_insulator", "sources", "cite", "calibration")
#: Keys inside a block that describe a value rather than being one.
NOT_VALUES = ("uncertainty_percent", "uncertainty_abs")

#: The source given to a value the file left to the built-in default.
DEFAULT_SOURCE = Source(
    "OpenTCAD's built-in value for this field (silicon's), in "
    "opentcad/materials/database.py", kind="default",
    note="the material file doesn't give this value")


class _ReadTag:
    """Where a block's values came from, for provenance notes."""
    __slots__ = ("group", "block", "file", "paths", "cited", "defaulted")

    def __init__(self, group, block, file, paths, cited, defaulted):
        self.group, self.block, self.file = group, block, file
        self.paths, self.cited, self.defaulted = paths, cited, defaulted

    def note(self, field: str, value) -> None:
        if field in NOT_VALUES:
            return
        path = self.paths.get(field, f"{self.block}.{field}")
        if any(path == d or path.startswith(d + ".") for d in self.defaulted):
            note_value(self.group, path, value, (DEFAULT_SOURCE,), file=self.file or None)
        else:
            note_value(self.group, path, value, sources_for(self.cited, path),
                       file=self.file or None)


class _Block(BaseModel):
    """A block of material values. While a provenance recording is active,
    reading a value notes it, with the source its file cites."""
    _tag: Optional[_ReadTag] = PrivateAttr(default=None)

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if name[:1] != "_" and active() is not None and name in type(self).model_fields:
            private = object.__getattribute__(self, "__pydantic_private__")
            tag = private.get("_tag") if private else None
            if tag is not None:
                tag.note(name, value)
        return value

    def __eq__(self, other: object) -> bool:
        # Compare values only; the provenance tag differs between two loads
        # of the same file.
        if type(other) is not type(self):
            return NotImplemented
        return (object.__getattribute__(self, "__dict__")
                == object.__getattribute__(other, "__dict__"))

    __hash__ = None   # like any pydantic model

    def items(self) -> list[tuple[str, Any]]:
        """``(name, value)`` for every field, read (and so recorded) the same
        way as ``block.name``. Use it instead of ``vars(block)``, which reads
        the values without recording them."""
        return [(n, getattr(self, n)) for n in type(self).model_fields]


class MobilityConstant(_Block):
    """Constant low-field mobilities [cm²/V/s] and their uncertainty [%].

    Field defaults are silicon's values; the required fields (see
    ``load_material``) must still be given in a material file."""
    electron_cm2_Vs: float = 1350.0
    hole_cm2_Vs: float = 480.0
    uncertainty_percent: float = 5.0


class MobilityKlaassen(_Block):
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


class MobilityLombardi(_Block):
    """Lombardi surface-mobility coefficients (CGS units, see the model).

    Reference: Lombardi et al., IEEE Trans. CAD 7, 1164 (1988); values from
    Darwish et al., IEEE TED 44, 1529 (1997), as in DEVSIM's Klaassen.py
    ``Philips_Surface_Mobility``. Field defaults are silicon's values; a
    material file that omits the block is refused by the ``Lombardi`` model."""
    B_e: float = 3.61e7
    C_e: float = 1.70e4
    tau_e: float = 0.0233
    kappa_e: float = 1.7
    A_e: float = 2.58
    alpha_e: float = 6.85e-21
    eta_e: float = 0.0767
    delta_e: float = 3.58e18
    B_h: float = 1.51e7
    C_h: float = 4.18e3
    tau_h: float = 0.0119
    kappa_h: float = 0.9
    A_h: float = 2.18
    alpha_h: float = 7.82e-21
    eta_h: float = 0.123
    delta_h: float = 4.10e15


class Recombination(_Block):
    """SRH lifetimes [s], trap energy relative to mid-gap [eV], Auger
    coefficients [cm⁶/s] and the radiative coefficient [cm³/s].

    Field defaults are silicon's values; the required fields (see
    ``load_material``) must still be given in a material file."""
    tau_n_s: float = 1e-5       # [s] electron SRH lifetime
    tau_p_s: float = 1e-5       # [s] hole SRH lifetime
    Et_eV: float = 0.0          # trap energy re mid-gap [eV]
    Cn_cm6_per_s: float = 2.8e-31  # Auger electron
    Cp_cm6_per_s: float = 9.9e-32  # Auger hole
    B_rad_cm3_per_s: float = 9.5e-15  # Radiative


class BandStructure(_Block):
    """Band gap [eV], electron affinity [eV], effective densities of states
    and intrinsic density at 300 K [cm⁻³], and relative permittivity.

    Field defaults are silicon's values; the required fields (see
    ``load_material``) must still be given in a material file."""
    Eg_eV_300K: float = 1.124
    electron_affinity_eV: float = 4.05
    Nc_cm3_300K: float = 2.86e19
    Nv_cm3_300K: float = 3.10e19
    ni_cm3_300K: float = 9.65e9
    permittivity_relative: float = 11.7


class VelocitySaturation(_Block):
    """Saturation velocities [cm/s] and Caughey–Thomas exponents β used by
    the ``Canali`` high-field model.

    Field defaults are silicon's values; the required fields (see
    ``load_material``) must still be given in a material file."""
    vsat_e_cm_s: float = 1.02e7
    vsat_h_cm_s: float = 0.72e7
    beta_e: float = 2.0
    beta_h: float = 1.0


class Avalanche(_Block):
    """Impact-ionisation Chynoweth coefficients, Si defaults are the
    van Overstraeten-de Man single-regime fit."""
    a_n_per_cm: float = 7.03e5
    b_n_V_per_cm: float = 1.231e6
    a_p_per_cm: float = 1.582e6
    b_p_V_per_cm: float = 2.036e6


class MaterialParams(BaseModel):
    """Validated material parameter set for one material."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    material: str
    symbol: str
    is_insulator: bool = False   # True for SiO2/Si3N4 (Poisson only, no carriers)
    band_structure: BandStructure = BandStructure()
    mobility_constant: MobilityConstant = MobilityConstant()
    mobility_klaassen: MobilityKlaassen = MobilityKlaassen()
    mobility_lombardi: MobilityLombardi = MobilityLombardi()
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
    #: The file's ``cite`` entries: ``{dotted path: sources}``. A value's
    #: sources are its own entry's or its block's (``sources_of``).
    cited: dict[str, tuple[Source, ...]] = {}

    def sources_of(self, path: str) -> tuple[Source, ...]:
        """The sources the file cites for a value (dotted path as in the
        file, e.g. ``"bandgap.Eg_eV_300K"``); empty if it cites none."""
        return sources_for(self.cited, path)

    def uncited(self) -> list[str]:
        """Dotted paths of the file's values that cite no source."""
        return [p for p in value_paths(self.raw) if not self.sources_of(p)]


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
        process: Optional process variant, e.g. "mylab". If given,
                 ``{process}/{symbol}.yaml`` must exist: a missing variant is
                 an error listing the variants that do exist, never a silent
                 fallback to ``{symbol}.yaml``.

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
    if process:
        yaml_path = find_data_file("materials", f"{process}/{symbol}.yaml")
        if yaml_path is None:
            variants = sorted({f.parent.name for d in data_dirs("materials")
                               for f in d.glob(f"*/{symbol}.yaml")})
            raise FileNotFoundError(
                f"No process variant {process!r} for '{symbol}' (looked for "
                f"{process}/{symbol}.yaml). Variants that exist for {symbol}: "
                f"{variants or 'none'}. Add the file, or drop the variant to "
                f"use {symbol}.yaml.")
    else:
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
    params = params_from_dict(raw, symbol, source=str(yaml_path))
    from opentcad.provenance import note_file
    note_file(yaml_path, params.material)
    return params


def value_paths(raw: dict) -> list[str]:
    """Dotted paths of every parameter value in a material file: numbers
    outside ``META_KEYS``, other than ``NOT_VALUES`` keys."""
    out: list[str] = []

    def walk(node, prefix):
        for k, v in node.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
            elif _is_number(v) and k not in NOT_VALUES:
                out.append(path)

    walk({k: v for k, v in raw.items() if k not in META_KEYS}, "")
    return out


def _is_number(v) -> bool:
    # PyYAML reads 2.86e19 (no exponent sign) as a string; the loader
    # converts it, so it counts as a value here too.
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


#: Where each BandStructure field sits in a material file.
_BAND_PATHS = {"Eg_eV_300K": "bandgap.Eg_eV_300K"}


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
    MaterialFileError instead of silently taking silicon's value. The
    ``sources`` and ``cite`` sections are checked too: a ``cite`` entry for a
    value the file doesn't have, or naming a missing source, is an error.
    A value with no ``cite`` entry loads, and is reported as having no
    source (``MaterialParams.uncited`` and run records). Optional
    model blocks (Klaassen, Lombardi, velocity saturation, Auger/radiative, avalanche)
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

    cited = parse_sources(raw, source or str(raw.get("symbol", symbol)),
                          error=MaterialFileError)
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

    params = MaterialParams(
        material=raw.get("material", symbol),
        symbol=raw.get("symbol", symbol),
        is_insulator=is_insulator,
        band_structure=band,
        mobility_constant=block("mobility_constant", MobilityConstant),
        mobility_klaassen=block("mobility_klaassen", MobilityKlaassen),
        mobility_lombardi=block("mobility_lombardi", MobilityLombardi),
        recombination=block("recombination", Recombination),
        velocity_saturation=block("velocity_saturation", VelocitySaturation),
        avalanche=block("avalanche", Avalanche),
        raw=raw,
        defaulted=defaulted,
        source=source,
        cited=cited,
    )
    for name, info in type(params).model_fields.items():
        if isinstance(info.annotation, type) and issubclass(info.annotation, _Block):
            paths = ({f: _BAND_PATHS.get(f, f) for f in BandStructure.model_fields}
                     if name == "band_structure" else {})
            getattr(params, name)._tag = _ReadTag(
                params.material, name, source, paths, cited, tuple(defaulted))
    return params
