"""
opentcad.process.structure_transfer — carry a Structure's doping, contacts
and metadata onto the mesh produced after topography steps.

``topography_to_meshfield`` meshes the level-set stack and knows only
materials. ``run_recipe`` calls ``carry_structure`` on that mesh so a
recipe with deposit / etch / oxidize steps still yields a device the
solver can run. The rules:

* **Doping.** A node takes a layer's (or region's) doping only where that
  layer or region contains it *and* one of the node's cells still has the
  layer's material. Silicon left after an etch or oxidation keeps its
  doping; oxide grown where silicon was consumed, and deposited material,
  get none (rather than the old silicon's). Regions override layers (last
  region wins), as in ``Structure.to_meshfield``.
* **Contacts.** A ``top`` contact sits on the final top surface over its
  x-range (a deposit may now cover the layer it was declared on); a
  ``bottom`` contact on the wafer floor for the substrate, or on its
  layer's original bottom otherwise. If the material under a contact
  changed between semiconductor and insulator — an ohmic contact turned
  into a gate, or the reverse — a warning says so. The material found
  under each contact is recorded in ``metadata["contact_materials"]``.
* **Regions.** The topography engine stacks layers only, so a region's
  material override cannot apply there; a warning says so. Its doping
  still applies where its material matches.
"""
from __future__ import annotations

import warnings

import numpy as np

from opentcad.geometry.formats import (MATERIAL_NAMES, ContactTag, Material,
                                       MeshField, ProcessStep)

#: Materials treated as semiconductors when deciding whether a contact
#: changed electrical character (ohmic ↔ gate).
SEMICONDUCTORS = frozenset({Material.SI, Material.POLY_SI, Material.SIGE,
                            Material.GAN, Material.SIC, Material.SUBSTRATE})
_EPS = 1e-6     # µm: geometric tolerance for "contains"
_TOL = 1e-3     # µm: contact-node matching, as Structure uses


def _node_materials(mf: MeshField) -> list[set[int]]:
    tris = np.asarray(mf.grid.cells_dict[5], dtype=np.int64)
    mats = np.asarray(mf.material_ids)
    out: list[set[int]] = [set() for _ in range(mf.n_points)]
    for tri, m in zip(tris, mats):
        for n in tri:
            out[n].add(int(m))
    return out


def carry_structure(structure, mf: MeshField) -> MeshField:
    """Write ``structure``'s doping, contacts and metadata onto ``mf`` (the
    mesh of the processed topography) in place, and return it."""
    layers = list(structure.layers)
    y = 0.0
    spans = []
    for layer in layers:
        spans.append((layer, y, y + layer.thickness_um))
        y += layer.thickness_um
    total_height = y

    if structure.regions:
        warnings.warn(
            f"structure {structure.name!r}: regions ({', '.join(r.name for r in structure.regions)}) "
            f"do not change material on the topography path (the level-set stack has layers "
            f"only); their doping still applies where their material matches.", UserWarning,
            stacklevel=3)

    # ---- doping ---------------------------------------------------------------
    pts = np.asarray(mf.points, dtype=float)[:, :2]
    node_mats = _node_materials(mf)
    nd = np.zeros(mf.n_points)
    na = np.zeros(mf.n_points)
    for i, (x, yp) in enumerate(pts):
        present = node_mats[i]
        chosen = None
        for reg in reversed(structure.regions):          # last region wins
            if (int(reg.material) in present
                    and reg.x_start - _EPS <= x <= reg.x_end + _EPS
                    and reg.y_start - _EPS <= yp <= reg.y_end + _EPS):
                chosen = reg
                break
        if chosen is None:
            for layer, y0, y1 in spans:                  # lower layer wins ties
                if int(layer.material) in present and y0 - _EPS <= yp <= y1 + _EPS:
                    chosen = layer
                    break
        if chosen is not None:
            nd[i] = chosen.doping_Nd
            na[i] = chosen.doping_Na
    mf.Nd = nd
    mf.Na = na

    # ---- contacts -------------------------------------------------------------
    from opentcad.process.doping.implant import surface_height_function
    top_of = surface_height_function(mf)
    floor = float(mf.bounds[2])
    contacts, contact_materials = [], {}
    for cs in structure.contacts:
        span = next(((l, y0, y1) for l, y0, y1 in spans if l.name == cs.layer_name), None)
        if span is None:
            warnings.warn(f"Contact {cs.name!r}: unknown layer {cs.layer_name!r}",
                          UserWarning, stacklevel=3)
            continue
        layer, y0, _ = span
        in_x = (pts[:, 0] >= cs.x_start - _TOL) & (pts[:, 0] <= cs.x_end + _TOL)
        if cs.surface == "top":
            on = np.abs(pts[:, 1] - top_of(pts[:, 0])) < _TOL
        else:
            y_c = floor if layer is layers[0] else y0
            on = np.abs(pts[:, 1] - y_c) < _TOL
        node_ids = np.flatnonzero(in_x & on)
        if len(node_ids) == 0:
            warnings.warn(f"Contact {cs.name!r}: no mesh nodes on the {cs.surface} "
                          f"surface over x = [{cs.x_start:g}, {cs.x_end:g}] µm",
                          UserWarning, stacklevel=3)
            continue
        found = set().union(*(node_mats[n] for n in node_ids))
        found_mats = sorted((Material(m) for m in found), key=int)
        contact_materials[cs.name] = [MATERIAL_NAMES.get(m, m.name) for m in found_mats]
        declared_semi = layer.material in SEMICONDUCTORS
        if cs.surface == "top" and declared_semi != any(m in SEMICONDUCTORS for m in found_mats):
            was, now = ("semiconductor", "insulator") if declared_semi else ("insulator", "semiconductor")
            warnings.warn(
                f"Contact {cs.name!r} was declared on {layer.name!r} ({MATERIAL_NAMES.get(layer.material, layer.material.name)}, "
                f"{was}) but after the recipe the top surface there is "
                f"{', '.join(contact_materials[cs.name])} ({now}): it now behaves as "
                f"{'a gate on an insulator' if now == 'insulator' else 'a contact on a semiconductor'}.",
                UserWarning, stacklevel=3)
        contacts.append(ContactTag(cs.name, node_ids, cs.contact_type,
                                   cs.work_function_eV, cs.flat_band_shift_V))
    mf.contacts = contacts

    # ---- metadata ---------------------------------------------------------------
    mf.metadata.update({"structure_name": structure.name,
                        "width_um": structure.width_um,
                        "total_height_um": total_height,
                        "contact_materials": contact_materials})
    mf.process_history.insert(0, ProcessStep("structure_definition",
                                             parameters={"name": structure.name}))
    return mf
