"""Private local content-addressed revisions and explicit portable exports."""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from ._canonical import canonical_bytes, digest, immutable_write
from .models import CatalogRecord, Issue, RecordRef, SourceRef, record_from_dict


def record_revision(record: CatalogRecord) -> str:
    return digest(canonical_bytes(record.model_dump(mode="json")))


def references(record: CatalogRecord):
    """Yield only declared entity references; source URIs are never followed."""
    payload = record.payload
    if record.kind == "equipment_instance" and payload.model_ref:
        yield "payload.model_ref", payload.model_ref
    if record.kind == "material_lot" and payload.product_ref:
        yield "payload.product_ref", payload.product_ref
    if record.kind == "process_flow":
        for index, step in enumerate(payload.steps):
            if step.tool_ref:
                yield f"payload.steps.{index}.tool_ref", step.tool_ref
            for n, ref in enumerate(step.material_refs):
                yield f"payload.steps.{index}.material_refs.{n}", ref
        for index, ref in enumerate(payload.mask_refs):
            yield f"payload.mask_refs.{index}", ref


class Catalog:
    """A private filesystem collection; this class has no network or publishing path.

    ``get(id)`` selects the most recently put revision for browsing. Execution is
    unsupported. Exports include exact revision resolutions for every dependency.
    """

    def __init__(self, root: str | Path, *, create: bool = True):
        """Open the collection at ``root``. With ``create=False`` a missing
        collection is an error instead of being created (read-only uses)."""
        self.root = Path(root).expanduser().resolve()
        if create:
            self.init()
        elif not all((self.root / name).is_dir() for name in ("records", "heads")):
            raise FileNotFoundError(
                f"no catalog at {self.root}; run `opentcad catalog --root {root} init` "
                f"or import into it first")

    def init(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("records", "heads", "attachments"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        return self

    def _key(self, entity_id: str) -> str:
        return digest(entity_id.encode("utf-8"))

    def put(self, record: CatalogRecord) -> RecordRef:
        # Revalidate nested mutable containers too, then detach caller-owned data.
        record = record_from_dict(record.model_dump(mode="json"))
        revision = record_revision(record)
        key = self._key(record.id)
        immutable_write(self.root / "records" / key / f"{revision}.json",
                        canonical_bytes(record.model_dump(mode="json")))
        ref = RecordRef(id=record.id, revision=revision)
        head = canonical_bytes(ref.model_dump(mode="json"))
        fd, name = tempfile.mkstemp(prefix=".head-", dir=self.root / "heads")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(head)
            os.replace(name, self.root / "heads" / f"{key}.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return ref

    def _head(self, entity_id: str) -> RecordRef:
        import json

        path = self.root / "heads" / f"{self._key(entity_id)}.json"
        if not path.exists():
            raise KeyError(f"Unknown catalog entity: {entity_id}")
        ref = RecordRef.model_validate(json.loads(path.read_bytes()))
        if ref.id != entity_id or ref.revision is None:
            raise ValueError(f"Corrupt catalog head for {entity_id}")
        return ref

    def get(self, entity_id: str, revision: str | None = None) -> CatalogRecord:
        import json

        if revision is None:
            revision = self._head(entity_id).revision
        revision = RecordRef(id=entity_id, revision=revision).revision
        path = self.root / "records" / self._key(entity_id) / f"{revision}.json"
        if not path.exists():
            raise KeyError(f"Unknown revision {entity_id}@{revision}")
        raw = path.read_bytes()
        if digest(raw) != revision:
            raise ValueError(f"Integrity failure for {entity_id}@{revision}")
        record = record_from_dict(json.loads(raw))
        if record.id != entity_id or record_revision(record) != revision:
            raise ValueError(f"Identity or canonical integrity failure for {entity_id}@{revision}")
        return record

    def list_records(self, kind: str | None = None) -> list[RecordRef]:
        import json

        refs = []
        for path in sorted((self.root / "heads").glob("*.json")):
            ref = RecordRef.model_validate(json.loads(path.read_bytes()))
            if path.stem != self._key(ref.id) or ref.revision is None:
                raise ValueError(f"Corrupt catalog head: {path}")
            record = self.get(ref.id, ref.revision)
            if kind is None or record.kind == kind:
                refs.append(ref)
        return sorted(refs, key=lambda ref: ref.id)

    def import_file(self, path: str | Path):
        from .importers import import_file

        result = import_file(path)
        if not result.ok:
            return result
        for sha, encoded in result.attachments.items():
            immutable_write(self.root / "attachments" / sha, base64.b64decode(encoded, validate=True))
        refs = [self.put(record) for record in result.records]
        return result.model_copy(update={"refs": refs})

    def check_flow(self, entity_id: str, revision: str | None = None):
        from .checks import check_record

        record = self.get(entity_id, revision)
        if record.kind != "process_flow":
            raise ValueError(f"{entity_id} is not a process_flow")
        return check_record(record, self)

    def snapshot_attachment(self, path: str | Path) -> SourceRef:
        """Explicitly copy a local original; no retrieval from URIs occurs."""
        source = Path(path)
        raw = source.read_bytes()
        sha = digest(raw)
        immutable_write(self.root / "attachments" / sha, raw)
        return SourceRef(uri=f"attachment:sha256:{sha}", sha256=sha,
                         description=source.name)

    def export_bundle(self, refs: list[RecordRef], *, include_attachments: bool = False) -> dict:
        records = {}
        resolved = {}
        visiting = set()
        origins = []
        issues = []
        roots = []

        def visit(ref):
            try:
                record = self.get(ref.id, ref.revision)
            except KeyError as exc:
                issues.append(Issue(code="missing_reference", severity="error", message=str(exc)))
                return None
            original = RecordRef(id=record.id, revision=record_revision(record))
            key = (original.id, original.revision)
            if key in resolved:
                return resolved[key]
            if key in visiting:
                issues.append(Issue(code="reference_cycle", severity="error", message=f"Entity reference cycle at {ref.id}; a complete recursively hash-pinned snapshot cannot be constructed."))
                return None
            visiting.add(key)
            data = record.model_dump(mode="json")
            for path, dependency in references(record):
                dependency_pin = visit(dependency)
                if dependency_pin is not None:
                    parts = path.split(".")
                    target = data
                    for part in parts[:-1]:
                        target = target[int(part)] if isinstance(target, list) else target[part]
                    # The last part is a list index for material_refs / mask_refs.
                    last = int(parts[-1]) if isinstance(target, list) else parts[-1]
                    target[last] = dependency_pin.model_dump(mode="json")
            snapshot = record_from_dict(data)
            pinned = RecordRef(id=snapshot.id, revision=record_revision(snapshot))
            records[(pinned.id, pinned.revision)] = snapshot
            resolved[key] = pinned
            origins.append({"original": original.model_dump(mode="json"),
                            "exported": pinned.model_dump(mode="json")})
            visiting.remove(key)
            return pinned

        for ref in refs:
            pin = visit(ref)
            if pin is not None:
                roots.append(pin.model_dump(mode="json"))
        bundle = {
            "schema_version": 1,
            "mode": "resolved_snapshot",
            "complete": not issues,
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "records": [r.model_dump(mode="json") for _, r in sorted(records.items())],
            "revisions": [RecordRef(id=r.id, revision=record_revision(r)).model_dump(mode="json")
                          for _, r in sorted(records.items())],
            "roots": roots,
            "origin_revisions": origins,
        }
        if include_attachments:
            hashes = set()

            def scan(value):
                if isinstance(value, dict):
                    uri = value.get("uri", "")
                    if isinstance(uri, str) and uri.startswith("attachment:sha256:"):
                        sha = uri.removeprefix("attachment:sha256:")
                        # Validate hashes before using them in any path.
                        RecordRef(id="attachment", revision=sha)
                        hashes.add(sha)
                    for item in value.values():
                        scan(item)
                elif isinstance(value, list):
                    for item in value:
                        scan(item)

            scan(bundle["records"])
            attachments = []
            for sha in sorted(hashes):
                raw = (self.root / "attachments" / sha).read_bytes()
                if digest(raw) != sha:
                    raise ValueError(f"Attachment integrity failure: {sha}")
                attachments.append({"sha256": sha, "data_base64": base64.b64encode(raw).decode()})
            bundle["attachments"] = attachments
        return bundle
