# Separate Reynolds S2E candidate fits

Training-only ideal single-diode effective pair candidates; application defaults and historical fit unchanged.

300 K is assumed, not measured. Two series cells, each 540 µm², and one sun = 1000 W/m² follow the figure context; no TCAD geometry is calibrated.

Holdout regions [0.90,1.05) and [1.15,1.25) V were excluded from both branches before any fitting, initialization, scaling or fixed-offset estimation. Both main hypotheses are retained without selecting a winner using holdouts. These are conditional model diagnostics, not an independent final accuracy test.

Objective: each branch has equal weight; within a branch each occupied voltage bin has equal weight, and native residuals within each bin are averaged in squared current. Bins are anchored at 0 V. The 1 nA residual scale serves numerical conditioning only, not experimental uncertainty. No point sorting, merging, trimming or offset subtraction is applied to observations.

| Training bin | Offset hypothesis | Offset nA | n (per cell) | Iph nA | Device Voc V | Device Pmax nW | Heldout equal-branch/bin RMS nA |
|---:|---|---:|---:|---:|---:|---:|---:|
| 25 mV | zero | 0.0000 | 1.377236 | 149.7248 | 1.228832 | 144.7797 | 20.4074 |
| 25 mV | shared_fit | 1.9251 | 1.370815 | 151.5852 | 1.230252 | 146.9094 | 20.3400 |
| 25 mV | fixed_dark_median | 1.8616 | 1.371026 | 151.5238 | 1.230205 | 146.8391 | 20.3410 |
| 12.5 mV | zero | 0.0000 | 1.332481 | 149.5827 | 1.230682 | 145.7964 | 18.2715 |
| 12.5 mV | shared_fit | 1.9481 | 1.325900 | 151.4712 | 1.232089 | 147.9715 | 18.1693 |
| 12.5 mV | fixed_dark_median | 1.8616 | 1.326190 | 151.3874 | 1.232027 | 147.8748 | 18.1720 |
| 50 mV | zero | 0.0000 | 1.221441 | 149.3411 | 1.233608 | 148.2495 | 14.5589 |
| 50 mV | shared_fit | 2.0193 | 1.214863 | 151.2957 | 1.234957 | 150.5220 | 14.3733 |
| 50 mV | fixed_dark_median | 1.8616 | 1.215372 | 151.1431 | 1.234853 | 150.3444 | 14.3838 |

Frozen historical fit diagnostic on the candidate-heldout regions, equal-branch/bin RMS at 25 mV: 11.1937 nA. Historical model observation offset remains zero. It was fitted to the full plotted raster curve, including these voltages: this is not a holdout-trained baseline or a fairness-controlled benchmark.

The shared fitted offset is bounded ±10 nA. A third sensitivity hypothesis fixes it to the training dark |V|<0.01 V median; none establishes a true instrument correction. Device Voc/MPP exclude this additive observation offset. Candidate parameter variation across 12.5/25/50 mV bins and offset choices is algorithmic sensitivity, not a confidence interval.

The single exponential leaves structural residuals, repeated-voltage scatter and possible instrumental effects. No Rs, shunt resistance, breakdown, mismatch, storage, electrochemistry or temperature dependence is inferred. Only n*T is constrained by the exponential slope at fixed series count; assumed T does not produce a unique physical ideality or a calibrated TCAD process. These DC results do not validate circuit transients, logic-PV scaling or robot mechanics.

Source authorship/archive version/license remain user-reported and unverified. JSON contains source hashes and aggregate fit diagnostics, not raw arrays. No raw files were copied or altered. The old model and application defaults remain unchanged.

Regenerate into a NEW or empty directory with:

```sh
.venv/bin/python -m examples.microrobot.reynolds_fit --source-dir /local/Reynolds-2022-data --output /local/new-fit-results
```

The command refuses nonempty output archives and destinations inside the source directory; no --force option exists.

Review decision: accepted as a separate candidate and sensitivity experiment; neither candidate is accepted as a calibrated default. Training error improves, but the withheld knee regions retain structured mismatch: 25 mV candidate errors are 20.34–20.41 nA versus the frozen model's descriptive 11.19 nA, and fitted ideality varies about 1.21–1.38 across bin choices. The frozen model used the full plotted curve, so this comparison is not a fairness-controlled held-out baseline. Keep both hypotheses separate from application defaults; no all-data refit or objective tuning was performed.

Closure verification on 2026-10-30: 34 focused Reynolds tests passed; Ruff lint and format checks passed for both Reynolds modules and their tests. Scoped whitespace and local relative-link checks passed. The wording correction preserves all 2,321 numerical JSON values; the original report is retained in [fit_report_as_executed.json](fit_report_as_executed.json). [Editorial provenance](editorial_provenance.json) records the hashes and closure checks. The earlier 254-test full suite is a pre-editorial checkpoint; no full suite, fit or simulation was rerun for this closure.
