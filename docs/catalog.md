# Private local process catalog

OpenTCAD's local catalog stores versioned descriptive materials, products, lots,
equipment and process graphs. It imports structured data, reports missing context,
and exports reviewable snapshots and runsheets. It does not execute a process graph,
predict tool performance, operate equipment or publish records. The broader
[open materials platform](open_materials_platform.md) remains a proposal.

The catalog requires the normal Pydantic and YAML dependencies; no simulator or LLM
service is needed for import, check or export. From a checkout, use `python -m
opentcad.cli` if the `opentcad` command is not installed.

## Start with the complete example

```sh
opentcad catalog --root /tmp/my-catalog init
opentcad catalog --root /tmp/my-catalog import examples/catalog/equipment.csv
opentcad catalog --root /tmp/my-catalog import examples/catalog/resist.yaml
opentcad catalog --root /tmp/my-catalog import examples/catalog/branch_flow.yaml
opentcad catalog --root /tmp/my-catalog list --kind material_product
opentcad catalog --root /tmp/my-catalog show demo:resist-split
opentcad catalog --root /tmp/my-catalog check demo:resist-split
opentcad catalog --root /tmp/my-catalog export demo:resist-split -o /tmp/snapshot.json
opentcad catalog --root /tmp/my-catalog export --flow demo:resist-split --format markdown -o /tmp/runsheet.md
```

`--root` (also `--store`) selects the collection; the default is `.opentcad/catalog`
relative to the current directory. Only `init`, `import` and `attach` create a
collection; `list`, `show`, `check` and `export` on a missing one report an error
instead of leaving an empty directory behind. Every record is private. The fictional CC0
[fixtures](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/catalog/README.md) preserve a split, sample parents, planned
metrology and an intentionally ambiguous bake duration. They supply no calibration
or measured result. Adapt their structure to your own records; their values are not
approved tool settings.

## What the checks mean

`check` reports structural validity separately from compatibility and simulation:

| Field | Meaning |
| --- | --- |
| `structural_valid` | Declared references and graph structure pass the implemented checks |
| `compatibility: needs_information` | Context such as units, tool restrictions, unresolved settings or calibration is missing |
| `compatibility: incompatible` | A declared operation conflicts with the tool's declared supported operations |
| `compatibility: no_declared_conflicts` | Implemented comparisons found no declared conflict; this is not a safety or validation claim |
| `simulation: unsupported` | This catalog has no process-graph simulation adapter |

Exit status 0 from `check` means structural checks passed, including a descriptive
flow with unknown compatibility. Exit 1 means structural problems remain. Read the
issues, compatibility and unsupported simulation fields before drawing conclusions.
Importing a flow before its inventory is allowed; checking then identifies missing
references. No check supplies missing physics, approves a recipe or establishes a
calibrated relationship between settings and sample state.

## Supported inputs and typed records

| Input | Current support |
| --- | --- |
| JSON / YAML | One typed record, or `{schema_version: 1, records: [...]}`; canonical exports can be imported |
| CSV | Flat equipment/product/lot inventory using the columns below; not graph or curve extraction |
| Datasheet PDF, scan, image, Word, XLSX, native tool export | Opaque attachment only; no OCR, table extraction, proprietary parser or remote retrieval |
| Unknown input extension | Actionable unsupported-format issue; no accepted records |

CSV columns are `kind,id,title,manufacturer,model,operations,facility,model_id,vendor,
product,generic_material,lot,product_id`. Operations use semicolons. Blank optional
cells remain unspecified. Rich properties, conditions, sources, calibration and
process graphs belong in JSON or YAML. Unknown schema fields are errors, rather
than silently discarded. See [equipment.csv](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/catalog/equipment.csv).

The current kinds are `material`, `material_product`, `material_lot`,
`equipment_model`, `equipment_instance` and `process_flow`. All have `schema_version`,
`id`, `kind`, `title`, `payload`, `sources`, optional `license`, private `visibility`,
`unresolved` and field-level `provenance`. Missing license does not establish rights
to redistribute. Reference a model from an installed tool with `model_ref`, and a
product from a lot with `product_ref`; do not flatten those distinctions.

Quantities use `{value, unit, uncertainty, sources, conditions}`. A null value or
unknown unit stays unresolved. This slice does not provide universal dimensional
analysis or unit conversion. Steps retain parameter units, tool/material references,
input/output samples, sources and unresolved questions. Typed edges preserve sequence,
split, branch, merge, rework and metrology links. No backend reorders them for execution.

```yaml
schema_version: 1
id: local:my-resist
kind: material_product
title: My lab's resist product
sources: [{uri: 'attachment:sha256:REPLACE_WITH_REAL_HASH', locator: 'page 2, table 1'}]
unresolved: [Vendor formulation and local calibration are not supplied.]
payload:
  generic_material: Photoresist
  vendor: null
  product: null
  properties: {}
```

Replace the placeholder source with your actual source or remove it until available.
Use `python -c 'from opentcad.catalog import record_schema; import json;
print(json.dumps(record_schema(), indent=2))'` for the complete schema.

## Revisions, attachments and exports

Records have SHA256 revisions derived from canonical content. Reimporting identical
input reuses the revision. Editing a record with the same identifier creates another
immutable revision; browsing without `--revision` selects the current head. Different
identifiers remain distinct: this slice does not guess aliases or merge duplicates.
`show ID --revision HASH` retrieves an earlier record. The stored source hash and
locators document import origin, without making extracted claims scientifically valid.

To retain an original datasheet or native file explicitly:

```sh
opentcad catalog --root /tmp/my-catalog attach my-datasheet.pdf
```

Copy the returned `SourceRef` into the relevant record's `sources` or `datasheets`
and import that revision. `attach` snapshots bytes by SHA256; it does not parse the
file or follow URLs. Importing `.pdf` as a record is unsupported. Existing source
URIs remain references unless you explicitly attach the original.

JSON exports include dependency records and pinned reference resolutions as derived
snapshots; original floating-reference revisions remain unchanged. Snapshot hashes
can therefore differ from the original record hashes. `complete` describes dependency
resolution, not scientific completeness. Missing references remain in an incomplete
snapshot with issues; the CLI writes that reviewable file and returns 1. Complete
snapshots return 0. Importing an export stores its snapshots unchanged, so another
collection gets the same pinned revisions; an incomplete export imports with its
issues repeated as warnings. (A plain `{schema_version: 1, records: [...]}` file,
such as an accepted draft, gets import provenance like a single record.) Exports
omit attachment bytes by default; add
`--include-attachments` only when you intend to copy referenced local snapshots.
No command publishes or sends the collection to an external service.

Markdown runsheets preserve the graph, sample lineage and unresolved fields for
human review. They are descriptive plans, not equipment instructions. JSON is the
canonical exchange format; arbitrary original-format round trips are unsupported.
Output files are created without replacing existing files unless `--force` is set.

## Optional prompt draft and explicit review

The prompt helper uses the existing `ChatClient` with a configured OpenAI-compatible
model server. Configure `OPENTCAD_LLM_URL`, `OPENTCAD_LLM_MODEL` and optionally
`OPENTCAD_LLM_API_KEY`, or supply `--url` and `--model`. The prompt and generated
content go to that server, so choose a deployment appropriate for your private data.

```sh
opentcad catalog draft 'Add my resist product PR-1; vendor and datasheet revision unknown' -o /tmp/draft.json
```

The command emits an **unaccepted** artifact containing the request, typed private
`bundle`, assumptions, questions and check findings. All model-generated fields are
unverified, including values repeated from the request. Each generated record also
retains that warning in `unresolved`. The helper requests schema-constrained JSON,
validates it deterministically and allows one bounded repair; an unreachable server
fails with its configuration error. It never substitutes a local keyword generator,
imports into a collection, installs code or runs a simulation.

Review the whole artifact, answer its questions, verify sources and quantities, and
edit the proposed records. To accept selected records, save their edited `bundle`
object as a separate canonical JSON file, retaining the original draft for provenance.
Carry any remaining assumptions into each affected record's `unresolved` and link
the retained draft in `sources` or field-level `provenance`; do not discard caveats
when extracting a bundle. Then run an explicit import:

```sh
opentcad catalog --root /tmp/my-catalog import /tmp/reviewed-bundle.json
opentcad catalog --root /tmp/my-catalog check
```

The draft wrapper itself is intentionally not an import format. Questions-only drafts
are valid when essentials are missing. Schema success does not establish provenance,
license permission, calibration, scientific validity or executability. The optional
assistant has mocked tests; no real model service is required to use the catalog.

This first slice does not implement federated search, public contributions, aliases,
scientific review, automatic calibration updates, arbitrary format extraction,
lab-to-lab recipe porting or quantitative propagation through the graph.
