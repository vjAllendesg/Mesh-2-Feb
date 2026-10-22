from datetime import datetime
import xml.etree.ElementTree as ET

from scaffold_feb.names import run_directory
from scaffold_feb.solver import prepare_input


def test_same_minute_keeps_existing_results(tmp_path):
    first=run_directory(tmp_path,'FEB',datetime(2026,10,21,15,30,1))
    retained=first/'resultado.txt'; retained.write_text('conservar')
    second=run_directory(tmp_path,'FEB',datetime(2026,10,21,15,30,59))
    assert first.name=='FEB_2026-10-21_15-30'
    assert second.name=='FEB_2026-10-21_15-30_2'
    assert retained.read_text()=='conservar'


def test_short_logs_cannot_collide_with_solver_or_each_other(tmp_path):
    source=tmp_path/'pieza.feb'
    source.write_text('''<febio_spec version="4.0"><Step/>
<Output><logfile>
<node_data file="../modelo_largo_fuerza_inferior.txt"/>
<node_data file="otro_F_inf.txt"/>
<node_data file="C:\\salida\\modelo_stress_superior.txt"/>
<node_data file="solver.log"/>
<node_data file="pieza.feb"/>
</logfile></Output></febio_spec>''')
    destination=tmp_path/'run'; destination.mkdir()
    copied=prepare_input(source,destination)
    names=[e.get('file') for e in ET.parse(copied).findall('Output/logfile/*')]
    assert names==['F_inf.txt','F_inf_2.txt','S_sup.txt','solver_2.log','pieza_2.feb']
    assert all('/' not in name and '\\' not in name for name in names)
    assert len({name.casefold() for name in names})==len(names)
    assert 'modelo_largo_fuerza_inferior.txt' in source.read_text()
