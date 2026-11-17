# Local process catalog example

These original CC0-1.0 fixtures describe fictional tools, resist and a planned
split experiment. They are a replaceable starting format for your own lab records.
They supply no calibrated prediction, measured result or approved equipment recipe.
Equipment names and nominal values are illustrative assumptions.

From the repository root:

```sh
opentcad catalog --root /tmp/opentcad-demo init
opentcad catalog --root /tmp/opentcad-demo import examples/catalog/equipment.csv
opentcad catalog --root /tmp/opentcad-demo import examples/catalog/resist.yaml
opentcad catalog --root /tmp/opentcad-demo import examples/catalog/branch_flow.yaml
opentcad catalog --root /tmp/opentcad-demo list
opentcad catalog --root /tmp/opentcad-demo check demo:resist-split
opentcad catalog --root /tmp/opentcad-demo export -o /tmp/catalog.json
opentcad catalog --root /tmp/opentcad-demo export --flow demo:resist-split --format markdown -o /tmp/runsheet.md
```

Repeated imports reuse identical revisions. JSON export preserves canonical records;
linked datasheet files are attachment references, not extracted PDF/OCR content.
The export above does not copy attachments. Keep `resist_datasheet.md` beside the
source data when reviewing the illustrative viscosity provenance.

## Descriptive example

`branch_flow.yaml` preserves two branches and their sample parents. Branch B's bake
duration is intentionally unresolved. Both branches end with planned metrology,
not fabricated measurements. Calibration is missing; all simulation is unsupported
by this local catalog. Check reports keep those limitations visible.

Import `unknown.native` to see an actionable unsupported-format error. Importing the
flow before the inventory is allowed as a descriptive draft; checking it then reports
missing references. Correct the data and import a revision rather than silently
replacing the history. See [catalog documentation](../../docs/catalog.md).
