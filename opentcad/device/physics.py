"""
opentcad/device/physics.py — Pluggable physics configuration for DeviceSolver.

A `PhysicsConfig` bundles together the physics models the solver should
use (mobility, eventually recombination, BGN, avalanche, ...). Each model
is an object with an `attach()` method that registers the DEVSIM
node/edge models it needs.

The continuity-equation builder in DeviceSolver expects each mobility
model to register two edge models per semiconductor region:
    ElectronMobilityEdge   — electron mobility on the edge [cm^2/V/s]
    HoleMobilityEdge       — hole mobility on the edge [cm^2/V/s]

If the mobility depends on the carrier densities (e.g. Klaassen), the
edge models must also register :Electrons@n0/@n1 and :Holes@n0/@n1
derivatives so the Newton solver can converge.

Usage:
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.models.mobility import Klaassen
    solver = DeviceSolver(mf, mat_params,
                          physics=PhysicsConfig(mobility=Klaassen()))
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


class MobilityModel(ABC):
    """Base class for low-field bulk mobility models.

    Subclasses register the DEVSIM parameters/models they need in
    `attach()` and expose the *expressions* the solver should substitute
    into the Scharfetter-Gummel current density via `mu_n_expr()` and
    `mu_p_expr()`. Inlining the expression rather than wrapping in an
    edge_model lets the constant case reduce to the original solver
    expression exactly, which is friendlier to Newton convergence.
    """

    #: Whether the model needs Electrons/Holes node solutions registered
    #: as dependencies (Klaassen yes, ConstantMobility no). Used by the
    #: solver to decide whether to register carrier cross-derivatives in
    #: the current-density expressions.
    requires_carriers: bool = False

    @abstractmethod
    def attach(self, ds, device: str, region: str, params, T_K: float) -> None:
        ...

    @abstractmethod
    def mu_n_expr(self) -> str:
        """DEVSIM expression for electron mobility on the edge."""

    @abstractmethod
    def mu_p_expr(self) -> str:
        """DEVSIM expression for hole mobility on the edge."""


class RecombinationModel(ABC):
    """Base class for net recombination contributors.

    Each model registers (1) a node model named after `term_name` with
    units of recombination rate * (-q) [A/cm^3] so it can be summed into
    the continuity node_model, and (2) its derivatives w.r.t. Electrons
    and Holes. The solver sums every model's term_name into the total
    recombination expression passed to the continuity equation.
    """

    @property
    @abstractmethod
    def term_name(self) -> str:
        """Unique node-model name this contributor will register."""

    @abstractmethod
    def attach(self, ds, device: str, region: str, params, T_K: float) -> None:
        ...


@dataclass
class PhysicsConfig:
    """Container of physics models used by DeviceSolver. New model classes
    (BGN, avalanche, ...) will be added as additional fields here."""
    mobility: MobilityModel = field(default=None)   # type: ignore[assignment]
    recombination: List[RecombinationModel] = field(default_factory=list)

    def __post_init__(self):
        if self.mobility is None:
            # Late import to avoid circular dep with models package.
            from .models.mobility import ConstantMobility
            self.mobility = ConstantMobility()
        if not self.recombination:
            from .models.recombination import SRH
            self.recombination = [SRH()]
