# process — Claude Code Context

## Purpose
Layers 1-2. Topography simulation (ViennaPS) and doping simulation (FiPy + Iradina).

## Subdirectories
- topography/  — ViennaPS wrappers for etch, deposition, oxidation (Phase 1)
- doping/      — Implant (Pearson IV + Iradina) and diffusion (FiPy) (Phase 2)
- data/        — Pearson IV parameter tables (YAML), diffusivity tables

## Key Interfaces
Input:  MeshField from geometry layer
Output: MeshField with evolved topography and/or doping profiles
Bridge: process MeshField → bridge/process_to_device.py → device MeshField

## ViennaPS Conventions
- ViennaPS Python API: import viennaps as vps
- ViennaPS uses um natively — no coordinate conversion needed
- Level-set domain: vps.Domain object wraps the geometry
- Process steps: vps.IsotropicProcess, vps.DirectionalEtching, vps.OxidationModel

## Diffusion Conventions
- FiPy mesh from MeshField: fipy.GmshImporter2D or manual CellVariable construction
- All concentrations in cm^-3 (same as MeshField)
- Time in seconds; temperature in Kelvin
- Diffusivity in cm^2/s

## Tests
pytest tests/process/ -v
Slow tests (ViennaPS): pytest tests/process/ -v -m requires_viennaps
