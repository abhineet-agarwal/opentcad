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
from typing import List, Optional, Tuple, Union

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

    Models:
      - "isotropic": recedes along the local surface normal (wet etch,
        downstream plasma). With `window_x_um=None` this is a uniform
        Minkowski erosion; with a window it becomes a curved-under-mask
        profile solved by the ViennaLS Lax-Friedrichs advection scheme.
      - "directional": RIE-style. Rate scales with how strongly the
        local surface normal faces the incoming ion beam, so horizontal
        tops recede at full rate and sidewalls barely move — giving
        near-vertical trench walls. `direction` is the beam propagation
        direction (etch travels along it); default is straight down.
      - `sidewall_ratio`: fraction of the full etch rate that a purely-
        lateral surface still receives (models chemical isotropy on top
        of the directional ion flux). 0.0 = pure directional.

    Mask forms:
      * `window_x_um=(x0, x1)`: photolithography-style opening.
      * `mask_material`: reserved for a hardmask level-set (multi-layer
        initial stack). Not yet honored.
    """
    depth_um: float
    model: str = "isotropic"
    window_x_um: Optional[Tuple[float, float]] = None
    mask_material: Optional[Material] = None
    direction: Tuple[float, float] = (0.0, -1.0)
    sidewall_ratio: float = 0.0

    def __post_init__(self):
        if self.depth_um <= 0:
            raise ValueError(
                f"Etch depth must be positive (got {self.depth_um} um)")
        if self.model not in ("isotropic", "directional"):
            raise ValueError(
                f"Etch model {self.model!r} not supported "
                f"(supported: 'isotropic', 'directional').")
        if self.window_x_um is not None:
            x0, x1 = self.window_x_um
            if not (x1 > x0):
                raise ValueError(
                    f"Etch window must be (x0, x1) with x1 > x0; got "
                    f"{self.window_x_um!r}")
        if self.model == "directional":
            dx, dy = self.direction
            if dx * dx + dy * dy < 1e-12:
                raise ValueError(
                    f"Directional etch direction must be a non-zero "
                    f"vector; got {self.direction!r}")
            if not (0.0 <= self.sidewall_ratio <= 1.0):
                raise ValueError(
                    f"sidewall_ratio must be in [0, 1]; got "
                    f"{self.sidewall_ratio}")


@dataclass(frozen=True)
class Oxidize:
    """Deal-Grove thermal oxidation of the exposed Si-SiO2 stack.

    Grows SiO2 on top of every exposed Si column following the linear-
    parabolic law x_ox^2 + A x_ox = B (t + tau). The Si-SiO2 boundary
    moves down by 0.44*dx_grown; the SiO2 top moves up by 0.56*dx_grown.

    Args:
      temperature_C: oxidation temperature in °C.
      time_s:        oxidation duration in seconds.
      ambient:       'dry' (O2) or 'wet' (H2O). Sets Deal-Grove
                     coefficients per Plummer/Deal fits for <100> Si.
      window_x_um:   optional (x0, x1). Only columns inside the window
                     oxidize at full rate. Modelling a nitride hardmask
                     over the rest of the wafer for LOCOS.
      bird_beak_length_um: characteristic feathering length outside the
                     window (heuristic stand-in for lateral O2 diffusion
                     under the nitride edge). 0.0 = perfectly sharp
                     mask; typical LOCOS value ≈ pad-oxide thickness
                     (30-100 nm).
    """
    temperature_C: float
    time_s: float
    ambient: str = "dry"
    window_x_um: Optional[Tuple[float, float]] = None
    bird_beak_length_um: float = 0.0

    def __post_init__(self):
        if self.time_s <= 0:
            raise ValueError("Oxidation time must be positive")
        if self.ambient not in ("dry", "wet"):
            raise ValueError(f"Ambient must be 'dry' or 'wet', got {self.ambient!r}")
        if self.window_x_um is not None:
            x0, x1 = self.window_x_um
            if not (x1 > x0):
                raise ValueError(
                    f"Oxidation window must be (x0, x1) with x1 > x0; "
                    f"got {self.window_x_um!r}")
        if self.bird_beak_length_um < 0:
            raise ValueError(
                f"bird_beak_length_um must be ≥ 0; got "
                f"{self.bird_beak_length_um}")


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
             window_x_um: Optional[Tuple[float, float]] = None,
             mask_material: Optional[Material] = None,
             direction: Tuple[float, float] = (0.0, -1.0),
             sidewall_ratio: float = 0.0) -> "Recipe":
        self.steps.append(Etch(depth_um, model, window_x_um, mask_material,
                                direction, sidewall_ratio))
        return self

    def oxidize(self, temperature_C: float, time_s: float,
                ambient: str = "dry",
                window_x_um: Optional[Tuple[float, float]] = None,
                bird_beak_length_um: float = 0.0) -> "Recipe":
        self.steps.append(Oxidize(temperature_C, time_s, ambient,
                                   window_x_um, bird_beak_length_um))
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
                bits = []
                if step.window_x_um is not None:
                    x0, x1 = step.window_x_um
                    bits.append(f" window=[{x0:.3f}..{x1:.3f}] um")
                if step.mask_material is not None:
                    bits.append(f" mask={step.mask_material.name}")
                lines.append(
                    f"  {i}. etch {step.depth_um*1000:.1f} nm "
                    f"({step.model}){''.join(bits)}")
            elif isinstance(step, Oxidize):
                bits = []
                if step.window_x_um is not None:
                    x0, x1 = step.window_x_um
                    bits.append(f" window=[{x0:.3f}..{x1:.3f}] um")
                if step.bird_beak_length_um > 0:
                    bits.append(
                        f" bird_beak={step.bird_beak_length_um*1000:.0f} nm")
                lines.append(
                    f"  {i}. oxidize @ {step.temperature_C:.0f}°C for "
                    f"{step.time_s:.0f} s ({step.ambient}){''.join(bits)}")
            else:
                lines.append(f"  {i}. {step}")
        return "\n".join(lines)
