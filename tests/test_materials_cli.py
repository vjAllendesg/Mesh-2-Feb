import json
import xml.etree.ElementTree as ET

import pytest

from scaffold_feb.cli import main
from scaffold_feb.materials import load_catalog, defaults, validate_material
from scaffold_feb.model import MeshError


def test_catalog_extension_and_duplicate_label(tmp_path):
    model = {"type":"custom scalar material","label":"Mi material","parameters":[
        {"name":"modulus","label":"Módulo","unit":"Pa","default":12,"min_exclusive":0}]}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"materials":[model]}),encoding="utf-8")
    loaded = load_catalog(path)[model["type"]]
    assert validate_material(loaded,defaults(loaded)) == {"modulus":12}
    path.write_text(json.dumps({"materials":[model,dict(model,type="another")]}),encoding="utf-8")
    with pytest.raises(MeshError,match="etiqueta"):
        load_catalog(path)


@pytest.mark.parametrize("value",["nan","inf",0,-1,True])
def test_reject_invalid_young(value):
    model = load_catalog()["neo-Hookean"]
    values = defaults(model)
    values["E"] = value
    with pytest.raises(MeshError):
        validate_material(model,values)


def test_cli_export_inspect_and_protect_output(tmp_path,capsys):
    from scaffold_feb.examples import generate
    generate(tmp_path / "inputs")
    path = tmp_path / "inputs" / "cubo.vtu"
    output = tmp_path / "out.feb"
    assert main([str(path),str(output),"--surfaces","Z-,Z+","--param","E=250"]) == 0
    before = output.read_bytes()
    root = ET.fromstring(before)
    assert root.findtext("Material/material/E") == "250"
    assert [s.get("name") for s in root.findall("Mesh/Surface")] == ["Z-","Z+"]
    assert main([str(path),str(output)]) == 2
    assert output.read_bytes() == before
    capsys.readouterr()
    assert main([str(path),"--inspect","--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["nodos"] == 8 and summary["elementos"] == {"tet4":6}
