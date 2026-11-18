"""Bounded, deterministic device design with a fixed simulation contract.

Only explicitly permitted geometry/process numbers change. This local coordinate
search makes no claim of feasibility, global optimality, or fabrication readiness.
Metric units are declarations, with no implicit out-of-plane depth conversion.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

import numpy as np
import yaml

from opentcad.io.deck import DeckError, _Loader, deck_from_dict, dumps_deck
from opentcad.io.sweep import _parse_path, set_path
from opentcad.plugins import get_metric


@dataclass(frozen=True)
class Variable:
    """One number of the simulation file that the search may change.

    Attributes:
        path: Field in the sweep path syntax, e.g.
            ``structure.layers[0].doping_Na``; one of :func:`variable_paths`.
        lower: Lower bound, in the field's own unit.
        upper: Upper bound.
        initial: Starting value, within the bounds.
        scale: ``"linear"``, or ``"log"`` to search in log(value); log bounds
            must be positive.
    """
    path: str
    lower: float
    upper: float
    initial: float
    scale: str = "linear"

    def encode(self, value):
        """``value`` → its position in [0, 1] between the bounds (log-spaced for ``"log"``)."""
        lo, hi, v = self.lower, self.upper, value
        if self.scale == "log":
            lo, hi, v = math.log(lo), math.log(hi), math.log(v)
        return (v - lo) / (hi - lo)

    def decode(self, value):
        """Position in [0, 1] → value, clipped to the bounds; the initial value round-trips."""
        if value == self.encode(self.initial):
            return self.initial
        if value <= 0:
            return self.lower
        if value >= 1:
            return self.upper
        if self.scale == "log":
            return math.exp(math.log(self.lower) + value *
                            (math.log(self.upper) - math.log(self.lower)))
        return self.lower + value * (self.upper - self.lower)


@dataclass(frozen=True)
class Target:
    """One acceptance interval on a metric of a named IV or CV analysis.

    Attributes:
        name: Label for the result rows.
        analysis: Name of an ``iv`` or ``cv`` analysis in the base file.
        metric: ``value_at``, ``max_abs``, ``vth_max_gm`` or
            ``vth_constant_current``.
        options: The metric's arguments, e.g. ``{"x": 0.5}`` for ``value_at``.
        scale: Positive normalization: a violation counts as
            (distance outside the interval) / ``scale``.
        unit: Declared unit, which must match the metric: A/cm for IV
            values, F/cm for CV values, V for thresholds. Nothing is converted.
        lower: Lower bound, or ``None``.
        upper: Upper bound, or ``None``; at least one bound is required.
    """
    name: str
    analysis: str
    metric: str
    options: dict
    scale: float
    unit: str
    lower: float | None = None
    upper: float | None = None


@dataclass
class Design:
    """A checked design plan: a fixed base simulation file, what may vary,
    the targets and the search budget. Make one with :func:`load_design`.

    Attributes:
        name: Plan name.
        base: The base simulation file as a mapping. Its physics, mesh,
            materials and analyses never change during the search.
        variables: What the search may change.
        targets: What a candidate has to meet.
        search: ``max_evaluations`` (every attempted candidate counts),
            ``initial_step`` and ``min_step`` in normalized [0, 1] units.
        description: Free text.
        assumptions: Choices made when the plan was written, kept with the evidence.
        limitations: Known limits of the plan, kept with the evidence.
        unresolved: Open questions; :func:`run_design` refuses to run while
            any remain.
    """
    name: str
    base: dict
    variables: list[Variable]
    targets: list[Target]
    search: dict
    description: str = ""
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self):
        """The plan as a mapping that :func:`load_design` reads back unchanged."""
        targets = [{k: v for k, v in asdict(t).items() if v is not None}
                   for t in self.targets]
        return copy.deepcopy({"version": 1, "name": self.name,
                              "description": self.description, "base": self.base,
                              "variables": [asdict(v) for v in self.variables],
                              "targets": targets, "search": self.search,
                              "assumptions": self.assumptions,
                              "limitations": self.limitations,
                              "unresolved": self.unresolved})

    def candidate_deck(self, values):
        """The base simulation file with ``{path: value}`` applied, as a new mapping."""
        data = copy.deepcopy(self.base)
        for path, value in values.items():
            set_path(data, path, value)
        return data


def _finite(value):
    if (not isinstance(value, (int, float, np.integer, np.floating))
            or isinstance(value, (bool, np.bool_))):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _check_finite_tree(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            _check_finite_tree(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (tuple, list)):
        for i, item in enumerate(value):
            _check_finite_tree(item, f"{path}[{i}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f"{path}: numbers must be finite")


def _keys(data, allowed, required=()):
    if not isinstance(data, dict):
        raise ValueError("expected a mapping")
    extra = set(data) - set(allowed)
    missing = set(required) - set(data)
    if extra:
        raise ValueError(f"unknown fields: {sorted(extra)}")
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _read(source):
    if isinstance(source, dict):
        return copy.deepcopy(source)
    return yaml.load(Path(source).read_text(), Loader=_Loader)


def _numeric_path(base, path):
    # Contact barrier/flat-band parameters are deliberately frozen physics.
    geometry = (r"structure\.width_um|"
                r"structure\.layers\[\d+\]\.(thickness_um|doping_Na|doping_Nd)|"
                r"structure\.regions\[\d+\]\.(doping_Na|doping_Nd|[xy]_um\[[01]\])|"
                r"structure\.contacts\[\d+\]\.x_um\[[01]\]")
    if not (re.fullmatch(geometry, path) or re.fullmatch(r"recipe\[\d+\]\..+", path)):
        raise ValueError("only existing geometry/doping or recipe numeric fields may vary; "
                         "device physics, contacts' barriers, mesh and analyses are fixed")
    node = base
    for key in _parse_path(path):
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"{path}: no existing numeric field") from None
    if not _finite(node):
        raise ValueError(f"{path}: expected an existing finite numeric field")


def variable_paths(base: dict) -> dict[str, float]:
    """Every field of a simulation file that a design may vary, with its value.

    Args:
        base: The simulation file as a mapping (``Deck.to_dict()``).

    Returns:
        ``{path: current value}`` in the sweep path syntax
        (``structure.layers[0].doping_Na``), in file order. These are the
        existing numeric geometry, doping and recipe fields; physics,
        contact barriers, mesh and analyses never appear.
    """
    found: dict[str, float] = {}

    def walk(node, path):
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif _finite(node):
            try:
                _numeric_path(base, path)
            except ValueError:
                return
            found[path] = node

    walk({"structure": base.get("structure", {}), "recipe": base.get("recipe", [])}, "")
    return found


def _expected_grid(analysis):
    args = analysis.args
    if not {"v_start", "v_end", "v_step"} <= args.keys():
        raise ValueError(f"{analysis.name}: design targets require explicit v_start/v_end/v_step")
    start, end, step = (args[k] for k in ("v_start", "v_end", "v_step"))
    if not all(_finite(x) for x in (start, end, step)) or step == 0:
        raise ValueError(f"{analysis.name}: finite sweep endpoints and nonzero step required")
    count = (end - start) / step
    if count < 0 or count > 1_000_000:
        raise ValueError(f"{analysis.name}: invalid sweep direction or more than 1000001 points")
    if not math.isclose(count, round(count), rel_tol=1e-12, abs_tol=1e-10):
        raise ValueError(f"{analysis.name}: sweep step must reach v_end exactly")
    expected = np.arange(start, end + step / 2, step)
    if len(expected) < (2 if analysis.type == "cv" else 1):
        raise ValueError(f"{analysis.name}: insufficient sweep points")
    return expected


def load_design(source, *, base_dir=None) -> Design:
    """Load and check a design plan without running any simulation.

    Args:
        source: Path to a YAML or JSON plan, or the plan as a mapping.
        base_dir: Folder a relative ``base`` path is read from. Defaults to
            the plan file's folder, or the current folder for a mapping.

    Returns:
        A :class:`Design` whose base file, variables, targets and search
        settings have all been checked.

    Raises:
        DeckError: Every problem found, e.g. a variable that isn't an
            existing numeric geometry, doping or recipe field, a target on a
            missing or non-IV/CV analysis, or a unit that doesn't match the metric.
    """
    try:
        data = _read(source)
        _keys(data, ("version", "name", "description", "base", "variables", "targets",
                     "search", "assumptions", "limitations", "unresolved"),
              ("name", "base", "variables", "targets", "search"))
        _check_finite_tree(data)
        if type(data.get("version", 1)) is not int or data.get("version", 1) != 1:
            raise ValueError("unsupported design version (expected 1)")
        here = Path(base_dir or (Path(source).resolve().parent
                                if not isinstance(source, dict) else "."))
        base = _read(data["base"] if isinstance(data["base"], dict)
                     else here / data["base"])
        if not isinstance(base, dict) or not isinstance(base.get("device"), dict):
            raise ValueError("base must contain a device with explicit physics")
        if not isinstance(base["device"].get("physics"), dict) or not base["device"]["physics"]:
            raise ValueError("base.device.physics must explicitly declare the fixed models")
        _check_finite_tree(base, "base")
        deck = deck_from_dict(base)
        base = deck.to_dict()
        variables = []
        if not isinstance(data["variables"], list) or not data["variables"]:
            raise ValueError("variables must be a non-empty list")
        for raw in data["variables"]:
            _keys(raw, ("path", "lower", "upper", "initial", "scale"),
                  ("path", "lower", "upper", "initial", "scale"))
            path = _text(raw["path"], "variable path")
            _numeric_path(base, path)
            if path in {v.path for v in variables}:
                raise ValueError(f"duplicate variable path {path!r}")
            if not all(_finite(raw[k]) for k in ("lower", "upper", "initial")):
                raise ValueError(f"{path}: bounds and initial must be finite real numbers")
            if not raw["lower"] < raw["upper"] or not raw["lower"] <= raw["initial"] <= raw["upper"]:
                raise ValueError(f"{path}: require lower < upper and initial within bounds")
            if raw["scale"] not in ("linear", "log"):
                raise ValueError(f"{path}: scale must be linear or log")
            if raw["scale"] == "log" and raw["lower"] <= 0:
                raise ValueError(f"{path}: log bounds must be positive")
            width = (math.log(raw["upper"]) - math.log(raw["lower"])
                     if raw["scale"] == "log" else raw["upper"] - raw["lower"])
            if not _finite(width) or width <= 0:
                raise ValueError(f"{path}: transformed bounds must have a positive finite width")
            variables.append(Variable(**raw))
        analyses = {a.name: a for a in deck.analyses}
        targets = []
        if not isinstance(data["targets"], list) or not data["targets"]:
            raise ValueError("targets must be a non-empty list")
        for raw in data["targets"]:
            _keys(raw, ("name", "analysis", "metric", "options", "lower", "upper", "scale", "unit"),
                  ("name", "analysis", "metric", "scale", "unit"))
            for key in ("name", "analysis", "metric", "unit"):
                _text(raw[key], f"target {key}")
            if raw["name"] in {t.name for t in targets}:
                raise ValueError(f"duplicate target name {raw['name']!r}")
            if not {"lower", "upper"} & raw.keys():
                raise ValueError(f"{raw['name']}: need at least one target bound")
            if not _finite(raw["scale"]) or raw["scale"] <= 0:
                raise ValueError(f"{raw['name']}: target scale must be positive and finite")
            if any(not _finite(raw[k]) for k in ("lower", "upper") if k in raw):
                raise ValueError(f"{raw['name']}: target bounds must be finite real numbers")
            if "lower" in raw and "upper" in raw and raw["lower"] > raw["upper"]:
                raise ValueError(f"{raw['name']}: lower exceeds upper")
            analysis = analyses.get(raw["analysis"])
            if analysis is None or analysis.type not in ("iv", "cv"):
                raise ValueError(f"{raw['analysis']}: targets currently require a named IV/CV analysis")
            _expected_grid(analysis)
            unit = None
            if raw["metric"] in ("vth_max_gm", "vth_constant_current"):
                if analysis.type != "iv":
                    raise ValueError("threshold metrics require IV analysis")
                unit = "V"
            elif raw["metric"] in ("value_at", "max_abs"):
                unit = "A/cm" if analysis.type == "iv" else "F/cm"
            else:
                raise ValueError(f"{raw['metric']}: no supported target unit contract; "
                                 "use value_at, max_abs, vth_max_gm or vth_constant_current")
            if unit and raw["unit"] != unit:
                raise ValueError(f"{raw['name']}: {raw['metric']} on {analysis.type} requires unit {unit}; "
                                 "no implicit depth or unit conversion is performed")
            options = raw.get("options", {})
            if not isinstance(options, dict):
                raise ValueError("target options must be a mapping")
            inspect.signature(get_metric(raw["metric"])).bind(None, **options)
            if not all(_finite(value) for value in options.values()):
                raise ValueError(f"{raw['name']}: metric options must be finite real numbers")
            if raw["metric"] == "value_at":
                grid = _expected_grid(analysis)
                if not min(grid) <= options["x"] <= max(grid):
                    raise ValueError(f"{raw['name']}: value_at x must lie within the sweep range")
            if raw["metric"] == "vth_constant_current" and options["i_crit"] <= 0:
                raise ValueError(f"{raw['name']}: i_crit must be positive")
            targets.append(Target(**{**raw, "options": options}))
        search = {"initial_step": 0.25, "min_step": 0.01, **data["search"]}
        _keys(search, ("max_evaluations", "initial_step", "min_step"), ("max_evaluations",))
        if type(search["max_evaluations"]) is not int or search["max_evaluations"] < 1:
            raise ValueError("max_evaluations must be a positive integer")
        if (not all(_finite(search[k]) for k in ("initial_step", "min_step"))
                or not 0 < search["min_step"] <= search["initial_step"] <= 1):
            raise ValueError("require 0 < min_step <= initial_step <= 1")
        lists = {}
        for key in ("assumptions", "limitations", "unresolved"):
            values = data.get(key, [])
            if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
                raise ValueError(f"{key} must be a list of strings")
            lists[key] = values
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError("description must be text")
        design = Design(_text(data["name"], "name"), base, variables, targets,
                        search, description, **lists)
        # Initial geometry must be coherent; later invalid geometry consumes an attempt.
        deck_from_dict(design.candidate_deck({v.path: v.initial for v in variables}))
        return design
    except DeckError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise DeckError([("design", str(exc))]) from None


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path, value):
    path.write_text(json.dumps(_json_safe(value), indent=2, allow_nan=False) + "\n")


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _environment(base, outdir):
    from opentcad.materials.database import load_material
    from opentcad.plugins import plugin_status

    versions = {}
    for package in ("opentcad", "numpy", "scipy", "devsim", "gmsh", "pyyaml", "pyvista"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed as distribution"
    materials = {}
    symbols = {x["material"] for kind in ("layers", "regions")
               for x in base["structure"].get(kind, [])}
    symbols.update(x["material"] for x in base.get("recipe", []) if "material" in x)
    material_dir = outdir / "materials"
    material_dir.mkdir()
    for symbol in sorted(symbols):
        try:
            params = load_material(symbol, process=base["device"].get("material_process", {}).get(symbol))
            content = Path(params.source).read_text()
            artifact = f"materials/{symbol}.yaml"
            (outdir / artifact).write_text(content)
            materials[symbol] = {"source": params.source, "sha256": _hash(content),
                                 "artifact": artifact, "resolved": params.model_dump()}
        except Exception as exc:
            materials[symbol] = {"error": f"{type(exc).__name__}: {exc}"}
    source_hashes = {}
    for relative in ("design.py", "io/deck.py", "device/solver.py", "materials/database.py"):
        path = Path(__file__).parent / relative
        source_hashes[relative] = _hash(path.read_text())
    return {"python": platform.python_version(), "platform": platform.platform(),
            "versions": versions, "plugins": plugin_status(), "materials": materials,
            "source_sha256": source_hashes,
            "limitations": ["Snapshots record declared materials and selected source files; "
                            "they do not freeze the entire runtime, process data, or plugin code.",
                            "Only target IV/CV analyses are checked for complete finite sweep grids."]}


def _evaluate(deck_dict, targets, row):
    from opentcad.io.deck import run_deck

    deck = deck_from_dict(deck_dict)
    result = run_deck(deck)
    row["analyses"] = result.analyses_to_dict()
    analyses = {a.name: a for a in deck.analyses}
    for name in dict.fromkeys(t.analysis for t in targets):
        actual = result.analyses.get(name)
        if not isinstance(actual, (tuple, list)) or len(actual) != 2:
            raise ValueError(f"{name}: missing (x, y) analysis arrays")
        x, y = (np.asarray(a, dtype=float) for a in actual)
        grid = _expected_grid(analyses[name])
        if (x.ndim != 1 or y.ndim != 1 or len(x) != len(grid) or len(y) != len(grid)
                or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
                or not np.allclose(x, grid, rtol=1e-12, atol=1e-14)):
            raise ValueError(f"{name}: incomplete, non-finite or unexpected sweep grid")
        row["completion"][name] = {"expected_points": len(grid), "observed_points": len(x),
                                    "first": float(x[0]), "last": float(x[-1])}
    for target in targets:
        value = get_metric(target.metric)(result.analyses[target.analysis], **target.options)
        if not _finite(value):
            raise ValueError(f"{target.name}: metric did not return a finite real scalar")
        value = float(value)
        lower = max(0.0, target.lower - value) if target.lower is not None else 0.0
        upper = max(0.0, value - target.upper) if target.upper is not None else 0.0
        violation = (lower + upper) / target.scale
        if not math.isfinite(violation):
            raise ValueError(f"{target.name}: normalized violation overflow")
        row["metrics"][target.name] = value
        row["violations"][target.name] = {"lower": lower, "upper": upper,
                                           "normalized": violation, "unit": target.unit}
    score = sum(v["normalized"] for v in row["violations"].values())
    if not math.isfinite(score):
        raise ValueError("total normalized violation overflow")
    # Compare raw bounds: normalization may underflow to zero for extreme scales.
    passed = all((t.lower is None or row["metrics"][t.name] >= t.lower)
                 and (t.upper is None or row["metrics"][t.name] <= t.upper) for t in targets)
    row.update(status="ok", score=score, target_met=passed)


@dataclass
class DesignResult:
    """What :func:`run_design` did.

    Attributes:
        outdir: The evidence folder.
        stop_reason: ``target_met``, ``budget_exhausted``, ``search_stalled``
            or ``no_valid_candidates``.
        attempts: One row per attempted candidate, failures included: values,
            metrics, violations, status, error and the files written for it.
        best: The valid candidate with the smallest total violation, or ``None``.
    """
    outdir: Path
    stop_reason: str
    attempts: list[dict]
    best: dict | None

    def to_dict(self):
        """JSON-safe summary; non-finite numbers become ``None``."""
        return _json_safe({"outdir": str(self.outdir), "stop_reason": self.stop_reason,
                           "evaluations": len(self.attempts), "attempts": self.attempts, "best": self.best})


def run_design(design: Design, outdir, *, log=None) -> DesignResult:
    """Search the plan's variables with real simulations until the targets are met.

    Adaptive coordinate search: each poll tries +/- step along every
    normalized coordinate, moves to the best strict improvement or halves
    the step. Every attempt, failed ones included, costs one evaluation;
    repeated points are cached. The search stops at the first candidate
    that meets every target. It is local: an unmet result doesn't show the
    targets are infeasible.

    Args:
        design: A plan from :func:`load_design`; it is checked again here.
        outdir: New evidence folder; it must not exist yet.
        log: Called with one line per candidate; ``None`` is silent.

    Returns:
        A :class:`DesignResult`. ``outdir`` holds the contract and its hash,
        the base file, material and environment snapshots, every candidate's
        file and result, ``design.json`` and ``best.yaml``.

    Raises:
        DeckError: The plan still has ``unresolved`` questions, or fails its checks.
        FileExistsError: ``outdir`` already exists.
    """
    # Revalidate a detached snapshot, so mutations of a public Design cannot bypass checks.
    design = load_design(design.to_dict())
    if design.unresolved:
        raise DeckError([("unresolved", "resolve before running: " + "; ".join(design.unresolved))])
    say = log or (lambda message: None)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    (outdir / "candidates").mkdir()
    contract = design.to_dict()
    contract_hash = _hash(json.dumps(contract, sort_keys=True, allow_nan=False))
    _write_json(outdir / "contract.json", {"sha256": contract_hash, "design": contract})
    (outdir / "base.yaml").write_text(dumps_deck(deck_from_dict(design.base)))
    environment = _environment(design.base, outdir)
    _write_json(outdir / "environment.json", environment)
    attempts = []
    cache = {}
    best = None
    budget = design.search["max_evaluations"]
    material_drift = None

    def check_materials():
        for symbol, snapshot in environment["materials"].items():
            if "source" in snapshot:
                path = Path(snapshot["source"])
                if not path.exists() or _hash(path.read_text()) != snapshot["sha256"]:
                    raise RuntimeError(f"fixed material source changed during search: {symbol}")

    def evaluate(point, reason, parent, step):
        nonlocal best, material_drift
        values = {v.path: v.decode(p) for v, p in zip(design.variables, point)}
        key = tuple(values.values())
        if key in cache:
            return cache[key]
        if len(attempts) >= budget:
            return None
        index = len(attempts)
        prefix = f"candidates/candidate_{index:04d}"
        candidate = design.candidate_deck(values)
        # Save even decks that fail semantic validation, exactly as attempted.
        text = yaml.safe_dump(candidate, sort_keys=False)
        (outdir / f"{prefix}.yaml").write_text(text)
        row = {"index": index, "values": values, "normalized_values": list(point),
               "status": "failed", "score": None, "target_met": False,
               "metrics": {}, "violations": {}, "completion": {}, "analyses": {},
               "reason": reason, "parent": parent, "step": step,
               "changes": {p: {"from": (attempts[parent]["values"][p] if parent is not None else None),
                                "to": value} for p, value in values.items()
                           if parent is None or value != attempts[parent]["values"][p]},
               "deck": f"{prefix}.yaml", "result": f"{prefix}.json",
               "deck_sha256": _hash(text), "contract_sha256": contract_hash,
               "settings": copy.deepcopy(design.search)}
        started = time.monotonic()
        try:
            check_materials()
            _evaluate(candidate, design.targets, row)
        except Exception as exc:
            row.update(status="failed", score=None, target_met=False)
            row["error"] = f"{type(exc).__name__}: {exc}"
        try:
            check_materials()
        except Exception as exc:
            material_drift = str(exc)
            row.update(status="failed", score=None, target_met=False)
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_s"] = time.monotonic() - started
        attempts.append(row)
        cache[key] = row
        if row["status"] == "ok" and (best is None or row["score"] < best["score"]
                                      or (row["target_met"] and not best["target_met"])):
            best = row
        _write_json(outdir / f"{prefix}.json", row)
        # Persist progress after each attempt, so interrupted searches retain evidence.
        _write_json(outdir / "design.json", {**DesignResult(outdir, "running", attempts, best).to_dict(),
                                             "contract_sha256": contract_hash})
        say(f"candidate {index + 1}/{budget}: {row['status']}; score={row['score']}")
        return row

    center = tuple(v.encode(v.initial) for v in design.variables)
    step = design.search["initial_step"]
    incumbent = evaluate(center, "initial", None, step)
    stop = "budget_exhausted"
    while not material_drift and not (best and best["target_met"]) and len(attempts) < budget:
        poll_best = incumbent
        for axis in range(len(center)):
            for direction in (1, -1):
                neighbor = list(center)
                neighbor[axis] = min(1.0, max(0.0, neighbor[axis] + direction * step))
                row = evaluate(tuple(neighbor), f"coordinate {axis} {direction:+d}", incumbent["index"], step)
                if row and row["status"] == "ok" and (poll_best["status"] != "ok"
                                                        or row["score"] < poll_best["score"]):
                    poll_best = row
                if material_drift or (best and best["target_met"]) or len(attempts) >= budget:
                    break
            if material_drift or (best and best["target_met"]) or len(attempts) >= budget:
                break
        if best and best["target_met"]:
            break
        if len(attempts) >= budget:
            break
        if poll_best is not incumbent:
            incumbent = poll_best
            center = tuple(incumbent["normalized_values"])
        elif step / 2 >= design.search["min_step"]:
            step /= 2
        else:
            stop = "search_stalled"
            break
    if best is None:
        stop = "no_valid_candidates"
    elif material_drift:
        stop = "search_stalled"
    elif best["target_met"]:
        stop = "target_met"
    result = DesignResult(outdir, stop, attempts, best)
    if best:
        (outdir / "best.yaml").write_text((outdir / best["deck"]).read_text())
    _write_json(outdir / "design.json", {**result.to_dict(), "contract_sha256": contract_hash,
                                         "material_drift": material_drift,
                                         "claim": "Bounded local search; no global optimality, "
                                                  "infeasibility or fabrication claim."})
    return result
