"""
opentcad/device/solver.py — DEVSIM device simulation wrapper.

Phase 0: 2D drift-diffusion with constant mobility and SRH recombination.
Takes a MeshField (triangular mesh, cell material_id, point Nd/Na, ContactTag
list) and exposes iv_sweep() for ohmic-contact IV curves.

Units: MeshField is um. DEVSIM coordinates are converted to cm on entry.
Doping stays in cm^-3 throughout.

Equations follow the edge-based Scharfetter-Gummel formulation from DEVSIM's
diode_2d reference example (devsim_data/testing/dio2_element_2d.py); the
element-based flux detour is not needed for Phase 0.
"""
from __future__ import annotations
import warnings
import numpy as np
from scipy.spatial import cKDTree
from ..geometry.formats import MATERIAL_NAMES, Material, MeshField
from ..materials.database import MaterialParams

Q_C = 1.602176634e-19   # elementary charge [C]
KB_J = 1.380649e-23     # Boltzmann [J/K]
EPS0_F_CM = 8.8541878128e-14   # vacuum permittivity [F/cm]
T_K_DEFAULT = 300.0


class DeviceSolver:
    """DEVSIM drift-diffusion solver wrapping a MeshField.

    Args:
        meshfield: 2D triangle MeshField with material_id cell data, Nd/Na
                   point data, and ContactTag boundary nodes.
        material_params: Mapping from material display name (e.g. "Silicon")
                         or enum short name (e.g. "SI") to MaterialParams.
        temperature_K: Lattice temperature [K].

    Example:
        solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
        V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.7, 0.05)
    """

    _instance_counter = 0

    def __init__(self, meshfield: MeshField,
                 material_params: dict[str, MaterialParams],
                 temperature_K: float = T_K_DEFAULT):
        self.mf = meshfield
        self.mat_params = material_params
        self.T = float(temperature_K)
        base = meshfield.metadata.get("structure_name", "device")
        # DEVSIM keeps global mesh/device state — disambiguate per instance.
        DeviceSolver._instance_counter += 1
        suffix = DeviceSolver._instance_counter
        self._device_name = f"{base}_{suffix}"
        self._mesh_name = f"{base}_{suffix}_mesh"
        self._initialized = False
        self._contact_regions: dict[str, str] = {}     # contact name -> region name
        self._region_materials: dict[str, Material] = {}   # region name -> Material
        self._region_is_insulator: dict[str, bool] = {}    # region name -> insulator?
        self._interfaces: list[tuple[str, str, str]] = []  # (if_name, r0, r1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Build the DEVSIM device + equations. Idempotent per instance."""
        if self._initialized:
            return
        try:
            import devsim as ds
        except ImportError as e:
            raise ImportError(
                "DEVSIM is not installed. Install with: pip install devsim"
            ) from e
        self._ds = ds
        self._convert_meshfield()
        self._setup_equations()
        self._initialized = True

    def solve_equilibrium(self) -> None:
        """Warm-start with Poisson-only then switch to coupled DD solve."""
        if not self._initialized:
            self.initialize()
        ds = self._ds
        # Initialise Electrons/Holes from the intrinsic guess (populated by
        # the Poisson-only solve below) before switching to the coupled system.
        # First: solve Poisson only. The IntrinsicCharge node_model is the
        # residual; PotentialEquation in "potential-only" mode uses it.
        # Insulator regions already have a Poisson-only equation set in
        # _build_insulator_potential — leave them alone.
        for region in self._region_materials:
            if self._region_is_insulator.get(region, False):
                continue
            ds.equation(device=self._device_name, region=region,
                        name="PotentialEquation", variable_name="Potential",
                        node_model="PotentialIntrinsicNodeCharge",
                        edge_model="PotentialEdgeFlux",
                        variable_update="log_damp")
        ds.solve(type="dc", absolute_error=1.0, relative_error=1e-12,
                 maximum_iterations=30)

        # Seed carrier densities from the equilibrium potential, then rebuild
        # PotentialEquation with the full DD node charge and couple in the
        # continuity equations. Insulator regions stay Poisson-only.
        for region in self._region_materials:
            if self._region_is_insulator.get(region, False):
                continue
            ds.set_node_values(device=self._device_name, region=region,
                               name="Electrons", init_from="IntrinsicElectrons")
            ds.set_node_values(device=self._device_name, region=region,
                               name="Holes", init_from="IntrinsicHoles")
            ds.equation(device=self._device_name, region=region,
                        name="PotentialEquation", variable_name="Potential",
                        node_model="PotentialNodeCharge",
                        edge_model="PotentialEdgeFlux",
                        variable_update="log_damp")
            self._build_continuity_equations(region)
        for contact in self._contact_regions:
            r = self._contact_regions[contact]
            if self._region_is_insulator.get(r, False):
                continue
            self._build_contact_dd_equations(contact)

        # Unstructured triangle meshes can't reach 1e-10 relative; UMFPACK
        # precision saturates around 1e-9. 1e-7 gives 7-digit residual which
        # is far below any current magnitude of physical interest.
        ds.solve(type="dc", absolute_error=1e10, relative_error=1e-7,
                 maximum_iterations=50)

    def iv_sweep(self, anode_contact: str, cathode_contact: str,
                 v_start: float, v_end: float, v_step: float
                 ) -> tuple[list[float], list[float]]:
        """Ramp `anode_contact` from v_start to v_end, holding cathode at 0V.

        Returns (voltages, currents). Current is total (electron+hole) at
        the anode in Amps (2D DEVSIM integrates per-unit-depth, so the
        numeric value is A/cm of out-of-plane length).
        """
        if not self._initialized:
            self.initialize()
        self.solve_equilibrium()
        self._set_contact_voltage(cathode_contact, 0.0)

        voltages = np.arange(v_start, v_end + v_step / 2, v_step)
        currents: list[float] = []
        for v in voltages:
            self._set_contact_voltage(anode_contact, float(v))
            self._solve_dc()
            currents.append(self._get_contact_current(anode_contact))
        return voltages.tolist(), currents

    # ------------------------------------------------------------------
    # Mesh conversion
    # ------------------------------------------------------------------
    def _convert_meshfield(self) -> None:
        ds = self._ds
        mf = self.mf

        import pyvista as pv
        if not np.all(np.asarray(mf.grid.celltypes) == pv.CellType.TRIANGLE):
            raise NotImplementedError(
                "DeviceSolver currently supports only 2D triangle meshes. "
                f"Found cell types: {set(mf.grid.celltypes.tolist())}"
            )

        pts_cm = np.asarray(mf.points, dtype=float) * 1e-4
        coords_flat = pts_cm.flatten().tolist()

        cells = mf.grid.cells.reshape(-1, 4)[:, 1:].astype(int)   # (n_cells, 3)
        mat_ids = np.asarray(mf.material_ids, dtype=np.int32)
        unique_mats = sorted({int(m) for m in mat_ids})

        region_names = {m: Material(m).name for m in unique_mats}
        contact_names = [c.name for c in mf.contacts]

        # Identify edges shared by two cells of *different* materials —
        # these are interior interfaces (Si/SiO2, SiO2/PolySi, ...).
        # Boundary edges (count == 1) are candidates for contacts.
        edge_count: dict[tuple[int, int], int] = {}
        edge_region: dict[tuple[int, int], int] = {}
        edge_other_region: dict[tuple[int, int], int] = {}
        for tri, mid in zip(cells, mat_ids):
            t0, t1, t2 = int(tri[0]), int(tri[1]), int(tri[2])
            mid_i = int(mid)
            for a, b in ((t0, t1), (t1, t2), (t2, t0)):
                e = (a, b) if a < b else (b, a)
                edge_count[e] = edge_count.get(e, 0) + 1
                if e not in edge_region:
                    edge_region[e] = mid_i
                elif edge_region[e] != mid_i:
                    edge_other_region[e] = mid_i
        boundary_edges = {e for e, c in edge_count.items() if c == 1}
        interface_edges_by_pair: dict[tuple[int, int], list] = {}
        for e in edge_other_region:
            a_mat, b_mat = sorted((edge_region[e], edge_other_region[e]))
            interface_edges_by_pair.setdefault((a_mat, b_mat), []).append(e)

        interface_phys_names = {
            pair: f"if_{Material(pair[0]).name}_{Material(pair[1]).name}"
            for pair in interface_edges_by_pair
        }

        # In-memory create_gmsh_mesh expects alphabetically-sorted physical
        # names (pythonmesh.read_gmsh_file sorts by name before indexing).
        physical_names = sorted(list(region_names.values()) + contact_names
                                + list(interface_phys_names.values()))
        name_to_idx = {n: i for i, n in enumerate(physical_names)}

        elements: list[int] = []
        for tri, mid in zip(cells, mat_ids):
            pn = name_to_idx[Material(int(mid)).name]
            elements.extend([2, pn, int(tri[0]), int(tri[1]), int(tri[2])])

        # Emit interface line elements. Each interface edge appears in two
        # triangles (different materials); emit it once under its interface
        # physical name. The "owning" region for the line element is one of
        # the two — pythonmesh sorts physical names so either is fine; pick
        # the alphabetically-lower material name to be deterministic.
        for pair, edges in interface_edges_by_pair.items():
            pn = name_to_idx[interface_phys_names[pair]]
            for e in edges:
                elements.extend([1, pn, e[0], e[1]])

        contact_region: dict[str, str] = {}
        for contact in mf.contacts:
            node_set = {int(n) for n in contact.boundary_nodes}
            pn = name_to_idx[contact.name]
            matched = 0
            for e in boundary_edges:
                if e[0] in node_set and e[1] in node_set:
                    elements.extend([1, pn, e[0], e[1]])
                    contact_region.setdefault(
                        contact.name, Material(edge_region[e]).name)
                    matched += 1
            if matched == 0:
                warnings.warn(
                    f"Contact '{contact.name}': no mesh boundary edges span "
                    f"its {len(node_set)} node(s); contact will be skipped.")

        ds.create_gmsh_mesh(mesh=self._mesh_name,
                            coordinates=coords_flat,
                            physical_names=physical_names,
                            elements=elements)
        for m in unique_mats:
            rname = Material(m).name
            display = MATERIAL_NAMES.get(Material(m), rname)
            ds.add_gmsh_region(mesh=self._mesh_name, gmsh_name=rname,
                               region=rname, material=display)
            self._region_materials[rname] = Material(m)
            try:
                p = self._params_for_region(Material(m))
                self._region_is_insulator[rname] = p.is_insulator
            except KeyError:
                self._region_is_insulator[rname] = False
        for cname, rname in contact_region.items():
            ds.add_gmsh_contact(mesh=self._mesh_name, gmsh_name=cname,
                                region=rname, name=cname, material="metal")
            self._contact_regions[cname] = rname
        for pair, _ in interface_edges_by_pair.items():
            if_name = interface_phys_names[pair]
            r0, r1 = Material(pair[0]).name, Material(pair[1]).name
            ds.add_gmsh_interface(mesh=self._mesh_name, gmsh_name=if_name,
                                  region0=r0, region1=r1, name=if_name)
            self._interfaces.append((if_name, r0, r1))

        ds.finalize_mesh(mesh=self._mesh_name)
        ds.create_device(mesh=self._mesh_name, device=self._device_name)

        # Populate Nd/Na/NetDoping per region. DEVSIM may re-order nodes per
        # region, so match region coordinates to MeshField nodes via KD-tree.
        # Insulator regions still get NetDoping (= 0) so Poisson can reference
        # it without a missing-model error.
        mf_pts_um = np.asarray(mf.points, dtype=float)[:, :2]
        tree = cKDTree(mf_pts_um)
        for region in self._region_materials:
            x_cm = np.asarray(
                ds.get_node_model_values(device=self._device_name,
                                         region=region, name="x"))
            y_cm = np.asarray(
                ds.get_node_model_values(device=self._device_name,
                                         region=region, name="y"))
            pts_um = np.column_stack([x_cm, y_cm]) * 1e4
            _, idx = tree.query(pts_um)
            if self._region_is_insulator.get(region, False):
                nd = np.zeros(len(idx))
                na = np.zeros(len(idx))
            else:
                nd = mf.Nd[idx]
                na = mf.Na[idx]
            for name, vals in (("Donors", nd), ("Acceptors", na),
                               ("NetDoping", nd - na)):
                ds.node_solution(device=self._device_name, region=region,
                                 name=name)
                ds.set_node_values(device=self._device_name, region=region,
                                   name=name,
                                   values=np.asarray(vals, dtype=float).tolist())

    # ------------------------------------------------------------------
    # Equation setup
    # ------------------------------------------------------------------
    def _setup_equations(self) -> None:
        for region, mat in self._region_materials.items():
            params = self._params_for_region(mat)
            self._set_region_parameters(region, params)
            if self._region_is_insulator.get(region, False):
                self._build_insulator_potential(region)
            else:
                self._build_potential_only(region)
        for contact in self._contact_regions:
            self._build_contact_potential_equation(contact)
        for if_name, r0, r1 in self._interfaces:
            self._build_interface_continuity(if_name, "Potential")

    def _params_for_region(self, mat: Material) -> MaterialParams:
        display = MATERIAL_NAMES.get(mat, mat.name)
        for key in (display, mat.name):
            if key in self.mat_params:
                return self.mat_params[key]
        raise KeyError(
            f"No MaterialParams provided for {mat.name} / {display}. "
            f"Available keys: {list(self.mat_params)}")

    def _set_region_parameters(self, region: str, p: MaterialParams) -> None:
        ds = self._ds
        V_t = KB_J * self.T / Q_C
        pairs = {
            "Permittivity": p.band_structure.permittivity_relative * EPS0_F_CM,
            "ElectronCharge": Q_C,
            "n_i": p.band_structure.ni_cm3_300K,
            "V_t": V_t,
            "mu_n": p.mobility_constant.electron_cm2_Vs,
            "mu_p": p.mobility_constant.hole_cm2_Vs,
            "taun": p.recombination.tau_n_s,
            "taup": p.recombination.tau_p_s,
            "n1": p.band_structure.ni_cm3_300K,
            "p1": p.band_structure.ni_cm3_300K,
        }
        for name, value in pairs.items():
            ds.set_parameter(device=self._device_name, region=region,
                             name=name, value=float(value))

    def _build_potential_only(self, region: str) -> None:
        """Create Potential solution + Poisson equation (intrinsic charge).

        After solve_equilibrium() switches to DD, PotentialEquation is rebuilt
        against PotentialNodeCharge (which uses Electrons/Holes as unknowns).
        """
        ds = self._ds
        device = self._device_name

        ds.node_solution(device=device, region=region, name="Potential")
        ds.edge_from_node_model(device=device, region=region,
                                node_model="Potential")

        for name, eq in (
            ("EField", "(Potential@n0 - Potential@n1)*EdgeInverseLength"),
            ("EField:Potential@n0", "EdgeInverseLength"),
            ("EField:Potential@n1", "-EdgeInverseLength"),
            ("PotentialEdgeFlux", "Permittivity*EField"),
            ("PotentialEdgeFlux:Potential@n0",
             "Permittivity*EdgeInverseLength"),
            ("PotentialEdgeFlux:Potential@n1",
             "-Permittivity*EdgeInverseLength"),
        ):
            ds.edge_model(device=device, region=region, name=name, equation=eq)

        # Intrinsic carrier node models (used as initial guess + Poisson source).
        # Use DEVSIM's symbolic diff() to avoid hand-derivative bugs.
        for name, eq in (
            ("IntrinsicElectrons", "n_i*exp(Potential/V_t)"),
            ("IntrinsicElectrons:Potential",
             "diff(n_i*exp(Potential/V_t), Potential)"),
            ("IntrinsicHoles", "n_i^2/IntrinsicElectrons"),
            ("IntrinsicHoles:Potential",
             "diff(n_i^2/IntrinsicElectrons, Potential)"),
            ("IntrinsicCharge",
             "IntrinsicHoles - IntrinsicElectrons + NetDoping"),
            ("IntrinsicCharge:Potential",
             "diff(IntrinsicHoles - IntrinsicElectrons, Potential)"),
            ("PotentialIntrinsicNodeCharge",
             "-ElectronCharge*IntrinsicCharge"),
            ("PotentialIntrinsicNodeCharge:Potential",
             "diff(-ElectronCharge*IntrinsicCharge, Potential)"),
        ):
            ds.node_model(device=device, region=region, name=name, equation=eq)

        # DD-mode node charge (active once Electrons/Holes are solutions)
        ds.node_solution(device=device, region=region, name="Electrons")
        ds.edge_from_node_model(device=device, region=region,
                                node_model="Electrons")
        ds.node_solution(device=device, region=region, name="Holes")
        ds.edge_from_node_model(device=device, region=region,
                                node_model="Holes")
        for name, eq in (
            ("PotentialNodeCharge",
             "-ElectronCharge*(Holes - Electrons + NetDoping)"),
            ("PotentialNodeCharge:Electrons", "ElectronCharge"),
            ("PotentialNodeCharge:Holes", "-ElectronCharge"),
        ):
            ds.node_model(device=device, region=region, name=name, equation=eq)

        # Poisson only (replaced later)
        ds.equation(device=device, region=region, name="PotentialEquation",
                    variable_name="Potential",
                    node_model="PotentialIntrinsicNodeCharge",
                    edge_model="PotentialEdgeFlux",
                    variable_update="log_damp")

    def _build_insulator_potential(self, region: str) -> None:
        """Poisson-only region (SiO2, Si3N4). No carriers — fixed-charge
        equation uses NetDoping (typically 0 in oxide)."""
        ds = self._ds
        device = self._device_name

        ds.node_solution(device=device, region=region, name="Potential")
        ds.edge_from_node_model(device=device, region=region,
                                node_model="Potential")

        for name, eq in (
            ("EField", "(Potential@n0 - Potential@n1)*EdgeInverseLength"),
            ("EField:Potential@n0", "EdgeInverseLength"),
            ("EField:Potential@n1", "-EdgeInverseLength"),
            ("PotentialEdgeFlux", "Permittivity*EField"),
            ("PotentialEdgeFlux:Potential@n0",
             "Permittivity*EdgeInverseLength"),
            ("PotentialEdgeFlux:Potential@n1",
             "-Permittivity*EdgeInverseLength"),
        ):
            ds.edge_model(device=device, region=region, name=name, equation=eq)

        for name, eq in (
            ("PotentialNodeCharge", "-ElectronCharge*NetDoping"),
        ):
            ds.node_model(device=device, region=region, name=name, equation=eq)

        ds.equation(device=device, region=region, name="PotentialEquation",
                    variable_name="Potential",
                    node_model="PotentialNodeCharge",
                    edge_model="PotentialEdgeFlux",
                    variable_update="log_damp")

    def _build_interface_continuity(self, if_name: str, variable: str) -> None:
        """Enforce `variable@r0 == variable@r1` across the interface."""
        ds = self._ds
        device = self._device_name
        mname = f"continuous{variable}"
        ds.interface_model(device=device, interface=if_name, name=mname,
                           equation=f"{variable}@r0 - {variable}@r1")
        ds.interface_model(device=device, interface=if_name,
                           name=f"{mname}:{variable}@r0", equation="1")
        ds.interface_model(device=device, interface=if_name,
                           name=f"{mname}:{variable}@r1", equation="-1")
        # Map "PotentialEquation" → "PotentialEquation", etc.
        eq_name = f"{variable}Equation" if variable == "Potential" \
            else f"{variable}ContinuityEquation"
        ds.interface_equation(device=device, interface=if_name, name=eq_name,
                              interface_model=mname, type="continuous")

    def _build_continuity_equations(self, region: str) -> None:
        ds = self._ds
        device = self._device_name

        # Scharfetter-Gummel current densities on edges.
        for name, eq in (
            ("vdiff", "(Potential@n0 - Potential@n1)/V_t"),
            ("vdiff:Potential@n0", "1/V_t"),
            ("vdiff:Potential@n1", "-1/V_t"),
            ("Bern01", "B(vdiff)"),
            ("Bern01:Potential@n0", "dBdx(vdiff)*vdiff:Potential@n0"),
            ("Bern01:Potential@n1", "dBdx(vdiff)*vdiff:Potential@n1"),
            ("Bern10", "Bern01 + vdiff"),
            ("Bern10:Potential@n0",
             "Bern01:Potential@n0 + vdiff:Potential@n0"),
            ("Bern10:Potential@n1",
             "Bern01:Potential@n1 + vdiff:Potential@n1"),
        ):
            ds.edge_model(device=device, region=region, name=name, equation=eq)

        Jn = ("ElectronCharge*mu_n*EdgeInverseLength*V_t*"
              "(Electrons@n1*Bern10 - Electrons@n0*Bern01)")
        for name, eq in (
            ("ElectronCurrent", Jn),
            ("ElectronCurrent:Electrons@n0",
             f"simplify(diff({Jn}, Electrons@n0))"),
            ("ElectronCurrent:Electrons@n1",
             f"simplify(diff({Jn}, Electrons@n1))"),
            ("ElectronCurrent:Potential@n0",
             f"simplify(diff({Jn}, Potential@n0))"),
            ("ElectronCurrent:Potential@n1",
             f"simplify(diff({Jn}, Potential@n1))"),
        ):
            ds.edge_model(device=device, region=region, name=name, equation=eq)

        Jp = ("-ElectronCharge*mu_p*EdgeInverseLength*V_t*"
              "(Holes@n1*Bern01 - Holes@n0*Bern10)")
        for name, eq in (
            ("HoleCurrent", Jp),
            ("HoleCurrent:Holes@n0", f"simplify(diff({Jp}, Holes@n0))"),
            ("HoleCurrent:Holes@n1", f"simplify(diff({Jp}, Holes@n1))"),
            ("HoleCurrent:Potential@n0", f"simplify(diff({Jp}, Potential@n0))"),
            ("HoleCurrent:Potential@n1", f"simplify(diff({Jp}, Potential@n1))"),
        ):
            ds.edge_model(device=device, region=region, name=name, equation=eq)

        # Time-node models (zero for DC, but equation() requires them)
        for name, eq in (
            ("NCharge", "-ElectronCharge*Electrons"),
            ("NCharge:Electrons", "-ElectronCharge"),
            ("PCharge", "-ElectronCharge*Holes"),
            ("PCharge:Holes", "-ElectronCharge"),
        ):
            ds.node_model(device=device, region=region, name=name, equation=eq)

        # SRH recombination
        USRH = ("-ElectronCharge*(Electrons*Holes - n_i^2)/"
                "(taup*(Electrons + n1) + taun*(Holes + p1))")
        for name, eq in (
            ("USRH", USRH),
            ("USRH:Electrons", f"simplify(diff({USRH}, Electrons))"),
            ("USRH:Holes", f"simplify(diff({USRH}, Holes))"),
        ):
            ds.node_model(device=device, region=region, name=name, equation=eq)

        ds.equation(device=device, region=region,
                    name="ElectronContinuityEquation",
                    variable_name="Electrons", edge_model="ElectronCurrent",
                    variable_update="positive",
                    time_node_model="NCharge", node_model="USRH")
        ds.equation(device=device, region=region,
                    name="HoleContinuityEquation",
                    variable_name="Holes", edge_model="HoleCurrent",
                    variable_update="positive",
                    time_node_model="PCharge", node_model="USRH")

    # ------------------------------------------------------------------
    # Contact BCs
    # ------------------------------------------------------------------
    def _build_contact_potential_equation(self, contact: str) -> None:
        ds = self._ds
        device = self._device_name
        region = self._contact_regions[contact]
        biasname = f"{contact}bias"
        ds.set_parameter(device=device, region=region, name=biasname,
                         value=0.0)

        pot_name = f"{contact}nodemodel"
        if self._region_is_insulator.get(region, False):
            # Metal-on-insulator: Potential pinned to bias (no semiconductor
            # built-in offset, no carrier BCs).
            ds.contact_node_model(device=device, contact=contact,
                                  name=pot_name,
                                  equation=f"Potential-{biasname}")
            ds.contact_node_model(device=device, contact=contact,
                                  name=f"{pot_name}:Potential", equation="1")
            ds.contact_equation(device=device, contact=contact,
                                name="PotentialEquation",
                                node_model=pot_name)
            return

        cemod = f"celec_{contact}"
        chmod = f"chole_{contact}"
        # Equilibrium carrier densities at the contact (ohmic assumption)
        ds.contact_node_model(
            device=device, contact=contact, name=cemod,
            equation="1e-10 + 0.5*(NetDoping + (NetDoping^2 + 4*n_i^2)^(0.5))")
        ds.contact_node_model(
            device=device, contact=contact, name=chmod,
            equation="1e-10 + 0.5*(-NetDoping + (NetDoping^2 + 4*n_i^2)^(0.5))")

        ds.contact_node_model(
            device=device, contact=contact, name=pot_name,
            equation=(f"ifelse(NetDoping > 0,"
                      f" Potential-{biasname}-V_t*log({cemod}/n_i),"
                      f" Potential-{biasname}+V_t*log({chmod}/n_i))"))
        ds.contact_node_model(device=device, contact=contact,
                              name=f"{pot_name}:Potential", equation="1")

        ds.contact_equation(device=device, contact=contact,
                            name="PotentialEquation",
                            node_model=pot_name)

    def _build_contact_dd_equations(self, contact: str) -> None:
        ds = self._ds
        device = self._device_name
        cemod = f"celec_{contact}"
        chmod = f"chole_{contact}"

        e_name = f"{contact}nodeelectrons"
        h_name = f"{contact}nodeholes"
        ds.contact_node_model(
            device=device, contact=contact, name=e_name,
            equation=(f"ifelse(NetDoping > 0,"
                      f" Electrons - {cemod},"
                      f" Electrons - n_i^2/{chmod})"))
        ds.contact_node_model(device=device, contact=contact,
                              name=f"{e_name}:Electrons", equation="1.0")
        ds.contact_node_model(
            device=device, contact=contact, name=h_name,
            equation=(f"ifelse(NetDoping < 0,"
                      f" Holes - {chmod},"
                      f" Holes - n_i^2/{cemod})"))
        ds.contact_node_model(device=device, contact=contact,
                              name=f"{h_name}:Holes", equation="1.0")

        ds.contact_equation(device=device, contact=contact,
                            name="ElectronContinuityEquation",
                            node_model=e_name,
                            edge_current_model="ElectronCurrent")
        ds.contact_equation(device=device, contact=contact,
                            name="HoleContinuityEquation",
                            node_model=h_name,
                            edge_current_model="HoleCurrent")

    # ------------------------------------------------------------------
    # Solve helpers
    # ------------------------------------------------------------------
    def _set_contact_voltage(self, contact: str, voltage: float) -> None:
        region = self._contact_regions[contact]
        self._ds.set_parameter(device=self._device_name, region=region,
                               name=f"{contact}bias", value=float(voltage))

    def _solve_dc(self) -> None:
        self._ds.solve(type="dc", absolute_error=1e10, relative_error=1e-7,
                       maximum_iterations=50)

    def _get_contact_current(self, contact: str) -> float:
        ecurr = self._ds.get_contact_current(
            contact=contact, equation="ElectronContinuityEquation",
            device=self._device_name)
        hcurr = self._ds.get_contact_current(
            contact=contact, equation="HoleContinuityEquation",
            device=self._device_name)
        return float(ecurr + hcurr)
