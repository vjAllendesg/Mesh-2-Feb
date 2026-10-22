from dataclasses import replace
import json
import xml.etree.ElementTree as ET

import meshio
import pytest

from scaffold_feb.batch import export_batch
from scaffold_feb.cli import main
from scaffold_feb.examples import cube
from scaffold_feb.geometry import clean_mesh
from scaffold_feb.materials import load_catalog,defaults
from scaffold_feb.model import Options,MeshError
from scaffold_feb.protocol import Protocol
from scaffold_feb.simulations import SIMULATION_KEY,build_simulation
from scaffold_feb.surfaces import extract_boundary,select_surfaces


@pytest.mark.parametrize('change',[
    dict(mode='bad'),dict(displacement=0),dict(force=float('nan'),mode='force'),
    dict(compression_percent=100,mode='percent'),dict(step1_dt=.03),
    dict(ramp_time=2),dict(ramp_time=.015),dict(step2_duration=0)])
def test_invalid_protocol(change):
    with pytest.raises(MeshError): replace(Protocol(),**change).validate()


def test_percentage_custom_timing_and_force_are_distinct():
    mesh=cube(); mesh.points*=2; clean_mesh(mesh)
    surfaces,_,_=select_surfaces(mesh,extract_boundary(mesh))
    protocol=Protocol(mode='percent',compression_percent=15,ramp_time=.2,
                      step1_duration=.6,step1_dt=.02,step2_duration=1,step2_dt=.1)
    blocks,_=build_simulation(mesh,surfaces,protocol=protocol)
    assert [int(s.findtext('Control/time_steps')) for s in blocks['Step']]==[30,10]
    for bc in blocks['Step'].findall("step/Boundary/bc[@type='prescribed displacement']"):
        assert float(bc.findtext('value'))==pytest.approx(-.3)
    assert [[float(v) for v in p.text.split(',')] for p in blocks['LoadData'].findall('load_controller/points/pt')]==[[0,0],[.2,1],[1.6,1]]
    blocks,_=build_simulation(mesh,surfaces,protocol=replace(protocol,mode='force',force=25))
    assert not blocks['Step'].findall("step/Boundary/bc[@type='prescribed displacement']")
    loads=blocks['Step'].findall('step/Loads/surface_load')
    assert len(loads)==2 and all(s.get('type')=='force' for s in loads)
    assert all(s.findtext('force')=='0,0,-25' for s in loads)
    assert loads[0].find('scale').get('lc')=='1' and loads[1].find('scale').get('lc') is None
    assert blocks['Boundary'].find("bc[@node_set='@surface:Z-']").get('type')=='prescribed displacement'


def write_cube(path,height=1):
    mesh=cube(); mesh.points[:,2]*=height
    path.parent.mkdir(exist_ok=True)
    meshio.write(path,meshio.Mesh(mesh.points,[("tetra",mesh.blocks[0].data)]))
    return path


def test_batch_preserves_parameters_collisions_and_continues_after_error(tmp_path):
    first=write_cube(tmp_path/'a'/'same.vtu')
    second=write_cube(tmp_path/'b'/'same.vtu',2)
    bad=tmp_path/'broken.vtu'; bad.write_text('invalid')
    model=load_catalog()['neo-Hookean']; values=defaults(model); values['E']=321
    events=[]
    result=export_batch([first,bad,second,first],tmp_path,Options(),model,values,SIMULATION_KEY,
                        protocol=Protocol(mode='percent',compression_percent=20),
                        progress=lambda *args:events.append(args))
    assert (result['ok'],result['errors'])==(2,1)
    assert len(events)==6
    successful=[r for r in result['results'] if r['status']=='ok']
    assert successful[0]['output']!=successful[1]['output']
    assert [r['applied_displacement_m'] for r in successful]==[.2,.4]
    for row in successful:
        root=ET.parse(row['output']).getroot()
        assert root.findtext('Material/material/E')=='321'
    from pathlib import Path
    directory=Path(result['directory'])
    params=json.loads((directory/'parametros.json').read_text(encoding='utf-8'))
    assert params['protocol']['compression_percent']==20
    assert len((directory/'resultados.jsonl').read_text(encoding='utf-8').splitlines())==3
    assert (directory/'resumen.csv').exists()
    again=export_batch([first],tmp_path,Options(),model,values)
    assert again['directory']!=result['directory']
    assert ET.parse(again['results'][0]['output']).getroot().find('Step') is None


def test_batch_cli_and_single_protocol(tmp_path,capsys):
    path=write_cube(tmp_path/'cube.vtu')
    assert main(['--batch',str(path),'--output-dir',str(tmp_path),'--simulation',SIMULATION_KEY,
                 '--control','force','--force','2','--json'])==0
    report=json.loads(capsys.readouterr().out)
    root=ET.parse(report['results'][0]['output']).getroot()
    assert root.findtext('Step/step/Loads/surface_load/force')=='0,0,-2'
    assert main([str(path),str(tmp_path/'single.feb'),'--simulation',SIMULATION_KEY,
                 '--control','percent','--compression-percent','25'])==0
    root=ET.parse(tmp_path/'single.feb').getroot()
    assert float(root.findtext("Step/step/Boundary/bc[@type='prescribed displacement']/value"))==-.25
