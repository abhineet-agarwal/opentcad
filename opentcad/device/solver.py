"""
opentcad/device/solver.py — DEVSIM device simulation wrapper.

Wraps DEVSIM to run drift-diffusion simulations on a MeshField.
This is the Phase 0 implementation target.

Phase 0 covers:
  - Convert MeshField to DEVSIM mesh format
  - Assign doping (Nd, Na) as DEVSIM node model variables
  - Set up constant-mobility Si equations (Poisson + DD)
  - Ramp bias and solve IV curves
  - Return results as numpy arrays

Claude Code: implement _setup_equations() first, then _convert_meshfield().
Reference: DEVSIM documentation at https://devsim.net
Key DEVSIM concepts: device, region, contact, interface, node_model, edge_model, equation.
"""
from __future__ import annotations
import numpy as np
from ..geometry.formats import MeshField
from ..materials.database import MaterialParams


class DeviceSolver:
    """DEVSIM drift-diffusion solver wrapping a MeshField.

    Args:
        meshfield: Input device geometry with doping profiles and contacts.
        material_params: Dict mapping material name to MaterialParams.
            Keys should match MATERIAL_NAMES values (e.g. "Silicon").

    Example:
        from opentcad.device.solver import DeviceSolver
        from opentcad.materials.database import load_material
        solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
        V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.7, 0.05)
    """

    def __init__(self, meshfield: MeshField,
                 material_params: dict[str, MaterialParams]):
        self.mf = meshfield
        self.mat_params = material_params
        self._device_name = meshfield.metadata.get("structure_name", "device")
        self._initialized = False

    def initialize(self) -> None:
        """Convert MeshField to DEVSIM internal representation.
        
        This must be called before solve() or iv_sweep().
        Called automatically by iv_sweep() if not already done.
        
        Steps:
          1. Create DEVSIM device from mesh nodes + elements
          2. Create regions with material assignments
          3. Create contacts from ContactTag list
          4. Add node models: potential, electron_concentration, hole_concentration
          5. Add Nd, Na as fixed node models from MeshField doping arrays
          6. Set up Poisson equation + electron/hole continuity equations
          7. Set up contact boundary conditions (ohmic: equilibrium carrier conc.)
        """
        try:
            import devsim as ds
        except ImportError:
            raise ImportError(
                "DEVSIM is not installed. Install with: pip install devsim\n"
                "Or visit https://devsim.org"
            )

        self._ds = ds
        self._convert_meshfield()
        self._setup_equations()
        self._initialized = True

    def _convert_meshfield(self) -> None:
        """Build DEVSIM mesh, regions, contacts from MeshField.
        
        Claude Code implementation note:
        - Use ds.create_gmsh_mesh() if mesh came from Gmsh (preferred)
        - Or use ds.create_1d_mesh() / ds.create_2d_mesh() for simple cases
        - Node coordinates in cm (DEVSIM uses CGS). MeshField is in um → multiply by 1e-4.
        - Doping in cm^-3 (same units, no conversion needed).
        - See DEVSIM examples at https://github.com/devsim/devsim/tree/main/testing
        """
        raise NotImplementedError(
            "DeviceSolver._convert_meshfield() not yet implemented.\n"
            "This is Milestone 0.4. See PHASES.md for implementation guide.\n"
            "Start by reading tests/device/test_solver.py for the expected API."
        )

    def _setup_equations(self) -> None:
        """Set up semiconductor equations in DEVSIM.
        
        For Phase 0 (constant mobility, basic SRH):
          1. Poisson: div(eps * grad(psi)) = -q*(p - n + Nd - Na)
          2. Electron continuity: dn/dt - div(Jn)/q = G - R
          3. Hole continuity:     dp/dt + div(Jp)/q = G - R
        
        Mobility: constant mu_n, mu_p from MaterialParams.
        Recombination: SRH only (no Auger in Phase 0).
        
        Claude Code: use DEVSIM's node_model and edge_model commands.
        Reference implementation: devsim/testing/diode_2d.py in DEVSIM repo.
        """
        raise NotImplementedError(
            "DeviceSolver._setup_equations() not yet implemented. Milestone 0.5."
        )

    def solve_equilibrium(self) -> None:
        """Solve at zero bias (equilibrium). Must be called before iv_sweep()."""
        if not self._initialized:
            self.initialize()
        # Use Gummel decoupling for initial guess: solve Poisson alone first
        # ds.solve(type="dc", absolute_error=1e10, relative_error=1e-10, maximum_iterations=30)
        raise NotImplementedError("Milestone 0.4")

    def iv_sweep(self, anode_contact: str, cathode_contact: str,
                 v_start: float, v_end: float, v_step: float
                 ) -> tuple[list[float], list[float]]:
        """Run a DC voltage sweep and return (voltages, currents).

        Args:
            anode_contact: Contact name to ramp voltage on.
            cathode_contact: Contact name held at 0V (reference).
            v_start, v_end: Voltage range [V].
            v_step: Voltage increment [V]. Must be positive.

        Returns:
            (voltages, currents): Lists of floats. Currents in A/um (2D) or A (3D).
        """
        if not self._initialized:
            self.initialize()
        self.solve_equilibrium()

        voltages = np.arange(v_start, v_end + v_step/2, v_step).tolist()
        currents = []

        for v in voltages:
            self._set_contact_voltage(anode_contact, v)
            self._solve_dc()
            I = self._get_contact_current(anode_contact)
            currents.append(I)

        return voltages, currents

    def _set_contact_voltage(self, contact: str, voltage: float) -> None:
        raise NotImplementedError("Milestone 0.4")

    def _solve_dc(self) -> None:
        raise NotImplementedError("Milestone 0.4")

    def _get_contact_current(self, contact: str) -> float:
        raise NotImplementedError("Milestone 0.4")
