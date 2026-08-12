# Known Issues, Caveats, and Follow-ups (through end of Phase 1)

Ranked list of things that work correctly in the regime we test them,
but are approximations, heuristics, or numerical artifacts. Each entry
gives the *current behavior*, the *regime where it breaks / becomes
inaccurate*, and the *proper fix* if we ever chase it.

Nothing on this list breaks the tests we ship; they're the honest limits
of the models under those tests. Consult before benchmarking against a
real fab process or extending into a new regime.

---

## Phase 1 — Topography

### 1.1  Numerical spikes at masked-etch mask corners
- **Current**: masked isotropic and directional etches use a
  discontinuous velocity field (`-rate` inside the window, `0`
  outside). Lax-Friedrichs numerical viscosity smears this
  discontinuity across ~2-3 grid cells at the sharp mask corner,
  leaving a small "pillar" of frozen LS values sticking up above the
  pristine surface at each edge.
- **Regime affected**: cosmetic only in raw LS plots. Extent scales
  with `grid_delta_um` (~15-25 nm at our default 5 nm grid). The mesh
  bridge silently keeps the lower y at multi-valued x, so meshed
  MeshFields ignore the spikes entirely.
- **Fix options**: (a) `tanh`-smoothed mask gate spanning 1-2 grid
  cells so `v(x)` is continuous; (b) upgrade to ViennaLS's Stencil
  Local Lax-Friedrichs scheme (`SpatialScheme=StencilLocalLaxFriedrichs`);
  (c) model the mask as its own level-set with boolean operations, so
  the corner is topologically enforced rather than numerically inferred.
- **Where noted in code**: `opentcad/process/topography/simulator.py`
  (`_MaskedIsotropicVelocity`, `_MaskedDirectionalVelocity`).

### 1.2  LOCOS bird's beak is a heuristic feathering, not a physics-derived shape
- **Current**: `Oxidize(window_x_um=..., bird_beak_length_um=L)`
  multiplies the Deal-Grove growth rate outside the window by
  `exp(-distance / L)`. `L` is a *user input*, not derived from any
  process condition.
- **Regime affected**: predictive LOCOS beak length as a function of
  temperature, time, pad-oxide thickness, and nitride stress. Our
  simulation gives the *visual* signature and correct 0.44:0.56 Si:SiO2
  ratio locally, but doesn't respond to varying any of the underlying
  process parameters.
- **Fix**: implement 2D coupled O2 diffusion PDE
  (`∂C/∂t = D ∇²C`) with `C = C_gas` at the exposed SiO2 surface and
  `C = 0` at the Si/SiO2 reaction front, coupled with Deal-Grove
  reaction kinetics at the moving interface. A first-order nitride
  mechanical model (elastic membrane lifting under the growing oxide)
  is the second-order refinement.
- **Where noted in code**: `oxidation.py` module docstring;
  `_apply_oxidize` / `_mask_factor` in `simulator.py`.

### 1.3  Multi-material etch uses one global rate — no selectivity
- **Current**: an etch step has a single global rate; when propagated
  through a multi-layer stack via `viennals.Advect.insertNextLevelSet`,
  both materials recede at the same rate.
- **Regime affected**: real RIE recipes have Si:SiO2 or SiN:SiO2
  rate ratios of 10:1 to 100:1. We cannot model "stop on oxide,"
  "stop on nitride," or any selectivity-driven flow.
- **Fix**: extend `_MaskedIsotropicVelocity` /
  `_MaskedDirectionalVelocity` to accept a per-material rate map,
  and use the `material` argument passed to `getScalarVelocity` (currently
  unused). Straightforward — the API is there, we just haven't wired
  a `Dict[Material, float]` through the DSL yet.

### 1.4  Directional etch — no sputter-yield angle dependence
- **Current**: rate scales with `max(0, -direction · normal)` — pure
  cosine model. Horizontal facets etch fastest, sidewalls freeze.
- **Regime affected**: real ion-etch sputter yield peaks at ~60° off
  normal (Sigmund/Yamamura theory), so profiles near a sloped facet
  are undercut relative to our prediction. Doesn't affect vertical-wall
  RIE trenches.
- **Fix**: replace `max(0, -d·n)` with a Sigmund yield function like
  `Y(θ) ∝ cos(θ) · [1 + β(1 - cos(θ)²)]` or a tabulated experimental
  yield curve.

### 1.5  No angled directional beam in DSL
- **Current**: `direction` parameter exists in the `Etch` dataclass but
  defaults to `(0, -1)`; no examples or tests exercise a non-vertical
  beam.
- **Regime affected**: ion-milling with an angled source, sidewall
  implants (though these belong to Phase 2 anyway).
- **Fix**: expose `direction` as a keyword in `Recipe.etch()`; verify
  the sputter cone comes out right. The math is already there.

### 1.6  Mesh bridge assumes single-valued top surfaces
- **Current**: `_polyline_to_y_of_x` collapses multi-valued x samples
  by keeping the *lower* y (dropping the overhang sliver above an
  undercut cavity).
- **Regime affected**: re-entrant profiles — deep isotropic etches
  with heavy undercut (radius > mask half-width), or complex etched
  cavities with overhanging lips. The physical LS is correct; the
  meshed MeshField loses the overhang.
- **Fix**: replace the y-of-x reduction with a proper polygon walker
  that traces each connected LS zero-crossing as a closed polygon,
  then triangulates the interior.
- **Where noted in code**: `mesh_bridge.py`, `_polyline_to_y_of_x`
  and above.

### 1.7  Deal-Grove — ultra-thin-oxide and stress corrections not modeled
- **Current**: Plummer/Deal linear-parabolic law for `<100>` Si at
  1 atm; matches Sze tables within ~30 % (the published-coefficient
  scatter).
- **Regime affected**:
  - Oxides < 20 nm at ≤ 900 °C: Massoud regime — real growth is
    faster than Deal-Grove predicts. We would overpredict the required
    oxidation time.
  - Non-`<100>` orientations: `<111>` grows ~1.6× faster, `<110>`
    ~1.4×. We don't offer an orientation parameter.
  - Chlorine ambients, high-pressure oxidation, water partial-pressure
    variations — all first-order effects in production, none modeled.
  - Nitride-mask stress modifying the oxide viscosity — coupled to
    the bird's beak issue above.
- **Fix**: publish an alternate `DealGroveArrhenius` block for the
  Massoud regime; add an `orientation` and `pressure_atm` kwarg to
  `Oxidize`. Straightforward extensions of the closed-form kinetics.

### 1.8  Oxidation applies to the top-most Si + adjacent SiO2 only
- **Current**: `_apply_oxidize` locates the top-most Si layer,
  optionally spawns a SiO2 layer above it, and grows there.
- **Regime affected**: SOI stacks (buried oxide under a Si film),
  polysilicon layers that would oxidize on top of an oxide, any
  device where you want to oxidize somewhere other than the "outer"
  Si surface.
- **Fix**: extend the Si-layer search to iterate all exposed Si
  interfaces; for each, insert or grow an adjacent SiO2 layer. Needs
  a "which surfaces are exposed to ambient" pre-pass through the
  stack.

### 1.9  ViennaPS process-model catalog is not wired up
- **Current**: we import `viennals` directly and reimplement the
  velocity fields we need in Python.
- **Regime affected**: everything ViennaPS offers as validated
  physics-based models — SF6O2Etching, MultiParticleProcess (for
  atomic-scale ion + neutral flux), FluorocarbonEtching, Faraday
  cage etching, IBE, TEOSDeposition, ALD kinetics. All wrappers
  we'd want long-term.
- **Fix**: wait for a working ViennaPS macOS wheel (the current
  4.6 wheel statically links VTK and duplicate-registers vtkCocoa
  classes, segfaulting when both packages load); when it arrives,
  plug ViennaPS `ProcessModel` instances into our `Recipe` — the
  boundaries (`Recipe` DSL, `TopographyState`, `mesh_bridge`) don't
  need to move.
- **Where noted in code**: `simulator.py` module docstring;
  `README.md` topography backend note.

---

## Phase 0 — Device Solver

### 0.1  Lombardi surface mobility uses proxy E_normal
- **Current**: `EField` magnitude via ViennaLS `edge_average_model` is
  fed as a stand-in for the interface-normal electric field. This is
  the *total* field magnitude, not the projection onto the interface
  normal.
- **Regime affected**: measured surface-mobility degradation
  underestimated — we see ~3 % at the Si/SiO2 interface where
  textbook values are 20-40 % under a strong inversion gate bias.
- **Fix**: compute a real element-based `E_normal` by identifying the
  interface elements, computing the local interface normal, and
  projecting the DEVSIM element `E` onto it. Requires a bit of mesh
  topology work in the DEVSIM bridge.
- **Where noted in code**: `models/mobility.py` (Lombardi class);
  earlier commit messages.

### 0.2  Q_f is a compact-model Vfb shift, not a physical interface charge
- **Current**: `flat_band_shift_V` on a metal-on-insulator contact
  packs Q_f, mid-gap D_it, and phi_MS into a single Vfb-offset number.
  The BC becomes `Potential = bias - flat_band_shift_V`.
- **Regime affected**: correct for integral device metrics (Vth, Ion,
  CV shape) — wrong for the local E-field profile at the Si/SiO2
  interface. Any analysis that needs the local field near the
  interface (surface generation, gate leakage, hot-carrier injection)
  will see the wrong number.
- **Fix**: attach a `SurfaceCharge` node model at the interface nodes
  with Q per unit area, and include it in the Poisson equation as a
  jump in `ε·E·n̂`. Requires a proper interface-node identification
  pass in the DEVSIM bridge.

### 0.3  Fermi-Dirac statistics — Blakemore approximation ceiling
- **Current**: `n_FD = n_boltz / (1 + ξ · n_boltz / N_c)` with
  ξ = 0.27.
- **Regime affected**: valid up to n ~ N_c / ξ ≈ 3.7 · N_c
  (~1.5e20 cm-3 in Si at 300 K). Beyond that, Blakemore saturates
  while true Fermi-Dirac keeps rising slowly.
- **Fix**: implement Joyce-Dixon inverse series expansion for the
  `F_{1/2}` integral to extend validity to arbitrary degeneracy. Only
  needed for source/drain regions above 1e20 cm-3.
- **Where noted in code**: `models/statistics.py` FermiDirac docstring.

### 0.4  No true small-signal AC / HF-CV
- **Current**: `cv_sweep()` is quasi-static (LF): sweep DC bias, at
  each point compute total semiconductor charge Q by integrating
  `q(p - n + Nd - Na) · NodeVolume`, take `dQ/dV` via
  `np.gradient`.
- **Regime affected**: LF CV — the inversion layer responds at every
  DC step, so C recovers to C_ox in inversion. Real HF-CV keeps the
  inversion layer frozen (~1 MHz > minority-carrier response) and C
  saturates at C_min instead. Our sweep cannot produce a HF-CV curve.
- **Fix**: wire DEVSIM's `circuit_add_node` / `circuit_solve_ac`
  machinery — apply a small AC perturbation at each DC bias, solve
  for `I_ac / (jω·V_ac)` = admittance, take `Im(Y) / ω` = capacitance.
  Substantial new code but a well-defined path.

### 0.5  Only steady-state and quasi-static analysis
- **Current**: `iv_sweep` (DC steady state) and `cv_sweep` (LF).
- **Regime affected**: transient switching (gate on/off, charge
  redistribution timescales), pulse-mode operation, SET/reset
  dynamics.
- **Fix**: use DEVSIM's `transient_dc()` / `transient_ac()`. Same
  discretization; you set a time step and integrate. Deferred with
  the AC work above.

### 0.6  No avalanche generation (breakdown)
- **Current**: recombination models cover SRH, Auger, Radiative — no
  generation term for impact ionization.
- **Regime affected**: breakdown voltage of pn junctions, hot-carrier
  reliability, snapback in MOS devices.
- **Fix**: add a `Recombination` subclass implementing van Overstraeten-
  de Man impact ionization coefficients:
  `α = a·exp(-b/|E|)` at high fields. Simple to slot in — one file
  under `models/`.

### 0.7  No density-gradient quantum correction
- **Current**: drift-diffusion + Poisson only.
- **Regime affected**: gate-length < 30 nm, inversion-layer quantum
  confinement, tunneling. Modern (7 nm, 3 nm) node devices really do
  need this.
- **Fix**: add a "quantum potential" equation of the form
  `V_q = -γ · (ℏ² / 12·m*·q) · ∇²√n / √n` to Poisson, coupled
  self-consistently. New Bohm-like PDE — real work, but a
  well-established recipe.

---

## Historical / documented

Present in older phases but *not* considered issues because their
resolution is a phase milestone rather than a fix. Listed here for
completeness.

- Analytic doping only (uniform / Gaussian profile specification) —
  will be replaced by simulated implant + diffusion in Phase 2.
- No process → device field interpolator invoked from `Recipe` — the
  topography path returns a `MeshField` with `material_id` but no
  doping. Phase 2 fills this in via the `bridge/` module.
