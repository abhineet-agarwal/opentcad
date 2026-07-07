"""
opentcad/process/topography/recipe.py — Chainable process-recipe DSL.

A Recipe is an ordered list of process steps (deposit, etch, oxidize, ...)
that a TopographySimulator plays back against an initial substrate
described by an opentcad Structure. The recipe itself is pure data — no
ViennaLS/ViennaPS coupling here — so recipes can be pickled, printed,
diffed, and unit-tested without a topography backend installed.

Units follow the project convention: um for distances, seconds for
durations, degrees Celsius for temperatures unless noted otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

from opentcad.geometry.formats import Material


@dataclass(frozen=True)
class Deposit:
    """Grow *thickness_um* of *material* on top of the current surface.

    The `model` selects the deposition physics:
      - "conformal": Minkowski-dilation of the surface by *thickness*.
        Textbook isotropic CVD / ALD.

    The DSL keeps the door open for "directional" (PVD-style, follows a
    supplied direction vector) and "selective" (only on a subset of the
    exposed materials) — those will be added when we wire the ViennaPS
    process models.
    """
    material: Material
    thickness_um: float
    model: str = "conformal"

    def __post_init__(self):
        if self.thickness_um <= 0:
            raise ValueError(
                f"Deposit thickness must be positive (got {self.thickness_um} um)")
        if self.model not in ("conformal",):
            raise ValueError(
                f"Deposit model {self.model!r} not supported yet "
                f"(supported: 'conformal').")


@dataclass(frozen=True)
class Etch:
    """Remove *depth_um* of the top material.

    - "isotropic": Minkowski-erosion — recedes uniformly along the local
      normal (wet etch, downstream plasma).
    - "directional": planned; recedes along a supplied direction only.

    `mask_material` — if provided, cells whose top material equals the
    mask are protected. Not yet honored by the backend (single-material
    stack for MVP).
    """
    depth_um: float
    model: str = "isotropic"
    mask_material: Optional[Material] = None

    def __post_init__(self):
        if self.depth_um <= 0:
            raise ValueError(
                f"Etch depth must be positive (got {self.depth_um} um)")
        if self.model not in ("isotropic",):
            raise ValueError(
                f"Etch model {self.model!r} not supported yet "
                f"(supported: 'isotropic').")


@dataclass(frozen=True)
class Oxidize:
    """Deal-Grove thermal oxidation stub. Placeholder for Milestone 1.4."""
    temperature_C: float
    time_s: float
    ambient: str = "dry"

    def __post_init__(self):
        if self.time_s <= 0:
            raise ValueError("Oxidation time must be positive")
        if self.ambient not in ("dry", "wet"):
            raise ValueError(f"Ambient must be 'dry' or 'wet', got {self.ambient!r}")


Step = Union[Deposit, Etch, Oxidize]


@dataclass
class Recipe:
    """Ordered process flow. Chainable; each method returns self.

    Example:
        recipe = (Recipe("locos_lite")
                  .deposit(Material.SIO2, 0.05)
                  .etch(0.02))
    """
    name: str = "recipe"
    steps: List[Step] = field(default_factory=list)

    def deposit(self, material: Material, thickness_um: float,
                model: str = "conformal") -> "Recipe":
        self.steps.append(Deposit(material, thickness_um, model))
        return self

    def etch(self, depth_um: float, model: str = "isotropic",
             mask_material: Optional[Material] = None) -> "Recipe":
        self.steps.append(Etch(depth_um, model, mask_material))
        return self

    def oxidize(self, temperature_C: float, time_s: float,
                ambient: str = "dry") -> "Recipe":
        self.steps.append(Oxidize(temperature_C, time_s, ambient))
        return self

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    def summary(self) -> str:
        lines = [f"Recipe {self.name!r}: {len(self.steps)} step(s)"]
        for i, step in enumerate(self.steps, 1):
            if isinstance(step, Deposit):
                lines.append(
                    f"  {i}. deposit {step.thickness_um*1000:.1f} nm of "
                    f"{step.material.name} ({step.model})")
            elif isinstance(step, Etch):
                mask = f" mask={step.mask_material.name}" if step.mask_material else ""
                lines.append(
                    f"  {i}. etch {step.depth_um*1000:.1f} nm "
                    f"({step.model}){mask}")
            elif isinstance(step, Oxidize):
                lines.append(
                    f"  {i}. oxidize @ {step.temperature_C:.0f}°C for "
                    f"{step.time_s:.0f} s ({step.ambient})")
            else:
                lines.append(f"  {i}. {step}")
        return "\n".join(lines)
