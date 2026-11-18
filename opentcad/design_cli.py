"""Bounded device-design commands; optional model drafting is imported lazily."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_design_parser(subparsers) -> None:
    parser = subparsers.add_parser("design", help="draft, check or search a bounded device design")
    commands = parser.add_subparsers(dest="design_command", required=True)
    check = commands.add_parser("check", help="validate a design plan without simulation")
    check.add_argument("file")
    run = commands.add_parser("run", help="search exactly the supplied reviewed design plan")
    run.add_argument("file")
    run.add_argument("-o", "--out", required=True, help="new evidence directory (must not exist)")
    run.add_argument("--verbose", action="store_true", help="show solver output and tracebacks")
    draft = commands.add_parser("draft", help="draft a reviewable plan with a configured model")
    draft.add_argument("request")
    source = draft.add_mutually_exclusive_group(required=True)
    source.add_argument("--base", help="existing simulation deck; physics and analyses stay fixed")
    source.add_argument("--current", help="existing design plan to revise; its base stays fixed")
    draft.add_argument("--feedback", "--evidence", dest="feedback",
                       help="explicit JSON run summary context (at most 80 KB)")
    draft.add_argument("-o", "--out", required=True, help="unaccepted draft review JSON")
    draft.add_argument("--plan-out", help="also write a separate editable plain plan; never run it")
    draft.add_argument("--url", help="OpenAI-compatible model server URL")
    draft.add_argument("--model", help="model name at that server")
    draft.add_argument("--max-repairs", type=int, default=1, choices=range(4))
    parser.set_defaults(func=run_design_command)


def _new_output(path) -> Path:
    path = Path(path)
    if path.exists():
        raise ValueError(f"output already exists: {path}; choose a new path")
    if not path.parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {path.parent}")
    return path


def _write(path: Path, data) -> None:
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_design_command(args: argparse.Namespace) -> int:
    try:
        return _run(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"design: {exc}", file=sys.stderr)
        return 1


def _run(args) -> int:
    from opentcad.design import load_design

    if args.design_command == "draft":
        from opentcad.assist.client import ChatClient, LLMError
        from opentcad.assist.design import draft_design
        out = _new_output(args.out)
        plan_out = _new_output(args.plan_out) if args.plan_out else None
        if plan_out is not None and plan_out.resolve() == out.resolve():
            raise ValueError("draft review output and plain plan output must be different files")
        evidence = None
        if args.feedback:
            path = Path(args.feedback)
            if path.stat().st_size > 80000:
                raise ValueError("feedback exceeds 80 KB; supply a smaller JSON evidence summary")
            evidence = json.loads(path.read_text())
        options = {key: value for key, value in
                   {"base_url": args.url, "model": args.model}.items() if value is not None}
        try:
            result = draft_design(args.request, client=ChatClient(**options),
                                  base=args.base, current=args.current, evidence=evidence,
                                  max_repairs=args.max_repairs)
        except LLMError as exc:
            raise ValueError(str(exc)) from exc
        _write(out, result.to_dict())
        if plan_out is not None and result.design is not None:
            _write(plan_out, result.design)
        print(f"Unaccepted design draft → {out}; every proposed value requires review.")
        if plan_out is not None:
            if result.design is None:
                print("No plain plan written: resolve questions or validation problems in the draft.",
                      file=sys.stderr)
                return 1
            print(f"Editable plan → {plan_out}; check it, resolve questions, then explicitly run it.")
        for question in result.to_dict()["questions"]:
            print(f"Unresolved: {question}", file=sys.stderr)
        for problem in result.problems:
            print(problem, file=sys.stderr)
        return 0 if result.ok else 1

    design = load_design(args.file)
    if args.design_command == "check":
        data = design.to_dict()
        unresolved = data.get("unresolved", [])
        print(f"{args.file}: schema checked; {len(data['variables'])} variable(s), "
              f"{len(data['targets'])} target(s), budget={data['search']['max_evaluations']}")
        print("Physics, mesh and analyses are fixed; target units are explicit with no conversion.")
        if unresolved:
            for question in unresolved:
                print(f"Unresolved: {question}", file=sys.stderr)
            return 1
        print("Ready for an explicit bounded run; scientific validity remains unverified.")
        return 0
    if args.design_command == "run":
        from opentcad.cli import _quiet_stdout
        from opentcad.design import run_design
        try:
            with _quiet_stdout(not args.verbose):
                result = run_design(design, args.out,
                                    log=lambda message: print(message, file=sys.stderr, flush=True))
        except Exception as exc:
            print(f"design run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if args.verbose:
                raise
            return 2
        print(f"Design search: {result.stop_reason}; {len(result.attempts)} candidate(s); "
              f"evidence → {result.outdir}")
        if result.best is not None:
            print(json.dumps({"best": {key: result.best[key] for key in
                                      ("index", "values", "metrics", "score")}},
                             indent=2, allow_nan=False))
        if result.stop_reason == "target_met":
            print("Targets met in the fixed numerical model; this is not calibration or fabrication approval.")
            return 0
        if result.stop_reason == "no_valid_candidates":
            print("All candidates failed validation, simulation or metric evaluation; inspect evidence.",
                  file=sys.stderr)
            return 2
        print("Targets remain unmet within this search; this does not prove infeasibility.", file=sys.stderr)
        return 1
    raise ValueError(f"unknown design command: {args.design_command}")
