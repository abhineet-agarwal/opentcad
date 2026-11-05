"""
opentcad.io.deck — simulation files.

One YAML (or JSON) document describes a whole run: the structure, the
process recipe, mesh settings, device physics and the analyses to perform.

    deck = load_deck("nmos.yaml")      # checked; DeckError lists every problem
    result = run_deck(deck)            # structure → run_recipe → DeviceSolver → analyses
    save_deck(deck, "copy.yaml")       # writes it back out

Format, version 1 (units as everywhere in OpenTCAD: µm, cm⁻³, K, eV, V)::

    version: 1
    name: nmos_demo
    description: free text            # optional
    structure:
      width_um: 2.0
      layers:                         # bottom first; the first is the substrate
        - {name: body, thickness_um: 0.5, material: Si, doping_Na: 1e17}
        - {name: oxide, thickness_um: 0.005, material: SiO2}
      regions:                        # optional rectangular overrides
        - {name: src, x_um: [0, 0.5], y_um: [0.4, 0.505], material: Si, doping_Nd: 1e20}
      contacts:
        - {name: gate, x_um: [0.5, 1.5], layer: oxide, surface: top, flat_band_shift_V: 0}
    recipe:                           # optional; any registered step
      - {step: implant, species: As, energy_keV: 30, dose_cm2: 1e15, window_x_um: [0, 0.5]}
      - {step: anneal, temperature_C: 1000, time_s: 10}
    mesh: {size_um: 0.03, grid_delta_um: 0.005}       # optional
    device:                           # optional; omit to stop after meshing
      temperature_K: 300
      physics: {mobility: {model: lombardi, base: klaassen}, recombination: [srh]}
      material_process: {Si: hackerfab}               # optional parameter variants
      interface_Qf: [{region: SI, Qf_C_per_cm2: 1e-8, y_um: 0.5}]
    analyses:                         # run in order on one solver
      - {name: idvg, type: iv, anode_contact: gate, cathode_contact: src,
         v_start: 0, v_end: 1.5, v_step: 0.1, hold_contacts: {drain: 0.05},
         measure_contact: drain}

Steps, physics models and analyses are looked up by name in
``opentcad.plugins``, so plugin-provided ones work in files too. Unknown
keys are errors, not ignored, so a misspelt field never silently falls back
to a default. ``1e15`` is read as a number (plain YAML reads it as text).
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from opentcad.geometry.formats import MATERIAL_NAMES, Material
from opentcad.geometry.structure import Structure
from opentcad.process.topography.recipe import Recipe

FORMAT_VERSION = 1

MATERIAL_SYMBOLS = {
    Material.VACUUM: "Vacuum", Material.SI: "Si", Material.SIO2: "SiO2",
    Material.SI3N4: "Si3N4", Material.POLY_SI: "PolySi", Material.AL: "Al",
    Material.PHOTORESIST: "Photoresist", Material.SIGE: "SiGe",
    Material.GAN: "GaN", Material.SIC: "SiC", Material.SUBSTRATE: "Substrate",
}
CONTACT_TYPES = ("ohmic", "schottky")
SURFACES = ("top", "bottom")
_TOP_KEYS = {"version", "name", "description", "structure", "recipe", "mesh",
             "device", "analyses"}


# =============================================================================
# Errors
# =============================================================================
class DeckError(ValueError):
    """Every problem found in a simulation file, each with its location
    (e.g. ``recipe[1].energy_keV``)."""

    def __init__(self, problems: list[tuple[str, str]]):
        self.problems = list(problems)
        super().__init__("\n".join(f"{p}: {m}" if p else m
                                   for p, m in self.problems))


class _Problems:
    def __init__(self):
        self.items: list[tuple[str, str]] = []

    def add(self, path: str, msg: str) -> None:
        self.items.append((path, msg))

    def raise_if_any(self) -> None:
        if self.items:
            raise DeckError(self.items)


_BAD = object()      # conversion failed (already reported)


# =============================================================================
# YAML that reads 1e15 as a number
# =============================================================================
class _Loader(yaml.SafeLoader):
    pass


_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)[eE][-+]?[0-9]+$"),
    list("-+0123456789."))


# =============================================================================
# Materials
# =============================================================================
def material_symbol(material: Material) -> str:
    """The name a file uses for a material (also its parameter-file name)."""
    return MATERIAL_SYMBOLS[Material(material)]


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]", "", s).lower()


_MATERIAL_LOOKUP = {}
for _m in Material:
    for _alias in (MATERIAL_SYMBOLS[_m], _m.name, MATERIAL_NAMES.get(_m, _m.name)):
        _MATERIAL_LOOKUP[_norm(_alias)] = _m


def parse_material(value) -> Material:
    """Material from a file value: ``Si``, ``SiO2``, ``PolySi`` … (case-,
    space- and underscore-insensitive; enum and display names work too)."""
    if isinstance(value, Material):
        return value
    if isinstance(value, str) and _norm(value) in _MATERIAL_LOOKUP:
        return _MATERIAL_LOOKUP[_norm(value)]
    raise ValueError(f"unknown material {value!r}; use one of "
                     f"{list(MATERIAL_SYMBOLS.values())}")


# =============================================================================
# Value conversion driven by type hints
# =============================================================================
def _to_float(v, path, probs):
    if isinstance(v, bool):
        probs.add(path, f"expected a number, got {v!r}")
        return _BAD
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            pass
    probs.add(path, f"expected a number, got {v!r}")
    return _BAD


def _convert(v, hint, path, probs):
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if hint is Any:
        return v
    if origin is Union:
        if v is None and type(None) in args:
            return None
        inner = [a for a in args if a is not type(None)]
        if len(inner) == 1:
            return _convert(v, inner[0], path, probs)
        return v
    if hint is float:
        return _to_float(v, path, probs)
    if hint is int:
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        probs.add(path, f"expected an integer, got {v!r}")
        return _BAD
    if hint is bool:
        if isinstance(v, bool):
            return v
        probs.add(path, f"expected true/false, got {v!r}")
        return _BAD
    if hint is str:
        if isinstance(v, str):
            return v
        probs.add(path, f"expected text, got {v!r}")
        return _BAD
    if hint is Material:
        try:
            return parse_material(v)
        except ValueError as exc:
            probs.add(path, str(exc))
            return _BAD
    if origin in (tuple, typing.Tuple):
        if not isinstance(v, (list, tuple)):
            probs.add(path, f"expected a list, got {v!r}")
            return _BAD
        if args and args[-1] is not Ellipsis:
            if len(v) != len(args):
                probs.add(path, f"expected {len(args)} values, got {len(v)}")
                return _BAD
            out = [_convert(x, a, f"{path}[{i}]", probs)
                   for i, (x, a) in enumerate(zip(v, args))]
        else:
            a = args[0] if args else Any
            out = [_convert(x, a, f"{path}[{i}]", probs) for i, x in enumerate(v)]
        return _BAD if any(o is _BAD for o in out) else tuple(out)
    if origin in (list, typing.List):
        if not isinstance(v, (list, tuple)):
            probs.add(path, f"expected a list, got {v!r}")
            return _BAD
        a = args[0] if args else Any
        out = [_convert(x, a, f"{path}[{i}]", probs) for i, x in enumerate(v)]
        return _BAD if any(o is _BAD for o in out) else out
    if origin in (dict, typing.Dict):
        if not isinstance(v, dict):
            probs.add(path, f"expected a mapping, got {v!r}")
            return _BAD
        ka, va = args if args else (Any, Any)
        out = {}
        for k, x in v.items():
            ck = _convert(k, ka, f"{path}.{k}", probs)
            cv = _convert(x, va, f"{path}.{k}", probs)
            if ck is _BAD or cv is _BAD:
                return _BAD
            out[ck] = cv
        return out
    return v


def _plain(v):
    """Python value → YAML/JSON-friendly value."""
    if isinstance(v, Material):
        return material_symbol(v)
    if isinstance(v, bool) or v is None or isinstance(v, (str, int)):
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {_plain(k): _plain(x) for k, x in v.items()}
    if hasattr(v, "item"):                 # numpy scalar
        return v.item()
    return v


# =============================================================================
# Records with fixed keys
# =============================================================================
def _check_keys(d, path, allowed, required, probs) -> bool:
    if not isinstance(d, dict):
        probs.add(path, f"expected a mapping, got {d!r}")
        return False
    ok = True
    for k in d:
        if k not in allowed:
            probs.add(f"{path}.{k}" if path else str(k),
                      f"unknown field; allowed: {sorted(allowed)}")
            ok = False
    for k in required:
        if k not in d:
            probs.add(path, f"missing required field {k!r}")
            ok = False
    return ok


def _get(d, key, hint, path, probs, default=None):
    if key not in d:
        return default
    return _convert(d[key], hint, f"{path}.{key}", probs)


# =============================================================================
# Structure
# =============================================================================
_LAYER_KEYS = {"name", "thickness_um", "material", "doping_Na", "doping_Nd"}
_REGION_KEYS = {"name", "x_um", "y_um", "material", "doping_Na", "doping_Nd"}
_CONTACT_KEYS = {"name", "x_um", "layer", "surface", "type",
                 "work_function_eV", "flat_band_shift_V"}
_PAIR = typing.Tuple[float, float]


def _structure_from_dict(d, name, probs) -> Optional[Structure]:
    path = "structure"
    if not _check_keys(d, path, {"name", "width_um", "layers", "regions",
                                 "contacts"}, ("width_um", "layers"), probs):
        return None
    width = _get(d, "width_um", float, path, probs)
    s_name = _get(d, "name", str, path, probs, default=name)
    # On a bad width or name keep going with placeholders, so the layers
    # and contacts still get checked; the problems already recorded stop
    # the deck from being returned.
    if width is _BAD or s_name is _BAD:
        width, s_name = 1.0, name
    elif width <= 0:
        probs.add(f"{path}.width_um", "must be > 0")
        width = 1.0
    struct = Structure(width_um=width, name=s_name)

    layers = d.get("layers")
    if not isinstance(layers, list) or not layers:
        probs.add(f"{path}.layers", "expected a non-empty list (bottom first)")
        return None
    for i, ld in enumerate(layers):
        p = f"{path}.layers[{i}]"
        if not _check_keys(ld, p, _LAYER_KEYS, ("name", "thickness_um", "material"),
                           probs):
            continue
        vals = [_get(ld, "name", str, p, probs),
                _get(ld, "thickness_um", float, p, probs),
                _get(ld, "material", Material, p, probs),
                _get(ld, "doping_Na", float, p, probs, 0.0),
                _get(ld, "doping_Nd", float, p, probs, 0.0)]
        if any(v is _BAD for v in vals):
            continue
        add = struct.add_substrate if i == 0 else struct.add_layer
        try:
            add(*vals)
        except ValueError as exc:
            probs.add(p, str(exc))

    for i, rd in enumerate(d.get("regions") or []):
        p = f"{path}.regions[{i}]"
        if not _check_keys(rd, p, _REGION_KEYS, ("name", "x_um", "y_um", "material"),
                           probs):
            continue
        vals = [_get(rd, k, h, p, probs, dflt) for k, h, dflt in (
            ("name", str, None), ("x_um", _PAIR, None), ("y_um", _PAIR, None),
            ("material", Material, None), ("doping_Na", float, 0.0),
            ("doping_Nd", float, 0.0))]
        if any(v is _BAD for v in vals):
            continue
        rname, (x0, x1), (y0, y1), mat, na, nd = vals
        try:
            struct.add_region(rname, x0, x1, y0, y1, mat, doping_Na=na, doping_Nd=nd)
        except ValueError as exc:
            probs.add(p, str(exc))

    layer_names = {ld["name"] for ld in layers
                   if isinstance(ld, dict) and isinstance(ld.get("name"), str)}
    for i, cd in enumerate(d.get("contacts") or []):
        p = f"{path}.contacts[{i}]"
        if not _check_keys(cd, p, _CONTACT_KEYS, ("name", "x_um", "layer"), probs):
            continue
        vals = [_get(cd, k, h, p, probs, dflt) for k, h, dflt in (
            ("name", str, None), ("x_um", _PAIR, None), ("layer", str, None),
            ("surface", str, "top"), ("type", str, "ohmic"),
            ("work_function_eV", Optional[float], None),
            ("flat_band_shift_V", float, 0.0))]
        if any(v is _BAD for v in vals):
            continue
        cname, (x0, x1), layer, surface, ctype, wf, vfb = vals
        if layer not in layer_names:
            probs.add(f"{p}.layer", f"no layer named {layer!r}; layers: "
                                    f"{sorted(layer_names)}")
            continue
        if surface not in SURFACES:
            probs.add(f"{p}.surface", f"must be one of {SURFACES}")
            continue
        if ctype not in CONTACT_TYPES:
            probs.add(f"{p}.type", f"must be one of {CONTACT_TYPES}")
            continue
        if ctype == "schottky" and wf is None:
            probs.add(p, "a schottky contact needs work_function_eV")
            continue
        struct.add_contact(cname, x0, x1, layer, surface=surface,
                           contact_type=ctype, work_function_eV=wf,
                           flat_band_shift_V=vfb)
    return struct


def _structure_to_dict(s: Structure) -> dict:
    layers = []
    for l in s.layers:
        ld = {"name": l.name, "thickness_um": l.thickness_um,
              "material": material_symbol(l.material)}
        if l.doping_Na:
            ld["doping_Na"] = l.doping_Na
        if l.doping_Nd:
            ld["doping_Nd"] = l.doping_Nd
        layers.append(ld)
    out = {"name": s.name, "width_um": s.width_um, "layers": layers}
    regions = []
    for r in s.regions:
        rd = {"name": r.name, "x_um": [r.x_start, r.x_end],
              "y_um": [r.y_start, r.y_end], "material": material_symbol(r.material)}
        if r.doping_Na:
            rd["doping_Na"] = r.doping_Na
        if r.doping_Nd:
            rd["doping_Nd"] = r.doping_Nd
        regions.append(rd)
    if regions:
        out["regions"] = regions
    contacts = []
    for c in s.contacts:
        cd = {"name": c.name, "x_um": [c.x_start, c.x_end], "layer": c.layer_name,
              "surface": c.surface}
        if c.contact_type != "ohmic":
            cd["type"] = c.contact_type
        if c.work_function_eV is not None:
            cd["work_function_eV"] = c.work_function_eV
        if c.flat_band_shift_V:
            cd["flat_band_shift_V"] = c.flat_band_shift_V
        contacts.append(cd)
    if contacts:
        out["contacts"] = contacts
    return _plain(out)


# =============================================================================
# Recipe
# =============================================================================
def _step_from_dict(d, path, probs):
    from opentcad.plugins import step_class
    if not isinstance(d, dict) or "step" not in d:
        probs.add(path, "expected a mapping with a 'step' field")
        return None
    try:
        cls = step_class(d["step"])
    except KeyError as exc:
        probs.add(f"{path}.step", exc.args[0])
        return None
    if not dataclasses.is_dataclass(cls):
        probs.add(f"{path}.step", f"step {d['step']!r} ({cls.__name__}) is not "
                                  f"a dataclass, so it can't be read from files")
        return None
    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
    required = [n for n, f in fields.items()
                if f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING]
    if not _check_keys(d, path, set(fields) | {"step"}, required, probs):
        return None
    kwargs = {}
    for k, v in d.items():
        if k == "step":
            continue
        cv = _convert(v, hints.get(k, Any), f"{path}.{k}", probs)
        if cv is _BAD:
            return None
        kwargs[k] = cv
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        probs.add(path, str(exc))
        return None


def _step_to_dict(step) -> dict:
    from opentcad.plugins import step_handler
    handler = step_handler(step)
    if not dataclasses.is_dataclass(step):
        raise TypeError(f"{type(step).__name__} is not a dataclass; it can't "
                        f"be written to a simulation file")
    out = {"step": handler.name}
    for f in dataclasses.fields(step):
        if not f.init:
            continue
        v = getattr(step, f.name)
        if f.default is not dataclasses.MISSING and v == f.default:
            continue
        out[f.name] = _plain(v)
    return out


# =============================================================================
# Physics
# =============================================================================
def _init_params(cls) -> dict[str, inspect.Parameter]:
    params = inspect.signature(cls.__init__).parameters
    return {n: p for n, p in params.items()
            if n != "self" and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}


def _model_from_spec(category, spec, path, probs):
    from opentcad.plugins import get_model
    if isinstance(spec, str):
        name, opts = spec, {}
    elif isinstance(spec, dict) and "model" in spec:
        name = spec["model"]
        opts = {k: v for k, v in spec.items() if k != "model"}
    else:
        probs.add(path, f"expected a model name or {{model: name, ...}}, got {spec!r}")
        return None
    try:
        cls = get_model(category, name)
    except KeyError as exc:
        probs.add(path, exc.args[0])
        return None
    params = _init_params(cls)
    kwargs = {}
    for k, v in opts.items():
        if k not in params:
            probs.add(f"{path}.{k}", f"unknown option for {name!r}; "
                                     f"allowed: {sorted(params)}")
            return None
        if k == "base":
            v = _model_from_spec(category, v, f"{path}.base", probs)
            if v is None:
                return None
        kwargs[k] = v
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        probs.add(path, str(exc))
        return None


def _model_to_spec(category, model):
    from opentcad.plugins import model_name
    name = model_name(category, model)
    opts = {}
    for k, p in _init_params(type(model)).items():
        v = getattr(model, k)
        if k == "base":
            opts[k] = _model_to_spec(category, v)
        elif p.default is inspect.Parameter.empty or v != p.default:
            opts[k] = _plain(v)
    return {"model": name, **opts} if opts else name


def _physics_from_dict(d, path, probs):
    from opentcad.device.physics import PhysicsConfig
    if not _check_keys(d, path, {"mobility", "recombination", "bgn", "statistics"},
                       (), probs):
        return None
    kwargs = {}
    for cat in ("mobility", "bgn", "statistics"):
        if cat in d:
            m = _model_from_spec(cat, d[cat], f"{path}.{cat}", probs)
            if m is None:
                return None
            kwargs[cat] = m
    if "recombination" in d:
        rec = d["recombination"]
        if not isinstance(rec, list):
            probs.add(f"{path}.recombination", "expected a list of models")
            return None
        models = [_model_from_spec("recombination", r, f"{path}.recombination[{i}]",
                                   probs) for i, r in enumerate(rec)]
        if any(m is None for m in models):
            return None
        kwargs["recombination"] = models
    return PhysicsConfig(**kwargs)


def _physics_to_dict(phys) -> dict:
    return {"mobility": _model_to_spec("mobility", phys.mobility),
            "recombination": [_model_to_spec("recombination", r)
                              for r in phys.recombination],
            "bgn": _model_to_spec("bgn", phys.bgn),
            "statistics": _model_to_spec("statistics", phys.statistics)}


# =============================================================================
# Device and analyses
# =============================================================================
@dataclass
class DeviceSettings:
    """Device-solver settings from a file's ``device`` section."""
    temperature_K: float = 300.0
    physics: Any = None                         # PhysicsConfig
    material_process: dict[str, str] = field(default_factory=dict)
    interface_Qf: list[dict] = field(default_factory=list)
    interface_Qf_width_um: float = 0.005


@dataclass
class AnalysisSpec:
    """One entry of a file's ``analyses`` list."""
    name: str
    type: str
    args: dict


def _device_from_dict(d, path, probs) -> Optional[DeviceSettings]:
    from opentcad.device.physics import PhysicsConfig
    if not _check_keys(d, path, {"temperature_K", "physics", "material_process",
                                 "interface_Qf", "interface_Qf_width_um"}, (), probs):
        return None
    out = DeviceSettings()
    t = _get(d, "temperature_K", float, path, probs, 300.0)
    w = _get(d, "interface_Qf_width_um", float, path, probs, 0.005)
    mp = _get(d, "material_process", typing.Dict[str, str], path, probs, {})
    if _BAD in (t, w) or mp is _BAD:
        return None
    for sym in mp:
        try:
            parse_material(sym)
        except ValueError as exc:
            probs.add(f"{path}.material_process.{sym}", str(exc))
            return None
    out.temperature_K, out.interface_Qf_width_um = t, w
    out.material_process = {material_symbol(parse_material(k)): v
                            for k, v in mp.items()}
    if "physics" in d:
        phys = _physics_from_dict(d["physics"], f"{path}.physics", probs)
        if phys is None:
            return None
        out.physics = phys
    else:
        out.physics = PhysicsConfig()
    for i, q in enumerate(d.get("interface_Qf") or []):
        p = f"{path}.interface_Qf[{i}]"
        if not _check_keys(q, p, {"region", "Qf_C_per_cm2", "y_um"},
                           ("region", "Qf_C_per_cm2", "y_um"), probs):
            return None
        region = _get(q, "region", str, p, probs)
        qf = _get(q, "Qf_C_per_cm2", float, p, probs)
        y = _get(q, "y_um", float, p, probs)
        if _BAD in (region, qf, y):
            return None
        out.interface_Qf.append({"region": region, "Qf_C_per_cm2": qf, "y_um": y})
    return out


def _device_to_dict(dev: DeviceSettings) -> dict:
    out = {"temperature_K": dev.temperature_K,
           "physics": _physics_to_dict(dev.physics)}
    if dev.material_process:
        out["material_process"] = dict(dev.material_process)
    if dev.interface_Qf:
        out["interface_Qf"] = [dict(q) for q in dev.interface_Qf]
        out["interface_Qf_width_um"] = dev.interface_Qf_width_um
    return _plain(out)


def _analysis_from_dict(d, i, path, probs) -> Optional[AnalysisSpec]:
    from opentcad.plugins import get_analysis
    if not isinstance(d, dict) or "type" not in d:
        probs.add(path, "expected a mapping with a 'type' field")
        return None
    atype = d["type"]
    try:
        fn = get_analysis(atype)
    except KeyError as exc:
        probs.add(f"{path}.type", exc.args[0])
        return None
    name = d.get("name", f"{atype}_{i}")
    if not isinstance(name, str):
        probs.add(f"{path}.name", f"expected text, got {name!r}")
        return None
    args = {k: v for k, v in d.items() if k not in ("type", "name")}
    sig = inspect.signature(fn)
    if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        allowed = list(sig.parameters)[1:]          # drop the solver
        unknown = [k for k in args if k not in allowed]
        for k in unknown:
            probs.add(f"{path}.{k}", f"unknown argument for {atype!r}; "
                                     f"arguments: {allowed}")
        try:
            sig.bind(None, **{k: v for k, v in args.items() if k not in unknown})
        except TypeError as exc:
            probs.add(path, f"{atype}: {exc}")
            return None
        if unknown:
            return None
    return AnalysisSpec(name=name, type=atype, args=args)


# =============================================================================
# The deck
# =============================================================================
@dataclass
class Deck:
    """A checked simulation file. Edit the objects freely; ``to_dict`` and
    ``save_deck`` write the current state back out."""
    name: str
    structure: Structure
    recipe: Recipe = field(default_factory=Recipe)
    description: str = ""
    mesh_size_um: float = 0.03
    grid_delta_um: float = 0.005
    device: Optional[DeviceSettings] = None
    analyses: list[AnalysisSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict = {"version": FORMAT_VERSION, "name": self.name}
        if self.description:
            out["description"] = self.description
        out["structure"] = _structure_to_dict(self.structure)
        if len(self.recipe):
            out["recipe"] = [_step_to_dict(s) for s in self.recipe]
        out["mesh"] = {"size_um": self.mesh_size_um,
                       "grid_delta_um": self.grid_delta_um}
        if self.device is not None:
            out["device"] = _device_to_dict(self.device)
        if self.analyses:
            out["analyses"] = [{"name": a.name, "type": a.type, **_plain(a.args)}
                               for a in self.analyses]
        return out


def deck_from_dict(data: dict) -> Deck:
    """Check and build a Deck from parsed YAML/JSON. Raises DeckError
    listing every problem found."""
    probs = _Problems()
    if not isinstance(data, dict):
        raise DeckError([("", f"a simulation file must be a mapping, got "
                              f"{type(data).__name__}")])
    _check_keys(data, "", _TOP_KEYS, ("structure",), probs)
    version = data.get("version", FORMAT_VERSION)
    if version != FORMAT_VERSION:
        probs.add("version", f"unsupported version {version!r}; this OpenTCAD "
                             f"reads version {FORMAT_VERSION}")
    name = data.get("name", "deck")
    if not isinstance(name, str) or not name:
        probs.add("name", "expected non-empty text")
        name = "deck"
    description = data.get("description", "")
    if not isinstance(description, str):
        probs.add("description", "expected text")
        description = ""

    struct = (_structure_from_dict(data["structure"], name, probs)
              if "structure" in data else None)

    recipe = Recipe(name)
    steps = data.get("recipe") or []
    if not isinstance(steps, list):
        probs.add("recipe", "expected a list of steps")
        steps = []
    for i, sd in enumerate(steps):
        step = _step_from_dict(sd, f"recipe[{i}]", probs)
        if step is not None:
            recipe.add(step)

    mesh_size, grid_delta = 0.03, 0.005
    if "mesh" in data:
        md = data["mesh"]
        if _check_keys(md, "mesh", {"size_um", "grid_delta_um"}, (), probs):
            ms = _get(md, "size_um", float, "mesh", probs, mesh_size)
            gd = _get(md, "grid_delta_um", float, "mesh", probs, grid_delta)
            for k, v in (("size_um", ms), ("grid_delta_um", gd)):
                if v is not _BAD and v <= 0:
                    probs.add(f"mesh.{k}", "must be > 0")
            if ms is not _BAD:
                mesh_size = ms
            if gd is not _BAD:
                grid_delta = gd

    device = None
    if data.get("device") is not None:
        device = _device_from_dict(data["device"], "device", probs)

    analyses: list[AnalysisSpec] = []
    raw = data.get("analyses") or []
    if not isinstance(raw, list):
        probs.add("analyses", "expected a list")
        raw = []
    if raw and data.get("device") is None:
        probs.add("analyses", "analyses need a 'device' section")
    indexed: list[tuple[int, AnalysisSpec]] = []     # keep file positions
    for i, ad in enumerate(raw):
        spec = _analysis_from_dict(ad, i, f"analyses[{i}]", probs)
        if spec is not None:
            indexed.append((i, spec))
    analyses = [a for _, a in indexed]
    seen = set()
    for i, a in indexed:
        if a.name in seen:
            probs.add(f"analyses[{i}].name", f"duplicate analysis name {a.name!r}")
        seen.add(a.name)

    # Names the file declares (a contact with its own problem still counts,
    # so it doesn't cause a second, misleading error here).
    sd = data.get("structure")
    raw_contacts = sd.get("contacts") if isinstance(sd, dict) else None
    if not isinstance(raw_contacts, list):
        raw_contacts = []
    contact_names = {c["name"] for c in raw_contacts
                     if isinstance(c, dict) and isinstance(c.get("name"), str)}
    for i, a in indexed:
        for k, v in a.args.items():
            if (k.endswith("contact") or k in ("terminal", "reference")) \
                    and isinstance(v, str) and struct and v not in contact_names:
                probs.add(f"analyses[{i}].{k}", f"no contact named {v!r}; "
                                                f"contacts: {sorted(contact_names)}")
            if k in ("hold_contacts", "bias_schedule") and isinstance(v, dict) and struct:
                for c in v:
                    if c not in contact_names:
                        probs.add(f"analyses[{i}].{k}.{c}", f"no contact named {c!r}")

    probs.raise_if_any()
    return Deck(name=name, structure=struct, recipe=recipe,
                description=description, mesh_size_um=mesh_size,
                grid_delta_um=grid_delta, device=device, analyses=analyses)


def load_deck(source) -> Deck:
    """Read and check a simulation file (``.yaml``/``.yml``/``.json`` path),
    or a dict already parsed. Raises DeckError listing every problem."""
    if isinstance(source, dict):
        return deck_from_dict(source)
    path = Path(source)
    text = path.read_text()
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.load(text, Loader=_Loader)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise DeckError([("", f"{path.name} is not valid "
                              f"{'JSON' if path.suffix.lower() == '.json' else 'YAML'}: "
                              f"{exc}")]) from None
    return deck_from_dict(data)


class _Dumper(yaml.SafeDumper):
    """Short lists of plain values on one line (``x_um: [0.0, 0.5]``)."""


def _represent_list(dumper, data):
    flow = all(not isinstance(x, (list, dict)) for x in data) and len(data) <= 8
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data,
                                     flow_style=flow)


_Dumper.add_representer(list, _represent_list)


def dumps_deck(deck: Deck) -> str:
    """The deck as YAML text."""
    return yaml.dump(deck.to_dict(), Dumper=_Dumper, sort_keys=False,
                     allow_unicode=True)


def save_deck(deck: Deck, path) -> Path:
    """Write ``deck`` as YAML (or JSON for a ``.json`` path)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(deck.to_dict(), indent=2) + "\n")
    else:
        path.write_text(dumps_deck(deck))
    return path


# =============================================================================
# Running
# =============================================================================
@dataclass
class DeckResult:
    """What ``run_deck`` produced."""
    meshfield: Any
    recipe_result: Any
    analyses: dict[str, Any] = field(default_factory=dict)

    def analyses_to_dict(self) -> dict:
        """Analysis results as JSON-friendly values (complex → [re, im])."""
        def conv(v):
            if isinstance(v, complex):
                return [v.real, v.imag]
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            if isinstance(v, dict):
                return {str(k): conv(x) for k, x in v.items()}
            if hasattr(v, "tolist"):
                return conv(v.tolist())
            return v
        return {k: conv(v) for k, v in self.analyses.items()}


def run_deck(deck: Deck, *, log=None) -> DeckResult:
    """Run a deck: build the structure, run the recipe (topography, mesh,
    doping), then — if the deck has a ``device`` section — create one
    DeviceSolver and run the analyses on it in order."""
    import numpy as np

    from opentcad.process import run_recipe

    say = log or (lambda msg: None)
    say(f"recipe: {len(deck.recipe)} step(s), mesh {deck.mesh_size_um} µm")
    rr = run_recipe(deck.structure, deck.recipe,
                    grid_delta_um=deck.grid_delta_um,
                    mesh_size_um=deck.mesh_size_um)
    mf = rr.meshfield
    say(f"meshfield: {mf.n_cells} cells, {mf.n_points} nodes")
    result = DeckResult(meshfield=mf, recipe_result=rr)
    if deck.device is None:
        return result

    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material

    dev = deck.device
    params = {}
    for mid in np.unique(np.asarray(mf.material_ids)):
        mat = Material(int(mid))
        sym = material_symbol(mat)
        params[MATERIAL_NAMES.get(mat, mat.name)] = load_material(
            sym, process=dev.material_process.get(sym))
    ac_terminals = sorted({a.args["terminal"] for a in deck.analyses
                           if a.type == "ac" and "terminal" in a.args})
    qf = {q["region"]: (q["Qf_C_per_cm2"], q["y_um"]) for q in dev.interface_Qf}
    solver = DeviceSolver(mf, params, temperature_K=dev.temperature_K,
                          physics=dev.physics,
                          interface_Qf_C_per_cm2=qf or None,
                          interface_Qf_width_um=dev.interface_Qf_width_um,
                          ac_terminals=ac_terminals or None)
    try:
        for a in deck.analyses:
            say(f"analysis {a.name} ({a.type})")
            result.analyses[a.name] = solver.run(a.type, **a.args)
    finally:
        solver.close()
    return result
