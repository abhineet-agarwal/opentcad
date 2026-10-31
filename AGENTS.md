# Agent workflow

The repository owner requests Astra orchestration with Sol execution.

- Use `gpt-6-astra` for task decomposition, architecture, delegation, evidence
  review and final acceptance decisions.
- Delegate substantive implementation, simulations, extraction, documentation
  edits, formatting and routine checks to `gpt-6.1-sol` workers. Specify the model
  explicitly when spawning so workers do not inherit Astra accidentally.
- Give workers bounded tasks, file ownership and concrete acceptance criteria.
  Coordinate shared-file edits and review their evidence before accepting work.
- If the current root conversation is running Sol, delegate planning/review to
  `astra_orchestrator` and follow its reviewed plan; do not claim the root model
  changed. Repository model defaults apply when the client loads them and can be
  overridden by an explicit conversation model selection.
- Preserve existing user changes. Keep reusable physics in `opentcad` and
  application-specific designs and evidence under `examples/microrobot`.
- Record what was actually executed, numerical assumptions and limitations.
  Simulator exit status alone is insufficient evidence of a complete transient.
- Do not submit, publish, push or initiate fabrication without user authorization
  for that action. Do not include local reference PDFs or raw SPICE transients
  in submission exports.
