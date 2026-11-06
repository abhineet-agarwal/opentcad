"""
opentcad.device.builtin_analyses — registers the built-in analyses so they
are reachable by name through ``DeviceSolver.run``:

    "iv"         → DeviceSolver.iv_sweep
    "cv"         → DeviceSolver.cv_sweep
    "transient"  → DeviceSolver.transient_sweep
    "ac"         → DeviceSolver.ac_sweep
    "fields"     → DeviceSolver.field_snapshot (a MeshField with the solution)

The unbound methods are registered as-is, so ``fn(solver, **kwargs)``
works and their signatures can be checked before a run.
``opentcad.plugins`` calls ``register()`` the first time a registry is
consulted.
"""
from __future__ import annotations

from opentcad.plugins import register_analysis


def register() -> None:
    from .solver import DeviceSolver
    register_analysis("iv", DeviceSolver.iv_sweep)
    register_analysis("cv", DeviceSolver.cv_sweep)
    register_analysis("transient", DeviceSolver.transient_sweep)
    register_analysis("ac", DeviceSolver.ac_sweep)
    register_analysis("fields", DeviceSolver.field_snapshot)
