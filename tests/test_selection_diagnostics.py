import numpy as np

from scaffold_feb.examples import cube
from scaffold_feb.geometry import clean_mesh
from scaffold_feb.model import Mesh,CellBlock
from scaffold_feb.pipeline import Prepared
from scaffold_feb.surfaces import extract_boundary,select_surfaces


def test_selection_warns_for_sidewall_band_without_changing_mesh():
    points = cube().points
    lower = points * [1,1,0.02]
    upper = points * [1,1,0.98] + [0,0,0.02]
    mesh = clean_mesh(Mesh(np.vstack((lower,upper)),[
        CellBlock('hex8',np.arange(16).reshape(2,8))]))
    boundary = extract_boundary(mesh)
    original_warnings = mesh.warnings.copy()
    selected,axis,tol = select_surfaces(mesh,boundary,'cylinder','z',0.05)
    result = Prepared(mesh,boundary,selected,axis,tol)
    summary = result.summary()
    assert summary['superficies']['inferior']['caras'] == 5
    assert summary['superficies']['inferior']['bounding_box_m'][1][2] == 0.02
    assert any('paredes laterales' in text for text in summary['advertencias'])
    assert mesh.warnings == original_warnings
    assert result.summary() == summary
    selected,axis,tol = select_surfaces(mesh,boundary,'cylinder','z',0.002)
    summary = Prepared(mesh,boundary,selected,axis,tol).summary()
    assert summary['superficies']['inferior']['caras'] == 1
    assert summary['advertencias'] == original_warnings
