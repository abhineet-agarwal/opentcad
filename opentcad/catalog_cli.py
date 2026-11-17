"""Local catalog commands. Importing this module never loads a simulator."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_catalog_parser(subparsers) -> None:
    parser = subparsers.add_parser("catalog", help="manage a local descriptive catalog")
    parser.add_argument("--root", "--store", dest="root", default=".opentcad/catalog",
                        help="local collection directory (default: .opentcad/catalog)")
    commands = parser.add_subparsers(dest="catalog_command", required=True)
    commands.add_parser("init", help="initialize a private local collection")
    imp = commands.add_parser("import", help="import a JSON, YAML or CSV record bundle")
    imp.add_argument("file")
    attach = commands.add_parser("attach", help="snapshot a local datasheet or other opaque attachment")
    attach.add_argument("file")
    listing = commands.add_parser("list", help="list current records")
    listing.add_argument("--kind")
    show = commands.add_parser("show", help="show a record as JSON")
    show.add_argument("id")
    show.add_argument("--revision")
    check = commands.add_parser("check", help="check references and descriptive flow support")
    check.add_argument("id", nargs="?")
    export = commands.add_parser("export", help="export a portable JSON bundle or flow runsheet")
    export.add_argument("ids", nargs="*", help="record identifiers (default: all current records)")
    export.add_argument("-o", "--out", required=True)
    export.add_argument("--flow", help="flow identifier for a runsheet export")
    export.add_argument("--format", choices=["json", "markdown"], default="json")
    export.add_argument("--include-attachments", action="store_true",
                        help="explicitly copy referenced local snapshots into JSON export")
    export.add_argument("--force", action="store_true", help="replace an existing output file")
    draft = commands.add_parser("draft", help="ask a configured model for a reviewable catalog draft")
    draft.add_argument("request")
    draft.add_argument("-o", "--out", required=True)
    draft.add_argument("--url", help="OpenAI-compatible model server URL")
    draft.add_argument("--model", help="model name at that server")
    draft.add_argument("--force", action="store_true", help="replace an existing output file")
    parser.set_defaults(func=run_catalog)


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def run_catalog(args: argparse.Namespace) -> int:
    try:
        return _run_catalog(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"catalog: {exc}", file=sys.stderr)
        return 1


def _run_catalog(args: argparse.Namespace) -> int:
    from opentcad.catalog import Catalog, check_record, runsheet

    if args.catalog_command == "draft":
        from opentcad.assist.client import ChatClient, LLMError
        from opentcad.assist.catalog import draft_catalog
        options = {k: v for k, v in {"base_url": args.url, "model": args.model}.items()
                   if v is not None}
        _check_output(args.out, args.force)
        try:
            result = draft_catalog(args.request, client=ChatClient(**options))
        except LLMError as exc:
            raise ValueError(str(exc)) from exc
        _write_output(args.out, json.dumps(result.to_dict(), indent=2) + "\n", args.force)
        print(f"Reviewable private draft → {args.out}; all generated values require review.")
        return 0 if result.ok else 1

    command = args.catalog_command
    # Only commands that write create a collection; reading a missing one is
    # an error rather than leaving an empty .opentcad/catalog behind.
    catalog = Catalog(args.root, create=command in {"init", "import", "attach"})
    if command == "init":
        print(f"Private local catalog: {Path(args.root).resolve()}")
        return 0
    if command == "import":
        result = catalog.import_file(args.file)
        _print({"records": [_json(r) for r in result.refs],
                "source_sha256": result.source_sha256,
                "issues": [_json(i) for i in result.issues]})
        return 1 if any(i.severity == "error" for i in result.issues) else 0
    if command == "attach":
        _print(_json(catalog.snapshot_attachment(args.file)))
        return 0
    if command == "list":
        _print([{"ref": _json(ref), "kind": catalog.get(ref.id, ref.revision).kind,
                 "title": catalog.get(ref.id, ref.revision).title}
                for ref in catalog.list_records(kind=args.kind)])
        return 0
    if command == "show":
        _print(_json(catalog.get(args.id, args.revision)))
        return 0
    if command == "check":
        records = ([catalog.get(args.id)] if args.id else
                   [catalog.get(r.id, r.revision) for r in catalog.list_records()])
        reports = [{"id": record.id, **_json(check_record(record, catalog))}
                   for record in records]
        _print(reports)
        return 0 if all(r["structural_valid"] for r in reports) else 1
    if command == "export":
        complete = True
        if args.flow:
            if args.ids:
                raise ValueError("choose record identifiers or --flow, not both")
            if args.format == "markdown" and args.include_attachments:
                raise ValueError("attachments can only be included in JSON bundles")
            record = catalog.get(args.flow)
            if record.kind != "process_flow":
                raise ValueError("--flow requires a process_flow record")
            if args.format == "markdown":
                content = runsheet(record)
            else:
                bundle = catalog.export_bundle([_ref(record)],
                                               include_attachments=args.include_attachments)
                complete = bundle.get("complete", True)
                content = json.dumps(bundle, indent=2) + "\n"
        else:
            if args.format != "json":
                raise ValueError("record bundles export as JSON; use --flow ID --format markdown for a runsheet")
            refs = ([_ref(catalog.get(id)) for id in args.ids] if args.ids else
                    catalog.list_records())
            bundle = catalog.export_bundle(refs, include_attachments=args.include_attachments)
            complete = bundle.get("complete", True)
            content = json.dumps(bundle, indent=2) + "\n"
        _write_output(args.out, content, args.force)
        print(f"Export → {args.out}")
        if not complete:
            print("catalog: exported an incomplete descriptive snapshot; review its issues", file=sys.stderr)
        return 0 if complete else 1
    raise ValueError(f"unknown catalog command: {command}")


def _json(value):
    return value.model_dump(mode="json")


def _ref(record):
    from opentcad.catalog import RecordRef
    return RecordRef(id=record.id)


def _check_output(path, force: bool) -> None:
    if Path(path).exists() and not force:
        raise ValueError(f"output already exists: {path}; choose another path or use --force")


def _write_output(path, content: str, force: bool) -> None:
    with Path(path).open("w" if force else "x") as stream:
        stream.write(content)
