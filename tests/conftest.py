"""Shared pytest fixtures for OpenTCAD tests."""
import numpy as np
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "requires_devsim: requires devsim installed")
    config.addinivalue_line("markers", "requires_viennaps: requires ViennaPS installed")
    config.addinivalue_line("markers", "integration: full pipeline integration tests")

@pytest.fixture
def simple_si_meshfield():
    import pyvista as pv
    from opentcad.geometry.formats import Material, MeshField
    pts = np.array([[0,0,0],[1,0,0],[.5,1,0],[.5,.5,1]], dtype=float)
    cells = np.array([4,0,1,2,3])
    ct = np.array([pv.CellType.TETRA])
    grid = pv.UnstructuredGrid(cells, ct, pts)
    grid.cell_data["material_id"] = np.array([int(Material.SI)], dtype=np.int32)
    return MeshField(grid=grid)
