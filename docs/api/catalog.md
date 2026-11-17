# Process catalog

Private records of materials, equipment and process flows.

For an introduction, see the [user guide](../catalog.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.catalog`: `Catalog`, `import_file`, `ImportResult`, `check_record`, `Assessment`, `Issue`, `runsheet`, `CatalogRecord`, `record_from_dict`, `record_revision`, `record_schema`, `Quantity`, `RecordRef`, `SourceRef`.

## Catalog

```python
class opentcad.catalog.Catalog(root: str | Path, *, create: bool = True)
```

A private filesystem collection; this class has no network or publishing path.

``get(id)`` selects the most recently put revision for browsing. Execution is
unsupported. Exports include exact revision resolutions for every dependency.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/store.py#L37)

### Catalog.init

```python
Catalog.init()
```

Create the folders of an empty collection (owner-only
permissions). Safe to call on an existing one. Returns the catalog.

### Catalog.put

```python
Catalog.put(record: CatalogRecord) -> RecordRef
```

Validate and store ``record`` as an immutable revision named by its
content hash, and make it the browsing head for its id. Returns the
pinned reference.

### Catalog.get

```python
Catalog.get(entity_id: str, revision: str | None = None) -> CatalogRecord
```

The record ``entity_id`` at ``revision``, or at its head if
``revision`` is None. Raises KeyError for an unknown revision and
ValueError if the stored bytes fail their integrity check.

### Catalog.list_records

```python
Catalog.list_records(kind: str | None = None) -> list[RecordRef]
```

References to the head revision of every record, optionally only
those of one ``kind`` (e.g. ``"process_flow"``).

### Catalog.import_file

```python
Catalog.import_file(path: str | Path)
```

Import a supported file (see ``import_file``) and store its records
and attachments. Nothing is stored if the import has errors. Returns
the ``ImportResult`` with ``refs`` set to the stored revisions.

### Catalog.check_flow

```python
Catalog.check_flow(entity_id: str, revision: str | None = None)
```

``check_record`` for a stored process flow, resolving its references
in this catalog. Raises ValueError if the record is not a process flow.

### Catalog.snapshot_attachment

```python
Catalog.snapshot_attachment(path: str | Path) -> SourceRef
```

Explicitly copy a local original; no retrieval from URIs occurs.

### Catalog.export_bundle

```python
Catalog.export_bundle(
    refs: list[RecordRef],
    *,
    include_attachments: bool = False,
) -> dict
```

A self-contained snapshot of ``refs`` and everything they reference,
with every reference pinned to an exact revision.

The bundle lists the records, their revisions, the roots and the
resolutions made. ``complete`` is False, with ``issues`` saying why,
if a reference is missing or cyclic. With ``include_attachments``
the referenced attachment files are embedded (base64).

## import_file

```python
opentcad.catalog.import_file(path: str | Path) -> ImportResult
```

Parse and validate the whole document without modifying any collection.

YAML uses SafeLoader with duplicate-key rejection. No code, attachments or
source references are executed or fetched. Existing canonical provenance is
preserved so portable exports keep the exact immutable record revisions.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/importers.py#L113)

## ImportResult

```python
class opentcad.catalog.ImportResult(
    *,
    records: list[EquipmentModelRecord | EquipmentInstanceRecord | MaterialRecord | MaterialProductRecord | MaterialLotRecord | ProcessFlowRecord] = list(),
    issues: list[Issue] = list(),
    source_sha256: str | None = None,
    refs: list[RecordRef] = list(),
    attachments: dict[str, str] = dict(),
) -> None
```

What an import produced: the records, any issues, the source file's
hash, and (after ``Catalog.import_file``) the stored ``refs``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L210)

### ImportResult.ok

```python
property ImportResult.ok: bool
```

True if no issue is an error.

## check_record

```python
opentcad.catalog.check_record(record, catalog=None) -> Assessment
```

Assess a record: is it structurally valid, and what is missing?

Gaps go into ``Assessment.issues``: unpinned or unresolvable
references, the wrong kind of referenced record, missing or out-of-date
calibration, and similar. ``compatibility`` is ``"incompatible"`` if a
declared conflict was found, ``"needs_information"`` if any issue is
above ``info``, and ``"no_declared_conflicts"`` otherwise. References
are resolved in ``catalog`` when one is given; without one they are
reported as unresolved.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/checks.py#L40)

## Assessment

```python
class opentcad.catalog.Assessment(
    *,
    structural_valid: bool,
    compatibility: Literal['needs_information', 'incompatible', 'no_declared_conflicts'] = 'needs_information',
    simulation: Literal['unsupported'] = 'unsupported',
    issues: list[Issue] = list(),
) -> None
```

The result of ``check_record``. ``simulation`` is always
``"unsupported"``: catalog records are not yet run as simulations.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L225)

## Issue

```python
class opentcad.catalog.Issue(
    *,
    code: str,
    message: str,
    path: str = '',
    severity: Literal['error', 'warning', 'info'] = 'warning',
) -> None
```

One finding: a machine-readable ``code``, a ``message``, where in the
record it applies (``path``) and its ``severity``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L201)

## runsheet

```python
opentcad.catalog.runsheet(record) -> str
```

Readable declared-order instructions preserving every graph edge and unknown.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/checks.py#L195)

## CatalogRecord

```python
opentcad.catalog.CatalogRecord = EquipmentModelRecord | EquipmentInstanceRecord | MaterialRecord | MaterialProductRecord | MaterialLotRecord | ProcessFlowRecord
```

## record_from_dict

```python
opentcad.catalog.record_from_dict(data: dict) -> CatalogRecord
```

Validate ``data`` as a catalog record of any kind (chosen by its
``kind`` field). Raises pydantic.ValidationError if it is not one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L186)

## record_revision

```python
opentcad.catalog.record_revision(record: CatalogRecord) -> str
```

Content hash of a record: the digest of its canonical JSON. Equal
records have equal revisions.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/store.py#L14)

## record_schema

```python
opentcad.catalog.record_schema() -> dict
```

JSON Schema for catalog records, covering every kind.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L194)

## Quantity

```python
class opentcad.catalog.Quantity(
    *,
    value: float | None = None,
    unit: str | None = None,
    uncertainty: float | None = None,
    sources: list[SourceRef] = list(),
    conditions: dict[str, str] = dict(),
) -> None
```

A measured or specified value with its unit, uncertainty (same unit,
≥ 0), sources and the conditions it holds under. Any part may be
unknown (None); checks report what is missing.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L34)

## RecordRef

```python
class opentcad.catalog.RecordRef(*, id: str, revision: str | None = None) -> None
```

A reference to record ``id``, pinned to a content-hash ``revision``
or, if None, following the browsing head.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L27)

## SourceRef

```python
class opentcad.catalog.SourceRef(
    *,
    uri: str,
    locator: str | None = None,
    sha256: str | None = None,
    description: str | None = None,
) -> None
```

Where a value came from: a URI (``attachment:sha256:…`` for stored
files), an optional locator within it (page, table), its hash and a
description.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/catalog/models.py#L17)
