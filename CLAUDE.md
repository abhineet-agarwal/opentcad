# OpenTCAD — Claude Code Context

## What This Project Is
OpenTCAD is a modular open-source TCAD framework: the open-source equivalent of Synopsys
Sentaurus. It connects process simulation → device simulation in a unified Python pipeline.

## Architecture
Process DSL → Gmsh meshing → ViennaPS topography → FiPy doping → bridge → DEVSIM device sim → VTK output

## Module Map
- opentcad/geometry/   — Gmsh DSL, MeshField data format (Layer 0)
- opentcad/process/    — ViennaPS etch/dep (Layer 1), implant+diffusion (Layer 2)
- opentcad/device/     — DEVSIM wrapper, physics models (Layer 3)
- opentcad/materials/  — YAML parameter database, calibration (Layer 4)
- opentcad/bridge/     — THE KEY PIECE: process→device mesh handoff
- opentcad/io/         — VTK, GDS file I/O
- opentcad/viz/        — Plotting helpers

## Central Data Object: MeshField
Defined in opentcad/geometry/formats.py. Wraps pyvista UnstructuredGrid.
Carries: material_id (cell), Nd/Na doping (point), ContactTag list, ProcessStep history.
EVERY module boundary passes MeshField. No raw numpy arrays between layers.

## Units (enforced, never implicit)
- Spatial: micrometers [um]
- Concentrations: cm^-3
- Temperature: Kelvin [K]
- Energy: eV

## Current Phase
Phase 0: geometry DSL + DEVSIM bridge. Goal: p-n junction IV curve.
See PHASES.md for full roadmap.

## Tests
pytest tests/ -v                     # all tests
pytest tests/geometry/ -v            # geometry only (no devsim/viennaps needed)
pytest -m "not slow" -v              # skip slow tests
