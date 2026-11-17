"""
opentcad/geometry/formats.py — Central MeshField data format.
Units: spatial=um, concentration=cm^-3, temperature=K, energy=eV
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional
import numpy as np
import pyvista as pv


class Material(IntEnum):
    """Region materials. The integer value is what a MeshField stores as
    ``material_id``; ``MATERIAL_NAMES`` gives the display name used to look
    up material parameters (e.g. ``"Silicon"``). A material needs a
    parameter file before the device solver can use it."""
    VACUUM=0; SI=1; SIO2=2; SI3N4=3; POLY_SI=4; AL=5
    PHOTORESIST=6; SIGE=7; GAN=8; SIC=9; SUBSTRATE=10

MATERIAL_NAMES = {
    Material.SI:"Silicon", Material.SIO2:"SiO2", Material.SI3N4:"Si3N4",
    Material.POLY_SI:"PolySi", Material.AL:"Aluminum",
    Material.PHOTORESIST:"Photoresist", Material.SIGE:"SiGe",
    Material.GAN:"GaN", Material.SIC:"SiC", Material.SUBSTRATE:"Substrate",
}

@dataclass
class ContactTag:
    """A named electrical contact on a MeshField.

    ``boundary_nodes`` are the mesh node indices the contact covers.
    ``contact_type`` is ``"ohmic"`` or ``"schottky"`` (which needs
    ``work_function_eV``); a contact on an insulator acts as a metal gate,
    and ``flat_band_shift_V`` then offsets its potential (see below)."""
    name: str
    boundary_nodes: np.ndarray
    contact_type: str = "ohmic"
    work_function_eV: Optional[float] = None
    #: Metal-on-insulator flat-band shift [V] — used to encode fixed oxide
    #: charge Qf, midgap Dit-driven Vfb offset, and metal-semi work-function
    #: differences on a gate contact in one compact-model number:
    #:     Vfb_eff = -Qf/Cox - q*Dit*(Emidgap-Ef_ref)/Cox + phi_MS.
    #: When set, the metal-on-insulator BC is Potential = bias - flat_band_shift_V.
    flat_band_shift_V: float = 0.0

#: Version of the MeshField .json sidecar written by ``MeshField.save``.
#: 1 adds every ContactTag field (flat_band_shift_V was dropped before).
MESHFIELD_FORMAT = 1


def _contact_to_json(c: "ContactTag") -> dict:
    from dataclasses import fields as _fields
    out = {}
    for f in _fields(c):
        v = getattr(c, f.name)
        out[f.name] = np.asarray(v).tolist() if f.name == "boundary_nodes" else v
    return out


def _contact_from_json(d: dict) -> "ContactTag":
    from dataclasses import fields as _fields
    known = {f.name for f in _fields(ContactTag)}
    unknown = set(d) - known
    if unknown:
        raise ValueError(f"contact {d.get('name')!r} has unknown fields {sorted(unknown)}")
    kw = {k: v for k, v in d.items() if k != "boundary_nodes"}
    return ContactTag(boundary_nodes=np.array(d["boundary_nodes"], dtype=int), **kw)


@dataclass
class ProcessStep:
    """One entry of a MeshField's process history: what was done
    (``step_type``, e.g. ``"implant"``), to which dopant ``species`` if
    any, and the step's ``parameters``."""
    step_type: str
    species: Optional[str] = None
    parameters: dict = field(default_factory=dict)

#: point_data key prefix for per-species dopant concentrations [cm^-3].
SPECIES_PREFIX = "C_"


@dataclass
class MeshField:
    """Central interchange object. Wraps pyvista UnstructuredGrid + semiconductor fields.

    grid cell_data must have 'material_id' (int32, Material enum values).
    grid point_data may have 'Nd', 'Na' (float64, cm^-3).
    grid point_data may also have per-species dopant fields 'C_<species>'
    (float64, cm^-3, e.g. 'C_boron'). Nd / Na stay the totals the device
    solver reads; process steps that track a species keep
    Nd = untracked + sum(donor species) and likewise for Na. Doping set
    directly through Nd / Na (e.g. by the Structure DSL) is "untracked".
    """
    grid: pv.UnstructuredGrid
    contacts: list[ContactTag] = field(default_factory=list)
    process_history: list[ProcessStep] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if "material_id" not in self.grid.cell_data:
            raise ValueError("MeshField grid must have 'material_id' cell data.")

    @property
    def n_points(self):
        """Number of mesh nodes."""
        return self.grid.n_points

    @property
    def n_cells(self):
        """Number of mesh cells (triangles)."""
        return self.grid.n_cells

    @property
    def points(self):
        """Node coordinates [um], shape (n_points, 3); z is 0."""
        return self.grid.points

    @property
    def bounds(self):
        """(x_min, x_max, y_min, y_max, z_min, z_max) [um]."""
        return self.grid.bounds

    @property
    def material_ids(self):
        """``Material`` value of each cell, shape (n_cells,)."""
        return self.grid.cell_data["material_id"]

    def get_cells_for_material(self, material: Material) -> np.ndarray:
        """Indices of the cells made of ``material``."""
        return np.where(self.material_ids == int(material))[0]

    @property
    def has_doping(self):
        """True if both ``Nd`` and ``Na`` fields are present."""
        return "Nd" in self.grid.point_data and "Na" in self.grid.point_data

    @property
    def Nd(self) -> np.ndarray:
        """Donor concentration [cm^-3], shape (n_points,)."""
        return self.grid.point_data.get("Nd", np.zeros(self.n_points))

    @Nd.setter
    def Nd(self, values: np.ndarray):
        assert values.shape == (self.n_points,), f"Shape mismatch: {values.shape} vs ({self.n_points},)"
        assert np.all(values >= 0), "Donor concentration must be non-negative"
        self.grid.point_data["Nd"] = values.astype(np.float64)

    @property
    def Na(self) -> np.ndarray:
        """Acceptor concentration [cm^-3], shape (n_points,)."""
        return self.grid.point_data.get("Na", np.zeros(self.n_points))

    @Na.setter
    def Na(self, values: np.ndarray):
        assert values.shape == (self.n_points,), f"Shape mismatch: {values.shape} vs ({self.n_points},)"
        assert np.all(values >= 0), "Acceptor concentration must be non-negative"
        self.grid.point_data["Na"] = values.astype(np.float64)

    @property
    def net_doping(self):
        """Nd − Na [cm^-3] at each node: positive where n-type."""
        return self.Nd - self.Na

    def species_names(self) -> list[str]:
        """Dopant species with a tracked 'C_<species>' field, sorted."""
        n = len(SPECIES_PREFIX)
        return sorted(k[n:] for k in self.grid.point_data.keys()
                      if k.startswith(SPECIES_PREFIX))

    def get_species(self, name: str) -> np.ndarray:
        """Concentration of one tracked species [cm^-3]; zeros if untracked."""
        return self.grid.point_data.get(SPECIES_PREFIX + name, np.zeros(self.n_points))

    def set_species(self, name: str, values: np.ndarray):
        """Write one species field. Does NOT touch Nd / Na — callers own that sum."""
        values = np.asarray(values)
        assert values.shape == (self.n_points,), f"Shape mismatch: {values.shape} vs ({self.n_points},)"
        assert np.all(values >= 0), f"Concentration of {name} must be non-negative"
        self.grid.point_data[SPECIES_PREFIX + name] = values.astype(np.float64)

    def get_contact(self, name: str) -> ContactTag:
        """The contact called ``name``. Raises KeyError, listing the
        contacts that exist, if there is none."""
        for c in self.contacts:
            if c.name == name: return c
        raise KeyError(f"Contact '{name}' not found. Available: {[c.name for c in self.contacts]}")

    def add_contact(self, contact: ContactTag):
        """Add ``contact``, replacing any existing contact of the same name."""
        self.contacts = [c for c in self.contacts if c.name != contact.name]
        self.contacts.append(contact)

    def save(self, path: str | Path):
        """Write the mesh to ``<path>.vtu`` and everything else (contacts,
        process history, metadata, ``meshfield_format``) to ``<path>.json``.
        Parent folders are created. ``load`` reads both back unchanged."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.grid.save(str(path.with_suffix(".vtu")))
        # Every ContactTag field is written, so a field added later can't be
        # dropped silently (flat_band_shift_V once was).
        meta = {
            "meshfield_format": MESHFIELD_FORMAT,
            "contacts": [_contact_to_json(c) for c in self.contacts],
            "process_history": [{"step_type": s.step_type, "species": s.species,
                                  "parameters": s.parameters} for s in self.process_history],
            "metadata": self.metadata,
        }
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "MeshField":
        """Read a MeshField written by ``save`` (the ``.vtu`` and ``.json``
        pair). Files from before ``meshfield_format`` existed still load;
        a newer format than this version understands raises ValueError."""
        path = Path(path)
        grid = pv.read(str(path.with_suffix(".vtu")))
        meta = json.loads(path.with_suffix(".json").read_text())
        version = meta.get("meshfield_format", 0)       # 0: files written before versioning
        if version > MESHFIELD_FORMAT:
            raise ValueError(f"{path.with_suffix('.json')} uses MeshField format {version}; "
                             f"this OpenTCAD reads up to {MESHFIELD_FORMAT}")
        contacts = [_contact_from_json(c) for c in meta["contacts"]]
        history = [ProcessStep(step_type=s["step_type"], species=s.get("species"),
                               parameters=s.get("parameters", {})) for s in meta["process_history"]]
        return cls(grid=grid, contacts=contacts, process_history=history,
                   metadata=meta.get("metadata", {}))

    def summary(self) -> str:
        """A short text description: size, bounds, cells per material,
        peak Nd / Na (and per tracked species) and contact names."""
        lines = [f"MeshField: {self.n_points} points, {self.n_cells} cells",
                 f"  Bounds [um]: x=[{self.bounds[0]:.3f},{self.bounds[1]:.3f}] "
                 f"y=[{self.bounds[2]:.3f},{self.bounds[3]:.3f}]"]
        mat_counts = {}
        for mid in self.material_ids:
            mat_counts[mid] = mat_counts.get(mid, 0) + 1
        lines.append("  Materials:")
        for mid, count in sorted(mat_counts.items()):
            try: name = MATERIAL_NAMES.get(Material(mid), Material(mid).name)
            except ValueError: name = f"UNKNOWN({mid})"
            lines.append(f"    {name}: {count} cells")
        if self.has_doping:
            lines.append(f"  Doping: Nd_max={self.Nd.max():.2e}, Na_max={self.Na.max():.2e} [cm^-3]")
        for s in self.species_names():
            lines.append(f"    {s}: max={self.get_species(s).max():.2e} [cm^-3]")
        if self.contacts:
            lines.append(f"  Contacts: {[c.name for c in self.contacts]}")
        return "\n".join(lines)

    def __repr__(self):
        return f"MeshField(n_points={self.n_points}, n_cells={self.n_cells}, contacts={[c.name for c in self.contacts]})"
