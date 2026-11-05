"""
opentcad.device.builtin_metrics — numbers extracted from analysis results,
used by sweeps. Each takes the analysis result first; for ``iv`` and ``cv``
that is ``(x_values, y_values)``.

    vth_max_gm(result, vds)            max-gm linear-extrapolation Vth [V]
    vth_constant_current(result, i_crit)  Vgs where |I| reaches i_crit [V]
    value_at(result, x)                |y| linearly interpolated at x
    max_abs(result)                    largest |y|

``opentcad.plugins`` calls ``register()`` the first time a registry is
consulted.
"""
from __future__ import annotations

import numpy as np

from opentcad.plugins import register_metric

from .extract import vth_constant_current as _vth_cc
from .extract import vth_max_gm as _vth_gm


def _xy(result):
    try:
        x, y = result
    except (TypeError, ValueError):
        raise ValueError("this metric needs an (x, y) result such as an "
                         "iv or cv analysis returns") from None
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def vth_max_gm(result, vds: float) -> float:
    x, y = _xy(result)
    return _vth_gm(x, y, vds)


def vth_constant_current(result, i_crit: float) -> float:
    x, y = _xy(result)
    return _vth_cc(x, y, i_crit)


def value_at(result, x: float) -> float:
    xs, ys = _xy(result)
    order = np.argsort(xs)
    xs, ys = xs[order], np.abs(ys[order])
    if not xs[0] <= x <= xs[-1]:
        raise ValueError(f"x = {x} is outside the swept range "
                         f"[{xs[0]}, {xs[-1]}]")
    return float(np.interp(x, xs, ys))


def max_abs(result) -> float:
    _, ys = _xy(result)
    return float(np.max(np.abs(ys)))


def register() -> None:
    register_metric("vth_max_gm", vth_max_gm)
    register_metric("vth_constant_current", vth_constant_current)
    register_metric("value_at", value_at)
    register_metric("max_abs", max_abs)
