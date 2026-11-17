"""Offline JSON/YAML and narrowly mapped inventory CSV import with source locations."""

from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from ._canonical import digest
from .models import ImportResult, Issue, RecordRef, SourceRef, record_from_dict
from .store import record_revision


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate mapping key {key!r}; resolve the ambiguity before import")
        result[key] = value
    return result


class _UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node):
    return _unique_pairs(loader.construct_pairs(node, deep=True))


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


CSV_COLUMNS = {
    "id", "kind", "title", "manufacturer", "model", "operations", "facility",
    "vendor", "product", "generic_material", "lot", "model_id", "product_id",
}
CSV_PAYLOAD_COLUMNS = {
    "equipment_model": {"manufacturer", "model", "operations"},
    "equipment_instance": {"model_id", "facility", "operations"},
    "material_product": {"vendor", "product", "generic_material"},
    "material_lot": {"product_id", "lot"},
}


def _csv_records(text, source):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"id", "kind", "title"} <= set(reader.fieldnames):
        raise ValueError("Inventory CSV requires id, kind, title columns; use canonical JSON/YAML for flows")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV has duplicate column names; provide unique headers")
    unknown = set(reader.fieldnames) - CSV_COLUMNS
    if unknown:
        raise ValueError(f"Unsupported CSV columns {sorted(unknown)}; map to canonical JSON/YAML explicitly")
    records = []
    for row in reader:
        line = reader.line_num
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"CSV row {line} has a different number of fields than the header")
        kind = row["kind"].strip()
        allowed = CSV_PAYLOAD_COLUMNS.get(kind)
        if allowed is None:
            raise ValueError(f"CSV row {line}: unsupported kind {kind!r}; use canonical JSON/YAML")
        payload = {}
        provenance = {}
        for field, raw in row.items():
            value = raw.strip()
            if field in {"id", "kind", "title"}:
                target = field
            elif not value:
                continue
            elif field not in allowed:
                raise ValueError(f"CSV row {line}: {field} does not apply to {kind}")
            elif field == "operations":
                target = "payload.supported_operations" if kind == "equipment_instance" else "payload.operations"
                payload[target.split(".")[1]] = [part.strip() for part in value.split(";") if part.strip()]
            elif field in {"model_id", "product_id"}:
                target = f"payload.{field.removesuffix('_id')}_ref"
                payload[target.split(".")[1]] = {"id": value}
            else:
                target = f"payload.{field}"
                payload[field] = value
            provenance[target] = [source.model_copy(update={"locator": f"row {line}, column {field}"}).model_dump(mode="json")]
        records.append({"schema_version": 1, "kind": kind, "id": row["id"].strip(),
                        "title": row["title"].strip(), "payload": payload,
                        "sources": [source.model_dump(mode="json")], "provenance": provenance})
    if not records:
        raise ValueError("CSV contains no inventory rows")
    return records


def _field_provenance(data, source, prefix=""):
    result = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "provenance":
                continue
            path = f"{prefix}.{key}" if prefix else key
            result.update(_field_provenance(value, source, path))
    elif isinstance(data, list) and data:
        for index, value in enumerate(data):
            result.update(_field_provenance(value, source, f"{prefix}.{index}"))
    else:
        result[prefix] = [source.model_copy(update={"locator": prefix}).model_dump(mode="json")]
    return result


def import_file(path: str | Path) -> ImportResult:
    """Parse and validate the whole document without modifying any collection.

    YAML uses SafeLoader with duplicate-key rejection. No code, attachments or
    source references are executed or fetched. Existing canonical provenance is
    preserved so portable exports keep the exact immutable record revisions.
    """
    source_path = Path(path)
    sha = None
    try:
        raw = source_path.read_bytes()
        sha = digest(raw)
        suffix = source_path.suffix.lower()
        if suffix not in {".json", ".yaml", ".yml", ".csv"}:
            return ImportResult(source_sha256=sha, issues=[Issue(
                code="unsupported_format", severity="error", path=str(source_path),
                message="Unsupported format. Original is unchanged. Export canonical JSON/YAML or inventory CSV; PDF/Word/OCR/native formats need a reviewed external extraction.",
            )])
        text = raw.decode("utf-8-sig")
        source = SourceRef(uri=source_path.resolve().as_uri(), sha256=sha,
                           description="Direct structured import; no scientific validation")
        wrapper = None
        if suffix == ".csv":
            data = _csv_records(text, source)
        else:
            parsed = (json.loads(text, object_pairs_hook=_unique_pairs) if suffix == ".json"
                      else yaml.load(text, Loader=_UniqueLoader))
            if isinstance(parsed, dict) and "records" in parsed:
                wrapper = parsed
                # The fields Catalog.export_bundle writes, plus "resolutions".
                extra = set(parsed) - {"schema_version", "mode", "complete", "issues",
                                       "records", "revisions", "roots", "origin_revisions",
                                       "resolutions", "attachments"}
                if extra:
                    raise ValueError(f"Unknown bundle fields {sorted(extra)}")
                if type(parsed.get("schema_version")) is not int or parsed["schema_version"] != 1:
                    raise ValueError("Bundle schema_version must be integer 1")
                if parsed.get("mode", "resolved_snapshot") != "resolved_snapshot":
                    raise ValueError(f"Unsupported bundle mode {parsed.get('mode')!r}")
                if not isinstance(parsed.get("complete", True), bool):
                    raise ValueError("Bundle complete must be true or false")
                data = parsed["records"]
                if not isinstance(data, list):
                    raise ValueError("Bundle records must be a list")
            elif isinstance(parsed, dict):
                data = [parsed]
            else:
                raise ValueError("Expected a canonical record object or {schema_version: 1, records: [...]} bundle")
        if not data:
            raise ValueError("Import contains no records")
        # A bundle that pins revisions (an export) holds exact snapshots: adding
        # provenance would change their hashes and break its own pins. A plain
        # {schema_version, records} bundle (e.g. an accepted draft) gets import
        # provenance like a single record.
        pinned = wrapper is not None and any(
            k in wrapper for k in ("revisions", "roots", "origin_revisions", "resolutions"))
        records = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"records[{index}] must be an object")
            if type(item.get("schema_version", 1)) is not int:
                raise ValueError(f"records[{index}].schema_version must be integer 1")
            item = dict(item)
            if not pinned and not item.get("provenance"):
                located = source.model_copy(update={"locator": f"records[{index}]"})
                item["provenance"] = _field_provenance(item, located, f"records[{index}]")
                item["sources"] = list(item.get("sources", [])) + [located.model_dump(mode="json")]
            records.append(record_from_dict(item))
        attachments = {}
        if wrapper:
            known = {(r.id, record_revision(r)) for r in records}
            for field in ("revisions", "roots"):
                for ref_data in wrapper.get(field, []):
                    ref = RecordRef.model_validate(ref_data)
                    if (ref.id, ref.revision) not in known:
                        raise ValueError(f"Bundle {field} references absent or changed record {ref.id}")
            resolutions = wrapper.get("resolutions", {})
            if not isinstance(resolutions, dict):
                raise ValueError("Bundle resolutions must be an object")
            for key, ref_data in resolutions.items():
                ref = RecordRef.model_validate(ref_data)
                if (ref.id, ref.revision) not in known:
                    raise ValueError(f"Bundle resolution {key} points outside pinned records")
            for entry in wrapper.get("origin_revisions", []):
                if not isinstance(entry, dict) or set(entry) != {"original", "exported"}:
                    raise ValueError("origin_revisions entries need exactly original and exported")
                RecordRef.model_validate(entry["original"])   # the source collection's revision
                ref = RecordRef.model_validate(entry["exported"])
                if (ref.id, ref.revision) not in known:
                    raise ValueError(f"Bundle origin_revisions references absent record {ref.id}")
            export_issues = [Issue.model_validate(i) for i in wrapper.get("issues", [])]
            for attachment in wrapper.get("attachments", []):
                if set(attachment) != {"sha256", "data_base64"}:
                    raise ValueError("Attachment requires only sha256 and data_base64")
                ref = RecordRef(id="attachment", revision=attachment["sha256"])
                decoded = base64.b64decode(attachment["data_base64"], validate=True)
                if digest(decoded) != ref.revision:
                    raise ValueError("Attachment hash does not match supplied bytes")
                attachments[ref.revision] = attachment["data_base64"]
        issues = []
        if wrapper and wrapper.get("complete") is False:
            # Importable (each record is valid), but the export said it could
            # not pin everything; carry that forward rather than hide it.
            issues.append(Issue(code="incomplete_bundle", message=(
                "The bundle was exported incomplete; its export issues follow. "
                "Check flows after import.")))
            issues.extend(i.model_copy(update={"severity": "warning"}) for i in export_issues)
        ids = [r.id for r in records]
        if len(set(ids)) < len(ids):
            issues.append(Issue(code="multiple_revisions", message="Repeated IDs are retained as separate revisions; the last listed revision becomes the browsing head."))
        return ImportResult(records=records, issues=issues, source_sha256=sha, attachments=attachments)
    except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError, ValidationError) as exc:
        return ImportResult(source_sha256=sha, issues=[Issue(
            code="invalid_import", severity="error", path=str(source_path),
            message=f"Import rejected without storing records: {exc}",
        )])
