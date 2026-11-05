"""
opentcad.device.extract — threshold voltage from simulated Id–Vgs curves.

Two standard definitions, so a TCAD curve and a reference curve (SPICE,
measurement) can be extracted the same way:

  * ``vth_max_gm`` — maximum-transconductance linear extrapolation (ELR):
    tangent to Id(Vgs) at the point of peak gm, extrapolated to Id = 0,
    minus Vds/2 (the linear-region correction).
  * ``vth_constant_current`` — Vgs at which |Id| reaches a chosen current,
    log-interpolated between the bracketing samples.

Currents can be in any unit (A, A/cm, A/µm) as long as the constant-current
criterion is in the same unit. Voltages in V.
"""
from __future__ import annotations

import numpy as np


def _validate(vgs, ids) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(vgs, dtype=float)
    i = np.abs(np.asarray(ids, dtype=float))
    if v.ndim != 1 or v.shape != i.shape:
        raise ValueError(f"vgs and ids must be 1-D and the same length "
                         f"(got {v.shape} and {i.shape})")
    if len(v) < 3:
        raise ValueError("need at least 3 bias points")
    if not np.all(np.diff(v) > 0):
        raise ValueError("vgs must be strictly increasing")
    return v, i


def vth_max_gm(vgs, ids, vds: float) -> float:
    """Threshold voltage [V] by maximum-gm linear extrapolation.

    Vth = Vgs* − Id*/gm* − Vds/2, where * is the bias of peak
    gm = dId/dVgs (central differences; non-uniform steps allowed).
    Meaningful for a linear-region sweep (small Vds).
    """
    v, i = _validate(vgs, ids)
    gm = np.gradient(i, v)
    k = int(np.argmax(gm))
    if gm[k] <= 0:
        raise ValueError("transconductance is never positive")
    if k == len(v) - 1:
        raise ValueError("peak gm is at the last bias point; extend the "
                         "sweep past the gm maximum")
    return float(v[k] - i[k] / gm[k] - vds / 2.0)


def vth_constant_current(vgs, ids, i_crit: float) -> float:
    """Threshold voltage [V] where |Id| first reaches ``i_crit``.

    Interpolates log10|Id| linearly between the two bracketing samples.
    The usual criterion is 100 nA × W/L; per unit width that is
    1e-7/L[µm] A/µm, or 1e-3/L[µm] A/cm.
    """
    v, i = _validate(vgs, ids)
    if i_crit <= 0:
        raise ValueError("i_crit must be positive")
    above = np.flatnonzero(i >= i_crit)
    if len(above) == 0:
        raise ValueError(f"|Id| never reaches {i_crit:.3e}")
    k = int(above[0])
    if k == 0:
        raise ValueError(f"|Id| already ≥ {i_crit:.3e} at the first bias "
                         "point; start the sweep lower")
    x0, x1 = v[k - 1], v[k]
    y0, y1 = np.log10(i[k - 1]), np.log10(i[k])
    return float(x0 + (np.log10(i_crit) - y0) * (x1 - x0) / (y1 - y0))
