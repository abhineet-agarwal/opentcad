# Device design from specifications

OpenTCAD can turn a prompt and an existing simulation deck into a reviewable
bounded design request, then search that request with real device simulations.
The first implementation varies numeric geometry, doping or process fields in a
fixed device family. The base topology, material assignments, physics models,
mesh and measurement analyses stay fixed. Arbitrary topology synthesis and
inventing new executable process models remain future work.

The model assistant is optional. A hand-written YAML or JSON plan runs the same
validator and search without a chat server. The assistant uses the existing
`ChatClient` with a configured OpenAI-compatible server; it neither starts a
server nor substitutes canned output when one is unavailable.

## Start with a concrete plan

The [PN diode example](https://github.com/abhineet-agarwal/opentcad/blob/main/examples/design/pn_current.yaml) tunes acceptor doping
to reduce current at 0.5 V. Its target is illustrative: 80% of the original
simulated baseline, with a ±5% acceptance interval. It is a workflow example,
with no experimental calibration claim.

```sh
opentcad design check examples/design/pn_current.yaml
opentcad design run examples/design/pn_current.yaml -o /tmp/pn-current-search
```

Each run requires a new output directory. A plan looks like:

```yaml
version: 1
name: pn_current_design
base: ../decks/pn_diode.yaml   # relative to this design file; an inline deck also works
variables:
  - path: structure.layers[0].doping_Na
    lower: 1e16
    upper: 1e18
    initial: 1e17
    scale: log
targets: []                   # replace with the targets block below
```

The `targets` block for this example is:

```yaml
targets:
  - name: forward_current
    analysis: forward
    metric: value_at
    options: {x: 0.5}
    lower: 1.590388974865894e-6
    upper: 1.7577983406412515e-6
    scale: 1.674093657753573e-6
    unit: A/cm
search: {max_evaluations: 8, initial_step: 0.25, min_step: 0.01}
assumptions: [Illustrative current reduction from a numerical baseline.]
limitations: [Fixed mesh and physics require independent validation.]
unresolved: []
```

Use the complete example file directly; the snippets explain its fields.
Variables need existing numeric paths, finite ordered bounds and an initial
value inside those bounds. Logarithmic bounds must be positive. The first slice
allows the existing structure dimensions/doping fields and numeric recipe
fields. Changing a device model, contact barrier, mesh, analysis or material
assignment through a variable is rejected.

Each target names an existing IV or CV analysis, a supported metric, its
options, at least one bound and a positive normalization `scale`. The search
minimizes the sum of out-of-bound distances divided by each target's scale.
A candidate meets the targets when every metric lies within all its bounds.
`scale` sets relative importance and numerical normalization; it is separate
from the target interval.

| Metric | Options | Result unit |
| --- | --- | --- |
| `value_at` | `x`: swept voltage within the analysis range | IV: A/cm; CV: F/cm |
| `max_abs` | none | IV: A/cm; CV: F/cm |
| `vth_max_gm` | `vds`: drain bias | V, IV only |
| `vth_constant_current` | `i_crit`: current criterion in A/cm | V, IV only |

`value_at` linearly interpolates the absolute output value; `max_abs` takes the
largest absolute value. Currents from the two-dimensional solver are **A/cm**
of out-of-plane width, rather than total amperes. Capacitance is F/cm. A total
A or F target requires an explicitly justified out-of-plane conversion before
writing the plan. The validator checks the unit label and performs no conversion.

`design check` validates the contract and lists unresolved questions without
running the solver. It returns 1 while `unresolved` contains questions.
Resolve them in the reviewed plain plan before execution.

## Draft a request by prompting

Configure a server using `OPENTCAD_LLM_URL`, `OPENTCAD_LLM_MODEL` and, when
required, `OPENTCAD_LLM_API_KEY`. The default URL is the local server
`http://127.0.0.1:8080/v1`. CLI `--url` and `--model` override the first two values.
Only a `design draft` invocation contacts this configured server.

```sh
opentcad design draft \
  'Keep the PN diode physics fixed. Vary p-body acceptor doping from 1e16 to 1e18 cm^-3, initially 1e17, on a log scale. Target absolute forward current at 0.5 V between 1.59e-6 and 1.76e-6 A/cm. Use scale 1.67e-6 A/cm and at most 8 evaluations.' \
  --base examples/decks/pn_diode.yaml \
  -o /tmp/pn-draft.json --plan-out /tmp/pn-plan.json
```

`pn-draft.json` is an unaccepted review envelope containing the proposed plan,
assumptions, questions and validation problems. `--plan-out` additionally writes
an editable plain plan when the response contains valid variables and targets.
Existing output files are preserved: choose new paths for each draft. An
unsupported or underspecified request can produce questions with no plain plan.

The assistant receives the selected base, the fields it may vary (each with
its current value; `opentcad.design.variable_paths` lists them), the base's
IV/CV analyses and the supported metric descriptions. Its response schema
accepts design knobs and targets but cannot supply a replacement base or
executable code. The schema is narrowed to the base: variable paths and
analyses are lists to choose from, each metric has its own options and unit,
and every field must be stated. A server that enforces schemas, such as
llama-server, can therefore only produce names the validator accepts. The values
are still the model's. The caller injects the trusted normalized base; the
core validator checks the entire proposed contract. One repair is allowed by
default, configurable from zero to three with `--max-repairs`.

Every model-proposed value remains marked **unverified**, including apparently
copied values. Schema validation cannot determine scientific validity or prove
which phrase produced a number. Inferences and missing information require
human review. The plain plan retains the unverified warning under `limitations`.
Questions populate its execution-blocking `unresolved` list.

Inspect both files, edit the plain plan, resolve the questions and check it.
An explicit run then executes exactly that reviewed plan:

```sh
opentcad design check /tmp/pn-plan.json
opentcad design run /tmp/pn-plan.json -o /tmp/pn-search-1
```

Drafting never runs simulations, modifies the source deck or imports catalog
records. A missing server produces an actionable connection error.

### Measured with a 3B model

Qwen2.5-3B-Instruct (Q4_K_M) on llama-server, on an M4 with 16 GB, with the
two example decks. Each request was drafted twice, with the same outcome both times.

| Request | Draft | Time |
|---|---|---|
| The PN request above, every value given | Correct plan on attempt 1 | 13–17 s |
| "Raise the NMOS threshold (max-gm, Vds 0.05 V) to 0.45–0.55 V by varying the substrate doping between 1e16 and 1e18, starting at 1e17; at most 10 evaluations", from `nmos_implanted.yaml` | Correct plan on attempt 1 | 10–12 s |
| "Reduce the forward current at 0.5 V by about 20 percent from 2.09e-6 A/cm by changing the p-side doping" | Valid but wrong: the target interval (1.7–2.4 and 1.68–2.3 × 10⁻⁶ A/cm in two runs) contains the starting current, so the first candidate would already meet it | 8–13 s |
| "Design a FinFET with 5 nm fins and a high-k gate" | Valid but meaningless: it varies every field of the PN diode instead of answering with questions only | 20–27 s |

In every case the model also added generic questions ("Is the evaluation
budget sufficient?"), which block `design run` until you remove them. So
the plan can't run until you've read it. The two bad drafts pass the
validator: only reading them catches the errors.

Running the reviewed NMOS plan met the target in 4 candidates (26 s): the
threshold is 0.50 V at 1 × 10¹⁶ cm⁻³. The first two candidates, at
1 × 10¹⁷ (the starting point) and 3.2 × 10¹⁷, failed. Their peak gm lies
beyond the deck's 1.5 V sweep, so `vth_max_gm` has nothing to extract.
Failed candidates use up budget. Choose a metric that is defined over the
whole range you search, e.g. `vth_constant_current`, or extend the sweep.

## Refine the request with run evidence

Provide the current plan and explicit JSON run summary as prompt context:

```sh
opentcad design draft \
  'Preserve the target and physics. Increase the evaluation budget to 16. Explain any new assumptions.' \
  --current /tmp/pn-plan.json --feedback /tmp/pn-search-1/design.json \
  -o /tmp/pn-revision-draft.json --plan-out /tmp/pn-plan-2.json
```

`--current` and `--base` are mutually exclusive. The current plan's base stays
fixed; prior assumptions and limitations are retained. Existing unresolved
questions also persist if the model omits them. After answering a question,
explicitly resolve and remove its entry in the reviewed plan before the next
draft or run. This conservative rule prevents model omission from silently
clearing an unknown.

Evidence is reference data only. It does not trigger an automatic simulation or
change the frozen physics. Context is bounded to 80,000 characters, with a 20,000
character request limit. If a full run summary grows too large, provide a smaller
JSON summary containing the stop reason, best metrics, relevant failures and
questions. Review and explicitly run each resulting plan.

## Search and evidence

The search starts at the supplied initial values and polls positive and negative
coordinate moves in normalized parameter space. It moves to a better candidate
or halves the step. Each attempted candidate, including invalid geometry or a
failed solver/metric evaluation, consumes the finite evaluation budget.
Previously visited coordinates are cached. This local method has no guarantee
of finding a feasible or globally optimal design.

The evidence directory contains the resolved contract and hash, base deck,
environment/material snapshots, per-candidate decks and JSON results, the final
`design.json` summary and `best.yaml` when at least one candidate was valid.
Candidate evidence records parameter changes and their search reason, actual
analysis arrays, completion checks, metrics, normalized violations and errors.
Target IV/CV sweeps must match the complete expected finite grid before a
candidate can be counted as valid. Environment snapshots aid auditing but do
not freeze the entire runtime or third-party plugin implementation.

| Outcome | Meaning | CLI exit |
| --- | --- | --- |
| `target_met` | All target intervals met in the fixed numerical model | 0 |
| `budget_exhausted` | Targets remain unmet at the evaluation limit | 1 |
| `search_stalled` | Local step refinement stopped without meeting all targets | 1 |
| `no_valid_candidates` | Every attempted candidate failed | 2 |

Validation problems return 1; execution/setup failures return 2. Interrupted
searches retain completed candidate evidence. Budget exhaustion or stalling
does not establish infeasibility. A target-met result still needs independent
physics, mesh and experimental validation for its intended use; it confers no
calibration, fabrication readiness, publication or submission approval.
