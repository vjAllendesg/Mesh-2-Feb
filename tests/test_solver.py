import json
from pathlib import Path
import sys
import threading
import time
import xml.etree.ElementTree as ET

import pytest

from scaffold_feb.model import MeshError
from scaffold_feb.solver import SolverBatch, normal_termination


@pytest.fixture
def fake_solver(tmp_path):
    script = tmp_path/"fake_solver.py"
    script.write_text('''import sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
args=sys.argv[1:]
source=Path(args[args.index('-i')+1]); log=Path(args[args.index('-o')+1])
root=ET.parse(source).getroot(); mode=root.get('test','ok')
if mode=='sleep':
    log.write_text('Ejecutando\\n')
    time.sleep(30)
elif mode=='fail':
    log.write_text('FATAL ERROR: modelo no válido\\n')
    sys.exit(0)
else:
    log.write_text('N O R M A L   T E R M I N A T I O N\\n')
    Path(args[args.index('-p')+1]).write_bytes(b'resultado')
    for entry in root.findall('Output/logfile/*'):
        Path(entry.get('file')).write_text('datos de salida')
''',encoding="utf-8")
    return [sys.executable,str(script)]


def model(path, behavior="ok"):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(f'''<febio_spec version="4.0" test="{behavior}">
<Step><step id="1"/></Step>
<Output><logfile><node_data data="Rz" file="../fuerzas.txt"/></logfile></Output>
</febio_spec>''',encoding="utf-8")
    return path


def wait(runner, seconds=15):
    runner.thread.join(timeout=seconds)
    if runner.running:
        runner.cancel(); runner.thread.join(timeout=5)
        pytest.fail("El ejecutor no terminó a tiempo")
    assert runner.report is not None
    return runner.report


def test_sequential_continue_after_failure_and_isolate_outputs(tmp_path,fake_solver):
    first=model(tmp_path/'a'/'same.feb')
    bad=model(tmp_path/'bad.feb','fail')
    last=model(tmp_path/'b'/'same.feb')
    before=first.read_bytes()
    events=[]
    runner=SolverBatch(fake_solver,[first,bad,last],tmp_path,events.append)
    directory=runner.start()
    result=wait(runner)
    assert (result['ok'],result['errors'],result['cancelled'])==(2,1,0)
    assert [r['status'] for r in result['results']]==['ok','error','ok']
    assert first.read_bytes()==before
    assert not (directory/'fuerzas.txt').exists()
    for row in (result['results'][0],result['results'][2]):
        case=Path(row['directory'])
        assert (case/'fuerzas.txt').read_text()=='datos de salida'
        assert (case/'resultados.xplt').is_file()
        assert (case/'consola.txt').is_file()
    assert result['results'][0]['directory']!=result['results'][2]['directory']
    assert result['results'][1]['returncode']==0  # El código 0 por sí solo no basta.
    assert (directory/'resumen.csv').exists()
    assert len((directory/'resultados.jsonl').read_text().splitlines())==3
    assert json.loads((directory/'resumen.json').read_text())['errors']==1
    assert [e['index'] for e in events if e['kind']=='started']==[0,1,2]
    assert events[-1]['kind']=='done'
    again=SolverBatch(fake_solver,[first],tmp_path)
    assert again.start()!=directory
    assert wait(again)['ok']==1


def test_cancel_stops_owned_process_and_does_not_start_pending(tmp_path,fake_solver):
    first=model(tmp_path/'slow.feb','sleep')
    second=model(tmp_path/'pending.feb')
    active=threading.Event()
    runner=SolverBatch(fake_solver,[first,second],tmp_path,
                       lambda e:active.set() if e['kind']=='heartbeat' else None)
    runner.start()
    assert active.wait(timeout=10)
    start=time.monotonic()
    runner.cancel()
    result=wait(runner,10)
    assert time.monotonic()-start<8
    assert (result['ok'],result['errors'],result['cancelled'])==(0,0,2)
    assert result['results'][1]['directory']==''
    assert runner.process is None


def test_bad_xml_and_geometry_only_are_reported(tmp_path,fake_solver):
    bad=tmp_path/'bad.feb'; bad.write_text('bad')
    geometry=tmp_path/'geometry.feb'; geometry.write_text('<febio_spec version="4.0"><Mesh/></febio_spec>')
    runner=SolverBatch(fake_solver,[bad,geometry],tmp_path)
    runner.start(); result=wait(runner)
    assert result['errors']==2
    assert 'solo geometría' in result['results'][1]['message']


def test_no_inputs_or_solver_is_clear_error(tmp_path,fake_solver):
    with pytest.raises(MeshError,match='ejecutable'):
        SolverBatch(tmp_path/'missing.exe',[],tmp_path).start()
    with pytest.raises(MeshError,match='al menos'):
        SolverBatch(fake_solver,[],tmp_path).start()
