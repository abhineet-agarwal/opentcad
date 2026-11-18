# Bounded device design

`pn_current.yaml` varies one existing PN diode doping field. The target is a
workflow illustration: 80% of the original simulated current at 0.5 V with a ±5%
interval. It is not an experimental specification or calibration dataset.

```sh
opentcad design check examples/design/pn_current.yaml
opentcad design run examples/design/pn_current.yaml -o /tmp/pn-current-search
```

Use a new output directory for each run. The bounded search can meet the target,
exhaust its budget, stall or fail; inspect the candidate evidence. A numerical
success does not establish physical accuracy or fabrication readiness. See
[the design guide](../../docs/design.md) for model-assisted prompting and review.
