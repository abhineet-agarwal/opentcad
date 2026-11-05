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
from typing import Dict, List, Optional, Tuple, Union

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

    Material selectivity:
      * `rates`: optional {Material: relative_rate} map. When set, each
        material in the stack is etched at `rates[material] * depth_um`
        and materials absent from the map are etched at
        `default_rate * depth_um`. Default = 0.0 → "stop on anything
        not listed" semantics. Classic use: strip nitride, stop on
        oxide, with `rates={Material.SI3N4: 1.0, Material.SIO2: 0.02}`.
      * When `rates is None` every material etches at the same rate
        (backward-compat for Phase 1 scripts).
    """
    depth_um: float
    model: str = "isotropic"
    window_x_um: Optional[Tuple[float, float]] = None
    mask_material: Optional[Material] = None
    direction: Tuple[float, float] = (0.0, -1.0)
    sidewall_ratio: float = 0.0
    rates: Optional[Dict[Material, float]] = None
    default_rate: float = 0.0

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
        if self.rates is not None:
            for mat, rate in self.rates.items():
                if not isinstance(mat, Material):
                    raise ValueError(
                        f"Etch rates key must be a Material enum; "
                        f"got {mat!r} ({type(mat).__name__})")
                if rate < 0.0:
                    raise ValueError(
                        f"Etch rate for {mat.name} must be ≥ 0; "
                        f"got {rate}")
        if self.default_rate < 0.0:
            raise ValueError(
                f"default_rate must be ≥ 0; got {self.default_rate}")


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


ANNEAL_MODELS = ("intrinsic", "fair")
IMPLANT_PROFILES = ("pearson", "gaussian")


@dataclass(frozen=True)
class Anneal:
    """Thermal anneal — diffusion of every dopant field at the given
    temperature for the given time.

    Each implanted species (tracked ``C_<species>`` field) diffuses with
    its own coefficients; doping that is only in Nd / Na uses
    species_Nd / species_Na. See opentcad.process.doping.anneal.

    Args:
      temperature_C: anneal temperature in °C.
      time_s:        duration in seconds.
      species_Nd:    species whose coefficients drive the untracked Nd
                     remainder. Default "As".
      species_Na:    same for the untracked Na remainder. Default "B".
      model:         "intrinsic" (Gaussian convolution with D_i; exact
                     below n_i) or "fair" (concentration-coupled Fair
                     model; needed at S/D-level doping).
    """
    temperature_C: float
    time_s: float
    species_Nd: str = "As"
    species_Na: str = "B"
    model: str = "intrinsic"

    def __post_init__(self):
        if self.time_s < 0:
            raise ValueError(f"Anneal time must be ≥ 0 (got {self.time_s} s)")
        if self.temperature_C <= -273.15:
            raise ValueError(
                f"Anneal temperature must be above absolute zero "
                f"(got {self.temperature_C} °C)")
        if self.model not in ANNEAL_MODELS:
            raise ValueError(
                f"Anneal model must be one of {ANNEAL_MODELS}; got {self.model!r}")


@dataclass(frozen=True)
class Implant:
    """Ion-implant step. Doping, not topography — plays no role in
    level-set evolution, picked up by the doping dispatcher after the
    topography state has been meshed.

    Args:
        species: 'boron' / 'B' / 'phosphorus' / 'P' / 'arsenic' / 'As' /
            'BF2' (case-insensitive).
        energy_keV: ion energy in keV. The dopant energy (for BF₂,
            ≈ 0.225 × this) must fall inside the tabulated range.
        dose_cm2: dose per unit area in cm⁻². Typical S/D is 1e14-1e16.
        window_x_um: (x0, x1) mask opening in µm, or None for a
            blanket implant. Mask edge is softened by the lateral
            straggle in the kernel.
        tilt_deg: beam tilt from the wafer normal in the cross-section
            plane, |tilt| < 89°. Positive leans toward +x with depth.
        profile: "pearson" (all four tabulated moments, default) or
            "gaussian" (Rp and ΔRp only).
    """
    species: str
    energy_keV: float
    dose_cm2: float
    window_x_um: Optional[Tuple[float, float]] = None
    tilt_deg: float = 0.0
    profile: str = "pearson"

    def __post_init__(self):
        if self.energy_keV <= 0:
            raise ValueError(f"Implant energy must be > 0 keV; got {self.energy_keV}")
        if self.dose_cm2 <= 0:
            raise ValueError(f"Implant dose must be > 0 cm⁻²; got {self.dose_cm2}")
        if self.window_x_um is not None:
            x0, x1 = self.window_x_um
            if not (x1 > x0):
                raise ValueError(
                    f"Implant window must be (x0, x1) with x1 > x0; "
                    f"got {self.window_x_um!r}")
        if not abs(self.tilt_deg) < 89.0:
            raise ValueError(f"Implant |tilt_deg| must be < 89°; got {self.tilt_deg}")
        if self.profile not in IMPLANT_PROFILES:
            raise ValueError(
                f"Implant profile must be one of {IMPLANT_PROFILES}; "
                f"got {self.profile!r}")


Step = Union[Deposit, Etch, Oxidize, Implant, Anneal]


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
             sidewall_ratio: float = 0.0,
             rates: Optional[Dict[Material, float]] = None,
             default_rate: float = 0.0) -> "Recipe":
        self.steps.append(Etch(depth_um, model, window_x_um, mask_material,
                                direction, sidewall_ratio,
                                rates, default_rate))
        return self

    def oxidize(self, temperature_C: float, time_s: float,
                ambient: str = "dry",
                window_x_um: Optional[Tuple[float, float]] = None,
                bird_beak_length_um: float = 0.0) -> "Recipe":
        self.steps.append(Oxidize(temperature_C, time_s, ambient,
                                   window_x_um, bird_beak_length_um))
        return self

    def implant(self, species: str, energy_keV: float, dose_cm2: float,
                window_x_um: Optional[Tuple[float, float]] = None,
                tilt_deg: float = 0.0,
                profile: str = "pearson") -> "Recipe":
        self.steps.append(Implant(species=species,
                                   energy_keV=energy_keV,
                                   dose_cm2=dose_cm2,
                                   window_x_um=window_x_um,
                                   tilt_deg=tilt_deg,
                                   profile=profile))
        return self

    def anneal(self, temperature_C: float, time_s: float,
               species_Nd: str = "As",
               species_Na: str = "B",
               model: str = "intrinsic") -> "Recipe":
        self.steps.append(Anneal(temperature_C=temperature_C,
                                  time_s=time_s,
                                  species_Nd=species_Nd,
                                  species_Na=species_Na,
                                  model=model))
        return self

    def add(self, step) -> "Recipe":
        """Append any registered step — the way to use plugin steps
        (see ``opentcad.plugins.register_step``). Raises TypeError for a
        step class with no registered handler."""
        from opentcad.plugins import step_handler
        step_handler(step)
        self.steps.append(step)
        return self

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    def summary(self) -> str:
        from opentcad.plugins import step_handler
        lines = [f"Recipe {self.name!r}: {len(self.steps)} step(s)"]
        for i, step in enumerate(self.steps, 1):
            try:
                describe = step_handler(step).describe
            except TypeError:          # unregistered: still printable
                describe = None
            lines.append(f"  {i}. {describe(step) if describe else repr(step)}")
        return "\n".join(lines)
