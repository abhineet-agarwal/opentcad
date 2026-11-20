"""Generate the API reference pages (docs/api/*.md) from docstrings.

    python tools/gen_api_docs.py            # rewrite docs/api/
    python tools/gen_api_docs.py --check    # exit 1 if docs/api/ is out of date

The pages are plain Markdown, so GitBook, GitHub and any Markdown viewer show
them as they are. What appears is listed in PAGES below: add a name there when
you add a public function or class, and write its docstring in Google style
(``Args:``, ``Returns:``, ``Raises:``). Signatures come from the code, so run
this after changing one. Use Python ≥ 3.14, which reads annotations exactly as
written in the source; the test that checks the pages are current skips on
older versions.
"""
from __future__ import annotations

import argparse
import dataclasses
import enum
import importlib
import inspect
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "api"
SOURCE = "https://github.com/abhineet-agarwal/opentcad/blob/main/"


@dataclasses.dataclass
class Page:
    slug: str
    title: str
    summary: str
    groups: list[tuple[str, list[str]]]
    guide: str = ""            # user-guide page to read first, relative to docs/api/


PAGES = [
    Page("geometry", "Geometry and the MeshField",
         "Describe a 2-D cross-section, mesh it, and the MeshField every layer passes.",
         [("opentcad.geometry.structure", ["Structure", "LayerSpec", "RegionSpec", "ContactSpec"]),
          ("opentcad.geometry.formats", ["MeshField", "ContactTag", "ProcessStep", "Material",
                                         "MATERIAL_NAMES", "MESHFIELD_FORMAT"])],
         guide="../concepts.md"),
    Page("process", "Process recipes and topography",
         "Recipes, topography steps on ViennaLS, meshing the result, and run_recipe.",
         [("opentcad.process", ["run_recipe", "RecipeRunResult"]),
          ("opentcad.process.topography", ["Recipe", "Deposit", "Etch", "Oxidize", "simulate",
                                           "topography_to_meshfield", "TopographyState", "Layer",
                                           "initial_state_from_structure",
                                           "extract_surface_polyline"]),
          ("opentcad.process.topography.oxidation", ["oxide_thickness"]),
          ("opentcad.process.structure_transfer", ["carry_structure"])],
         guide="../process.md"),
    Page("doping", "Implant and anneal",
         "Ion implantation, diffusion and the dopant data tables.",
         [("opentcad.process.topography.recipe", ["Implant", "Anneal"]),
          ("opentcad.process.doping", ["apply_doping_recipe", "DopingRecipeResult", "apply_implant",
                                       "ImplantResult", "apply_anneal", "AnnealResult",
                                       "apply_anneal_fair", "FairAnnealResult", "moments_for",
                                       "PearsonMoments", "pearson_density", "diffusivity_intrinsic",
                                       "available_species", "canonicalize_species", "dopant_kind",
                                       "resolve_implant_species", "surface_height_function"])],
         guide="../process.md#doping"),
    Page("device", "Device solver",
         "The DEVSIM drift–diffusion solver, physics configuration, extraction and optics.",
         [("opentcad.device.solver", ["DeviceSolver"]),
          ("opentcad.device.physics", ["PhysicsConfig", "MobilityModel", "RecombinationModel",
                                       "BandgapNarrowingModel", "StatisticsModel"]),
          ("opentcad.device.extract", ["vth_max_gm", "vth_constant_current"]),
          ("opentcad.device.optical", ["BeerLambert", "current_from_2d"]),
          ("opentcad.device.compact", ["SingleDiodePV", "fit_single_diode"])],
         guide="../device_physics.md"),
    Page("models", "Physics models",
         "Mobility, recombination, bandgap-narrowing and carrier-statistics models.",
         [("opentcad.device.models", ["ConstantMobility", "Klaassen", "Canali", "Lombardi",
                                      "SRH", "Auger", "Radiative", "Avalanche", "NoBGN",
                                      "Slotboom", "Boltzmann", "FermiDirac", "JoyceDixon"])],
         guide="../device_physics.md#physics-models"),
    Page("materials", "Materials",
         "Material parameter files and the objects they load into.",
         [("opentcad.materials.database", ["load_material", "MaterialParams", "MaterialFileError",
                                           "params_from_dict", "value_paths", "BandStructure",
                                           "MobilityConstant",
                                           "MobilityKlaassen", "MobilityLombardi",
                                           "VelocitySaturation",
                                           "Recombination", "Avalanche"])],
         guide="../device_physics.md#materials"),
    Page("calibrate", "Calibration",
         "Fitting model parameters to reference data, and writing the result as a material file.",
         [("opentcad.calibrate", ["fit", "Parameter", "FitResult", "Evaluation",
                                  "apply_overrides", "write_material_variant"])],
         guide="../calibration.md"),
    Page("io", "Simulation files and sweeps",
         "Loading, checking, running and saving simulation files; parameter sweeps.",
         [("opentcad.io", ["load_deck", "run_deck", "save_deck", "dumps_deck", "deck_from_dict",
                           "Deck", "DeckResult", "DeckError", "load_sweep", "run_sweep", "Sweep",
                           "SweepResult"]),
          ("opentcad.io.deck", ["example_decks_dir"])],
         guide="../simulation_files.md"),
    Page("provenance", "Provenance",
         "Where each value a run used came from: sources in data files and run records.",
         [("opentcad.provenance", ["recording", "Record", "Value", "Source", "parse_sources",
                                   "sources_for", "note_value", "note_model", "note_file",
                                   "note_input", "active", "summarize", "format_table",
                                   "code_version", "display_path"])],
         guide="../provenance.md"),
    Page("design", "Device design",
         "Bounded design search over a fixed simulation file, and model-drafted plans.",
         [("opentcad.design", ["load_design", "run_design", "variable_paths", "Design",
                               "Variable", "Target", "DesignResult"]),
          ("opentcad.assist.design", ["draft_design", "DesignDraft"])],
         guide="../design.md"),
    Page("plugins", "Plugin registries",
         "Registering and looking up process steps, analyses, models, metrics and data folders.",
         [("opentcad.plugins", ["register_step", "StepHandler", "step_handler", "step_class",
                                "registered_steps", "register_analysis", "get_analysis",
                                "available_analyses", "register_model", "get_model", "model_name",
                                "available_models", "MODEL_CATEGORIES", "register_metric",
                                "get_metric", "available_metrics", "register_data_dir",
                                "data_dirs", "find_data_file", "load_entry_points",
                                "plugin_status"])],
         guide="../plugins.md"),
    Page("viz", "Visualization",
         "Figure data on the mesh, interactive Plotly figures and the colour palette.",
         [("opentcad.viz.fields", ["sample_on_grid", "GridField", "cells_on_grid",
                                   "cell_values_on_grid", "cell_gradient",
                                   "electric_field_V_per_cm", "net_doping", "signed_log10",
                                   "zero_contour", "material_edges", "material_labels",
                                   "vertical_cut", "points_um", "triangles"]),
          ("opentcad.viz.interactive", ["structure_map", "doping_map", "doping_profile",
                                        "field_map", "iv_figures", "metric_figure"]),
          ("opentcad.viz.palette", ["material_color", "species_color", "diverging_colorscale",
                                    "sequential_colorscale", "oklch"])],
         guide="../visualization.md"),
    Page("catalog", "Process catalog",
         "Private records of materials, equipment and process flows.",
         [("opentcad.catalog", ["Catalog", "import_file", "ImportResult", "check_record",
                                "Assessment", "Issue", "runsheet", "CatalogRecord",
                                "record_from_dict", "record_revision", "record_schema",
                                "Quantity", "RecordRef", "SourceRef"])],
         guide="../catalog.md"),
    Page("assist", "Assistant",
         "Drafting simulation files and catalog records with a local open-weights model.",
         [("opentcad.assist", ["draft_deck", "Draft", "Flag", "unstated_values",
                               "request_numbers", "ChatClient", "LLMError", "draft_catalog",
                               "CatalogDraft"])],
         guide="../assistant.md"),
    Page("bridge", "Mesh-to-mesh interpolation",
         "Moving doping fields between separate meshes.",
         [("opentcad.bridge.field_interpolator", ["interpolate_doping_field"])]),
]

_SECTIONS = {"args": "Parameters", "arguments": "Parameters", "parameters": "Parameters",
             "keyword args": "Keyword parameters", "returns": "Returns", "return": "Returns",
             "yields": "Yields", "raises": "Raises", "attributes": "Attributes",
             "example": "Example", "examples": "Example", "note": "Note", "notes": "Notes",
             "warning": "Warning", "see also": "See also"}
_ITEM_SECTIONS = {"Parameters", "Keyword parameters", "Raises", "Attributes"}
_BOILERPLATE = ("An enumeration.", "Create a collection of name/value pairs.",
                "Common base class for all non-exit exceptions.")


# ── formatting ────────────────────────────────────────────────────────────────

def _short(text: str) -> str:
    """Drop package paths from type names: opentcad.geometry.formats.Material → Material."""
    text = re.sub(r"\bopentcad(?:\.\w+)*\.(?=\w)", "", text)
    text = re.sub(r"\bnumpy\.", "np.", text)
    return re.sub(r"\btyping\.", "", text)


def _strip_annotated(text: str) -> str:
    """Annotated[X, metadata] → X (pydantic field metadata is noise here)."""
    while (start := text.find("Annotated[")) >= 0:
        depth, i, comma = 0, start + len("Annotated["), None
        while i < len(text):
            c = text[i]
            if c in "[(":
                depth += 1
            elif c in "])":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0 and comma is None:
                comma = i
            i += 1
        inner = text[start + len("Annotated["):comma if comma is not None else i]
        text = text[:start] + inner.strip() + text[i + 1:]
    return text


def _annotation(ann) -> str:
    if ann is inspect.Parameter.empty:
        return ""
    text = ann if isinstance(ann, str) else inspect.formatannotation(ann)
    text = re.sub(r"""^(['"])(.*)\1$""", r"\2", text.strip())      # forward refs
    return _short(_strip_annotated(text))


def _default(value) -> str:
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, float) and value and not 1e-3 <= abs(value) < 1e6:
        return f"{value:.6g}".replace("e+", "e")
    if isinstance(value, (frozenset, set)):
        items = sorted(value, key=lambda v: (str(type(v)), v))
        return f"{type(value).__name__}({{{', '.join(_default(v) for v in items)}}})"
    if isinstance(value, (tuple, list)):
        inner = ", ".join(_default(v) for v in value)
        return f"({inner},)" if isinstance(value, tuple) and len(value) == 1 else (
            f"({inner})" if isinstance(value, tuple) else f"[{inner}]")
    if inspect.isfunction(value) or inspect.isclass(value) or inspect.isbuiltin(value):
        return value.__name__
    text = repr(value)
    return f"{type(value).__name__}(…)" if " at 0x" in text else _short(text)


def _signature(obj):
    kwargs = {}
    if sys.version_info >= (3, 14):
        import annotationlib
        kwargs["annotation_format"] = annotationlib.Format.STRING
    try:
        return inspect.signature(obj, **kwargs)
    except (TypeError, ValueError):
        return None


def _factories(obj) -> dict:
    """Dataclass / pydantic default factories, so `<factory>` can show `list()`."""
    out = {}
    for f in getattr(obj, "__dataclass_fields__", {}).values():
        if f.default_factory is not dataclasses.MISSING:
            out[f.name] = f.default_factory
    for name, f in getattr(obj, "model_fields", {}).items():
        if getattr(f, "default_factory", None) is not None:
            out[name] = f.default_factory
    return out


def _format_signature(prefix: str, obj, *, drop_first: bool = False) -> str:
    sig = _signature(obj)
    if sig is None:
        return prefix
    factories = _factories(obj) if inspect.isclass(obj) else {}
    params = list(sig.parameters.values())
    if drop_first and params and params[0].name in ("self", "cls"):
        params = params[1:]
    parts, kw_marker_done = [], False
    for i, p in enumerate(params):
        if p.kind is p.KEYWORD_ONLY and not kw_marker_done:
            if not any(q.kind is q.VAR_POSITIONAL for q in params[:i]):
                parts.append("*")
            kw_marker_done = True
        if p.kind is p.POSITIONAL_ONLY and (i + 1 == len(params)
                                            or params[i + 1].kind is not p.POSITIONAL_ONLY):
            pending_slash = True
        else:
            pending_slash = False
        star = "*" if p.kind is p.VAR_POSITIONAL else "**" if p.kind is p.VAR_KEYWORD else ""
        text = star + p.name
        ann = _annotation(p.annotation)
        if ann:
            text += f": {ann}"
        if p.name in factories and inspect.isclass(factories[p.name]):
            default = f"{factories[p.name].__name__}()"
        elif p.name in factories:
            default = "<factory>"
        elif p.default is not p.empty:
            default = _default(p.default)
        else:
            default = None
        if default is not None:
            text += f" = {default}" if ann else f"={default}"
        parts.append(text)
        if pending_slash:
            parts.append("/")
    ret = _annotation(sig.return_annotation)
    tail = f" -> {ret}" if ret else ""
    one_line = f"{prefix}({', '.join(parts)}){tail}"
    if len(one_line) <= 88 or not parts:
        return one_line
    body = "".join(f"    {p},\n" for p in parts)
    return f"{prefix}(\n{body}){tail}"


def _escape(line: str) -> str:
    """Stop prose like C_<species> being read as an HTML tag (outside `code`)."""
    pieces = re.split(r"(`[^`]*`)", line)
    return "".join(p if p.startswith("`") else re.sub(r"<(?=[A-Za-z/!])", "&lt;", p)
                   for p in pieces)


def _render_docstring(doc: str) -> str:
    lines = inspect.cleandoc(doc).splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        header = line.strip().rstrip(":").lower()
        if line.strip().endswith(":") and not line.startswith(" ") and header in _SECTIONS:
            title = _SECTIONS[header]
            i += 1
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith(" ")):
                block.append(lines[i])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            out += ["", f"**{title}**", ""]
            out += _render_section(title, block)
            out.append("")
            continue
        if line.startswith("    "):                       # an indented block → code
            block = []
            while i < len(lines) and (lines[i].startswith("    ") or (
                    not lines[i].strip() and i + 1 < len(lines)
                    and lines[i + 1].startswith("    "))):
                block.append(lines[i][4:])
                i += 1
            out += ["", "```", *block, "```", ""]
            continue
        out.append(_escape(line))
        i += 1
    text = "\n".join(out).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def _render_section(title: str, block: list[str]) -> list[str]:
    nonblank = [ln for ln in block if ln.strip()]
    if not nonblank:
        return []
    indent = min(len(ln) - len(ln.lstrip()) for ln in nonblank)
    body = [ln[indent:] if ln.strip() else "" for ln in block]
    if title == "Example":
        code = [ln[4:] if ln.startswith(">>> ") or ln.startswith("... ") else ln for ln in body]
        return ["```python", *code, "```"]
    if title not in _ITEM_SECTIONS:
        return [_escape(ln.strip()) for ln in body]
    items: list[str] = []
    for ln in body:
        m = re.match(r"^(\*{0,2}[\w.]+)\s*(\([^)]*\))?\s*:\s*(.*)$", ln)
        if m and not ln.startswith(" "):
            name, kind, desc = m.groups()
            kind = f" {kind}" if kind else ""
            items.append(f"- `{name}`{kind}: {_escape(desc)}".rstrip(": ").rstrip()
                         if desc else f"- `{name}`{kind}")
        elif ln.strip() and items:
            items[-1] += " " + _escape(ln.strip())
        elif ln.strip():
            items.append(_escape(ln.strip()))
    return items


def _own_doc(obj) -> str:
    doc = obj.__doc__ if inspect.isclass(obj) else inspect.getdoc(obj)
    if not doc:
        return ""
    doc = inspect.cleandoc(doc)
    if inspect.isclass(obj) and (doc.startswith(f"{obj.__name__}(") or doc in _BOILERPLATE):
        return ""
    return doc


def _source_link(obj) -> str:
    try:
        path = Path(inspect.getsourcefile(obj)).resolve().relative_to(ROOT)
        line = inspect.getsourcelines(obj)[1]
    except (TypeError, OSError, ValueError):
        return ""
    return f"[source]({SOURCE}{path.as_posix()}#L{line})"


# ── one entry per object ──────────────────────────────────────────────────────

def _members(cls):
    for name, raw in vars(cls).items():
        if name.startswith("_"):
            continue
        if isinstance(raw, property):
            yield name, "property", raw
        elif isinstance(raw, classmethod):
            yield name, "classmethod", raw.__func__
        elif isinstance(raw, staticmethod):
            yield name, "staticmethod", raw.__func__
        elif inspect.isfunction(raw):
            if raw.__doc__ is None and any(name in vars(base) for base in cls.__mro__[1:]
                                           if base.__module__.startswith("opentcad")):
                continue            # an undocumented override: the base class documents it
            yield name, "method", raw


def _render_object(module: str, name: str, obj) -> list[str]:
    path = f"{module}.{name}"
    out = [f"## {name}", ""]
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        out += ["```python", f"class {path}({obj.__bases__[0].__name__})", "```", ""]
    elif inspect.isclass(obj):
        out += ["```python", _format_signature(f"class {path}", obj), "```", ""]
    elif hasattr(obj, "__origin__") or hasattr(obj, "__metadata__"):       # a type alias
        out += ["```python", f"{path} = {_annotation(obj)}", "```", ""]
        return out
    elif callable(obj):
        out += ["```python", _format_signature(path, obj), "```", ""]
    else:
        value = _short(repr(obj))
        out += ["```python", f"{path} = {value}", "```", ""]
        return out
    doc = _own_doc(obj)
    if doc:
        out += [_render_docstring(doc), ""]
    link = _source_link(obj)
    if link:
        out += [link, ""]
    if inspect.isclass(obj) and issubclass(obj, enum.Enum):
        out += ["| Member | Value |", "|---|---|"]
        out += [f"| `{m.name}` | `{m.value!r}` |" for m in obj]
        out.append("")
        return out
    if inspect.isclass(obj):
        for mname, kind, member in _members(obj):
            out += [f"### {name}.{mname}", ""]
            if kind == "property":
                ret = _annotation(_signature(member.fget).return_annotation) if member.fget else ""
                out += ["```python", f"property {name}.{mname}" + (f": {ret}" if ret else ""),
                        "```", ""]
                doc = inspect.getdoc(member) or ""
            else:
                label = "" if kind == "method" else f"{kind} "
                out += ["```python",
                        _format_signature(f"{label}{name}.{mname}", member,
                                          drop_first=kind != "staticmethod"),
                        "```", ""]
                doc = inspect.getdoc(member) or ""
            if doc:
                out += [_render_docstring(doc), ""]
    return out


def render_page(page: Page) -> str:
    out = [f"# {page.title}", "", page.summary]
    if page.guide:
        out += ["", f"For an introduction, see the [user guide]({page.guide}). "
                    "This page is generated from the docstrings by `tools/gen_api_docs.py`."]
    else:
        out += ["", "This page is generated from the docstrings by `tools/gen_api_docs.py`."]
    out.append("")
    for module, names in page.groups:
        mod = importlib.import_module(module)
        out += [f"Import from `{module}`: "
                + ", ".join(f"`{n}`" for n in names) + ".", ""]
        for name in names:
            out += _render_object(module, name, getattr(mod, name))
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"


def render_index() -> str:
    out = ["# API reference", "",
           "Every public class and function, generated from the docstrings. The",
           "[user guide](../concepts.md) explains how the pieces fit together; this",
           "reference is for looking up exact signatures and behaviour.", "",
           "| Page | Covers | Main entry points |", "|---|---|---|"]
    for page in PAGES:
        first = [n for _, names in page.groups for n in names][:4]
        out.append(f"| [{page.title}]({page.slug}.md) | {page.summary} | "
                   + ", ".join(f"`{n}`" for n in first) + " |")
    out += ["", "Units follow the rest of OpenTCAD: lengths in µm, concentrations in cm⁻³,",
            "device temperature in K, process temperatures in °C, energies in eV, voltages",
            "in V. Names carry their unit where it isn't obvious (`thickness_um`,",
            "`dose_cm2`, `temperature_K`).", ""]
    return "\n".join(out)


def build() -> dict[str, str]:
    warnings.simplefilter("ignore")
    files = {"README.md": render_index()}
    for page in PAGES:
        files[f"{page.slug}.md"] = render_page(page)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if docs/api/ is out of date")
    args = ap.parse_args(argv)
    files = build()
    if args.check:
        stale = [n for n, text in files.items()
                 if not (OUT / n).exists() or (OUT / n).read_text() != text]
        extra = sorted({p.name for p in OUT.glob("*.md")} - set(files))
        if stale or extra:
            print("docs/api is out of date; run: python tools/gen_api_docs.py")
            for n in stale + extra:
                print("  ", n)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        if old.name not in files:
            old.unlink()
    for name, text in files.items():
        (OUT / name).write_text(text)
    print(f"wrote {len(files)} pages to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
