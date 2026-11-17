# Open materials and simulation platform — proposed direction

**Status: design proposal, not an implemented platform or a promise of universal simulation.**
The first [private local catalog slice](catalog.md) is implemented: typed
materials/products/lots, equipment models/instances and descriptive process graphs;
JSON/YAML and inventory CSV imports; opaque local attachment snapshots; revisioned
storage and pinned JSON/runsheet exports; and optional model-generated private drafts
for explicit review. The [teaching fixture](../examples/catalog/README.md) includes
a split, planned metrology and an unresolved setting. This is not the bounded
process-import acceptance gate below: PDF/OCR extraction, public contribution,
calibrated propagation and automatic calibration proposals remain unimplemented.

OpenTCAD could become a shared, open place to discover and contribute materials,
devices, interfaces, measurements, equations, models, algorithms, tools and workflows.
People should be able to describe a contribution or simulation in ordinary language,
inspect the resulting structured specification, and reproduce it without an AI service.

The catalog may eventually describe any material or device. Executable support must
remain narrower: a particular implementation, parameter set, geometry, coupling and
backend must support the requested regime. Finding an equation in the catalog does
not make it executable. Selecting assumptions exactly does not make them physically
exact; outputs remain conditional on data, approximations and validation evidence.

## What exists, and what this proposal adds

| Existing foundation | Proposed addition |
| --- | --- |
| Python API, checked YAML/JSON decks, CLI run/sweep | Negotiated contracts, pinned manifests and evidence bundles |
| Material YAML and plugin registries | Versioned linked catalog, capability manifests and contribution assistant |
| Gmsh geometry, ViennaLS topography, DEVSIM device path | Additional backends with declared support and conversion losses |

See [simulation files](simulation_files.md), [plugins](plugins.md) and
[architecture](../README.md#architecture). Current deck checks are not full scientific
capability validation. Material enum entries exceed shipped parameter files; plugins
cannot yet add enum members. Recipes stage all topography before doping, so arbitrary
process interleaving is unsupported. Installed plugin discovery imports Python code;
it cannot safely become automatic execution of public catalog artifacts.

## One discovery experience, many maintained collections

A shared index should link collections maintained by researchers, laboratories,
teaching projects and backend authors. It need not own every underlying file.
Use durable references plus immutable, content-addressed artifact snapshots and local
caches so a run survives upstream edits or outages. Record retrieval dates and
availability; do not claim reproducibility from a mutable URL alone.
Private or restricted user data can stay local, with explicit export controls.
An index entry may describe unavailable or non-redistributable data without copying it.

Start with a small schema and useful import/export tools; extend it through actual
contributions rather than require a complete ontology before sharing a measured curve.

## Linked knowledge entities

Each entity needs a stable identifier, immutable revisions, schema version, authors,
license, source references, creation method, review state and links to related entities.
Human-readable names and aliases aid discovery; runs resolve identifiers and hashes.

| Entity | Required distinction and useful links |
| --- | --- |
| Source | Citation, durable reference, artifact hash, rights and extraction method; source credibility is distinct from model calibration |
| Dataset | Raw or derived measurements, computational results or digitized curves; specimen, method, conditions and transformations |
| Material | Composition, phase, orientation, processing state and parameter sets; a name alone is insufficient |
| Interface | Ordered material pair, orientation, fabrication/history, boundary geometry, charge/trap/transport descriptions |
| Device | Geometry, contacts, process history and material/interface assignments; a template is distinct from a measured specimen |
| Equation | Mathematical definition, variables, dimensions, boundary/initial conditions and assumptions |
| Model | A physical approximation plus parameter requirements, validity domain and links to equations and evidence |
| Implementation | Executable realization of a model, code revision, dependencies, discretization and known deviations from the equation |
| Solver/backend | Supported equations, meshes, dimensions, couplings, numerical controls and platform/dependency constraints |
| Algorithm/tool | Fitting, meshing, extraction or analysis operation with typed inputs/outputs and reproducibility requirements |
| Workflow | Ordered operations and artifacts, including calibration, simulation, extraction and comparison |
| Validation | Claim, reference data, protocol, metric, tolerance, tested domain, outcome and limitations |
| Run | Resolved contract, environment, executed operations, logs, outputs and numerical/physical checks |

Parameters and arrays carry machine-readable units, coordinate conventions, reference
frames and sign conventions. Ingestion validates dimensional consistency and records
every conversion; an unknown unit blocks executable use until resolved.
Validity includes temperature, field, doping, composition, dimensions and relevant
fabrication conditions. Unknown bounds remain unknown, never unlimited by default.
Represent measurement uncertainty, parameter-fit uncertainty and model discrepancy
separately where available; record correlations and distributions when justified.
Missing uncertainty is not zero uncertainty.

Contradictory measurements and model variants should coexist. Link disagreements,
specimen differences, contested interpretations and superseding evidence without
silently averaging them. A useful model is chosen for a stated purpose and regime;
the index should not assign a universal “best model” or convert popularity to truth.
Derived fits retain links to source data, fitting algorithm, residuals and exclusions.

## Process flows, equipment and lab-specific materials (proposed)

The shared catalog should also support a person bringing their own process flow,
equipment inventory, resist, material product or datasheet. Each accepted addition
grows the local/workspace knowledge collection; sharing selected records can grow the
public commons. Recording a useful flow must not require a calibrated simulator.
[FabuBlox's official product overview](https://www.fabublox.com/) provides inspiration:
it describes process design/version control and stack emulation, facility tools and
constraints, lots/metrology, and links between outcomes and physical models. This is
an analogy for connected process knowledge, not a feature comparison or a claim that
these proposed OpenTCAD capabilities exist today.

### Entities that preserve the fabrication context

| Entity | Context that must remain explicit |
| --- | --- |
| Equipment model | Manufacturer/model, nominal capabilities, supported operations and documentation revisions |
| Installed equipment instance | Facility identity, chamber/configuration, installed options, maintenance state and time-scoped calibration; model specifications alone do not characterize it |
| Material product | Generic material link, vendor formulation/product identifier, datasheet revision and supplied properties; proprietary composition can remain unknown |
| Material lot/container | Product revision, lot, relevant storage/expiry/history and measured properties; avoid treating all lots as identical |
| Process intent | Desired transformation and tolerances, such as removing a target oxide thickness; independent of a particular tool |
| Tool recipe | Versioned settings, units, sequence and applicable equipment/configuration/product context; a plan, not evidence of execution |
| Observed execution | Actual tool/chamber, timestamps, sample/lot, settings/logs, deviations and operator annotations |
| Predicted sample state | Model-dependent estimated geometry/composition/properties, linked to its initial state, contract, backend and uncertainty |
| Metrology observation | Method/instrument/calibration, sample/site, time, units, uncertainty and the execution/state it evaluates |

A resist product is more specific than a generic `Photoresist` material. Store
reported viscosity, spin curves, bake/exposure/development conditions and thickness
measurements with their source and applicability. A datasheet curve at one bake,
substrate and tool condition is not a universal process law. Do not infer missing
composition, reaction kinetics or exposure physics from the product name or prose.
Separate vendor claims, local measurements and fitted models with distinct provenance.

Represent the process as a versioned directed graph with explicit typed edges and
ordered steps within each route. Support branches, experimental splits, rework,
mask/design revisions, metrology checkpoints and sample/wafer/lot genealogy, including
splits and merges. A rework record must identify the prior sample state and actual
repeat; ambiguous cycles need resolution rather than an invented execution order.
Keep planned routes, observed routes and predicted states linked but distinct: an
execution can deviate from its plan, and a prediction is not a measurement.

Match tool capabilities and recipe compatibility against the installed configuration,
substrate/material restrictions, contamination history/policies, parameter ranges,
units and cumulative thermal budget. Unknown constraints remain visible and can block
a compatibility claim. An alternative tool match proposes a new recipe/context for
review; identical settings on a different chamber do not imply identical results.
“Port this flow to my lab's tools and resists” should produce explicit differences,
required calibrations and predicted or unknown effects. A target device can likewise
produce a candidate process graph, remaining a proposal until inventory constraints
and model/data gaps are resolved.
Without applicable calibration, default to a descriptive flow or labeled qualitative
preview. A supported uncalibrated model may run an explicitly accepted exploratory
numerical scenario, labeled as uncalibrated rather than predicted lab/tool performance.
Missing models or input states block quantitative propagation: never silently cross
an unsupported state-changing step. Resume only from an explicitly supplied, measured
or accepted assumed state, preserving its uncertainty and lineage.
Metrology can propose a scoped calibration revision with fit evidence and holdout
checks; it must not automatically overwrite prior data, recipes or model parameters.

### Broad imports with reviewable extraction

Provide adapters for structured CSV, XLSX, JSON and YAML, and assisted extraction for
PDF/Word documents, images/scans, free text and supported native tool exports.
“Bring your format” means best-effort ingestion with explicit support boundaries;
proprietary, encrypted, undecodable or unknown formats return an actionable unsupported
result, preserving the original and suggesting an available export or manual mapping.

Retain originals according to workspace policy, hash them, and keep source page/table/
cell references or image regions for extracted fields. Report extraction confidence,
unit conversions, uncertain associations and unresolved fields. OCR confidence does
not establish scientific validity. Preview the original beside the canonical graph
and exact patch so contributors can correct mappings before accepting them.
Never silently drop steps, invent missing settings or reorder a flow to fit a backend.
If order, a branch, a merged cell or a handwritten value is ambiguous, retain it as
unresolved and ask for clarification before the affected route becomes executable.

On accepting an import or prompt addition, create or reuse versioned draft records
for tools, products, lots and flows in the selected local/workspace collection.
Suggest aliases and possible duplicates using identifiers and context; require review
for ambiguous merges, preserve conflicting revisions and show dependency changes.
A new name must not silently replace an existing material or equipment instance.
Private additions remain private: public contribution uses an explicit publish policy,
rights/provenance checks and a preview of records and linked artifacts to be shared.
Workspace growth is automatic within that chosen scope; public disclosure is not.

Export the canonical graph, resolved entity references and machine-readable runsheets
alongside readable instructions and an unresolved-field report. Document each adapter's
mapping and export losses; do not promise arbitrary-format lossless round-tripping.
Descriptive imports can retain an interleaved process even when execution is unsupported.
Today's `run_recipe` stages all topography before doping; it cannot execute a general
interleaved fabrication graph. A future adapter must preserve route semantics or reject
the route, rather than present reordered operations as the requested simulation.
Importing, planning, simulating or exporting a flow does not authorize equipment operation.

### Bounded process-import acceptance gate

Alongside the first simulation slice, use a small redistributable fixture containing
a flow with a split and metrology step, a resist datasheet and an installed-tool
inventory. Acceptance requires source-linked extraction into draft entities, stable
aliases/revisions on a repeated import, preserved sample genealogy and a canonical
graph/runsheet export. Include one ambiguous setting and one unsupported native file:
neither may produce a silently completed route. Verify private additions stay private
and publishing shares only selected records with permitted rights. A missing chamber
calibration must yield a descriptive flow or labeled qualitative preview; a separately
supported calibrated step may produce a prediction with its evidence. Demonstrate a
metrology-driven calibration proposal without overwriting the prior revision. This
gate establishes useful ingestion and explicit limits, not arbitrary process simulation.

## Contribution by prompting, with an inspectable patch

A newcomer might say “add my measured Si/SiO2 capacitance curve” or “implement this
mobility equation.” The assistant asks only for missing essentials, maps the request
to typed entities, and produces a local draft patch with sources and unresolved fields.
It must distinguish user statements, extracted facts and its own proposed inferences.

The same workflow is accessible through forms, text files, CLI and Python API:

1. Import or describe the artifact; preview parsed columns, units and licensing.
2. Create a draft entity and links; preserve the original artifact and transformation log.
3. Show the exact diff, validation findings, missing fields and proposed quality labels.
4. Run schema checks; for code, separately review dependencies and execute approved
   checks in an isolated environment with explicit resource/network boundaries.
5. Open a reviewable contribution through a contributor-selected publication action;
   maintainers or collection stewards accept it according to published criteria.

Catalog text, uploads and generated code are untrusted. Indexing must not execute
them, install packages or grant credentials. Executable plugins need an explicit
installation/trust boundary. Preserve local exploratory drafts, small examples,
field-level errors and a path to contribute data without writing Python.

## Simulation as a negotiated, executable contract

The proposed flow is:

`request → draft typed contract → capability matching → assumption negotiation`
`→ resolved contract → backend execution → checked evidence bundle`

The draft captures the scientific question, requested observables and tolerances,
geometry/dimensionality, materials/interfaces, conditions, model choices, data,
boundary/initial conditions, numerical controls, resources and required validation.
Capability matching checks combinations, including contact type plus analysis,
statistics, units, coupling and discretization. Required parameters depend on the
active models, analyses and domain, not every possible material property. Report
supported, unsupported and unknown requirements separately.

Present consequential choices with evidence and tradeoffs: measured versus literature
parameters, constant versus doping-dependent mobility, 2-D scaling versus a 3-D model,
and computational cost versus the requested accuracy. State what additional data or
implementation would close a gap. Ask for decisions that affect the question; ordinary
numerical defaults can be proposed together in one visible contract for acceptance.
Cited defaults are allowed when displayed, accepted and frozen; recheck their validity
when the regime changes.

No silent replacement of a model, value, backend, material, dataset, boundary condition or observable.
If a requested combination is unavailable, stop before execution and offer explicit
alternatives, a scoped exploratory approximation, or a contribution task. Changing
the scientific contract creates a new revision requiring acceptance. Numerical retries
may follow an accepted policy, but every retry and changed setting must be recorded.

Resolve all defaults into the final artifact, pin data/code/backend versions and
hashes, and export a lock manifest. Conversational history can explain a choice; it
must not be necessary to reconstruct it. Deterministic orchestration means the same
resolved inputs take the same declared path; numerical reproducibility has a recorded
tolerance because platforms and parallel solvers may differ. Seeds are explicit.
The CLI/API executes the same contract with the AI interface entirely optional.

### Example negotiation (proposed behavior)

> **User:** Simulate my long-channel Si/SiO2 NMOS Id–Vg at 300 K using my measured
> oxide thickness and doping. Compare constant and Klaassen mobility.
>
> **OpenTCAD:** I mapped the imported nm and cm⁻³ columns. Gate work function and
> interface charge are missing. Use measured values, or a proposed 4.5 eV work function
> and Qf = 0? Both variants share classical drift-diffusion, Boltzmann statistics and
> SRH; this comparison does not validate them for your process.
>
> **User:** Use the proposed work function and Qf = 0; label them assumptions.
>
> **OpenTCAD:** Review this two-run contract and check policy, then accept to run or
> export for the CLI. Only mobility differs; missing calibration remains visible.

### Typed contract sketch (proposed schema, not a current deck)

```yaml
schema: opentcad.simulation-contract/v0-draft
status: accepted                    # also record accepting actor and revision
structure: {artifact: local:nmos-geometry, revision: geometry-r1}
inputs:
  specimen_data: {artifact: local:user-measurements, revision: import-r1}
  mapping: {oxide_thickness: nm, acceptor_density: cm^-3}
conditions: {temperature_K: 300, drain_bias_V: 0.05}
physics:
  equations: [poisson, electron_drift_diffusion, hole_drift_diffusion]
  statistics: {id: core:boltzmann, revision: model-r1}
  recombination: [{id: core:srh, revision: model-r1}]
variants:
  - {name: constant, mobility: {id: core:constant, revision: model-r1}}
  - {name: klaassen, mobility: {id: core:klaassen, revision: model-r1}}
assumptions:
  - {field: gate_work_function_eV, value: 4.5, basis: user_accepted_proposal}
  - {field: interface_Qf_C_per_cm2, value: 0, basis: user_accepted_assumption}
execution: {backend: devsim, lock: local:resolved-run-lock}
analysis: {type: iv, gate_bias_V: {start: 0, stop: 1.5, step: 0.05}, current_unit: A_per_cm}
checks:
  completion: {all_requested_biases: true}
  current_balance: {relative_tolerance: 0.001, absolute_tolerance_A_per_cm: 1.0e-12}
  mesh_comparison: {observable: drain_current, relative_tolerance: 0.05}
limitations: [uncalibrated_process_parameters, interface_traps_omitted]
```

The lock supplies hashes, full geometry/contacts/mesh, region-scoped parameters and
numerical settings omitted here. Check tolerances are examples, not demonstrated
accuracy or current defaults. Every active model's required parameters must resolve.

## Execution evidence and modular backends

| Existing module | Proposed responsibility |
| --- | --- |
| `opentcad.materials` | Typed parameter adapters and explicit completeness checks; catalog entities remain separate from solver parameter layouts |
| `opentcad.geometry` / `MeshField` | Geometry, contacts and field interchange with versioned metadata and unit conventions |
| `opentcad.device.physics` / `models` | Executable model interfaces linked to equations, validity and implementation revisions |
| `opentcad.process` / `bridge` | Process operations and transfer artifacts with conservation/error evidence |
| `opentcad.plugins` | Local registration; add capability manifests and explicit trust/install controls for catalog execution |
| `opentcad.io` / CLI | Contract/deck migration, resolution, checking, lock files and reproducible run bundles |
| `validation` / `examples` | Reusable checks and worked evidence; application designs stay under their examples |

Adapters declare capabilities; unsupported couplings fail before a run. New solvers
may need native meshes beyond `MeshField`. Keep reusable physics in `opentcad` and
microrobot designs/evidence in `examples/microrobot`. Show backend licenses/dependencies.

A run bundle records inputs, assumptions, actual environment/commands, requested versus
effective settings and reached bias/time ranges, residuals, failures and output checks.
An exit code alone cannot establish a complete transient. Check terminal conservation,
domain-specific invariants and mesh/time-step sensitivity as applicable. Numerical
convergence, agreement with an analytic benchmark, calibration and independent physical
validation are separate claims; a fitted curve is not independent validation data.
Failed or partial runs remain inspectable and must not receive a complete label.

## Trust, stewardship and openness

Publish open schemas and migration rules. Distinguish code, data and documentation
licenses; record per-artifact rights, attribution and upstream/backend obligations.
Unresolved redistribution rights block public copying. Prefer citations to copyrighted
papers; exclude local reference PDFs and raw SPICE transients from submission exports.

Collection stewards review domain claims; backend maintainers own execution support.
Schema changes need public compatibility review and appeals. Publish moderation rules
and conflicts of interest; permit forks with attribution/lineage. Address abuse, unsafe
code and misleading claims while allowing exploratory drafts below validation standards.

Use scoped labels such as `draft`, `schema_checked`, `numerically_verified`,
`calibrated` and `independently_validated`, each tied to a revision, domain and evidence.
These are distinct assertions. Withdrawn claims retain history and affected-run links.

## Milestones and acceptance gates

**1. A community-usable Si/SiO2 vertical slice.** Ship importable specimen data,
catalog cards and an exportable contract for the NMOS comparison above, with constant
and Klaassen mobility as two explicitly compatible choices in a documented regime.
Include a CLI path, an optional prompt/form draft path, and a newcomer contribution
example. Acceptance requires both variants reproduce within stated tolerances, user
data round-trips with provenance/units, and an unsupported request (for example quantum
confinement) reports the missing capability without substituting classical transport.

The metadata-fidelity prerequisites for that slice are resolved (2026-11-17):
`MeshField.save/load` writes every `ContactTag` field (including
`flat_band_shift_V`) with a format version; `load_material` errors on a missing
process variant instead of falling back, errors on missing required fields instead
of taking silicon's values, propagates `uncertainty_percent` and `B_rad_cm3_per_s`,
and lists defaulted optional blocks so models that need them refuse to run; and a
topography-containing `run_recipe` carries the structure's doping, contacts and
metadata onto a conformal mesh (it previously returned a mesh with materials only,
disconnected at material interfaces). Region material overrides still apply only on
the doping-only path (a warning says so).

**2. Reviewable community contributions and federated discovery.** Acceptance:
independently maintained collections can publish compatible manifests; immutable
snapshots replay offline; conflicting datasets remain discoverable; draft typed
patches and review labels work without AI; no catalog import executes uploaded code.

**3. New physics and backends through demonstrated capability.** Acceptance for each
addition: documented equation/implementation links, a tested capability matrix,
supported and rejected contract examples, conservation/convergence evidence and
validation scoped to the claimed domain. Expand materials and couplings incrementally
from contributor demand; these milestones specify evidence, not delivery dates.

Open decisions: minimal schema/identifier authority; index hosting versus references;
code/data license defaults; evidence-label stewardship; and the first cross-backend
benchmark. Resolve them through the vertical slice and public review.
