"""
opentcad.device.builtin_analyses — registers the built-in analyses so they
are reachable by name through ``DeviceSolver.run``:

    "iv"         → DeviceSolver.iv_sweep
    "cv"         → DeviceSolver.cv_sweep
    "transient"  → DeviceSolver.transient_sweep
    "ac"         → DeviceSolver.ac_sweep

``opentcad.plugins`` calls ``register()`` the first time a registry is
consulted.
"""
from __future__ import annotations

from opentcad.plugins import register_analysis


def _iv(solver, **kwargs):
    return solver.iv_sweep(**kwargs)


def _cv(solver, **kwargs):
    return solver.cv_sweep(**kwargs)


def _transient(solver, **kwargs):
    return solver.transient_sweep(**kwargs)


def _ac(solver, **kwargs):
    return solver.ac_sweep(**kwargs)


def register() -> None:
    register_analysis("iv", _iv)
    register_analysis("cv", _cv)
    register_analysis("transient", _transient)
    register_analysis("ac", _ac)
