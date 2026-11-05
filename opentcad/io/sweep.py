"""
opentcad.io.sweep — parameter sweeps over a simulation file.

A sweep file names a base simulation file, the values to vary, and the
numbers to extract from each run::

    version: 1
    name: tox_sweep
    base: nmos_implanted.yaml          # simulation file, relative to this file
    mode: product                      # every combination; or zip (lists of equal length)
    vary:                              # path in the simulation file → values
      structure.layers[1].thickness_um: [0.003, 0.004, 0.005]
      recipe[4].time_s: [600, 1800]
    metrics:                           # optional
      - {name: vth, analysis: idvg, metric: vth_max_gm, vds: 0.05}
      - {name: ion, analysis: idvg, metric: value_at, x: 1.5}

Paths address the simulation file as written by ``save_deck``:
dotted keys, ``[i]`` for list items. A key that is absent (e.g. an
implant's default ``tilt_deg``) can be set; it is then checked like any
other field. Every point is checked before anything runs.

``run_sweep`` writes to an output folder:

    table.csv                  one row per point: varied values, metrics, status
    sweep.json                 the same rows plus the sweep definition
    points/point_NNN.yaml      the exact simulation file of each point
    points/point_NNN.json      that point's full analysis results

A point that fails is recorded with its error and the sweep continues.
With ``jobs > 1`` points run in separate processes (DEVSIM keeps global
state), which see entry-point plugins but not ones registered at runtime.
"""
from __future__ import annotations

import copy
import csv
import inspect
import itertools
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .deck import DeckError, _Loader, deck_from_dict, dumps_deck, load_deck

SWEEP_VERSION = 1
MODES = ("product", "zip")
_KEYS = {"version", "name", "description", "base", "mode", "vary", "metrics"}
_TOKEN = re.compile(r"^([^\[\]]+)((?:\[\d+\])*)$")


# =============================================================================
# Paths into a simulation-file dict
# =============================================================================
def _parse_path(path: str) -> list:
    """``recipe[4].time_s`` → ``["recipe", 4, "time_s"]``."""
    if not isinstance(path, str) or not path:
        raise ValueError("path must be non-empty text")
    out: list = []
    for part in path.split("."):
        m = _TOKEN.match(part)
        if not m:
            raise ValueError(f"cannot parse {part!r} in path {path!r}")
        out.append(m.group(1))
        out.extend(int(i) for i in re.findall(r"\[(\d+)\]", m.group(2)))
    return out


def set_path(data: dict, path: str, value) -> None:
    """Set ``value`` at ``path`` in a nested dict/list structure. The last
    key may be new; list indices must exist."""
    keys = _parse_path(path)
    node = data
    for i, k in enumerate(keys[:-1]):
        node = _step(node, k, keys[: i + 1])
    last = keys[-1]
    if isinstance(node, dict) and isinstance(last, str):
        node[last] = value
    elif isinstance(node, list) and isinstance(last, int):
        if not 0 <= last < len(node):
            raise ValueError(f"{_fmt(keys)}: index out of range "
                             f"(length {len(node)})")
        node[last] = value
    else:
        where = _fmt(keys[:-1]) or "the file"
        raise ValueError(f"{where}: not a list" if isinstance(last, int)
                         else f"{where}: not a mapping")


def _step(node, key, so_far):
    where = _fmt(so_far)
    if isinstance(key, int):
        if not isinstance(node, list):
            raise ValueError(f"{where}: not a list")
        if not 0 <= key < len(node):
            raise ValueError(f"{where}: index out of range (length {len(node)})")
        return node[key]
    if not isinstance(node, dict) or key not in node:
        raise ValueError(f"{where}: no such field")
    return node[key]


def _fmt(keys) -> str:
    s = ""
    for k in keys:
        s += f"[{k}]" if isinstance(k, int) else (f".{k}" if s else k)
    return s


# =============================================================================
# The sweep
# =============================================================================
@dataclass
class MetricSpec:
    name: str
    analysis: str
    metric: str
    options: dict


@dataclass
class Sweep:
    """A checked sweep: the base simulation file (as a dict) and every point."""
    name: str
    base: dict
    vary: list[tuple[str, list]]
    mode: str = "product"
    metrics: list[MetricSpec] = field(default_factory=list)
    description: str = ""
    points: list[dict] = field(default_factory=list)      # path → value

    def point_deck(self, values: dict) -> dict:
        """The simulation-file dict for one point."""
        data = copy.deepcopy(self.base)
        for path, value in values.items():
            set_path(data, path, value)
        return data


def _combinations(vary, mode) -> list[dict]:
    paths = [p for p, _ in vary]
    lists = [v for _, v in vary]
    combos = itertools.product(*lists) if mode == "product" else zip(*lists)
    return [dict(zip(paths, c)) for c in combos]


def load_sweep(source, *, base_dir=None) -> Sweep:
    """Read and check a sweep file (path) or an already-parsed dict.
    Every point's simulation file is checked; DeckError lists all problems."""
    if isinstance(source, dict):
        data, here = source, Path(base_dir or ".")
    else:
        path = Path(source)
        try:
            data = yaml.load(path.read_text(), Loader=_Loader)
        except yaml.YAMLError as exc:
            raise DeckError([("", f"{path.name} is not valid YAML: {exc}")]) from None
        here = path.resolve().parent
    probs: list[tuple[str, str]] = []
    if not isinstance(data, dict):
        raise DeckError([("", "a sweep file must be a mapping")])
    for k in data:
        if k not in _KEYS:
            probs.append((str(k), f"unknown field; allowed: {sorted(_KEYS)}"))
    for k in ("base", "vary"):
        if k not in data:
            probs.append(("", f"missing required field {k!r}"))
    if data.get("version", SWEEP_VERSION) != SWEEP_VERSION:
        probs.append(("version", f"unsupported version {data.get('version')!r}"))
    mode = data.get("mode", "product")
    if mode not in MODES:
        probs.append(("mode", f"must be one of {MODES}"))
    name = data.get("name", "sweep")
    if probs:
        raise DeckError(probs)

    # Base simulation file: a path relative to the sweep file, or inline.
    base_src = data["base"]
    try:
        if isinstance(base_src, dict):
            base_deck = deck_from_dict(base_src)
        else:
            base_deck = load_deck(here / str(base_src))
    except DeckError as exc:
        raise DeckError([(f"base.{p}" if p else "base", m)
                         for p, m in exc.problems]) from None
    except OSError as exc:
        raise DeckError([("base", f"cannot read {base_src!r}: {exc}")]) from None
    base = base_deck.to_dict()

    vary_raw = data["vary"]
    vary: list[tuple[str, list]] = []
    if not isinstance(vary_raw, dict) or not vary_raw:
        probs.append(("vary", "expected a mapping of path → list of values"))
    else:
        for path, values in vary_raw.items():
            if not isinstance(values, list) or not values:
                probs.append((f"vary.{path}", "expected a non-empty list of values"))
                continue
            try:
                set_path(copy.deepcopy(base), path, values[0])
            except ValueError as exc:
                probs.append((f"vary.{path}", str(exc)))
                continue
            vary.append((path, values))
    if mode == "zip" and len({len(v) for _, v in vary}) > 1:
        probs.append(("vary", "mode zip needs value lists of equal length"))

    analysis_names = {a.name for a in base_deck.analyses}
    metrics = _metrics_from(data.get("metrics") or [], analysis_names, probs)
    clash = {m.name for m in metrics} & {p for p, _ in vary}
    if clash:
        probs.append(("metrics", f"names clash with varied paths: {sorted(clash)}"))
    if probs:
        raise DeckError(probs)

    sweep = Sweep(name=name, base=base, vary=vary, mode=mode, metrics=metrics,
                  description=data.get("description", ""))
    sweep.points = _combinations(vary, mode)
    for k, values in enumerate(sweep.points):
        try:
            deck_from_dict(sweep.point_deck(values))
        except DeckError as exc:
            label = ", ".join(f"{p}={v!r}" for p, v in values.items())
            probs.extend((f"point {k} ({label}): {p}" if p else f"point {k} ({label})", m)
                         for p, m in exc.problems)
    if probs:
        raise DeckError(probs)
    return sweep


def _metrics_from(raw, analysis_names, probs) -> list[MetricSpec]:
    from opentcad.plugins import get_metric
    out = []
    if not isinstance(raw, list):
        probs.append(("metrics", "expected a list"))
        return out
    seen = set()
    for i, md in enumerate(raw):
        p = f"metrics[{i}]"
        if not isinstance(md, dict) or not {"name", "analysis", "metric"} <= set(md):
            probs.append((p, "expected {name, analysis, metric, ...options}"))
            continue
        name, analysis, metric = md["name"], md["analysis"], md["metric"]
        options = {k: v for k, v in md.items()
                   if k not in ("name", "analysis", "metric")}
        if name in seen:
            probs.append((f"{p}.name", f"duplicate metric name {name!r}"))
        seen.add(name)
        if analysis not in analysis_names:
            probs.append((f"{p}.analysis", f"no analysis named {analysis!r} in the "
                                           f"base file; analyses: {sorted(analysis_names)}"))
        try:
            fn = get_metric(metric)
        except KeyError as exc:
            probs.append((f"{p}.metric", exc.args[0]))
            continue
        try:
            inspect.signature(fn).bind(None, **options)
        except TypeError as exc:
            allowed = list(inspect.signature(fn).parameters)[1:]
            probs.append((p, f"{metric}: {exc}; options: {allowed}"))
            continue
        out.append(MetricSpec(name, analysis, metric, options))
    return out


# =============================================================================
# Running
# =============================================================================
def _run_point(index: int, deck_dict: dict, metrics: list[MetricSpec]) -> dict:
    """Run one point; never raises (errors are recorded in the row)."""
    from opentcad.plugins import get_metric

    from .deck import run_deck
    t0 = time.time()
    row = {"point": index, "status": "ok", "metrics": {}, "notes": [],
           "analyses": {}, "mesh": None}
    try:
        res = run_deck(deck_from_dict(deck_dict))
    except Exception as exc:
        row["status"] = f"failed: {type(exc).__name__}: {exc}"
        row["elapsed_s"] = round(time.time() - t0, 2)
        return row
    row["mesh"] = {"cells": int(res.meshfield.n_cells),
                   "nodes": int(res.meshfield.n_points)}
    row["analyses"] = res.analyses_to_dict()
    for m in metrics:
        try:
            row["metrics"][m.name] = float(get_metric(m.metric)(
                res.analyses[m.analysis], **m.options))
        except Exception as exc:
            row["metrics"][m.name] = None
            row["notes"].append(f"{m.name}: {exc}")
    row["elapsed_s"] = round(time.time() - t0, 2)
    return row


@dataclass
class SweepResult:
    outdir: Path
    rows: list[dict]

    def table(self) -> list[dict]:
        return self.rows


def run_sweep(sweep: Sweep, outdir, *, jobs: int = 1, log=None) -> SweepResult:
    """Run every point and write the output folder. Returns the rows."""
    say = log or (lambda msg: None)
    outdir = Path(outdir)
    (outdir / "points").mkdir(parents=True, exist_ok=True)
    decks = [sweep.point_deck(v) for v in sweep.points]
    for k, d in enumerate(decks):
        (outdir / "points" / f"point_{k:03d}.yaml").write_text(
            dumps_deck(deck_from_dict(d)))

    n = len(decks)
    results: dict[int, dict] = {}
    if jobs <= 1:
        for k, d in enumerate(decks):
            say(f"point {k + 1}/{n}: {_label(sweep.points[k])}")
            results[k] = _run_point(k, d, sweep.metrics)
            say(f"  {results[k]['status']}  {_fmt_metrics(results[k])}")
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as pool:
            futures = {pool.submit(_run_point, k, d, sweep.metrics): k
                       for k, d in enumerate(decks)}
            for fut in as_completed(futures):
                k = futures[fut]
                results[k] = fut.result()
                say(f"point {k + 1}/{n}: {_label(sweep.points[k])} → "
                    f"{results[k]['status']}  {_fmt_metrics(results[k])}")

    rows = []
    for k in range(n):
        r = results[k]
        (outdir / "points" / f"point_{k:03d}.json").write_text(json.dumps(
            {"point": k, "values": sweep.points[k], "status": r["status"],
             "mesh": r["mesh"], "metrics": r["metrics"],
             "analyses": r["analyses"]}, indent=2) + "\n")
        rows.append({"point": k, **sweep.points[k], **r["metrics"],
                     "status": r["status"], "elapsed_s": r["elapsed_s"],
                     "notes": "; ".join(r["notes"])})

    columns = (["point"] + [p for p, _ in sweep.vary]
               + [m.name for m in sweep.metrics] + ["status", "elapsed_s", "notes"])
    with (outdir / "table.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for row in rows:
            w.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
    (outdir / "sweep.json").write_text(json.dumps({
        "name": sweep.name, "description": sweep.description, "mode": sweep.mode,
        "vary": {p: v for p, v in sweep.vary},
        "metrics": [{"name": m.name, "analysis": m.analysis, "metric": m.metric,
                     **m.options} for m in sweep.metrics],
        "rows": rows}, indent=2) + "\n")
    return SweepResult(outdir=outdir, rows=rows)


def _label(values: dict) -> str:
    return ", ".join(f"{p}={v}" for p, v in values.items())


def _fmt_metrics(row) -> str:
    return "  ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}"
                     for k, v in row["metrics"].items())
