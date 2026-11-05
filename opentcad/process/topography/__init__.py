"""
opentcad.process.topography — Level-set topography simulation.

Public surface:
    Recipe, Deposit, Etch, Oxidize     — recipe DSL (pure data)
    TopographyState, Layer             — simulation state (viennals-backed)
    simulate                           — run a Recipe on a Structure
    initial_state_from_structure       — get the starting stack
    extract_surface_polyline           — level-set → (nodes, lines)
    topography_to_meshfield            — final state → MeshField for the
                                          device solver

The recipe classes import eagerly. Everything backed by ViennaLS loads on
first use, so recipes, doping and the device solver work without ViennaLS
installed; only running a topography step needs it.
"""
from __future__ import annotations

import importlib

from .recipe import Deposit, Etch, Oxidize, Recipe

_LAZY = {
    "Layer": ".simulator",
    "TopographyState": ".simulator",
    "extract_surface_polyline": ".simulator",
    "initial_state_from_structure": ".simulator",
    "simulate": ".simulator",
    "topography_to_meshfield": ".mesh_bridge",
}


def __getattr__(name: str):
    if name in _LAZY:
        try:
            module = importlib.import_module(_LAZY[name], __name__)
        except ImportError as exc:
            raise ImportError(
                f"opentcad.process.topography.{name} needs ViennaLS "
                f"(pip install ViennaLS): {exc}") from exc
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Recipe", "Deposit", "Etch", "Oxidize",
    "Layer", "TopographyState",
    "extract_surface_polyline",
    "initial_state_from_structure",
    "simulate",
    "topography_to_meshfield",
]
