"""Transparent knowledge-gap checks, without solver or equipment execution."""

from __future__ import annotations

from datetime import date

from .models import Assessment, Issue
from .store import references

# Recognition only. This is deliberately not a dimensional-analysis/conversion engine.
RECOGNIZED_UNITS = {
    "1", "%", "s", "ms", "us", "min", "h", "K", "degC", "°C", "rpm",
    "nm", "um", "µm", "mm", "cm", "m", "A", "mA", "V", "W", "mW",
    "Pa", "mbar", "Torr", "Hz", "mJ/cm^2", "mJ/cm2", "cP", "g/cm^3",
}


def _cyclic(nodes, edges):
    adjacency = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    visiting, done = set(), set()

    def visit(node):
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        if any(visit(target) for target in adjacency[node]):
            return True
        visiting.remove(node)
        done.add(node)
        return False

    return any(visit(node) for node in adjacency)


def check_record(record, catalog=None) -> Assessment:
    """Assess a record: is it structurally valid, and what is missing?

    Gaps go into ``Assessment.issues``: unpinned or unresolvable
    references, the wrong kind of referenced record, missing or out-of-date
    calibration, and similar. ``compatibility`` is ``"incompatible"`` if a
    declared conflict was found, ``"needs_information"`` if any issue is
    above ``info``, and ``"no_declared_conflicts"`` otherwise. References
    are resolved in ``catalog`` when one is given; without one they are
    reported as unresolved."""
    issues = []
    incompatible = False

    def add(code, message, path="", severity="warning"):
        issues.append(Issue(code=code, message=message, path=path, severity=severity))

    def resolve(ref, path, expected=None):
        if ref.revision is None:
            add("unpinned_reference", "Draft reference follows a mutable browsing head; pin a revision for reproducibility.", path)
        if catalog is None:
            add("unresolved_reference", f"No collection supplied to resolve {ref.id}.", path)
            return None
        try:
            target = catalog.get(ref.id, ref.revision)
        except (KeyError, ValueError) as exc:
            add("missing_reference", str(exc), path, "error")
            return None
        if expected and target.kind not in expected:
            add("reference_kind", f"Expected {sorted(expected)}, got {target.kind}.", path, "error")
            return None
        return target

    def calibration(instance, path):
        cal = instance.payload.calibration
        if cal.status != "current":
            add("missing_calibration", f"Installed-tool calibration is {cal.status}; lab performance cannot be predicted.", path)
        else:
            if not cal.valid_from or not cal.valid_until:
                add("calibration_scope_unknown", "Current calibration claim lacks a complete validity interval.", path)
            if not cal.evidence:
                add("calibration_evidence_missing", "Current calibration is a recorded claim without evidence references.", path)
            today = date.today().isoformat()
            if (cal.valid_from and today < cal.valid_from) or (cal.valid_until and today > cal.valid_until):
                add("calibration_out_of_date", f"Calibration interval does not cover assessment date {today}.", path)
        if not instance.payload.configuration:
            add("configuration_unknown", "Installed chamber/options configuration is unspecified.", path)
        if instance.payload.constraints:
            add("constraints_unassessed", "Declared quantities are descriptive constraints without operators; no numeric compatibility was inferred.", path)

    for field in record.unresolved:
        add("unresolved_field", field, "unresolved")
    if not record.sources:
        add("missing_sources", "No source provenance supplied.", "sources")
    if not record.license:
        add("rights_unknown", "Redistribution rights are unspecified; private export is not public-publishing permission.", "license")

    def quantities(value, path=""):
        if isinstance(value, dict):
            if {"value", "unit", "uncertainty"} <= set(value):
                if value["value"] is None:
                    add("unknown_quantity", "Value is unknown; no numeric setting was invented.", path)
                if value["unit"] is None:
                    add("unknown_unit", "Unit is unknown; quantitative use is blocked.", path)
                elif value["unit"] not in RECOGNIZED_UNITS:
                    add("unsupported_unit", f"Unit {value['unit']!r} is preserved but not recognized; supply an explicit reviewed mapping.", path)
                if value["uncertainty"] is None:
                    add("unknown_uncertainty", "Uncertainty is unknown, not zero.", path)
            for key, child in value.items():
                quantities(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                quantities(child, f"{path}.{index}")

    quantities(record.payload.model_dump(mode="json"), "payload")
    if record.kind == "equipment_instance":
        calibration(record, "payload.calibration")
        if record.payload.model_ref is None:
            add("missing_model_reference", "Equipment instance has no model reference.", "payload.model_ref")
    if record.kind == "material_lot" and record.payload.product_ref is None:
        add("missing_product_reference", "Lot has no pinned product context.", "payload.product_ref")
    for path, ref in references(record):
        if record.kind == "process_flow" and ".tool_ref" in path:
            continue
        expected = None
        if path.endswith("model_ref"):
            expected = {"equipment_model"}
        elif path.endswith("product_ref"):
            expected = {"material_product"}
        elif "material_refs" in path:
            expected = {"material", "material_product", "material_lot"}
        resolve(ref, path, expected)

    if record.kind == "process_flow":
        flow = record.payload
        ids = [step.id for step in flow.steps]
        samples = [sample.id for sample in flow.samples]
        if not ids:
            add("empty_flow", "No process steps supplied.", "payload.steps", "error")
        if len(set(ids)) != len(ids):
            add("duplicate_step", "Step IDs must be unique.", "payload.steps", "error")
        if len(set(samples)) != len(samples):
            add("duplicate_sample", "Sample IDs must be unique.", "payload.samples", "error")
        edges = [(edge.source, edge.target) for edge in flow.edges]
        if len(set((e.source, e.target, e.kind) for e in flow.edges)) != len(flow.edges):
            add("duplicate_edge", "Duplicate graph edges require review.", "payload.edges", "error")
        for index, edge in enumerate(flow.edges):
            if edge.source not in ids or edge.target not in ids:
                add("dangling_edge", "Edge references an absent step.", f"payload.edges.{index}", "error")
        if _cyclic(ids, edges):
            add("unresolved_cycle", "Process graph contains a cycle; preserve descriptively and unroll actual rework before ordering execution.", "payload.edges")
        genealogy = []
        for index, sample in enumerate(flow.samples):
            if sample.state_status == "unknown":
                add("unknown_sample_state", f"Sample {sample.id} state is unknown; quantitative propagation is blocked.", f"payload.samples.{index}")
            if sample.state_status != "unknown" and not sample.sources:
                add("state_evidence_missing", f"Sample {sample.id} is labeled {sample.state_status} without evidence/assumption provenance.", f"payload.samples.{index}")
            for parent in sample.parent_ids:
                if parent not in samples:
                    add("missing_parent_sample", f"Parent sample {parent} is absent.", f"payload.samples.{index}", "error")
                genealogy.append((parent, sample.id))
        if _cyclic(samples, genealogy):
            add("genealogy_cycle", "Sample genealogy cannot contain ancestry cycles.", "payload.samples", "error")
        for index, step in enumerate(flow.steps):
            path = f"payload.steps.{index}"
            for unknown in step.unresolved:
                add("unresolved_setting", unknown, path)
            if not step.input_samples:
                add("unknown_input_state", "No input sample/state supplied; quantitative propagation cannot begin.", path)
            for sample in step.input_samples + step.output_samples:
                if sample not in samples:
                    add("missing_sample", f"Step sample {sample} is not declared.", path, "error")
            if step.tool_ref is None:
                add("missing_tool", "No installed equipment instance selected; compatibility is unknown.", path)
                continue
            tool = resolve(step.tool_ref, f"{path}.tool_ref", {"equipment_instance"})
            if tool is None:
                continue
            calibration(tool, f"{path}.tool_ref")
            if not tool.payload.supported_operations:
                add("capability_unknown", "Installed instance declares no operations; nominal model specs were not substituted.", path)
            elif step.operation not in tool.payload.supported_operations:
                incompatible = True
                add("operation_mismatch", f"Operation {step.operation!r} is not in the installed tool's declared operations.", path)
            else:
                add("declared_operation_match", "Exact operation-name match only; performance/safety remain unassessed.", path, "info")
        if flow.route_status == "observed":
            add("execution_evidence_unassessed", "Observed route label alone supplies no run timestamps/logs or verified completion; execution evidence is not validated by this slice.")
    add("constraints_scope_unassessed", "Thermal budget, contamination, substrate restrictions, dimensional consistency and numerical constraint ranges are not evaluated by this first slice.", severity="info")
    add("simulation_unsupported", "Catalog records are descriptive. No calibrated process propagation or simulator adapter is implemented; unsupported state-changing steps are never crossed numerically.", severity="info")
    structural = not any(issue.severity == "error" for issue in issues)
    status = ("incompatible" if incompatible else "needs_information"
              if any(issue.severity != "info" for issue in issues) else "no_declared_conflicts")
    return Assessment(structural_valid=structural, compatibility=status, issues=issues)


def runsheet(record) -> str:
    """Readable declared-order instructions preserving every graph edge and unknown."""
    if record.kind != "process_flow":
        raise ValueError("Runsheets require a process_flow record")
    flow = record.payload
    lines = [f"# {record.title}", "", "Descriptive process runsheet; equipment operation and quantitative simulation are not authorized.",
             f"Route status: {flow.route_status}. Step display follows declared list order; graph edges define routes.", ""]
    for index, step in enumerate(flow.steps, 1):
        lines.append(f"{index}. {step.id}: {step.operation}")
        if step.intent:
            lines.append(f"   Intent: {step.intent}")
        lines.append(f"   Tool: {step.tool_ref.id if step.tool_ref else 'UNKNOWN'}")
        for name, quantity in step.parameters.items():
            lines.append(f"   {name}: {quantity.value if quantity.value is not None else 'UNKNOWN'} {quantity.unit or 'UNKNOWN UNIT'}")
        lines.append(f"   Samples: {', '.join(step.input_samples) or 'UNKNOWN'} -> {', '.join(step.output_samples) or 'UNKNOWN'}")
        for unknown in step.unresolved:
            lines.append(f"   UNRESOLVED: {unknown}")
    lines.extend(["", "Graph edges:"])
    lines.extend(f"- {e.source} -> {e.target} ({e.kind})" for e in flow.edges)
    lines.extend(["", "Sample genealogy:"])
    lines.extend(f"- {s.id}: parents={','.join(s.parent_ids) or 'none declared'}; state={s.state_status}" for s in flow.samples)
    return "\n".join(lines) + "\n"
