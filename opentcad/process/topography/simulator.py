"""
opentcad/process/topography/simulator.py — Level-set topography engine.

Plays a Recipe against an initial substrate and produces a stack of
material level-sets. Uses ViennaLS (viennals) as the low-level level-set
library.

Why viennals directly and not viennaps?
  On macOS the current viennaps 4.6 wheel statically links VTK and
  registers duplicate Objective-C classes (vtkCocoa*) that collide with
  viennals's copy, causing SIGSEGV in `MakePlane.apply()` and
  `getMaterialsInDomain()`. viennals alone is stable and gives us
  everything Milestone 1.1a needs:

    * Domain construction with bounds + boundary conditions
    * Plane / Sphere / Box primitives via MakeGeometry
    * GeometricAdvect with SphereDistribution for Minkowski
      dilation/erosion (isotropic deposit/etch)
    * BooleanOperation for stack maintenance
    * ToSurfaceMesh to extract polylines for the mesh bridge

    We wrap process-model semantics ourselves (deposit vs. etch, mask
    handling); ViennaPS's PlasmaEtchingParameters and friends will slot
    in when the macOS wheel is fixed.

State representation:
  A `TopographyState` holds an ordered list of level-sets, bottom-first.
  Convention: each level-set's implicit surface is the *top* of that
  material. The material fills the region between its top and the top of
  the material below (or the domain floor for the bottom material). This
  matches how viennals's ToVoxelMesh / disk-mesh multi-LS conventions
  work and how ViennaPS labels materials in a stacked domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import viennals

from opentcad.geometry.formats import Material

from .recipe import Deposit, Etch, Oxidize, Recipe


@dataclass
class Layer:
    """One material layer in the topography stack.

    Attributes:
        material: opentcad Material enum for the layer.
        level_set: viennals 2D Domain whose implicit surface marks the
            *top* of this material.
    """
    material: Material
    level_set: "viennals.d2.Domain"


@dataclass
class TopographyState:
    """Full topography stack — bottom material first.

    Attributes:
        bounds_um: (xmin, xmax, ymin, ymax) simulation window in um.
        grid_delta_um: level-set grid spacing in um.
        layers: material layers, bottom-to-top.
    """
    bounds_um: tuple  # (xmin, xmax, ymin, ymax)
    grid_delta_um: float
    layers: List[Layer] = field(default_factory=list)

    @property
    def top(self) -> Layer:
        if not self.layers:
            raise RuntimeError("TopographyState has no layers yet.")
        return self.layers[-1]


def _boundary_conditions() -> Sequence:
    """Reflective x, infinite y — the standard 2D wafer-column convention."""
    bc = viennals._core.BoundaryConditionEnum
    return [bc.REFLECTIVE_BOUNDARY, bc.INFINITE_BOUNDARY]


def _empty_domain(bounds_um: tuple, grid_delta_um: float) -> "viennals.d2.Domain":
    xmin, xmax, ymin, ymax = bounds_um
    return viennals.d2.Domain(
        [float(xmin), float(xmax), float(ymin), float(ymax)],
        _boundary_conditions(),
        float(grid_delta_um),
    )


def _plane_at(bounds_um: tuple, grid_delta_um: float, y_um: float,
              normal_up: bool = True) -> "viennals.d2.Domain":
    """Build a level-set whose surface is the horizontal plane y = y_um.

    normal_up=True → material occupies y < y_um (surface faces up).
    """
    ls = _empty_domain(bounds_um, grid_delta_um)
    origin = [0.0, float(y_um)]
    normal = [0.0, 1.0 if normal_up else -1.0]
    plane = viennals.d2.Plane(origin, normal)
    viennals.d2.MakeGeometry(ls, plane).apply()
    return ls


def _dilate(level_set: "viennals.d2.Domain", radius_um: float) -> None:
    """Minkowski-dilate the surface by radius_um (positive grows out,
    negative erodes inward). In-place.

    Uses viennals GeometricAdvect + SphereDistribution — the standard
    "isotropic advance for time T with unit velocity" primitive. In 2D
    the SphereDistribution is really a disk of the given radius.
    """
    dist = viennals.d2.SphereDistribution(float(radius_um))
    advector = viennals.d2.GeometricAdvect()
    advector.setLevelSet(level_set)
    advector.setAdvectionDistribution(dist)
    advector.apply()


def initial_state_from_structure(structure, grid_delta_um: float = 0.01
                                 ) -> TopographyState:
    """Build the starting TopographyState from an opentcad Structure.

    Currently supports single-substrate structures (add_substrate + no
    add_layer calls). Multi-layer initial stacks are trivial to add — I
    just haven't needed one yet for Milestone 1.1a.
    """
    if len(structure._layers) < 1:
        raise ValueError(
            "Structure has no layers to serve as initial substrate.")

    xmin, xmax = 0.0, float(structure.width_um)

    y_bottom = 0.0
    y_top_total = sum(l.thickness_um for l in structure._layers)
    # Domain top gets some headroom so subsequent deposits don't run into
    # the boundary. The bottom stays at the substrate floor — the mesh
    # bridge uses ymin as the physical wafer floor, and going below it
    # would silently thicken the substrate.
    ymin = y_bottom
    ymax = y_top_total + max(0.5, 0.5 * y_top_total)

    state = TopographyState(bounds_um=(xmin, xmax, ymin, ymax),
                            grid_delta_um=float(grid_delta_um))

    y = y_bottom
    for layer in structure._layers:
        y += layer.thickness_um
        ls = _plane_at(state.bounds_um, state.grid_delta_um, y_um=y)
        state.layers.append(Layer(material=layer.material, level_set=ls))
    return state


def _apply_deposit(state: TopographyState, step: Deposit) -> None:
    """Add a new layer on top: duplicate the current top surface, dilate
    it by thickness. The old top marks the bottom of the new material;
    the dilated LS marks its new top."""
    if not state.layers:
        raise RuntimeError("Cannot deposit onto an empty stack.")

    top_ls = state.top.level_set
    # Deep-copy the top surface to become the new material's top LS.
    new_ls = viennals.d2.Domain(top_ls)
    _dilate(new_ls, +step.thickness_um)
    state.layers.append(Layer(material=step.material, level_set=new_ls))


def _apply_etch(state: TopographyState, step: Etch) -> None:
    """Erode the top layer by depth. If depth exceeds the top material's
    thickness the top LS drops below the layer beneath it — the mesh
    bridge deals with intersection when it happens.
    """
    if not state.layers:
        raise RuntimeError("Cannot etch an empty stack.")
    _dilate(state.top.level_set, -step.depth_um)


def simulate(structure, recipe: Recipe, grid_delta_um: float = 0.01
             ) -> TopographyState:
    """Run *recipe* on *structure*, returning the final TopographyState.

    Args:
        structure: opentcad Structure — provides the substrate + width.
        recipe: opentcad Recipe — ordered process steps.
        grid_delta_um: level-set grid spacing.
    """
    state = initial_state_from_structure(structure, grid_delta_um)
    for step in recipe:
        if isinstance(step, Deposit):
            _apply_deposit(state, step)
        elif isinstance(step, Etch):
            _apply_etch(state, step)
        elif isinstance(step, Oxidize):
            raise NotImplementedError(
                "Oxidize step not implemented yet — Milestone 1.4.")
        else:
            raise TypeError(f"Unknown recipe step type: {type(step).__name__}")
    return state


def extract_surface_polyline(level_set: "viennals.d2.Domain"
                             ) -> "tuple[list, list]":
    """Extract the (nodes, lines) representation of a 2D level-set's
    surface. Returns the raw viennals Mesh contents:
      nodes: list of [x, y, z] (z always 0 in 2D)
      lines: list of [i, j] node indices forming the polyline segments.
    """
    mesh = viennals.Mesh()
    to_mesh = viennals.d2.ToSurfaceMesh()
    to_mesh.setLevelSet(level_set)
    to_mesh.setMesh(mesh)
    to_mesh.apply()
    return mesh.getNodes(), mesh.getLines()
