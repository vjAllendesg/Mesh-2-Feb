from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from scaffold_feb.examples import cylinder,cube
from scaffold_feb.geometry import clean_mesh
from scaffold_feb.materials import load_catalog,defaults
from scaffold_feb.model import Mesh,CellBlock,MeshError
from scaffold_feb.simulations import SIMULATION_KEY,build_simulation
from scaffold_feb.surfaces import extract_boundary,select_surfaces
from scaffold_feb.writer import build_document,write_feb


def fixture(axis=2,scale=1):
    mesh=cylinder()
    mesh.points *= scale
    mesh.points[:,[axis,2]]=mesh.points[:,[2,axis]]
    clean_mesh(mesh)
    surfaces,_,_=select_surfaces(mesh,extract_boundary(mesh),'cylinder','xyz'[axis])
    return mesh,surfaces


@pytest.mark.parametrize('axis',[0,1,2])
def test_axis_bindings_material_and_absolute_displacement(axis):
    mesh,surfaces=fixture(axis,2)
    model=load_catalog()['isotropic elastic']; values=defaults(model); values['E']=723
    root=build_document(mesh,surfaces,model,values,simulation=SIMULATION_KEY,simulation_axis='xyz'[axis]).getroot()
    assert root.find('Material/material').get('type')=='isotropic elastic'
    assert root.findtext('Material/material/E')=='723'
    assert root.find('Material/material/elastic') is None
    names={s.get('name') for s in root.findall('Mesh/NodeSet')}
    face_names={s.get('name') for s in root.findall('Mesh/Surface')}
    for bc in root.iter('bc'):
        target=bc.get('node_set')
        if target.startswith('@surface:'): assert target.removeprefix('@surface:') in face_names
        else: assert target in names
    for bc in root.findall("Step/step/Boundary/bc[@type='prescribed displacement']"):
        assert bc.findtext('dof')=='xyz'[axis]
        assert float(bc.findtext('value'))==-0.1
        assert bc.get('node_set')=='@surface:superior'
    for bc in root.findall(".//bc[@node_set='sim_guia_superior']"):
        assert [bc.findtext(f'{d}_dof') for d in 'xyz']==['0' if i==axis else '1' for i in range(3)]
    anchors=[int(root.findtext(f"Mesh/NodeSet[@name='{name}']"))-1 for name in ('sim_apoyo_inferior','sim_guia_superior')]
    assert anchors[0] in surfaces[0].nodes and anchors[1] in surfaces[1].nodes
    transverse=[i for i in range(3) if i!=axis]
    assert np.linalg.norm(mesh.points[anchors[0],transverse]-mesh.points[anchors[1],transverse])>0
    assert all(entry.get('data')=='R'+'xyz'[axis] for entry in root.findall('Output/logfile/node_data'))
    assert all(entry.get('data')=='s'+'xyz'[axis] for entry in root.findall('Output/logfile/element_data'))


def signature(element):
    return (element.tag,element.attrib,(element.text or '').strip(),[signature(child) for child in element])


def test_protocol_is_identical_to_reference_and_log_selections_are_scoped():
    mesh,surfaces=fixture()
    blocks,sets=build_simulation(mesh,surfaces,'z','my_model')
    reference=ET.parse(Path(__file__).resolve().parents[1]/'reference/ejemplo.feb').getroot()
    assert signature(blocks['LoadData'])==signature(reference.find('LoadData'))
    for actual,expected in zip(blocks['Step'],reference.findall('Step/step')):
        assert signature(actual.find('Control'))==signature(expected.find('Control'))
    assert [int(s.findtext('Control/time_steps')) for s in blocks['Step']]==[100,700]
    assert [s.findtext('Control/step_size') for s in blocks['Step']]==['0.01','0.01']
    assert 'Material' not in blocks
    for entry in blocks['Output'].find('logfile'):
        surface=surfaces[0] if '_inf.' in entry.get('file') else surfaces[1]
        expected=surface.nodes if entry.tag=='node_data' else sorted({f.owner for f in surface.faces})
        assert list(map(int,entry.text.split(',')))==[n+1 for n in expected]
        assert entry.get('file').startswith('my_model_')


def test_missing_caps_short_height_and_disconnected_mesh_are_rejected():
    mesh,surfaces=fixture()
    with pytest.raises(MeshError,match='ambas tapas'): build_simulation(mesh,surfaces[:1])
    short,ss=fixture(scale=.05)
    with pytest.raises(MeshError,match='0.1 m'): build_simulation(short,ss)
    other=mesh.points+[4,0,0]
    n=len(mesh.points)
    disconnected=Mesh(np.vstack([mesh.points,other]),[CellBlock('tet4',np.vstack([mesh.blocks[0].data,mesh.blocks[0].data+n]))])
    with pytest.raises(MeshError,match='pieza conectada'): build_simulation(disconnected,surfaces)


@pytest.mark.parametrize('material',['isotropic elastic','neo-Hookean','Mooney-Rivlin'])
def test_simulation_uses_selected_material_and_geometry_only_is_unchanged(material,tmp_path):
    mesh=clean_mesh(cube()); surfaces,_,_=select_surfaces(mesh,extract_boundary(mesh))
    model=load_catalog()[material]; values=defaults(model)
    for simulation in (None,SIMULATION_KEY):
        output=tmp_path/('simulation.feb' if simulation else 'geometry.feb')
        write_feb(output,mesh,surfaces,model,values,simulation=simulation)
        root=ET.parse(output).getroot()
        assert root.find('Material/material').get('type')==material
        assert (root.find('Step') is not None)==bool(simulation)
        assert (root.find('Boundary') is not None)==bool(simulation)
        assert (root.find('LoadData') is not None)==bool(simulation)
