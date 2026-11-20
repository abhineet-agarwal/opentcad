# Physics models

Mobility, recombination, bandgap-narrowing and carrier-statistics models.

For an introduction, see the [user guide](../device_physics.md#physics-models). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.device.models`: `ConstantMobility`, `Klaassen`, `Canali`, `Lombardi`, `SRH`, `Auger`, `Radiative`, `Avalanche`, `NoBGN`, `Slotboom`, `Boltzmann`, `FermiDirac`, `JoyceDixon`.

## ConstantMobility

```python
class opentcad.device.models.ConstantMobility()
```

Constant mobility from MaterialParams.mobility_constant.

No doping or carrier dependence. This is the Phase 0 default and
reproduces the original DeviceSolver behavior exactly.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/mobility.py#L22)

## Klaassen

```python
class opentcad.device.models.Klaassen()
```

Klaassen unified low-field bulk mobility.

Reference: Klaassen, *A unified mobility model for device simulation*,
Solid-State Electronics 35, 953 (1992). The implementation follows
DEVSIM's reference Klaassen.py.

Captures:
  - lattice scattering (mu_L ~ T^-theta)
  - donor / acceptor ionized impurity scattering with clustering (Z_D, Z_A)
  - carrier–carrier scattering (mu_e_c, mu_h_c)
  - majority/minority partitioning via the F_P, G_P factors

Output edge models `ElectronMobilityEdge` / `HoleMobilityEdge` are
geometric means of node values; carrier derivatives are registered
so Newton on the continuity equations converges.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/mobility.py#L42)

## Canali

```python
class opentcad.device.models.Canali(
    base: Optional[MobilityModel] = None,
    driving_force: str = 'quasi_fermi',
    density_ref_cm3: float = 1e15,
)
```

Canali high-field velocity-saturation mobility (1975).

Wraps an underlying low-field bulk model:

```
mu_eff = mu_bulk / (1 + (mu_bulk*F / vsat)^beta)^(1/beta)
```

In the low-field limit mu_eff -> mu_bulk; at high driving force F the
drift velocity saturates at vsat regardless of mu_bulk. Reference:
Canali, Majni, Minder, Ottaviani, IEEE TED 22, 1045 (1975).

The driving force F on each mesh edge is one of:

* ``"quasi_fermi"`` (default): the gradient of the carrier's quasi-Fermi
  potential along the edge, phi_n = psi - V_t*ln(n/n_i) (the Boltzmann
  form). Only the field that drives the current counts: across an
  inversion layer the quasi-Fermi level is flat, so the gate field
  doesn't slow carriers moving along the channel.
* ``"efield"``: the electric field along the edge (the earlier
  default). On a mesh whose edges are not aligned with the current, oblique
  edges in a MOSFET channel pick up the vertical gate field, so
  saturation is overstated: in the SKY130 NMOS check Ion is 38 % low
  with it and 3.6 % low with ``"quasi_fermi"``.

For ``"quasi_fermi"`` both densities in the logarithm are offset by
``density_ref_cm3``. Where the carrier density is well above it the
force is the quasi-Fermi gradient; well below, it tends to the electric
field. Without the offset, minority carriers that drop by orders of
magnitude over the last mesh edge before an ohmic contact see a large
quasi-Fermi step there, and their diffusion is throttled (a forward p-n
diode's current halves). The offset is a numerical choice, not a
material parameter. In the Jacobian the force's density dependence is
left out (its potential dependence is kept): with it, Newton's first
update after a bias step diverges. The converged solution is unchanged.

In a uniform resistor the two forces are the same.

Composes with any MobilityModel:

```
Canali(base=Klaassen())       — full CMOS mobility
Canali(base=ConstantMobility()) — simple high-field
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/mobility.py#L166)

### Canali.requires_carriers

```python
property Canali.requires_carriers: bool
```

Returns True when the argument is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

## Lombardi

```python
class opentcad.device.models.Lombardi(
    base: Optional[MobilityModel] = None,
    e_normal_axis: str = 'y',
)
```

Lombardi surface mobility model.

Combines a bulk mobility with acoustic-phonon and surface-roughness
scattering via Matthiessen's rule:

```
1/mu_surf = 1/mu_bulk + 1/mu_ac + 1/mu_sr
```

where mu_ac and mu_sr depend on the normal field at the Si/SiO2
interface:

```
mu_ac(E_norm) = B/E_norm + C*NI^tau / (E_norm^(1/3) * (T/300)^kappa)
mu_sr(E_norm) = delta / E_norm^gamma
gamma        = A + alpha*(n+p) / NI^eta
```

NI = |Donors| + |Acceptors| is the total ionised impurity density.
Reference: Lombardi, Manzini, Saporito, Vanzi, IEEE TCAD 7, 1164 (1988).
The coefficients come from the material file's ``mobility_lombardi``
block (Si.yaml carries Darwish 1997's values, as in DEVSIM's Klaassen.py
``Philips_Surface_Mobility``); a file without the block is refused.

Composes with any bulk model. Typical MOS use:

```
Lombardi(base=Canali(base=Klaassen()))
```

E_normal selection via the ``e_normal_axis`` kwarg:
  * ``"y"`` (default) — use ``|Potential_grady|`` via DEVSIM

```
``vector_gradient``. This is the physical normal field for a
horizontal Si/SiO2 interface (the layered-DSL case), so it is
the right default for planar MOSFETs. Averaging node→edge
matches what ``Lb_NI`` already does.
```

  * ``"x"`` — use ``|Potential_gradx|`` for vertical-sidewall

```
interfaces (FinFET fin side, trench MOS).
```

  * ``"magnitude"`` — the earlier behavior: the edge ``EField``

```
magnitude, isotropic and independent of the interface
orientation. Use for comparison or for devices without a
well-defined interface normal.
```

Caveats:
  * The axis toggle is global per region — a device whose Si/SiO2

```
interface genuinely changes orientation (curved birds-beak,
45-degree sidewalls) still needs a per-element projection, which
requires element-aware models and is documented as follow-up.
```

  * ``Potential_grady`` depends on ``Potential`` only — its

```
derivative wrt ``Potential`` at each node is finite but
averaging to edges smooths out the step; Newton converges.
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/mobility.py#L316)

### Lombardi.requires_carriers

```python
property Lombardi.requires_carriers: bool
```

Returns True when the argument is true, False otherwise.
The builtins True and False are the only two instances of the class bool.
The class bool is a subclass of the class int, and cannot be subclassed.

## SRH

```python
class opentcad.device.models.SRH()
```

Shockley-Read-Hall recombination with a single mid-gap trap.

U_SRH = (n*p - n_i^2) / (tau_p*(n + n1) + tau_n*(p + p1))

Parameters tau_n_s, tau_p_s come from MaterialParams.recombination.
n1 = p1 = n_i for a mid-gap trap (Et = 0 in the YAML default).
`n_i_expr` is substituted for the bare n_i wherever BGN is active.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/recombination.py#L38)

## Auger

```python
class opentcad.device.models.Auger()
```

Auger recombination — three-particle process where the energy
released by an electron-hole recombination is given to a third
carrier instead of a photon.

U_Auger = (C_n*n + C_p*p) * (n*p - n_i^2)

Coefficients C_n, C_p for Si: Dziewior & Schmid, APL 31, 346 (1977).
Auger dominates over SRH for carrier densities > ~1e18 cm^-3, i.e.
in the n+ emitter / source-drain regions of bipolar and MOS devices.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/recombination.py#L65)

## Radiative

```python
class opentcad.device.models.Radiative()
```

Band-to-band radiative recombination.

U_rad = B * (n*p - n_i^2)

Coefficient B from MaterialParams.recombination.B_rad_cm3_per_s.
Negligible in indirect-gap Si (B ~ 1e-14 cm^3/s); dominant in direct-
gap GaAs/GaN (B ~ 1e-10).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/recombination.py#L94)

## Avalanche

```python
class opentcad.device.models.Avalanche()
```

Impact-ionisation generation (van Overstraeten-de Man, 1970).

Pair generation rate per unit volume is

```
G_avalanche = alpha_n(|E|) * |J_n|/q + alpha_p(|E|) * |J_p|/q
```

with Chynoweth-form ionisation coefficients:

```
alpha_s(|E|) = a_s * exp(-b_s / |E|)   for s ∈ {n, p}
```

We register this as a RecombinationModel with a NEGATIVE value (since
the sign convention is U = -q*(net recomb)); the solver then adds
the contribution to both ElectronSource and HoleSource via the
URec±URec slots that already handle generation terms (optical, etc.).

MVP approximations (Phase 2a — unblocks breakdown-voltage story,
does not calibrate exact Vbd):
  * Node-level |E| via DEVSIM's `vector_gradient(Potential)` — the

```
gradient magnitude of the Potential at each node. Sharper than
edge-averaging; coarser than an element-based projection.
```

  * Current magnitude via the saturation-velocity proxy

```
    |J_s| ≈ q · v_sat_s · carrier_density
This is CORRECT in the saturation-drift regime where avalanche
actually fires (fields of ~3–5e5 V/cm in Si where v_s → v_sat).
It OVERESTIMATES in the quasi-neutral bulk where n ≈ N_d and
alpha is near-zero — the alpha factor saves us there, since
exp(−b/|E|) with |E|≈0 is numerically zero. In the depletion
region it UNDERESTIMATES because n has dropped by orders. Net:
the model gets a knee at a higher Vbd than textbook (~2–3× too
high for Si at N_sub=1e17). Follow-up: replace proxy with the
real drift-diffusion |J_n|/|J_p| via edge/element-aware models.
```

  * Alpha derivatives w.r.t. Potential (through EMagAval) are

```
omitted from the Newton Jacobian — frozen-field each outer
iteration. Newton still converges; slower near the knee.
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/recombination.py#L116)

## NoBGN

```python
class opentcad.device.models.NoBGN()
```

No bandgap narrowing. n_i stays constant. Used as the default so
existing callers get identical behavior to Phase 0.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/bgn.py#L22)

## Slotboom

```python
class opentcad.device.models.Slotboom()
```

Slotboom empirical bandgap narrowing (1976, updated fit).

```
dEg(N) = E_ref * ( ln(N / N_ref)
                  + sqrt(ln(N / N_ref)^2 + 0.5) )   [eV]
```

where N is |NetDoping|, N_ref = 1e17 cm^-3, E_ref = 6.92 meV in the
updated del Alamo / Slotboom fit (Klaassen unified BGN gives similar
results). Below N_ref, dEg is essentially 0.

n_i_eff = n_i * exp(dEg / (2*V_t))

Reference: Slotboom & de Graaff, Solid-State Electron. 19, 857 (1976).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/bgn.py#L34)

## Boltzmann

```python
class opentcad.device.models.Boltzmann()
```

Boltzmann (Maxwell-Boltzmann) statistics — the Phase 0 default.

n = N_c * exp((E_F - E_c) / kT) — valid when E_F is at least a few
kT below E_c. Breaks down at doping > ~1e19 cm^-3 in Si where
degeneracy becomes important.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/statistics.py#L27)

## FermiDirac

```python
class opentcad.device.models.FermiDirac()
```

Fermi-Dirac statistics via the Blakemore approximation.

F_{1/2}(eta) ≈ 1 / (exp(-eta) + xi) with xi = 0.27 in the standard
Blakemore fit. Rearranging in terms of the Boltzmann-form n:

```
n_FD = n_boltz / (1 + xi * n_boltz / N_c)
```

Valid for n/N_c up to ~ 1/xi = 3.7 (Blakemore ceiling). Above this
the more accurate Joyce-Dixon inverse expansion is needed — noted
as follow-up.

Impact:
  - Light doping (n << N_c): reduces to Boltzmann (n_FD ≈ n_boltz).
  - Heavy doping (n ~ N_c): softens the exp() growth of n vs. E_F,

```
so the built-in potential and Vth extraction shift by 10-100 mV
compared to Boltzmann.
```

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/statistics.py#L44)

## JoyceDixon

```python
class opentcad.device.models.JoyceDixon()
```

Joyce-Dixon series inverse of F_{1/2} for heavy-doping statistics.

The Blakemore approximation that the parent FermiDirac class uses
saturates (and the inverse's log denominator vanishes) at n = N_c/ξ
≈ 3.7·N_c — making it unreliable for S/D wells doped above ~1e20
cm⁻³ in Si. Joyce & Dixon (APL 31, 354, 1977) derived an explicit
series for the inverse Fermi-Dirac integral:

```
η(u) = ln(u) + a_1·u + a_2·u² + a_3·u³ + a_4·u⁴ + …
```

with a_1 = 1/√8 ≈ 0.3536, a_2 ≈ -4.950e-3, a_3 ≈ 1.483e-4,
a_4 ≈ -4.426e-6. The first two terms are accurate to <1 % for
u ≤ 10 (i.e., n ≤ ~3e20 in Si at 300 K).

What this class changes vs. the parent FermiDirac:
  * `electron_potential_offset` and `hole_potential_offset` are

```
replaced by the explicit Joyce-Dixon form. No more Blakemore
ceiling in the ohmic-contact BC: as n/N_c grows past 4 the
parent's `log(n / (n_i*(1 - ξn/Nc)))` floors at 1e-3 and loses
physical meaning; this form keeps running.
```

  * `wrap_electron_density` / `wrap_hole_density` keep the Blakemore

```
forward expressions. Replacing those symbolically with a true
F_{1/2} inverse-of-inverse isn't straightforwardly expressible
in DEVSIM's symbolic engine, and the forward form matters less
in practice since Newton iterates in the carrier variables.
```

Use case: this is the right class to pick for Si sources/drains at
1e20+ doping where Blakemore distorts the contact BC noticeably.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/device/models/statistics.py#L99)
