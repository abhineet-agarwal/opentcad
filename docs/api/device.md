# Device solver

The DEVSIM drift–diffusion solver, physics configuration, extraction and optics.

For an introduction, see the [user guide](../device_physics.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.device.solver`: `DeviceSolver`.

## DeviceSolver

```python
class opentcad.device.solver.DeviceSolver(
    meshfield: MeshField,
    material_params: dict[str, MaterialParams],
    temperature_K: float = 300.0,
    physics: PhysicsConfig | None = None,
    interface_Qf_C_per_cm2: dict | None = None,
    interface_Qf_width_um: float = 0.005,
    ac_terminals: list[str] | None = None,
)
```

DEVSIM drift-diffusion solver wrapping a MeshField.

**Parameters**

- `meshfield`: 2D triangle MeshField with material_id cell data, Nd/Na point data, and ContactTag boundary nodes.
- `material_params`: Mapping from material display name (e.g. "Silicon") or enum short name (e.g. "SI") to MaterialParams.
- `temperature_K`: Lattice temperature [K].

**Example**

```python
solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.7, 0.05)
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/solver.py#L29)

### DeviceSolver.initialize

```python
DeviceSolver.initialize() -> None
```

Build the DEVSIM device + equations. Idempotent per instance.

### DeviceSolver.solve_equilibrium

```python
DeviceSolver.solve_equilibrium() -> None
```

Warm-start with Poisson-only then switch to coupled DD solve.

With a prescribed optical generation field this returns an illuminated
steady state at the current contact biases, NOT thermal equilibrium.

### DeviceSolver.cv_sweep

```python
DeviceSolver.cv_sweep(
    terminal: str,
    reference: str,
    v_start: float,
    v_end: float,
    v_step: float,
) -> tuple[list[float], list[float]]
```

Quasi-static CV sweep on `terminal` vs `reference` (held at 0V).

For each Vg in [v_start, v_end], solve DC and query the total
charge stored at `terminal` via DEVSIM's get_contact_charge.
Capacitance C(V) is then dQ/dV computed by central differences:

```
C(V_i) = (Q(V_{i+1}) - Q(V_{i-1})) / (V_{i+1} - V_{i-1}).
```

Returns (voltages, C_values). Units of C follow DEVSIM's 2-D
integration: F/cm of out-of-plane depth.

**Notes**

- Requires `terminal` to be a metal-on-insulator (gate) contact,
  on which we register PotentialEdgeFlux as the edge_charge_model.
- The result is quasi-static (the DC-diff limit) — equivalent to
  measured LF CV. For HF CV where minority carriers can't follow,
  use ``ac_sweep`` (small-signal, requires declaring the gate in
  ``ac_terminals=[...]`` at solver construction).

### DeviceSolver.iv_sweep

```python
DeviceSolver.iv_sweep(
    anode_contact: str,
    cathode_contact: str,
    v_start: float,
    v_end: float,
    v_step: float,
    hold_contacts: dict[str, float] | None = None,
    measure_contact: str | None = None,
) -> tuple[list[float], list[float]]
```

Ramp `anode_contact` from v_start to v_end, holding cathode at 0V.

Returns (voltages, currents). Current is total (electron+hole) at
`measure_contact` in A/cm of out-of-plane length. Use
``opentcad.device.optical.current_from_2d`` for physical Amps.

**Parameters**

- `anode_contact`: contact whose voltage is ramped.
- `cathode_contact`: reference contact, held at 0 V.
- `hold_contacts`: {name: voltage} of other contacts to hold at a nonzero DC bias — e.g. `{"drain": 0.05}` for a MOSFET Id-Vgs sweep at Vds = 50 mV. Each is ramped from 0 up to its target in ~50 mV steps before the main sweep begins.
- `measure_contact`: contact to read current from. Defaults to `anode_contact` (the classic diode / two-terminal case). For an NMOS Id-Vgs sweep, set to the drain.

### DeviceSolver.transient_sweep

```python
DeviceSolver.transient_sweep(
    bias_schedule,
    times,
    *,
    measure_contacts=None,
    integrator: str = 'bdf1',
    charge_error: float = 0.5,
) -> tuple[list[float], dict[str, list[float]]]
```

Transient DC sweep. Step through *times* applying *bias_schedule*.

Returns ``(times_list, {contact: current_history_A_per_cm})``.

**Parameters**

- `bias_schedule`: mapping ``{contact_name: f(t)}`` or ``{contact_name: array-like}`` giving the contact voltage at each sample time. Callables are evaluated at every step; arrays must have the same length as ``times``. Contacts not in the dict stay at their current bias.
- `times`: 1D array of absolute time points (s). The first entry is treated as the initial condition (no transient solve taken; biases are applied + DC-resolved as a settled starting state). Each subsequent entry drives one transient solve with ``tdelta = t[i] - t[i-1]``.
- `measure_contacts`: list of contacts whose currents to record; defaults to every contact on the MeshField.
- `integrator`: DEVSIM transient type — one of ``"bdf1"`` (first-order implicit, default; damped), ``"bdf2"`` (second-order, better accuracy, less damped), ``"tr"``   (trapezoidal, second-order, undamped).
- `charge_error`: tolerance on the relative difference between BDF projected charge and the Newton-solved charge at each step. **Convergence** knob, not accuracy — DEVSIM refuses to label a step converged while this ratio is above the threshold. Default 0.5 (50 %) survives turn-on ramps where each dt adds a factor of e to the current; tighten (0.05 or 0.01) for small-signal / near-steady runs where Newton converges tightly from the BDF projection.

Step-response example:

```
# Gate steps from 0 -> 1 V at t = 0, settle for 10 ns.
import numpy as np
times = np.linspace(0, 10e-9, 101)
V_gate = np.where(times > 0, 1.0, 0.0)
t, I = solver.transient_sweep({"gate": V_gate}, times,
                               measure_contacts=["drain"])
```

Caveats:
  * The initial condition at ``times[0]`` is a DC solve at the

```
prescribed biases, not an arbitrary user-provided state.
```

  * BDF1 adds numerical damping; BDF2/TR are preferred for

```
ringing-sensitive measurements. Try BDF2 first if a result
looks over-damped.
```

  * Junction capacitance from carrier-storage is represented

```
(NCharge, PCharge time terms exist). External wiring
parasitics are not — add them via DEVSIM's circuit layer.
```

### DeviceSolver.ac_sweep

```python
DeviceSolver.ac_sweep(
    terminal: str,
    reference: str,
    frequencies,
    *,
    dc_bias: float = 0.0,
) -> tuple[list[float], list[complex]]
```

Small-signal AC analysis — complex admittance Y(f) at *terminal*.

``terminal`` must have been named in ``ac_terminals=[...]`` at
``DeviceSolver`` construction time — DEVSIM blocks adding circuit
nodes once any DC analysis has run (process-global gate), so the
AC scaffold is built in ``initialize``, before the first solve.

Procedure:
  1. Equilibrium → ramp ``reference`` to 0 V and ``terminal`` to

```
 ``dc_bias`` in ≤ 50 mV steps (``circuit_alter`` on the pre-
 wired V source carries the DC through to the KCL).
```

  2. For every frequency f: ``ds.solve(type="ac", frequency=f)``.

```
 Read the real & imag branch currents of the V source from
 circuit node ``V_<terminal>_src__<device>.I`` (DEVSIM
 auto-creates the ``.I`` node for voltage sources).
 Admittance:

    Y(f) = -I_V1(f) / V_ac     with V_ac = 1 V

 so ``Y_real = -V1.I_real`` and ``Y_imag = -V1.I_imag``.
 Convert to capacitance / conductance by
 ``C(f) = Im(Y(f)) / (2πf)`` and ``G(f) = Re(Y(f))``.
```

**Returns**

``(freqs, Y)`` where ``freqs`` is a ``list[float]`` and ``Y`` a
``list[complex]`` in Siemens per cm of out-of-plane depth
(matching the 2-D integration convention used elsewhere).

Scope:

```
Supports metal-on-insulator (MOS gate) terminals — the
HF-CV case this method was built for. Ohmic/Schottky
semiconductor terminals need the Electron/HoleContinuity
flux also routed into the same circuit node; that
extension raises NotImplementedError explicitly.
```

Caveats:
  * The acreal=1 V AC amplitude is the DEVSIM small-signal

```
convention — the returned Y(f) is independent of it.
```

  * ``_set_contact_voltage`` on an AC-wired contact routes

```
through ``circuit_alter`` on the pre-wired source; any
subsequent iv_/cv_/transient sweep that drives this contact
still works, driven through the same path.
```

### DeviceSolver.contact_current_A_per_cm

```python
DeviceSolver.contact_current_A_per_cm(contact: str) -> float
```

Read conventional current entering a contact at the last DD solution.

Requires a successful ``solve_equilibrium`` or ``iv_sweep`` first.
Photovoltaic power delivery has negative current at its positive terminal.

### DeviceSolver.set_contact_voltage

```python
DeviceSolver.set_contact_voltage(contact: str, voltage: float) -> None
```

Set a contact's bias [V]; it takes effect at the next
``solve_dc()``. Requires ``solve_equilibrium()`` first.

### DeviceSolver.solve_dc

```python
DeviceSolver.solve_dc() -> None
```

Newton DC solve at the current contact biases.

### DeviceSolver.snapshot

```python
DeviceSolver.snapshot(fields=('Potential', 'Electrons', 'Holes')) -> MeshField
```

A copy of the MeshField carrying the current solution as point
data: ``Potential`` [V, relative to the intrinsic level, Fermi
level at 0 V], ``Electrons`` and ``Holes`` [cm⁻³]. Carrier
densities are 0 in insulators; on a semiconductor/insulator
interface node the semiconductor's value is used. The contact
biases go in ``metadata["solution_bias_V"]``.

### DeviceSolver.field_snapshot

```python
DeviceSolver.field_snapshot(
    biases: dict[str, float] | None = None,
    fields=('Potential', 'Electrons', 'Holes'),
) -> MeshField
```

Solve at ``biases`` ({contact: V}; unnamed contacts at 0 V) and
return ``snapshot(fields)``. Biases are ramped from 0 V in ≤ 50 mV
steps. Registered as the ``fields`` analysis.

### DeviceSolver.close

```python
DeviceSolver.close() -> None
```

Delete this solver's DEVSIM device (DEVSIM keeps devices in
global state; every ds.solve acts on all live devices). The solver
can't be used afterwards.

### DeviceSolver.run

```python
DeviceSolver.run(analysis: str, **kwargs)
```

Run a registered analysis by name and return its result.

Built-ins: ``"iv"``, ``"cv"``, ``"transient"`` and ``"ac"`` (the
``*_sweep`` methods, same keyword arguments). Plugins add more with
``opentcad.plugins.register_analysis``; ``run(name, **kw)`` calls
``fn(self, **kw)``.

Import from `opentcad.device.physics`: `PhysicsConfig`, `MobilityModel`, `RecombinationModel`, `BandgapNarrowingModel`, `StatisticsModel`.

## PhysicsConfig

```python
class opentcad.device.physics.PhysicsConfig(
    mobility: MobilityModel = None,
    recombination: List[RecombinationModel] = list(),
    bgn: BandgapNarrowingModel = None,
    statistics: StatisticsModel = None,
) -> None
```

Container of physics models used by DeviceSolver. New model classes
(avalanche, ...) will be added as additional fields here.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/physics.py#L201)

### PhysicsConfig.note_provenance

```python
PhysicsConfig.note_provenance() -> None
```

Note each model, its settings and its references in the active
provenance record (a no-op outside ``opentcad.provenance.recording``).

## MobilityModel

```python
class opentcad.device.physics.MobilityModel()
```

Base class for low-field bulk mobility models.

Subclasses register the DEVSIM parameters/models they need in
`attach()` and expose the *expressions* the solver should substitute
into the Scharfetter-Gummel current density via `mu_n_expr()` and
`mu_p_expr()`. Inlining the expression rather than wrapping in an
edge_model lets the constant case reduce to the original solver
expression exactly, which is friendlier to Newton convergence.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/physics.py#L30)

### MobilityModel.required_params

```python
MobilityModel.required_params() -> tuple[str, ...]
```

Material-file fields this model needs beyond the required core
(block names like ``"mobility_klaassen"`` or keys like
``"recombination.Cn_cm6_per_s"``). The solver refuses to run the
model on a material whose file left them to the silicon defaults
(``MaterialParams.defaulted``).

### MobilityModel.attach

```python
MobilityModel.attach(ds, device: str, region: str, params, T_K: float) -> None
```

Register this model's DEVSIM parameters and node/edge models on
one semiconductor region. The solver calls it once per region.

**Parameters**

- `ds`: the ``devsim`` module.
- `device`: DEVSIM device name.
- `region`: DEVSIM region name.
- `params`: the region's ``MaterialParams``.
- `T_K`: lattice temperature [K].

### MobilityModel.mu_n_expr

```python
MobilityModel.mu_n_expr() -> str
```

DEVSIM expression for electron mobility on the edge.

### MobilityModel.mu_p_expr

```python
MobilityModel.mu_p_expr() -> str
```

DEVSIM expression for hole mobility on the edge.

## RecombinationModel

```python
class opentcad.device.physics.RecombinationModel()
```

Base class for net recombination contributors.

Each model registers (1) a node model named after `term_name` with
units of recombination rate * (-q) [A/cm^3] so it can be summed into
the continuity node_model, and (2) its derivatives w.r.t. Electrons
and Holes. The solver sums every model's term_name into the total
recombination expression passed to the continuity equation.

`n_i_expr` is the DEVSIM expression for the effective intrinsic
density — "n_i" (a parameter) when no BGN model is active, or the
node model registered by the BGN model when BGN is on. Recombination
formulas contain n_i^2 which must use the effective value.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/physics.py#L81)

### RecombinationModel.required_params

```python
RecombinationModel.required_params() -> tuple[str, ...]
```

Material-file fields this model needs beyond the required core
(block names like ``"mobility_klaassen"`` or keys like
``"recombination.Cn_cm6_per_s"``). The solver refuses to run the
model on a material whose file left them to the silicon defaults
(``MaterialParams.defaulted``).

### RecombinationModel.term_name

```python
property RecombinationModel.term_name: str
```

Unique node-model name this contributor will register.

### RecombinationModel.attach

```python
RecombinationModel.attach(
    ds,
    device: str,
    region: str,
    params,
    T_K: float,
    n_i_expr: str = 'n_i',
) -> None
```

Register the node model named ``term_name`` and its derivatives
with respect to Electrons and Holes on one semiconductor region.
Arguments are as for ``MobilityModel.attach``; ``n_i_expr`` is the
expression to use for the (effective) intrinsic density.

## BandgapNarrowingModel

```python
class opentcad.device.physics.BandgapNarrowingModel()
```

Base class for effective-intrinsic-density models.

A BGN model registers a node model `n_i_eff` that captures the
doping-induced bandgap narrowing, and `n_i_expr()` returns the
name the solver substitutes for `n_i` in Poisson, contact BCs,
and recombination terms. The default (`NoBGN`) is a no-op and
returns the plain parameter name "n_i".

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/physics.py#L121)

### BandgapNarrowingModel.required_params

```python
BandgapNarrowingModel.required_params() -> tuple[str, ...]
```

Material-file fields this model needs beyond the required core
(block names like ``"mobility_klaassen"`` or keys like
``"recombination.Cn_cm6_per_s"``). The solver refuses to run the
model on a material whose file left them to the silicon defaults
(``MaterialParams.defaulted``).

### BandgapNarrowingModel.attach

```python
BandgapNarrowingModel.attach(ds, device: str, region: str, params, T_K: float) -> None
```

Register ``n_i_eff`` (or nothing, for ``NoBGN``) on one
semiconductor region. Arguments are as for ``MobilityModel.attach``.

### BandgapNarrowingModel.n_i_expr

```python
BandgapNarrowingModel.n_i_expr() -> str
```

DEVSIM node/parameter name to use in place of the bare n_i.

## StatisticsModel

```python
class opentcad.device.physics.StatisticsModel()
```

Base class for carrier-statistics models.

Wraps a Boltzmann-form expression for `n(potential)` (and `p`) with
the statistics-specific correction. The solver substitutes the
wrapped forms into IntrinsicElectrons/Holes and the ohmic contact
built-in potential offset. Boltzmann is a no-op identity; FermiDirac
applies the Blakemore approximation.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/physics.py#L152)

### StatisticsModel.required_params

```python
StatisticsModel.required_params() -> tuple[str, ...]
```

Material-file fields this model needs beyond the required core
(block names like ``"mobility_klaassen"`` or keys like
``"recombination.Cn_cm6_per_s"``). The solver refuses to run the
model on a material whose file left them to the silicon defaults
(``MaterialParams.defaulted``).

### StatisticsModel.attach

```python
StatisticsModel.attach(ds, device: str, region: str, params, T_K: float) -> None
```

Register any per-region parameters (Nc, Nv, ...) needed for
the wrapping expressions. Boltzmann needs nothing; FermiDirac
registers Nc and Nv.

### StatisticsModel.wrap_electron_density

```python
StatisticsModel.wrap_electron_density(boltz_expr: str, params) -> str
```

Given a Boltzmann-form expression for n, return the corrected
expression for the active statistics.

### StatisticsModel.wrap_hole_density

```python
StatisticsModel.wrap_hole_density(boltz_expr: str, params) -> str
```

Same for p.

### StatisticsModel.electron_potential_offset

```python
StatisticsModel.electron_potential_offset(n_expr: str, n_i_expr: str, params) -> str
```

Return the built-in potential offset  V_t * log(n / n_i)
under the active statistics. Used in ohmic contact BCs to set
Potential so equilibrium n = n_expr is consistent with the
statistics model.

### StatisticsModel.hole_potential_offset

```python
StatisticsModel.hole_potential_offset(p_expr: str, n_i_expr: str, params) -> str
```

Same for the p-side ohmic contact.

Import from `opentcad.device.extract`: `vth_max_gm`, `vth_constant_current`.

## vth_max_gm

```python
opentcad.device.extract.vth_max_gm(vgs, ids, vds: float) -> float
```

Threshold voltage [V] by maximum-gm linear extrapolation.

Vth = Vgs* − Id*/gm* − Vds/2, where * is the bias of peak
gm = dId/dVgs (central differences; non-uniform steps allowed).
Meaningful for a linear-region sweep (small Vds).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/extract.py#L34)

## vth_constant_current

```python
opentcad.device.extract.vth_constant_current(vgs, ids, i_crit: float) -> float
```

Threshold voltage [V] where |Id| first reaches ``i_crit``.

Interpolates log10|Id| linearly between the two bracketing samples.
The usual criterion is 100 nA × W/L; per unit width that is
1e-7/L[µm] A/µm, or 1e-3/L[µm] A/cm.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/extract.py#L52)

Import from `opentcad.device.optical`: `BeerLambert`, `current_from_2d`.

## BeerLambert

```python
class opentcad.device.optical.BeerLambert(
    wavelength_nm: float,
    irradiance_W_m2: float,
    absorption_cm_inv: float,
    reflectance: float = 0.0,
    quantum_yield: float = 1.0,
) -> None
```

Uniform incident irradiance on a flat, homogeneous absorbing slab.

``G(d) = yield * (1-R) * irradiance / photon_energy * alpha * exp(-alpha*d)``.
Irradiance is W/m^2, wavelength nm, alpha cm^-1, depth um. ``quantum_yield``
is pairs per absorbed photon (0..1). It is not collection efficiency;
carrier collection is computed by drift-diffusion. The caller must use
a wavelength/absorption coefficient appropriate to the material/bandgap.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/optical.py#L21)

### BeerLambert.photon_flux_cm2_s

```python
property BeerLambert.photon_flux_cm2_s: float
```

Incident photons/cm^2/s (before reflection).

### BeerLambert.generation_cm3_s

```python
BeerLambert.generation_cm3_s(depth_um)
```

Evaluate at non-negative depths inside the absorbing material.

### BeerLambert.absorbed_pairs_cm2_s

```python
BeerLambert.absorbed_pairs_cm2_s(thickness_um: float) -> float
```

Analytical depth integral of G, for photon-budget validation.

### BeerLambert.apply

```python
BeerLambert.apply(
    meshfield: MeshField,
    *,
    surface_y_um: float,
    material: Material = Material.SI,
) -> None
```

Replace the mesh's prescribed generation field; illumination travels -y.

``surface_y_um`` is the flat entrance plane in the absorber, not the
top of an overlying optical stack. Other materials get zero generation.
Shared interface nodes belong to both materials; DeviceSolver ignores
generation in insulators. Multiple absorbing layers/oblique incidence
need their own field calculation, not repeated calls to this method.
No automatic shadowing or transmission through overlayers is computed.

## current_from_2d

```python
opentcad.device.optical.current_from_2d(current_A_per_cm, *, depth_um: float)
```

Scale a translationally invariant 2D terminal current to physical A.

The in-plane width has already been integrated by DEVSIM. Multiply only
by the OUT-OF-PLANE depth in cm. This assumes no edge effects in that
direction; it does not convert arbitrary 2D geometry into a 3D device.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/optical.py#L102)

Import from `opentcad.device.compact`: `SingleDiodePV`, `fit_single_diode`.

## SingleDiodePV

```python
class opentcad.device.compact.SingleDiodePV(
    saturation_A: float,
    ideality: float,
    photocurrent_A: float,
    reference_irradiance_W_m2: float = 1000.0,
    series_cells: int = 1,
    temperature_K: float = 300.0,
) -> None
```

Delivering current is positive; dark forward terminal current is negative.

``I = Iph_ref * E/Eref - I0 * expm1(V/(Ns*n*kT/q))``.
``ideality`` is per cell and ``saturation_A`` is the current through the
series string. Parameters are defined at ``temperature_K`` only. Changing
temperature requires a separately justified parameter set.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/compact.py#L20)

### SingleDiodePV.diode_voltage_V

```python
property SingleDiodePV.diode_voltage_V
```

Ns·n·kT/q [V]: the voltage scale of the diode exponential.

### SingleDiodePV.current_A

```python
SingleDiodePV.current_A(voltage_V, irradiance_W_m2=1000.0)
```

Delivered current [A] at terminal voltage ``voltage_V`` and
irradiance [W/m²] (scalars or arrays). Raises ValueError for
non-finite inputs or negative irradiance.

### SingleDiodePV.open_circuit_V

```python
SingleDiodePV.open_circuit_V(irradiance_W_m2=1000.0)
```

Open-circuit voltage [V] at the given irradiance [W/m²].

### SingleDiodePV.maximum_power_point

```python
SingleDiodePV.maximum_power_point(irradiance_W_m2=1000.0)
```

Return (V, delivering A, W) at the unique first-quadrant maximum.

### SingleDiodePV.scaled_current

```python
SingleDiodePV.scaled_current(factor: float)
```

Scale I0 and Iph together, e.g. assumed identical current density.

This preserves Voc, but is not valid when edge recombination, shading
or contact geometry change with physical device area.

### SingleDiodePV.spice_subcircuit

```python
SingleDiodePV.spice_subcircuit(name='photovoltaic')
```

Export an ideal diode + photocurrent subcircuit with pins p, n.

Run SPICE at the fitted temperature (in Celsius). No capacitance is
inferred from DC IV. ``illumination`` is W/m²; ``area_scale`` multiplies
both currents. The external simulator is not a Python dependency.

## fit_single_diode

```python
opentcad.device.compact.fit_single_diode(
    voltage_V,
    delivered_A,
    irradiance_W_m2,
    *,
    series_cells=1,
    temperature_K=300.0,
    reference_irradiance_W_m2=1000.0,
    uncertainty_A=None,
)
```

Fit I0, per-cell ideality and Iph to dark/illuminated terminal data.

Ideality is constrained to 0.5..4 (an explicit model bound); Rs and shunt
leakage are fixed absent. At least two light levels and a forward-current
region are required. Supplied uncertainties weight current residuals.
Returned diagnostics are numerical fit metrics, not confidence intervals.
Horizontal uncertainty and parameter non-uniqueness need separate analysis.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/compact.py#L116)
