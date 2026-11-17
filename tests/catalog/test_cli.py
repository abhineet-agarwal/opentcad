"""Real command dispatch and disk persistence, without simulation backends."""
import json
from pathlib import Path

from opentcad.cli import main

FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "catalog"


def invoke(root, *args):
    return main(["catalog", "--root", str(root), *map(str, args)])


def test_import_repeat_export_and_runsheet(tmp_path, capsys):
    root = tmp_path / "collection"
    assert invoke(root, "init") == 0
    for filename in ("equipment.csv", "resist.yaml", "branch_flow.yaml"):
        assert invoke(root, "import", FIXTURES / filename) == 0
    capsys.readouterr()
    assert invoke(root, "list") == 0
    first = json.loads(capsys.readouterr().out)
    assert len(first) == 9
    assert invoke(root, "import", FIXTURES / "branch_flow.yaml") == 0
    capsys.readouterr()
    assert invoke(root, "list") == 0
    assert json.loads(capsys.readouterr().out) == first
    assert invoke(root, "show", "demo:resist-split") == 0
    flow = json.loads(capsys.readouterr().out)
    assert flow["payload"]["samples"][-1]["parent_ids"] == ["coated-0"]
    assert invoke(root, "check", "demo:resist-split") == 0
    report = json.loads(capsys.readouterr().out)[0]
    assert report["structural_valid"]
    assert report["simulation"] == "unsupported"
    assert report["compatibility"] == "needs_information"
    assert report["issues"]
    bundle_path = tmp_path / "export.json"
    assert invoke(root, "export", "demo:resist-split", "-o", bundle_path) == 0
    bundle = json.loads(bundle_path.read_text())
    assert len(bundle["records"]) == 9
    assert "attachments" not in bundle
    second_root = tmp_path / "imported"
    assert invoke(second_root, "import", bundle_path) == 0
    sheet = tmp_path / "runsheet.md"
    assert invoke(root, "export", "--flow", "demo:resist-split", "--format", "markdown",
                  "-o", sheet) == 0
    assert "bake-b" in sheet.read_text()
    assert "ambiguous" in sheet.read_text().lower()


def test_missing_reference_is_distinct_from_descriptive_support(tmp_path, capsys):
    root = tmp_path / "collection"
    assert invoke(root, "import", FIXTURES / "branch_flow.yaml") == 0
    capsys.readouterr()
    assert invoke(root, "check", "demo:resist-split") == 1
    report = json.loads(capsys.readouterr().out)[0]
    assert not report["structural_valid"]
    assert report["simulation"] == "unsupported"
    assert any("reference" in i["code"] for i in report["issues"])
    assert invoke(root, "export", "-o", tmp_path / "bad.json") == 1
    assert not json.loads((tmp_path / "bad.json").read_text())["complete"]


def test_unsupported_and_invalid_import_do_not_add_records(tmp_path, capsys):
    root = tmp_path / "collection"
    assert invoke(root, "import", FIXTURES / "unknown.native") == 1
    report = json.loads(capsys.readouterr().out)
    assert report["records"] == []
    assert report["issues"][0]["severity"] == "error"
    assert invoke(root, "list") == 0
    assert json.loads(capsys.readouterr().out) == []
    assert invoke(root, "show", "missing") == 1
    assert "missing" in capsys.readouterr().err


def test_cli_draft_writes_review_artifact_without_store(tmp_path, monkeypatch):
    from opentcad.assist.catalog import CatalogDraft, Proposal
    from opentcad.catalog import record_from_dict

    proposal = Proposal(records=[record_from_dict({"id": "local:resist", "kind": "material_product",
                                                 "title": "My resist", "payload": {}})],
                        questions=["Which vendor and datasheet revision?"])
    monkeypatch.setattr("opentcad.assist.catalog.draft_catalog",
                        lambda request, client: CatalogDraft(proposal=proposal, attempts=1))
    root = tmp_path / "not-created"
    out = tmp_path / "draft.json"
    assert invoke(root, "draft", "Add my resist", "-o", out) == 0
    artifact = json.loads(out.read_text())
    assert artifact["status"] == "unaccepted"
    assert artifact["questions"]
    assert artifact["bundle"]["records"][0]["visibility"] == "private"
    assert not root.exists()


def test_exported_bundle_round_trips_with_identical_pins(tmp_path, capsys):
    root = tmp_path / "collection"
    for filename in ("equipment.csv", "resist.yaml", "branch_flow.yaml"):
        assert invoke(root, "import", FIXTURES / filename) == 0
    bundle_path = tmp_path / "export.json"
    assert invoke(root, "export", "-o", bundle_path) == 0
    bundle = json.loads(bundle_path.read_text())
    assert bundle["complete"] and bundle["mode"] == "resolved_snapshot"
    second = tmp_path / "second"
    capsys.readouterr()
    assert invoke(second, "import", bundle_path) == 0
    report = json.loads(capsys.readouterr().out)
    # The importer stores the snapshots unchanged: same ids, same revisions.
    expected = sorted((r["id"], r["revision"]) for r in bundle["revisions"])
    assert sorted((r["id"], r["revision"]) for r in report["records"]) == expected
    # The pinned flow resolves entirely inside the second collection.
    capsys.readouterr()
    assert invoke(second, "check", "demo:resist-split") == 0
    flow_report = json.loads(capsys.readouterr().out)[0]
    assert not [i for i in flow_report["issues"] if i["code"] == "missing_reference"]


def test_incomplete_bundle_imports_with_its_issues_as_warnings(tmp_path, capsys):
    root = tmp_path / "collection"
    assert invoke(root, "import", FIXTURES / "branch_flow.yaml") == 0
    assert invoke(root, "export", "-o", tmp_path / "partial.json") == 1
    capsys.readouterr()
    assert invoke(tmp_path / "other", "import", tmp_path / "partial.json") == 0
    issues = json.loads(capsys.readouterr().out)["issues"]
    assert issues[0]["code"] == "incomplete_bundle"
    assert any(i["code"] == "missing_reference" and i["severity"] == "warning"
               for i in issues)


def test_plain_bundle_gets_provenance_but_pinned_bundle_is_unchanged(tmp_path):
    from opentcad.catalog import import_file, record_from_dict, record_revision
    record = {"id": "local:r", "kind": "material_product", "title": "R", "payload": {}}
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"schema_version": 1, "records": [record]}))
    imported = import_file(plain).records[0]
    assert imported.provenance and imported.sources          # import origin recorded
    rev = record_revision(record_from_dict(record))
    pinned = tmp_path / "pinned.json"
    pinned.write_text(json.dumps({"schema_version": 1, "records": [record],
                                  "revisions": [{"id": "local:r", "revision": rev}]}))
    result = import_file(pinned)
    assert result.ok and record_revision(result.records[0]) == rev


def test_reading_a_missing_catalog_does_not_create_it(tmp_path, capsys):
    root = tmp_path / "nowhere"
    for command in (["list"], ["show", "x"], ["check"], ["export", "-o", tmp_path / "o.json"]):
        assert invoke(root, *command) == 1
        assert "no catalog at" in capsys.readouterr().err
    assert not root.exists()
    assert invoke(root, "init") == 0 and root.is_dir()
