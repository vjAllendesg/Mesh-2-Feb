"""Exportación secuencial: una malla en memoria y un informe por lote."""
from dataclasses import asdict
import csv
import json
from pathlib import Path

from .materials import validate_material
from .model import MeshError
from .pipeline import prepare
from .protocol import Protocol
from .simulations import SIMULATION_KEY
from .writer import write_feb
from .names import run_directory, reserve_filename


def export_batch(paths, directory, options, model, values, simulation=None,
                 simulation_axis="z", protocol=None, progress=None):
    values = validate_material(model,values)
    if simulation not in (None,SIMULATION_KEY):
        raise MeshError("Simulación desconocida.")
    protocol = (protocol or Protocol()).validate() if simulation else None
    paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
    if not paths: raise MeshError("Añade al menos una geometría al lote.")
    directory = Path(directory)
    if not directory.is_dir(): raise MeshError("La carpeta de salida no existe.")
    run = run_directory(directory,"FEB")
    configuration = dict(material=model,parameters=values,geometry=asdict(options),
                         simulation=simulation,simulation_axis=simulation_axis,
                         protocol=asdict(protocol) if protocol else None)
    (run/"parametros.json").write_text(json.dumps(configuration,ensure_ascii=False,indent=2),encoding="utf-8")
    rows = []
    names = set()
    for index,path in enumerate(paths,1):
        output = run/reserve_filename(path.stem+".feb",names)
        row = dict(input=str(path),output=str(output),status="error",message="")
        if progress: progress(index,len(paths),str(path),"Preparando")
        try:
            result = prepare(path,options)
            write_feb(output,result.mesh,result.surfaces,model,values,simulation=simulation,
                      simulation_axis=result.axis or simulation_axis,protocol=protocol)
            row.update(status="ok",summary=result.summary())
            if simulation:
                from .simulations import simulation_geometry
                height=simulation_geometry(result.mesh,result.surfaces,result.axis or simulation_axis,protocol)[4]
                row["applied_displacement_m"] = protocol.displacement_for(height)
        except Exception as exc:
            row["message"] = str(exc)
        finally:
            result = None
        rows.append(row)
        # Un registro por archivo conserva el diagnóstico si se interrumpe el lote.
        with (run/"resultados.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
        if progress: progress(index,len(paths),str(path),"Exportado" if row["status"]=="ok" else "Error: "+row["message"])
    with (run/"resumen.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["input","output","status","message"],extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    return dict(directory=str(run),ok=sum(row["status"]=="ok" for row in rows),
                errors=sum(row["status"]!="ok" for row in rows),results=rows)
