"""Small, versioned process-knowledge schema. These records do not execute physics."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourceRef(Model):
    """Where a value came from: a URI (``attachment:sha256:…`` for stored
    files), an optional locator within it (page, table), its hash and a
    description."""
    uri: Text
    locator: str | None = None
    sha256: Hash | None = None
    description: str | None = None


class RecordRef(Model):
    """A reference to record ``id``, pinned to a content-hash ``revision``
    or, if None, following the browsing head."""
    id: Text
    revision: Hash | None = None


class Quantity(Model):
    """A measured or specified value with its unit, uncertainty (same unit,
    ≥ 0), sources and the conditions it holds under. Any part may be
    unknown (None); checks report what is missing."""
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Text | None = None
    uncertainty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sources: list[SourceRef] = Field(default_factory=list)
    conditions: dict[str, str] = Field(default_factory=dict)


class Calibration(Model):
    status: Literal["unknown", "missing", "current", "expired"] = "unknown"
    valid_from: str | None = None
    valid_until: str | None = None
    notes: str | None = None
    evidence: list[SourceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def dates(self):
        from datetime import date

        for field in ("valid_from", "valid_until"):
            value = getattr(self, field)
            if value is not None:
                date.fromisoformat(value)
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("calibration valid_from must precede valid_until")
        return self


class EquipmentModel(Model):
    manufacturer: str | None = None
    model: str | None = None
    operations: list[Text] = Field(default_factory=list)


class EquipmentInstance(Model):
    model_ref: RecordRef | None = None
    facility: str | None = None
    configuration: dict[str, str] = Field(default_factory=dict)
    supported_operations: list[Text] = Field(default_factory=list)
    calibration: Calibration = Field(default_factory=Calibration)
    constraints: dict[str, Quantity] = Field(default_factory=dict)


class Material(Model):
    composition: str | None = None
    phase: str | None = None
    properties: dict[str, Quantity] = Field(default_factory=dict)


class MaterialProduct(Model):
    generic_material: str | None = None
    vendor: str | None = None
    product: str | None = None
    datasheets: list[SourceRef] = Field(default_factory=list)
    properties: dict[str, Quantity] = Field(default_factory=dict)


class MaterialLot(Model):
    product_ref: RecordRef | None = None
    lot: str | None = None
    history: list[str] = Field(default_factory=list)
    properties: dict[str, Quantity] = Field(default_factory=dict)


class ProcessStep(Model):
    id: Text
    operation: Text
    intent: str | None = None
    tool_ref: RecordRef | None = None
    material_refs: list[RecordRef] = Field(default_factory=list)
    parameters: dict[str, Quantity] = Field(default_factory=dict)
    input_samples: list[Text] = Field(default_factory=list)
    output_samples: list[Text] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    unresolved: list[Text] = Field(default_factory=list)


class ProcessEdge(Model):
    source: Text
    target: Text
    kind: Literal["sequence", "split", "merge", "branch", "rework", "metrology"] = "sequence"


class Sample(Model):
    id: Text
    parent_ids: list[Text] = Field(default_factory=list)
    state_status: Literal["unknown", "measured", "assumed", "predicted"] = "unknown"
    sources: list[SourceRef] = Field(default_factory=list)


class ProcessFlow(Model):
    steps: list[ProcessStep] = Field(default_factory=list)
    edges: list[ProcessEdge] = Field(default_factory=list)
    samples: list[Sample] = Field(default_factory=list)
    mask_refs: list[RecordRef] = Field(default_factory=list)
    mask_sources: list[SourceRef] = Field(default_factory=list)
    route_status: Literal["planned", "observed"] = "planned"


class RecordBase(Model):
    schema_version: Literal[1] = 1
    id: Text
    title: Text
    sources: list[SourceRef] = Field(default_factory=list)
    license: str | None = None
    visibility: Literal["private"] = "private"
    unresolved: list[Text] = Field(default_factory=list)
    provenance: dict[str, list[SourceRef]] = Field(default_factory=dict)


class EquipmentModelRecord(RecordBase):
    kind: Literal["equipment_model"]
    payload: EquipmentModel


class EquipmentInstanceRecord(RecordBase):
    kind: Literal["equipment_instance"]
    payload: EquipmentInstance


class MaterialRecord(RecordBase):
    kind: Literal["material"]
    payload: Material


class MaterialProductRecord(RecordBase):
    kind: Literal["material_product"]
    payload: MaterialProduct


class MaterialLotRecord(RecordBase):
    kind: Literal["material_lot"]
    payload: MaterialLot


class ProcessFlowRecord(RecordBase):
    kind: Literal["process_flow"]
    payload: ProcessFlow


CatalogRecord = Annotated[
    Union[
        EquipmentModelRecord, EquipmentInstanceRecord, MaterialRecord,
        MaterialProductRecord, MaterialLotRecord, ProcessFlowRecord,
    ],
    Field(discriminator="kind"),
]


def record_from_dict(data: dict) -> CatalogRecord:
    """Validate ``data`` as a catalog record of any kind (chosen by its
    ``kind`` field). Raises pydantic.ValidationError if it is not one."""
    from pydantic import TypeAdapter

    return TypeAdapter(CatalogRecord).validate_python(data)


def record_schema() -> dict:
    """JSON Schema for catalog records, covering every kind."""
    from pydantic import TypeAdapter

    return TypeAdapter(CatalogRecord).json_schema()


class Issue(Model):
    """One finding: a machine-readable ``code``, a ``message``, where in the
    record it applies (``path``) and its ``severity``."""
    code: str
    message: str
    path: str = ""
    severity: Literal["error", "warning", "info"] = "warning"


class ImportResult(Model):
    """What an import produced: the records, any issues, the source file's
    hash, and (after ``Catalog.import_file``) the stored ``refs``."""
    records: list[CatalogRecord] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    source_sha256: Hash | None = None
    refs: list[RecordRef] = Field(default_factory=list)
    attachments: dict[str, str] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True if no issue is an error."""
        return not any(issue.severity == "error" for issue in self.issues)


class Assessment(Model):
    """The result of ``check_record``. ``simulation`` is always
    ``"unsupported"``: catalog records are not yet run as simulations."""
    structural_valid: bool
    compatibility: Literal[
        "needs_information", "incompatible", "no_declared_conflicts"
    ] = "needs_information"
    simulation: Literal["unsupported"] = "unsupported"
    issues: list[Issue] = Field(default_factory=list)
