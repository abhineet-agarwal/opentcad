"""
opentcad.cli — command-line interface.

    opentcad check FILE                 check a simulation or sweep file, list every problem
    opentcad run FILE [-o OUT.json]     run it; write analysis results as JSON
                      [--vtu MESH.vtu]  also save the final MeshField
                      [--verbose]       show DEVSIM's solver output
    opentcad sweep FILE [-o DIR] [-j N] run a sweep; table.csv + per-point results
    opentcad plugins                    list registered steps, analyses, models,
                                        metrics, data folders and plugins

Exit status: 0 success, 1 the file has problems, 2 the run (or a sweep
point) failed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path


@contextlib.contextmanager
def _quiet_stdout(enabled: bool):
    """Silence C-level stdout (DEVSIM prints every Newton iteration).
    Python-level messages go to stderr, so they still show."""
    if not enabled:
        yield
        return
    sys.stdout.flush()
    saved = os.dup(1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(devnull)
        os.close(saved)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _report(file, exc) -> int:
    _err(f"{file}: {len(exc.problems)} problem(s)")
    for path, msg in exc.problems:
        _err(f"  {path}: {msg}" if path else f"  {msg}")
    return 1


def _is_sweep_file(path) -> bool:
    import yaml

    from opentcad.io.deck import _Loader
    try:
        data = yaml.load(Path(path).read_text(), Loader=_Loader)
    except Exception:
        return False
    return isinstance(data, dict) and "vary" in data


def _cmd_check(args) -> int:
    from opentcad.io.deck import DeckError, load_deck
    from opentcad.io.sweep import load_sweep
    try:
        if _is_sweep_file(args.file):
            sweep = load_sweep(args.file)
            print(f"{args.file}: OK — sweep {sweep.name}: {len(sweep.points)} "
                  f"point(s) ({sweep.mode} of {len(sweep.vary)} parameter(s)), "
                  f"{len(sweep.metrics)} metric(s)")
            return 0
        deck = load_deck(args.file)
    except DeckError as exc:
        return _report(args.file, exc)
    print(f"{args.file}: OK — {deck.name}: {len(deck.structure.layers)} layer(s), "
          f"{len(deck.recipe)} recipe step(s), {len(deck.analyses)} analysis/es")
    return 0


def _cmd_sweep(args) -> int:
    from opentcad.io.deck import DeckError
    from opentcad.io.sweep import load_sweep, run_sweep
    try:
        sweep = load_sweep(args.file)
    except DeckError as exc:
        return _report(args.file, exc)
    outdir = Path(args.out) if args.out else Path(args.file).with_suffix("")
    t0 = time.time()
    _err(f"sweep {sweep.name}: {len(sweep.points)} point(s), jobs={args.jobs} "
         f"→ {outdir}")
    with _quiet_stdout(not args.verbose):
        result = run_sweep(sweep, outdir, jobs=args.jobs,
                           log=lambda m: _err(f"[{time.time()-t0:6.1f} s] {m}"))
    failed = [r for r in result.rows if r["status"] != "ok"]
    _err(f"table → {outdir / 'table.csv'}  ({len(result.rows) - len(failed)} ok, "
         f"{len(failed)} failed)")
    return 2 if failed else 0


def _cmd_run(args) -> int:
    from opentcad.io.deck import DeckError, load_deck, run_deck
    try:
        deck = load_deck(args.file)
    except DeckError as exc:
        return _report(args.file, exc)
    out_path = Path(args.out) if args.out else Path(args.file).with_suffix(".results.json")
    t0 = time.time()
    try:
        with _quiet_stdout(not args.verbose):
            result = run_deck(deck, log=lambda m: _err(f"[{time.time()-t0:6.1f} s] {m}"))
    except Exception as exc:          # report, don't dump a traceback at users
        _err(f"run failed: {type(exc).__name__}: {exc}")
        if args.verbose:
            raise
        return 2
    mf = result.meshfield
    payload = {
        "deck": deck.name,
        "source": str(args.file),
        "elapsed_s": round(time.time() - t0, 2),
        "mesh": {"cells": int(mf.n_cells), "nodes": int(mf.n_points)},
        "analyses": result.analyses_to_dict(),
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    _err(f"results → {out_path}")
    from opentcad.geometry.formats import MeshField
    for name, res in result.analyses.items():
        if isinstance(res, MeshField):            # "fields" snapshots
            vtu = out_path.with_name(f"{out_path.name.split('.')[0]}.{name}.vtu")
            res.save(vtu)
            _err(f"fields {name} → {vtu}")
    if args.vtu:
        saved = mf.save(args.vtu)
        _err(f"mesh → {saved if saved else args.vtu}")
    return 0


def _cmd_plugins(args) -> int:
    from opentcad import plugins
    print("Process steps:")
    for h in plugins.registered_steps().values():
        print(f"  {h.name:<18} {h.stage:<11} {h.step_type.__name__} ({h.source})")
    print("Analyses:")
    for name in plugins.available_analyses():
        print(f"  {name:<18} ({plugins._analyses[name][1]})")
    print("Physics models:")
    for cat in plugins.MODEL_CATEGORIES:
        print(f"  {cat:<14} {', '.join(plugins.available_models(cat))}")
    print("Metrics:")
    print(f"  {', '.join(plugins.available_metrics())}")
    print("Data folders:")
    for kind in plugins.DATA_KINDS:
        for d in plugins.data_dirs(kind):
            print(f"  {kind:<10} {d}")
    status = plugins.plugin_status()
    print("Entry-point plugins:" + ("" if status else " none"))
    for name, st in status.items():
        print(f"  {name}: {st}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opentcad",
                                description="OpenTCAD command-line interface")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="check a simulation file")
    c.add_argument("file")
    c.set_defaults(func=_cmd_check)
    r = sub.add_parser("run", help="run a simulation file")
    r.add_argument("file")
    r.add_argument("-o", "--out", help="results JSON (default: FILE.results.json)")
    r.add_argument("--vtu", help="also save the final MeshField to this .vtu path")
    r.add_argument("--verbose", action="store_true",
                   help="show solver output and full tracebacks")
    r.set_defaults(func=_cmd_run)
    sw = sub.add_parser("sweep", help="run a parameter sweep file")
    sw.add_argument("file")
    sw.add_argument("-o", "--out", help="output folder (default: FILE without .yaml)")
    sw.add_argument("-j", "--jobs", type=int, default=1,
                    help="points to run in parallel (separate processes)")
    sw.add_argument("--verbose", action="store_true", help="show solver output")
    sw.set_defaults(func=_cmd_sweep)
    pl = sub.add_parser("plugins", help="list registered extensions")
    pl.set_defaults(func=_cmd_plugins)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
