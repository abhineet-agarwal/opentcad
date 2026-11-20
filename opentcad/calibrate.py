"""Fit physical-model parameters to reference data.

A calibration names the parameters it may change (:class:`Parameter`, a
dotted material-file field such as ``"mobility_lombardi.delta_e"`` with
bounds), supplies a function that runs the simulation for a set of values
and returns residuals against the reference, and calls :func:`fit`. The fit
is bounded nonlinear least squares (``scipy.optimize.least_squares``). Each
residual evaluation is usually a full device simulation, so the
finite-difference Jacobian can run its evaluations in parallel processes
(``workers``); DEVSIM keeps one global state per process, so processes, not
threads, are what parallelise it.

:func:`apply_overrides` puts fitted values into a ``MaterialParams``, and
:func:`write_material_variant` writes them as a process-variant material
file that ``load_material(symbol, process=...)`` reads, with a
``calibration`` block saying what was fitted, to what, and from which
starting values. Fitted values are effective: they absorb whatever the
simulation leaves out, so the file records the conditions of the fit.

Example::

    from opentcad.calibrate import Parameter, fit

    def residuals(values):            # module-level, so workers can import it
        ids = simulate(values)        # your simulation
        return ids / reference - 1.0

    result = fit(residuals, [Parameter("mobility_lombardi.delta_e", 3.58e18, 1e16, 1e20)])
    print(result.values, result.rms)
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import math
import multiprocessing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from opentcad.materials.database import MaterialParams, params_from_dict

Residuals = Callable[[dict[str, float]], Sequence[float]]


@dataclass(frozen=True)
class Parameter:
    """One parameter a calibration may change.

    Attributes:
        name: Dotted material-file field, e.g. ``"mobility_lombardi.delta_e"``
            (see :func:`apply_overrides`), or any name your residual function
            understands.
        initial: Starting value, normally the literature value.
        lower: Lower bound.
        upper: Upper bound.
        log: Fit ``log10(value)`` instead of the value. Use it for positive
            coefficients that can move by factors rather than by amounts.
        step: Finite-difference step: in log10 units when ``log``, in the
            parameter's own units otherwise. ``None`` uses ``fit``'s
            ``rel_step``. Give one for a parameter the result is very
            sensitive to, such as an exponent.
    """
    name: str
    initial: float
    lower: float
    upper: float
    log: bool = True
    step: float | None = None

    def __post_init__(self):
        if not self.lower <= self.initial <= self.upper:
            raise ValueError(f"{self.name}: initial {self.initial:g} is outside "
                             f"[{self.lower:g}, {self.upper:g}]")
        if self.log and self.lower <= 0:
            raise ValueError(f"{self.name}: a log-scaled parameter needs lower > 0")
        if self.step is not None and self.step <= 0:
            raise ValueError(f"{self.name}: step must be positive")

    def to_internal(self, value: float) -> float:
        return math.log10(value) if self.log else value / self._scale

    def from_internal(self, u: float) -> float:
        return 10.0 ** u if self.log else u * self._scale

    @property
    def _scale(self) -> float:
        return max(abs(self.initial), abs(self.lower), abs(self.upper), 1e-300)


@dataclass
class Evaluation:
    """One run of the residual function."""
    values: dict[str, float]
    residuals: list[float]
    rms: float


@dataclass
class FitResult:
    """The outcome of :func:`fit`.

    Attributes:
        parameters: The parameters that were fitted.
        values: Fitted values by name.
        initial_values: Starting values by name.
        residuals: Residuals at the fitted values.
        rms: Root-mean-square residual at the fitted values.
        initial_rms: Root-mean-square residual at the starting values.
        evaluations: Every residual evaluation, in the order they finished.
        success: Whether the optimizer reports convergence.
        message: The optimizer's message.
        correlation: Correlation of the fitted parameters, from the Jacobian
            at the solution (in the fitted, possibly log, scale). Values near
            ±1 mean the data cannot tell those parameters apart.
        at_bound: Names of parameters that ended on a bound.
    """
    parameters: list[Parameter]
    values: dict[str, float]
    initial_values: dict[str, float]
    residuals: np.ndarray
    rms: float
    initial_rms: float
    evaluations: list[Evaluation] = field(default_factory=list)
    success: bool = False
    message: str = ""
    correlation: np.ndarray | None = None
    at_bound: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """A JSON-ready summary (without the evaluation history)."""
        return {
            "parameters": [{"name": p.name, "initial": p.initial, "lower": p.lower,
                            "upper": p.upper, "log": p.log,
                            "fitted": self.values[p.name]} for p in self.parameters],
            "rms": self.rms,
            "initial_rms": self.initial_rms,
            "n_evaluations": len(self.evaluations),
            "success": self.success,
            "message": self.message,
            "at_bound": list(self.at_bound),
            "correlation": None if self.correlation is None
            else np.round(self.correlation, 3).tolist(),
        }


def _rms(r) -> float:
    r = np.asarray(r, dtype=float)
    return float(np.sqrt(np.mean(r ** 2)))


def fit(residuals: Residuals, parameters: Sequence[Parameter], *,
        workers: int = 1, max_iterations: int = 15, rel_step: float = 0.05,
        tolerance: float = 1e-3, log: Callable[[str], None] | None = print) -> FitResult:
    """Fit ``parameters`` so that ``residuals(values)`` is smallest in the
    least-squares sense.

    Args:
        residuals: ``f(values) -> residual vector``, where ``values`` maps
            each parameter name to a value. With ``workers > 1`` it must be
            importable by name (a module-level function), because it runs in
            separate processes. A non-finite residual is treated as a failed
            run and raises.
        parameters: What to fit, with bounds.
        workers: Processes used for the finite-difference Jacobian
            (``len(parameters)`` evaluations per iteration). 1 runs everything
            in this process.
        max_iterations: Most optimizer iterations (residual evaluations at a
            new point); each also costs one Jacobian.
        rel_step: Finite-difference step for parameters without their own
            ``step``: a factor ``1 + rel_step`` for log parameters,
            ``rel_step`` of the parameter's scale otherwise.
        tolerance: Relative tolerance on the parameters and on the cost.
        log: Called with one line per evaluation; ``None`` is silent.

    Returns:
        A :class:`FitResult`.
    """
    from scipy.optimize import least_squares

    params = list(parameters)
    if not params:
        raise ValueError("nothing to fit")
    names = [p.name for p in params]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate parameter names in {names}")
    say = log or (lambda _msg: None)
    u0 = np.array([p.to_internal(p.initial) for p in params])
    lo = np.array([p.to_internal(p.lower) for p in params])
    hi = np.array([p.to_internal(p.upper) for p in params])
    steps = np.array([(p.step if p.log else p.step / p._scale) if p.step is not None
                      else (math.log10(1.0 + rel_step) if p.log else rel_step) for p in params])

    history: list[Evaluation] = []
    cache: dict[tuple, np.ndarray] = {}

    def values_at(u) -> dict[str, float]:
        return {p.name: p.from_internal(float(x)) for p, x in zip(params, u)}

    def record(u, r) -> np.ndarray:
        r = np.asarray(r, dtype=float)
        if r.ndim != 1 or not np.all(np.isfinite(r)):
            raise ValueError(f"residuals at {values_at(u)} are not a finite vector")
        cache[_key(u)] = r
        ev = Evaluation(values_at(u), r.tolist(), _rms(r))
        history.append(ev)
        say(f"[{len(history):3d}] rms {ev.rms:.4f}  " + "  ".join(
            f"{n.rsplit('.', 1)[-1]}={v:.4g}" for n, v in ev.values.items()))
        return r

    pool = None
    if workers > 1:
        pool = cf.ProcessPoolExecutor(max_workers=workers,
                                      mp_context=multiprocessing.get_context("spawn"))

    def evaluate_many(points: list[np.ndarray]) -> list[np.ndarray]:
        todo = [u for u in points if _key(u) not in cache]
        if pool is None or len(todo) < 2:
            for u in todo:
                record(u, residuals(values_at(u)))
        else:
            futures = {pool.submit(residuals, values_at(u)): u for u in todo}
            for fut in cf.as_completed(futures):
                record(futures[fut], fut.result())
        return [cache[_key(u)] for u in points]

    def fun(u):
        return evaluate_many([np.asarray(u, dtype=float)])[0]

    def jac(u):
        u = np.asarray(u, dtype=float)
        h = np.where(u + steps <= hi, steps, -steps)      # step inward at the upper bound
        points = [u] + [u + h[i] * np.eye(len(u))[i] for i in range(len(u))]
        r0, *rs = evaluate_many(points)
        return np.column_stack([(r - r0) / h[i] for i, r in enumerate(rs)])

    try:
        r_init = fun(u0)
        sol = least_squares(fun, u0, jac=jac, bounds=(lo, hi), method="trf",
                            x_scale=1.0, xtol=tolerance, ftol=tolerance,
                            gtol=tolerance, max_nfev=max_iterations)
        J = jac(sol.x)
    finally:
        if pool is not None:
            pool.shutdown()

    corr = None
    try:
        cov = np.linalg.pinv(J.T @ J)
        d = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
        corr = cov / np.outer(d, d)
    except np.linalg.LinAlgError:
        pass
    tol_b = 1e-6 * np.maximum(1.0, np.abs(hi - lo))
    at_bound = [p.name for p, x, a, b, t in zip(params, sol.x, lo, hi, tol_b)
                if x - a < t or b - x < t]
    r_fit = cache[_key(sol.x)] if _key(sol.x) in cache else fun(sol.x)
    return FitResult(
        parameters=params, values=values_at(sol.x),
        initial_values={p.name: p.initial for p in params},
        residuals=r_fit, rms=_rms(r_fit), initial_rms=_rms(r_init),
        evaluations=history, success=bool(sol.success), message=str(sol.message),
        correlation=corr, at_bound=at_bound)


def _key(u) -> tuple:
    return tuple(np.round(np.asarray(u, dtype=float), 12))


# --------------------------------------------------------------------------
# Material files
# --------------------------------------------------------------------------
def _split(name: str) -> tuple[str, str]:
    block, _, key = name.partition(".")
    if not key or "." in key:
        raise ValueError(f"{name!r} is not a 'block.field' material name")
    return block, key


#: The source a value set by ``apply_overrides`` cites unless told otherwise.
OVERRIDE_SOURCE = {"kind": "override",
                   "cite": "Set in code with opentcad.calibrate.apply_overrides"}


def apply_overrides(params: MaterialParams, values: Mapping[str, float], *,
                    source: Optional[Mapping] = None) -> MaterialParams:
    """A copy of ``params`` with ``values`` (``{"block.field": value}``) set.

    Every name must be an existing field of a material block, e.g.
    ``"mobility_lombardi.delta_e"`` or ``"velocity_saturation.vsat_e_cm_s"``.
    The copy is rebuilt through the material-file loader, so it is checked the
    same way a file is, and its ``raw`` dict carries the new values.

    Each new value cites ``source`` (a source in file form, see
    ``opentcad.provenance``) instead of the file's citation, which was for the
    old value. The default says the value was set in code.
    """
    raw = copy.deepcopy(params.raw)
    src = dict(source or OVERRIDE_SOURCE)
    key = _source_key(raw, "fit" if src.get("kind") == "fit" else "override", src)
    for name, value in values.items():
        block, field = _split(name)
        model = getattr(params, block, None)
        if model is None or field not in getattr(type(model), "model_fields", {}):
            raise KeyError(f"{name!r} is not a material parameter")
        raw.setdefault(block, {})[field] = float(value)
        raw.setdefault("cite", {})[name] = key
    if values:
        raw.setdefault("sources", {})[key] = src
    return params_from_dict(raw, params.symbol, source=params.source)


def _source_key(raw: dict, base: str, src: dict) -> str:
    """A key for ``src`` in ``raw['sources']``: ``base``, or ``base2``... if
    ``base`` is taken by a different source."""
    have = raw.get("sources") or {}
    key, n = base, 1
    while key in have and have[key] != src:
        n += 1
        key = f"{base}{n}"
    return key


def write_material_variant(path: str | Path, base: MaterialParams,
                           values: Mapping[str, float], *, calibration: Mapping) -> Path:
    """Write ``base`` with ``values`` applied as a material file at ``path``.

    Save it as ``<folder>/<process>/<symbol>.yaml`` and register ``<folder>``
    with ``opentcad.plugins.register_data_dir("materials", folder)``; then
    ``load_material(symbol, process=<process>)`` reads it.

    Args:
        path: Output file.
        base: The material the fit started from (usually ``load_material(symbol)``).
        values: Fitted values, ``{"block.field": value}``.
        calibration: Written as the file's ``calibration`` block, replacing the
            base file's. Say what the values were fitted to and how
            (``status``, ``calibrated_against``, ``notes``...).
    """
    against = calibration.get("calibrated_against")
    how = "; ".join(f"{k}: {calibration[k]}" for k in ("fitted_with", "result")
                    if calibration.get(k))
    fit = {"kind": "fit",
           "cite": f"Fitted to {against}" if against else "Fitted; the data is not recorded"}
    if how:
        fit["note"] = how
    fitted = apply_overrides(base, values, source=fit)
    raw = copy.deepcopy(fitted.raw)
    raw["calibration"] = dict(calibration)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# {raw.get('material', base.symbol)} — a calibrated variant of "
              f"{Path(base.source).name or base.symbol}, written by "
              f"opentcad.calibrate.write_material_variant.\n"
              "# The fitted values are listed under calibration.fitted and cite the fit "
              "(sources.fit);\n# every other value keeps the base file's source.\n")
    path.write_text(header + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    return path
