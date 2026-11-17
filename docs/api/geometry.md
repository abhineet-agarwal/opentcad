# Geometry and the MeshField

Describe a 2-D cross-section, mesh it, and the MeshField every layer passes.

For an introduction, see the [user guide](../concepts.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.geometry.structure`: `Structure`, `LayerSpec`, `RegionSpec`, `ContactSpec`.

## Structure

```python
class opentcad.geometry.structure.Structure(width_um: float, name: str = 'structure')
```

Semiconductor device structure builder (DSL).

Coordinate system: x=horizontal [0..width_um], y=vertical [0..total_height].
All coordinates in micrometers.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/structure.py#L63)

### Structure.add_substrate

```python
Structure.add_substrate(
    name: str,
    thickness_um: float,
    material: Material = Material.SI,
    doping_Na: float = 0.0,
    doping_Nd: float = 0.0,
) -> Structure
```

Add the bottommost substrate layer. Must be called before add_layer().

### Structure.add_layer

```python
Structure.add_layer(
    name: str,
    thickness_um: float,
    material: Material,
    doping_Na: float = 0.0,
    doping_Nd: float = 0.0,
) -> Structure
```

Add a layer on top of the stack.

### Structure.add_region

```python
Structure.add_region(
    name: str,
    x_start: float,
    x_end: float,
    y_start: float,
    y_end: float,
    material: Material,
    doping_Na: float = 0.0,
    doping_Nd: float = 0.0,
) -> Structure
```

Override material in a rectangular region. Later calls take precedence.

### Structure.add_contact

```python
Structure.add_contact(
    name: str,
    x_start: float,
    x_end: float,
    layer_name: str,
    surface: str = 'top',
    contact_type: str = 'ohmic',
    work_function_eV: Optional[float] = None,
    flat_band_shift_V: float = 0.0,
) -> Structure
```

Define a named electrical contact on a layer surface.

`flat_band_shift_V` applies only to metal-on-insulator contacts
(typically the gate on an oxide). It packs fixed oxide charge Qf,
midgap Dit-driven Vfb offset, and metal-semi work-function
differences into a single compact-model number so a MOS-cap or
MOSFET can hit a target Vth without invoking the full interface-
Poisson surface-charge machinery.

### Structure.layers

```python
property Structure.layers: tuple[LayerSpec, ...]
```

Layers bottom-first (the first is the substrate). Read-only view.

### Structure.regions

```python
property Structure.regions: tuple[RegionSpec, ...]
```

Region overrides in the order applied. Read-only view.

### Structure.contacts

```python
property Structure.contacts: tuple[ContactSpec, ...]
```

Contacts in definition order. Read-only view.

### Structure.total_height_um

```python
property Structure.total_height_um: float
```

Sum of the layer thicknesses [um].

### Structure.to_meshfield

```python
Structure.to_meshfield(mesh_size_um: float = 0.05) -> MeshField
```

Generate mesh and return a MeshField. This is the DSL exit point.

**Parameters**

- `mesh_size_um`: Default element size [um]. Automatically refined at material interfaces to mesh_size_um / 2.

**Returns**

MeshField with material tags, doping from layer/region specs, and contacts.

## LayerSpec

```python
class opentcad.geometry.structure.LayerSpec(
    name: str,
    thickness_um: float,
    material: Material,
    doping_Na: float = 0.0,
    doping_Nd: float = 0.0,
    y_bottom: float = 0.0,
) -> None
```

One layer of a Structure's stack: uniform material and doping
[cm^-3] over the full width. ``y_bottom`` [um] is filled in as the
stack is built.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/structure.py#L25)

## RegionSpec

```python
class opentcad.geometry.structure.RegionSpec(
    name: str,
    x_start: float,
    x_end: float,
    y_start: float,
    y_end: float,
    material: Material,
    doping_Na: float = 0.0,
    doping_Nd: float = 0.0,
) -> None
```

Rectangular sub-region overriding layer material/doping.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/structure.py#L38)

## ContactSpec

```python
class opentcad.geometry.structure.ContactSpec(
    name: str,
    x_start: float,
    x_end: float,
    layer_name: str,
    surface: str = 'top',
    contact_type: str = 'ohmic',
    work_function_eV: Optional[float] = None,
    flat_band_shift_V: float = 0.0,
) -> None
```

A contact declared on a Structure: an x-span [um] on the ``"top"``
or ``"bottom"`` surface of layer ``layer_name``. The other fields are
copied to the meshed ``ContactTag``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/structure.py#L49)

Import from `opentcad.geometry.formats`: `MeshField`, `ContactTag`, `ProcessStep`, `Material`, `MATERIAL_NAMES`, `MESHFIELD_FORMAT`.

## MeshField

```python
class opentcad.geometry.formats.MeshField(
    grid: pv.UnstructuredGrid,
    contacts: list[ContactTag] = list(),
    process_history: list[ProcessStep] = list(),
    metadata: dict = dict(),
) -> None
```

Central interchange object. Wraps pyvista UnstructuredGrid + semiconductor fields.

grid cell_data must have 'material_id' (int32, Material enum values).
grid point_data may have 'Nd', 'Na' (float64, cm^-3).
grid point_data may also have per-species dopant fields 'C_&lt;species>'
(float64, cm^-3, e.g. 'C_boron'). Nd / Na stay the totals the device
solver reads; process steps that track a species keep
Nd = untracked + sum(donor species) and likewise for Na. Doping set
directly through Nd / Na (e.g. by the Structure DSL) is "untracked".

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/formats.py#L86)

### MeshField.n_points

```python
property MeshField.n_points
```

Number of mesh nodes.

### MeshField.n_cells

```python
property MeshField.n_cells
```

Number of mesh cells (triangles).

### MeshField.points

```python
property MeshField.points
```

Node coordinates [um], shape (n_points, 3); z is 0.

### MeshField.bounds

```python
property MeshField.bounds
```

(x_min, x_max, y_min, y_max, z_min, z_max) [um].

### MeshField.material_ids

```python
property MeshField.material_ids
```

``Material`` value of each cell, shape (n_cells,).

### MeshField.get_cells_for_material

```python
MeshField.get_cells_for_material(material: Material) -> np.ndarray
```

Indices of the cells made of ``material``.

### MeshField.has_doping

```python
property MeshField.has_doping
```

True if both ``Nd`` and ``Na`` fields are present.

### MeshField.Nd

```python
property MeshField.Nd: np.ndarray
```

Donor concentration [cm^-3], shape (n_points,).

### MeshField.Na

```python
property MeshField.Na: np.ndarray
```

Acceptor concentration [cm^-3], shape (n_points,).

### MeshField.net_doping

```python
property MeshField.net_doping
```

Nd − Na [cm^-3] at each node: positive where n-type.

### MeshField.species_names

```python
MeshField.species_names() -> list[str]
```

Dopant species with a tracked 'C_&lt;species>' field, sorted.

### MeshField.get_species

```python
MeshField.get_species(name: str) -> np.ndarray
```

Concentration of one tracked species [cm^-3]; zeros if untracked.

### MeshField.set_species

```python
MeshField.set_species(name: str, values: np.ndarray)
```

Write one species field. Does NOT touch Nd / Na — callers own that sum.

### MeshField.get_contact

```python
MeshField.get_contact(name: str) -> ContactTag
```

The contact called ``name``. Raises KeyError, listing the
contacts that exist, if there is none.

### MeshField.add_contact

```python
MeshField.add_contact(contact: ContactTag)
```

Add ``contact``, replacing any existing contact of the same name.

### MeshField.save

```python
MeshField.save(path: str | Path)
```

Write the mesh to ``&lt;path>.vtu`` and everything else (contacts,
process history, metadata, ``meshfield_format``) to ``&lt;path>.json``.
Parent folders are created. ``load`` reads both back unchanged.

### MeshField.load

```python
classmethod MeshField.load(path: str | Path) -> MeshField
```

Read a MeshField written by ``save`` (the ``.vtu`` and ``.json``
pair). Files from before ``meshfield_format`` existed still load;
a newer format than this version understands raises ValueError.

### MeshField.summary

```python
MeshField.summary() -> str
```

A short text description: size, bounds, cells per material,
peak Nd / Na (and per tracked species) and contact names.

## ContactTag

```python
class opentcad.geometry.formats.ContactTag(
    name: str,
    boundary_nodes: np.ndarray,
    contact_type: str = 'ohmic',
    work_function_eV: Optional[float] = None,
    flat_band_shift_V: float = 0.0,
) -> None
```

A named electrical contact on a MeshField.

``boundary_nodes`` are the mesh node indices the contact covers.
``contact_type`` is ``"ohmic"`` or ``"schottky"`` (which needs
``work_function_eV``); a contact on an insulator acts as a metal gate,
and ``flat_band_shift_V`` then offsets its potential (see below).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/formats.py#L30)

## ProcessStep

```python
class opentcad.geometry.formats.ProcessStep(
    step_type: str,
    species: Optional[str] = None,
    parameters: dict = dict(),
) -> None
```

One entry of a MeshField's process history: what was done
(``step_type``, e.g. ``"implant"``), to which dopant ``species`` if
any, and the step's ``parameters``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/formats.py#L73)

## Material

```python
class opentcad.geometry.formats.Material(IntEnum)
```

Region materials. The integer value is what a MeshField stores as
``material_id``; ``MATERIAL_NAMES`` gives the display name used to look
up material parameters (e.g. ``"Silicon"``). A material needs a
parameter file before the device solver can use it.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/geometry/formats.py#L15)

| Member | Value |
|---|---|
| `VACUUM` | `0` |
| `SI` | `1` |
| `SIO2` | `2` |
| `SI3N4` | `3` |
| `POLY_SI` | `4` |
| `AL` | `5` |
| `PHOTORESIST` | `6` |
| `SIGE` | `7` |
| `GAN` | `8` |
| `SIC` | `9` |
| `SUBSTRATE` | `10` |

## MATERIAL_NAMES

```python
opentcad.geometry.formats.MATERIAL_NAMES = {<Material.SI: 1>: 'Silicon', <Material.SIO2: 2>: 'SiO2', <Material.SI3N4: 3>: 'Si3N4', <Material.POLY_SI: 4>: 'PolySi', <Material.AL: 5>: 'Aluminum', <Material.PHOTORESIST: 6>: 'Photoresist', <Material.SIGE: 7>: 'SiGe', <Material.GAN: 8>: 'GaN', <Material.SIC: 9>: 'SiC', <Material.SUBSTRATE: 10>: 'Substrate'}
```

## MESHFIELD_FORMAT

```python
opentcad.geometry.formats.MESHFIELD_FORMAT = 1
```
