"""
opentcad.assist.prompt — what the model is told, built from the live
registries so it always matches what the simulation-file checker accepts.

    reference_sheet()   text: fields, units, steps, species, models, analyses
    deck_json_schema()  JSON Schema of a simulation file (for constrained decoding)
    response_schema()   the reply: {deck, assumptions, questions}
    system_prompt()     instructions + reference sheet + example files
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import typing
from typing import Any, Union

from opentcad.geometry.formats import Material
from opentcad.io.deck import (CONTACT_TYPES, MATERIAL_SYMBOLS, SURFACES,
                              example_decks_dir, load_deck)

_EXAMPLES = example_decks_dir()

# Field values a step accepts, where the dataclass only says "str".
_FIELD_ENUMS = {
    ("deposit", "model"): ["conformal"],
    ("etch", "model"): ["isotropic", "directional"],
    ("oxidize", "ambient"): ["dry", "wet"],
    ("implant", "profile"): ["pearson", "gaussian"],
    ("anneal", "model"): ["intrinsic", "fair"],
}

_NUMBER = {"type": "number"}
_STRING = {"type": "string"}


def _materials() -> list[str]:
    return [MATERIAL_SYMBOLS[m] for m in Material if m is not Material.VACUUM]


def _species_ranges() -> dict[str, tuple[str, float, float]]:
    """canonical species → (symbol, min keV, max keV) from the implant tables."""
    from opentcad.process.doping.pearson_iv import _read_yaml, _species_index
    idx = _species_index()
    out = {}
    for name, path in idx.files.items():
        energies = [r["energy_keV"] for r in _read_yaml(path)["moments"]]
        out[name] = (idx.symbols[name], float(min(energies)), float(max(energies)))
    return out


def _species_names() -> list[str]:
    names = []
    for name, (sym, _, _) in _species_ranges().items():
        names += [sym, name]
    return names + ["BF2"]


# ---- type → schema / text ------------------------------------------------------
def _schema_for(hint, enum=None) -> dict:
    if enum:
        return {"type": "string", "enum": list(enum)}
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is Union:
        inner = [a for a in args if a is not type(None)]
        base = _schema_for(inner[0]) if len(inner) == 1 else {}
        return {"anyOf": [base, {"type": "null"}]} if type(None) in args else base
    if hint is float or hint is int:
        return dict(_NUMBER)
    if hint is str:
        return dict(_STRING)
    if hint is bool:
        return {"type": "boolean"}
    if hint is Material:
        return {"type": "string", "enum": _materials()}
    if origin in (tuple, typing.Tuple) and args and args[-1] is not Ellipsis:
        return {"type": "array", "items": _schema_for(args[0]),
                "minItems": len(args), "maxItems": len(args)}
    if origin in (dict, typing.Dict):
        return {"type": "object", "additionalProperties": _schema_for(args[1])
                if len(args) == 2 else {}}
    return {}


def _text_for(hint) -> str:
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is Union:
        inner = [a for a in args if a is not type(None)]
        return (_text_for(inner[0]) if len(inner) == 1 else "any") + \
            (" or null" if type(None) in args else "")
    if hint in (float, int):
        return "number"
    if hint is str:
        return "text"
    if hint is Material:
        return "material"
    if origin in (tuple, typing.Tuple):
        return "[" + ", ".join(_text_for(a) for a in args) + "]"
    if origin in (dict, typing.Dict):
        return "{" + f"{_text_for(args[0])}: {_text_for(args[1])}" + "}"
    return getattr(hint, "__name__", str(hint))


def _annotation_schema(annotation) -> dict:
    """Schema from a solver-method annotation (they are strings here)."""
    a = str(annotation)
    if a in ("float", "int"):
        return dict(_NUMBER)
    if a == "str":
        return dict(_STRING)
    if a.startswith("str") and "None" in a:
        return {"anyOf": [dict(_STRING), {"type": "null"}]}
    if a.startswith("dict"):
        return {"type": "object", "additionalProperties": dict(_NUMBER)}
    return {}


def _record(props: dict, required) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


# ---- schemas ------------------------------------------------------------------
def deck_json_schema() -> dict:
    """JSON Schema of a simulation file built from the registries: only the
    keys, step names, materials, models and analysis arguments that exist."""
    from opentcad import plugins

    pair = {"type": "array", "items": dict(_NUMBER), "minItems": 2, "maxItems": 2}
    material = {"type": "string", "enum": _materials()}
    layer = _record({"name": _STRING, "thickness_um": _NUMBER, "material": material,
                     "doping_Na": _NUMBER, "doping_Nd": _NUMBER},
                    ["name", "thickness_um", "material"])
    region = _record({"name": _STRING, "x_um": pair, "y_um": pair,
                      "material": material, "doping_Na": _NUMBER,
                      "doping_Nd": _NUMBER}, ["name", "x_um", "y_um", "material"])
    contact = _record({"name": _STRING, "x_um": pair, "layer": _STRING,
                       "surface": {"type": "string", "enum": list(SURFACES)},
                       "type": {"type": "string", "enum": list(CONTACT_TYPES)},
                       "work_function_eV": _NUMBER, "flat_band_shift_V": _NUMBER},
                      ["name", "x_um", "layer", "surface"])
    structure = _record({"name": _STRING, "width_um": _NUMBER,
                         "layers": {"type": "array", "items": layer, "minItems": 1},
                         "regions": {"type": "array", "items": region},
                         "contacts": {"type": "array", "items": contact}},
                        ["width_um", "layers", "contacts"])

    steps = []
    for h in plugins.registered_steps().values():
        if not dataclasses.is_dataclass(h.step_type):
            continue
        hints = typing.get_type_hints(h.step_type)
        props = {"step": {"type": "string", "enum": [h.name]}}
        required = ["step"]
        for f in dataclasses.fields(h.step_type):
            if not f.init:
                continue
            enum = _FIELD_ENUMS.get((h.name, f.name))
            if h.name == "implant" and f.name == "species":
                enum = _species_names()
            if h.name == "anneal" and f.name in ("species_Nd", "species_Na"):
                enum = _species_names()[:-1]
            props[f.name] = _schema_for(hints.get(f.name, Any), enum)
            if f.default is dataclasses.MISSING and \
                    f.default_factory is dataclasses.MISSING:
                required.append(f.name)
        steps.append(_record(props, required))

    def model(cat):
        return {"type": "string", "enum": plugins.available_models(cat)}

    axis = {"type": "string", "enum": ["y", "x", "magnitude"]}
    inner_mob = {"anyOf": [model("mobility"), _record(
        {"model": model("mobility"), "base": model("mobility")}, ["model"])]}
    physics = _record({"mobility": {"anyOf": [model("mobility"), _record(
        {"model": model("mobility"), "base": inner_mob, "e_normal_axis": axis},
        ["model"])]},
        "recombination": {"type": "array", "items": model("recombination")},
        "bgn": model("bgn"), "statistics": model("statistics")}, [])
    qf = _record({"region": _STRING, "Qf_C_per_cm2": _NUMBER, "y_um": _NUMBER},
                 ["region", "Qf_C_per_cm2", "y_um"])
    device = _record({"temperature_K": _NUMBER, "physics": physics,
                      "material_process": {"type": "object",
                                           "additionalProperties": dict(_STRING)},
                      "interface_Qf": {"type": "array", "items": qf},
                      "interface_Qf_width_um": _NUMBER}, [])

    analyses = []
    for name in plugins.available_analyses():
        sig = inspect.signature(plugins.get_analysis(name))
        params = list(sig.parameters.values())[1:]
        if any(p.kind == p.VAR_KEYWORD for p in params):
            continue
        props = {"name": _STRING, "type": {"type": "string", "enum": [name]}}
        required = ["name", "type"]
        for p in params:
            props[p.name] = _annotation_schema(p.annotation)
            if p.default is inspect.Parameter.empty:
                required.append(p.name)
        analyses.append(_record(props, required))

    return _record({
        "version": {"type": "integer", "enum": [1]},
        "name": _STRING, "description": _STRING, "structure": structure,
        "recipe": {"type": "array", "items": {"anyOf": steps}},
        "mesh": _record({"size_um": _NUMBER, "grid_delta_um": _NUMBER}, []),
        "device": device,
        "analyses": {"type": "array", "items": {"anyOf": analyses}},
    }, ["version", "name", "structure"])


def response_schema(deck_schema: dict | None = None) -> dict:
    """The model's reply: the file, the values it chose, and questions."""
    return _record({
        "deck": deck_schema or {"type": "object"},
        "assumptions": {"type": "array", "items": _record(
            {"path": _STRING, "value": {}, "reason": _STRING}, ["path", "reason"])},
        "questions": {"type": "array", "items": _STRING},
    }, ["deck", "assumptions", "questions"])


# ---- text ---------------------------------------------------------------------
def reference_sheet() -> str:
    from opentcad import plugins
    out = ["UNITS: lengths µm (1 nm = 0.001 µm), doping cm^-3, implant energy keV, "
           "dose cm^-2, process temperatures °C, times s, device temperature K, "
           "voltages V.",
           f"MATERIALS: {', '.join(_materials())}.",
           f"CONTACTS: surface top|bottom; type {'|'.join(CONTACT_TYPES)} "
           "(a contact on an insulator layer is a gate: metal on oxide).",
           "RECIPE STEPS (field: type = default):"]
    for h in plugins.registered_steps().values():
        if not dataclasses.is_dataclass(h.step_type):
            continue
        hints = typing.get_type_hints(h.step_type)
        parts = []
        for f in dataclasses.fields(h.step_type):
            if not f.init:
                continue
            t = _text_for(hints.get(f.name, Any))
            enum = _FIELD_ENUMS.get((h.name, f.name))
            if enum:
                t = "|".join(enum)
            parts.append(f"{f.name}: {t}" + ("" if f.default is dataclasses.MISSING
                                             else f" = {f.default!r}"))
        out.append(f"  {h.name} ({h.stage}): " + "; ".join(parts))
    ranges = ", ".join(f"{sym} ({name}) {lo:g}–{hi:g} keV"
                       for name, (sym, lo, hi) in _species_ranges().items())
    out.append(f"IMPLANT SPECIES: {ranges}; BF2 (boron at 0.225 × energy).")
    out.append("PHYSICS MODELS: " + "; ".join(
        f"{c}: {', '.join(plugins.available_models(c))}"
        for c in plugins.MODEL_CATEGORIES)
        + ". mobility may be {model: lombardi, base: klaassen}.")
    out.append("ANALYSES (arguments):")
    for name in plugins.available_analyses():
        sig = inspect.signature(plugins.get_analysis(name))
        args = []
        for p in list(sig.parameters.values())[1:]:
            args.append(p.name if p.default is inspect.Parameter.empty
                        else f"{p.name}={p.default!r}")
        out.append(f"  {name}({', '.join(args)})")
    return "\n".join(out)


_INSTRUCTIONS = """\
You write OpenTCAD simulation files: JSON descriptions of a 2-D semiconductor
device cross-section, its process steps, and the simulations to run.

Reply with ONE JSON object: {"deck": <simulation file>, "assumptions": [...],
"questions": [...]}.

Rules:
1. Use the values the user gives, converted to OpenTCAD units.
2. Any value the user did not give is your assumption. List EVERY such value in
   "assumptions" as {"path": "<path in the file>", "value": <value>,
   "reason": "<why this value>"}. Paths look like structure.layers[1].thickness_um
   or recipe[0].dose_cm2. Choose typical textbook values. Never present a guess
   as the user's value.
3. If the request is too vague, still return your best file and ask what you
   need in "questions".
4. Use only the fields, step names, models and analysis arguments in the
   reference below. Unknown keys are rejected.
5. Geometry: x runs left to right from 0 to width_um; y runs bottom to top.
   Layers are listed bottom first; the first is the substrate. A layer's y
   range is the sum of the thicknesses below it. Regions are rectangles that
   replace the material AND doping under them.
6. MOSFET pattern: p-type body layer, thin SiO2 gate-oxide layer on top, a
   gate contact on the oxide's top surface over the channel, and silicon
   source/drain windows (regions through the oxide, material Si, repeating the
   body doping) with source/drain contacts on top. n+ source/drain come from
   arsenic or phosphorus implants into the windows (window_x_um) followed by an
   anneal. Id-Vg: an iv analysis with anode_contact gate, cathode_contact
   source, hold_contacts {"drain": Vds}, measure_contact drain.
7. When editing an existing file, change only what the user asks for and keep
   everything else identical.
"""


def _example(name: str) -> str:
    d = load_deck(_EXAMPLES / name).to_dict()
    return json.dumps(d, separators=(",", ":"))


def system_prompt() -> str:
    parts = [_INSTRUCTIONS, "REFERENCE\n" + reference_sheet()]
    for name in ("pn_diode.yaml", "nmos_implanted.yaml"):
        path = _EXAMPLES / name
        if path.exists():
            parts.append(f"EXAMPLE FILE ({name}):\n{_example(name)}")
    return "\n\n".join(parts)
