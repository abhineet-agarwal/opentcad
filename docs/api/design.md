# Device design

Bounded design search over a fixed simulation file, and model-drafted plans.

For an introduction, see the [user guide](../design.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.design`: `load_design`, `run_design`, `variable_paths`, `Design`, `Variable`, `Target`, `DesignResult`.

## load_design

```python
opentcad.design.load_design(source, *, base_dir=None) -> Design
```

Load and check a design plan without running any simulation.

**Parameters**

- `source`: Path to a YAML or JSON plan, or the plan as a mapping.
- `base_dir`: Folder a relative ``base`` path is read from. Defaults to the plan file's folder, or the current folder for a mapping.

**Returns**

A :class:`Design` whose base file, variables, targets and search
settings have all been checked.

**Raises**

- `DeckError`: Every problem found, e.g. a variable that isn't an existing numeric geometry, doping or recipe field, a target on a missing or non-IV/CV analysis, or a unit that doesn't match the metric.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L259)

## run_design

```python
opentcad.design.run_design(design: Design, outdir, *, log=None) -> DesignResult
```

Search the plan's variables with real simulations until the targets are met.

Adaptive coordinate search: each poll tries +/- step along every
normalized coordinate, moves to the best strict improvement or halves
the step. Every attempt, failed ones included, costs one evaluation;
repeated points are cached. The search stops at the first candidate
that meets every target. It is local: an unmet result doesn't show the
targets are infeasible.

**Parameters**

- `design`: A plan from :func:`load_design`; it is checked again here.
- `outdir`: New evidence folder; it must not exist yet.
- `log`: Called with one line per candidate; ``None`` is silent.

**Returns**

A :class:`DesignResult`. ``outdir`` holds the contract and its hash,
the base file, material and environment snapshots, every candidate's
file and result, ``design.json`` and ``best.yaml``.

**Raises**

- `DeckError`: The plan still has ``unresolved`` questions, or fails its checks.
- `FileExistsError`: ``outdir`` already exists.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L522)

## variable_paths

```python
opentcad.design.variable_paths(base: dict) -> dict[str, float]
```

Every field of a simulation file that a design may vary, with its value.

**Parameters**

- `base`: The simulation file as a mapping (``Deck.to_dict()``).

**Returns**

``{path: current value}`` in the sweep path syntax
(``structure.layers[0].doping_Na``), in file order. These are the
existing numeric geometry, doping and recipe fields; physics,
contact barriers, mesh and analyses never appear.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L209)

## Design

```python
class opentcad.design.Design(
    name: str,
    base: dict,
    variables: list[Variable],
    targets: list[Target],
    search: dict,
    description: str = '',
    assumptions: list[str] = list(),
    limitations: list[str] = list(),
    unresolved: list[str] = list(),
) -> None
```

A checked design plan: a fixed base simulation file, what may vary,
the targets and the search budget. Make one with :func:`load_design`.

**Attributes**

- `name`: Plan name.
- `base`: The base simulation file as a mapping. Its physics, mesh, materials and analyses never change during the search.
- `variables`: What the search may change.
- `targets`: What a candidate has to meet.
- `search`: ``max_evaluations`` (every attempted candidate counts), ``initial_step`` and ``min_step`` in normalized [0, 1] units.
- `description`: Free text.
- `assumptions`: Choices made when the plan was written, kept with the evidence.
- `limitations`: Known limits of the plan, kept with the evidence.
- `unresolved`: Open questions; :func:`run_design` refuses to run while any remain.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L96)

### Design.to_dict

```python
Design.to_dict()
```

The plan as a mapping that :func:`load_design` reads back unchanged.

### Design.candidate_deck

```python
Design.candidate_deck(values)
```

The base simulation file with ``{path: value}`` applied, as a new mapping.

## Variable

```python
class opentcad.design.Variable(
    path: str,
    lower: float,
    upper: float,
    initial: float,
    scale: str = 'linear',
) -> None
```

One number of the simulation file that the search may change.

**Attributes**

- `path`: Field in the sweep path syntax, e.g. ``structure.layers[0].doping_Na``; one of :func:`variable_paths`.
- `lower`: Lower bound, in the field's own unit.
- `upper`: Upper bound.
- `initial`: Starting value, within the bounds.
- `scale`: ``"linear"``, or ``"log"`` to search in log(value); log bounds must be positive.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L29)

### Variable.encode

```python
Variable.encode(value)
```

``value`` → its position in [0, 1] between the bounds (log-spaced for ``"log"``).

### Variable.decode

```python
Variable.decode(value)
```

Position in [0, 1] → value, clipped to the bounds; the initial value round-trips.

## Target

```python
class opentcad.design.Target(
    name: str,
    analysis: str,
    metric: str,
    options: dict,
    scale: float,
    unit: str,
    lower: float | None = None,
    upper: float | None = None,
) -> None
```

One acceptance interval on a metric of a named IV or CV analysis.

**Attributes**

- `name`: Label for the result rows.
- `analysis`: Name of an ``iv`` or ``cv`` analysis in the base file.
- `metric`: ``value_at``, ``max_abs``, ``vth_max_gm`` or ``vth_constant_current``.
- `options`: The metric's arguments, e.g. ``{"x": 0.5}`` for ``value_at``.
- `scale`: Positive normalization: a violation counts as (distance outside the interval) / ``scale``.
- `unit`: Declared unit, which must match the metric: A/cm for IV values, F/cm for CV values, V for thresholds. Nothing is converted.
- `lower`: Lower bound, or ``None``.
- `upper`: Upper bound, or ``None``; at least one bound is required.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L69)

## DesignResult

```python
class opentcad.design.DesignResult(
    outdir: Path,
    stop_reason: str,
    attempts: list[dict],
    best: dict | None,
) -> None
```

What :func:`run_design` did.

**Attributes**

- `outdir`: The evidence folder.
- `stop_reason`: ``target_met``, ``budget_exhausted``, ``search_stalled`` or ``no_valid_candidates``.
- `attempts`: One row per attempted candidate, failures included: values, metrics, violations, status, error and the files written for it.
- `best`: The valid candidate with the smallest total violation, or ``None``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/design.py#L495)

### DesignResult.to_dict

```python
DesignResult.to_dict()
```

JSON-safe summary; non-finite numbers become ``None``. Each
candidate's provenance record stays in its own JSON file.

Import from `opentcad.assist.design`: `draft_design`, `DesignDraft`.

## draft_design

```python
opentcad.assist.design.draft_design(
    request: str,
    *,
    client,
    base=None,
    current=None,
    evidence: dict | None = None,
    max_repairs: int = 1,
) -> DesignDraft
```

Ask a model to turn a request into a design plan for review.

Nothing is simulated, written or imported. The model sees the request,
the locked base, the fields it may vary, the IV/CV analyses and the
metrics, and replies in a schema narrowed to that base (see
``_response_schema``). The reply then goes through the same checks as
``opentcad design check``. Passing them says nothing about whether the
values are physically sensible.

**Parameters**

- `request`: The specification in plain language, at most 20,000 characters.
- `client`: A :class:`ChatClient`, or anything with the same ``chat``.
- `base`: Path to the simulation file to design from. Give this or ``current``.
- `current`: An existing plan (path or mapping) to revise; its base stays, and its assumptions, limitations and open questions are kept.
- `evidence`: A JSON run summary to show the model, e.g. a ``design.json``.
- `max_repairs`: How many times a failed reply is sent back with the problems (0–3).

**Returns**

A :class:`DesignDraft`.

**Raises**

- `ValueError`: Bad arguments, or a context over 80,000 characters.
- `LLMError`: The model server can't be reached.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/design.py#L198)

## DesignDraft

```python
class opentcad.assist.design.DesignDraft(
    proposal: DesignProposal | None = None,
    design: dict | None = None,
    problems: list[str] = list(),
    attempts: int = 0,
    raw_reply: str = '',
    request: str = '',
) -> None
```

A model's unaccepted design proposal and what the checks found.

**Attributes**

- `proposal`: The parsed reply, or ``None`` if it never parsed or validated.
- `design`: The proposal as a checked plain plan (base injected, questions as ``unresolved``), or ``None`` when it has no variables or targets.
- `problems`: Validation problems left after the last repair.
- `attempts`: Model calls made.
- `raw_reply`: The last reply text.
- `request`: The request as given.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/design.py#L57)

### DesignDraft.ok

```python
property DesignDraft.ok: bool
```

The reply parsed and passed the checks (it may still hold only questions).

### DesignDraft.to_dict

```python
DesignDraft.to_dict() -> dict
```

The review file ``opentcad design draft -o`` writes, marked unaccepted.
