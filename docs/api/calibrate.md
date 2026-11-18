# Calibration

Fitting model parameters to reference data, and writing the result as a material file.

For an introduction, see the [user guide](../calibration.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.calibrate`: `fit`, `Parameter`, `FitResult`, `Evaluation`, `apply_overrides`, `write_material_variant`.

## fit

```python
opentcad.calibrate.fit(
    residuals: Residuals,
    parameters: Sequence[Parameter],
    *,
    workers: int = 1,
    max_iterations: int = 15,
    rel_step: float = 0.05,
    tolerance: float = 0.001,
    log: Callable[[str], None] | None = print,
) -> FitResult
```

Fit ``parameters`` so that ``residuals(values)`` is smallest in the
least-squares sense.

**Parameters**

- `residuals`: ``f(values) -> residual vector``, where ``values`` maps each parameter name to a value. With ``workers > 1`` it must be importable by name (a module-level function), because it runs in separate processes. A non-finite residual is treated as a failed run and raises.
- `parameters`: What to fit, with bounds.
- `workers`: Processes used for the finite-difference Jacobian (``len(parameters)`` evaluations per iteration). 1 runs everything in this process.
- `max_iterations`: Most optimizer iterations (residual evaluations at a new point); each also costs one Jacobian.
- `rel_step`: Finite-difference step for parameters without their own ``step``: a factor ``1 + rel_step`` for log parameters, ``rel_step`` of the parameter's scale otherwise.
- `tolerance`: Relative tolerance on the parameters and on the cost.
- `log`: Called with one line per evaluation; ``None`` is silent.

**Returns**

A :class:`FitResult`.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L155)

## Parameter

```python
class opentcad.calibrate.Parameter(
    name: str,
    initial: float,
    lower: float,
    upper: float,
    log: bool = True,
    step: float | None = None,
) -> None
```

One parameter a calibration may change.

**Attributes**

- `name`: Dotted material-file field, e.g. ``"mobility_lombardi.delta_e"`` (see :func:`apply_overrides`), or any name your residual function understands.
- `initial`: Starting value, normally the literature value.
- `lower`: Lower bound.
- `upper`: Upper bound.
- `log`: Fit ``log10(value)`` instead of the value. Use it for positive coefficients that can move by factors rather than by amounts.
- `step`: Finite-difference step: in log10 units when ``log``, in the parameter's own units otherwise. ``None`` uses ``fit``'s ``rel_step``. Give one for a parameter the result is very sensitive to, such as an exponent.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L49)

### Parameter.to_internal

```python
Parameter.to_internal(value: float) -> float
```

### Parameter.from_internal

```python
Parameter.from_internal(u: float) -> float
```

## FitResult

```python
class opentcad.calibrate.FitResult(
    parameters: list[Parameter],
    values: dict[str, float],
    initial_values: dict[str, float],
    residuals: np.ndarray,
    rms: float,
    initial_rms: float,
    evaluations: list[Evaluation] = list(),
    success: bool = False,
    message: str = '',
    correlation: np.ndarray | None = None,
    at_bound: list[str] = list(),
) -> None
```

The outcome of :func:`fit`.

**Attributes**

- `parameters`: The parameters that were fitted.
- `values`: Fitted values by name.
- `initial_values`: Starting values by name.
- `residuals`: Residuals at the fitted values.
- `rms`: Root-mean-square residual at the fitted values.
- `initial_rms`: Root-mean-square residual at the starting values.
- `evaluations`: Every residual evaluation, in the order they finished.
- `success`: Whether the optimizer reports convergence.
- `message`: The optimizer's message.
- `correlation`: Correlation of the fitted parameters, from the Jacobian at the solution (in the fitted, possibly log, scale). Values near ±1 mean the data cannot tell those parameters apart.
- `at_bound`: Names of parameters that ended on a bound.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L102)

### FitResult.to_dict

```python
FitResult.to_dict() -> dict
```

A JSON-ready summary (without the evaluation history).

## Evaluation

```python
class opentcad.calibrate.Evaluation(
    values: dict[str, float],
    residuals: list[float],
    rms: float,
) -> None
```

One run of the residual function.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L94)

## apply_overrides

```python
opentcad.calibrate.apply_overrides(
    params: MaterialParams,
    values: Mapping[str, float],
) -> MaterialParams
```

A copy of ``params`` with ``values`` (``{"block.field": value}``) set.

Every name must be an existing field of a material block, e.g.
``"mobility_lombardi.delta_e"`` or ``"velocity_saturation.vsat_e_cm_s"``.
The copy is rebuilt through the material-file loader, so it is checked the
same way a file is, and its ``raw`` dict carries the new values.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L283)

## write_material_variant

```python
opentcad.calibrate.write_material_variant(
    path: str | Path,
    base: MaterialParams,
    values: Mapping[str, float],
    *,
    calibration: Mapping,
) -> Path
```

Write ``base`` with ``values`` applied as a material file at ``path``.

Save it as ``&lt;folder>/&lt;process>/&lt;symbol>.yaml`` and register ``&lt;folder>``
with ``opentcad.plugins.register_data_dir("materials", folder)``; then
``load_material(symbol, process=&lt;process>)`` reads it.

**Parameters**

- `path`: Output file.
- `base`: The material the fit started from (usually ``load_material(symbol)``).
- `values`: Fitted values, ``{"block.field": value}``.
- `calibration`: Written as the file's ``calibration`` block, replacing the base file's. Say what the values were fitted to and how (``status``, ``calibrated_against``, ``notes``...).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/calibrate.py#L301)
