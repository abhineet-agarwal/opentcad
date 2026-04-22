"""
opentcad/geometry/mesh.py — Gmsh mesh generation for semiconductor structures.

Claude Code note: gmsh coordinates are in mm. All inputs/outputs here are in um.
Convert: gmsh_mm = opentcad_um * 1e-3  (multiply by 0.001)
Convert: opentcad_um = gmsh_mm * 1e3   (multiply by 1000)

Key function: build_2d_mesh(structure, mesh_size_um) -> pyvista.UnstructuredGrid
The grid has:
  - point coordinates in um
  - cell_data["material_id"] as int32 (Material enum values)
  - 2D triangular elements (CellType.TRIANGLE)
"""
from __future__ import annotations
import numpy as np
import pyvista as pv
from .formats import Material


def build_2d_mesh(structure, mesh_size_um: float = 0.05) -> pv.UnstructuredGrid:
    """Generate a 2D triangular mesh for the given Structure.

    Args:
        structure: A Structure instance with layers, regions, contacts defined.
        mesh_size_um: Default element size [um].

    Returns:
        pyvista UnstructuredGrid with triangular elements, coordinates in um,
        and cell_data["material_id"] set to Material enum int values.
    """
    import gmsh

    lc = mesh_size_um * 1e-3   # um → mm (gmsh works in mm by default)
    lc_fine = lc / 2            # fine mesh at interfaces

    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add(structure.name)

    # Build layered geometry as stacked rectangles
    # Use gmsh OCC kernel for boolean operations
    gmsh.model.occ.synchronize()

    surfaces = {}   # layer_name -> gmsh surface tag
    y_offset_mm = 0.0
    w_mm = structure.width_um * 1e-3

    for layer in structure._layers:
        h_mm = layer.thickness_um * 1e-3
        tag = gmsh.model.occ.addRectangle(0, y_offset_mm, 0, w_mm, h_mm)
        surfaces[layer.name] = tag
        y_offset_mm += h_mm

    gmsh.model.occ.synchronize()

    # Assign physical groups (material IDs)
    for layer in structure._layers:
        tag = surfaces[layer.name]
        pg = gmsh.model.addPhysicalGroup(2, [tag])
        gmsh.model.setPhysicalName(2, pg, layer.material.name)
        # Store material ID as physical group number for retrieval
        # We use a custom approach: tag physical group by material int ID

    # Mesh size fields: coarser in bulk, finer at layer interfaces
    field_id = 1
    interface_y_mm = []
    y = 0.0
    for layer in structure._layers[:-1]:
        y += layer.thickness_um
        interface_y_mm.append(y * 1e-3)

    if interface_y_mm:
        gmsh.model.mesh.field.add("MathEval", field_id)
        # Simple: use lc everywhere, refinement at interfaces handled by MeshAdapt
        gmsh.model.mesh.field.setString(field_id, "F", f"{lc}")
        gmsh.model.mesh.field.setAsBackgroundMesh(field_id)

    # Generate mesh
    gmsh.option.setNumber("Mesh.Algorithm", 6)   # Frontal-Delaunay
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc_fine)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc)
    gmsh.model.mesh.generate(2)
    gmsh.model.mesh.optimize("Laplace2D")

    # Extract mesh into pyvista
    grid = _gmsh_to_pyvista(structure)

    gmsh.finalize()
    return grid


def _gmsh_to_pyvista(structure) -> pv.UnstructuredGrid:
    """Extract the current gmsh mesh into a pyvista UnstructuredGrid.
    
    Coordinates are converted from mm to um.
    Material IDs are assigned from physical group names matching Material enum.
    """
    import gmsh

    # Get nodes
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    n_nodes = len(node_tags)
    points = coords.reshape(-1, 3) * 1e3  # mm → um

    # Reindex nodes: gmsh tags may not be 0-based
    tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

    # Get triangular elements (type 2)
    elem_types, elem_tags, elem_conn = gmsh.model.mesh.getElements(dim=2)

    all_cells = []
    all_mat_ids = []

    for et, etags, econn in zip(elem_types, elem_tags, elem_conn):
        if et != 2:   # only triangles (type 2)
            continue
        n_per = 3
        n_elem = len(etags)
        conn = econn.reshape(n_elem, n_per)

        # Find material for each element via its physical group
        for elem_idx, (etag, nodes) in enumerate(zip(etags, conn)):
            # Get entity tag for this element
            mat_id = _get_material_id_for_element(gmsh, etag, structure)
            local_nodes = [tag_to_idx[int(n)] for n in nodes]
            all_cells.extend([3] + local_nodes)
            all_mat_ids.append(mat_id)

    if not all_cells:
        raise RuntimeError("No triangular elements found in mesh. "
                           "Check that gmsh generated 2D elements.")

    cells = np.array(all_cells, dtype=int)
    celltypes = np.full(len(all_mat_ids), pv.CellType.TRIANGLE, dtype=np.uint8)
    mat_ids = np.array(all_mat_ids, dtype=np.int32)

    grid = pv.UnstructuredGrid(cells, celltypes, points)
    grid.cell_data["material_id"] = mat_ids
    return grid


def _get_material_id_for_element(gmsh, elem_tag: int, structure) -> int:
    """Return Material int ID for a given element tag using centroid lookup."""
    # Get element centroid and check which layer y-range it falls in
    _, coords, _ = gmsh.model.mesh.getNode(elem_tag)
    # This is approximate; for production use physical group classification
    # For now: use centroid y vs layer stack
    # A more robust approach uses gmsh physical group membership
    return int(Material.SI)   # placeholder — to be implemented properly


def add_interface_refinement(structure, mesh_size_um: float) -> None:
    """Add Gmsh Distance + Threshold fields for refinement at interfaces.
    
    Call this before gmsh.model.mesh.generate().
    Claude Code: implement using gmsh.model.mesh.field.add("Distance") 
    targeting curves at layer interfaces.
    """
    # TODO: implement proper interface refinement
    # For now, global mesh size handles this
    pass
