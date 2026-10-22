"""Interfaz de línea de comandos, con errores legibles y salida JSON opcional."""
import argparse
import json
from pathlib import Path
import sys
from dataclasses import asdict

from .materials import load_catalog, defaults, validate_material
from .model import MeshError, Options
from .pipeline import prepare
from .writer import write_feb
from .simulations import SIMULATION_KEY, build_simulation
from .protocol import Protocol
from .batch import export_batch


def parser():
    p = argparse.ArgumentParser(description="Convertir VTK/VTU/STL a geometría FEBio 4.0 en SI.")
    p.add_argument("input", type=Path, nargs="?", help="Malla de entrada")
    p.add_argument("output", type=Path, nargs="?", help="Salida .feb (se omite con --inspect)")
    p.add_argument("--shape",choices=("cube","cylinder"),default="cube")
    p.add_argument("--axis",choices=("auto","x","y","z"),default="auto")
    p.add_argument("--surfaces",help="Nombres separados por comas: X-,X+,Y-,Y+,Z-,Z+ o inferior,superior; none para ninguna")
    p.add_argument("--scale",type=float,default=1.,help="Factor de coordenadas a metros, p.ej. 0.001 si la entrada está en mm")
    p.add_argument("--merge-tolerance",type=float,default=0.,help="Tolerancia de fusión en metros; 0 fusiona coincidencias exactas")
    p.add_argument("--plane-tolerance",type=float,help="Distancia máxima de todos los nodos de una cara al plano, en metros")
    p.add_argument("--element-size",type=float,help="Tamaño nominal h en metros para tetraedralizar superficies")
    p.add_argument("--largest",action="store_true",help="Conservar la pieza conectada por caras de mayor volumen")
    p.add_argument("--material",default="neo-Hookean",help="Nombre FEBio del material en el catálogo")
    p.add_argument("--catalog",type=Path,help="JSON alternativo de materiales")
    p.add_argument("--simulation",choices=("none",SIMULATION_KEY),default="none",
                   help="Añadir el ensayo del ejemplo con el material elegido")
    p.add_argument("--simulation-axis",choices=("x","y","z"),default="z",
                   help="Eje del ensayo en cubos; en cilindros se usa el eje de las tapas")
    p.add_argument("--param",action="append",default=[],metavar="NOMBRE=VALOR")
    p.add_argument("--batch",nargs="+",type=Path,help="Geometrías para exportar en lote")
    p.add_argument("--output-dir",type=Path,help="Carpeta de salida del lote")
    p.add_argument("--control",choices=("displacement","percent","force"),default="displacement")
    for name in ("displacement","compression_percent","force","ramp_time","step1_duration","step1_dt","step2_duration","step2_dt"):
        p.add_argument("--"+name.replace("_","-"),type=float,default=getattr(Protocol(),name))
    p.add_argument("--overwrite",action="store_true",help="Permitir reemplazar una salida existente")
    p.add_argument("--inspect",action="store_true",help="Preparar e informar sin escribir FEB")
    p.add_argument("--json",action="store_true",help="Resumen estructurado")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.batch:
        if not args.output_dir or args.input or args.output or args.inspect:
            p.error("usa --batch ARCHIVOS --output-dir CARPETA, sin entrada/salida posicional ni --inspect")
    elif args.input is None:
        p.error("indica una malla de entrada o --batch")
    elif not args.inspect and args.output is None:
        p.error("indica una salida .feb o utiliza --inspect")
    try:
        catalog = load_catalog(args.catalog)
        if args.material not in catalog:
            raise MeshError("Material desconocido. Disponibles: " + ", ".join(catalog))
        model = catalog[args.material]
        values = defaults(model)
        for assignment in args.param:
            if "=" not in assignment:
                raise MeshError("Usa --param NOMBRE=VALOR.")
            name,value = assignment.split("=",1)
            values[name] = value
        values = validate_material(model,values)
        selected = None if args.surfaces is None else (() if args.surfaces == "none" else tuple(s.strip() for s in args.surfaces.split(",")))
        opt = Options(args.scale,args.merge_tolerance,args.largest,args.element_size,
                      args.shape,args.axis,args.plane_tolerance,selected)
        simulation = None if args.simulation=="none" else args.simulation
        protocol = Protocol(mode=args.control,**{name:getattr(args,name) for name in vars(Protocol()) if name!="mode"}).validate() if simulation else None
        if args.batch:
            report=export_batch(args.batch,args.output_dir,opt,model,values,simulation,args.simulation_axis,protocol)
            print(json.dumps(report,ensure_ascii=False,indent=2) if args.json else
                  f"Lote: {report['directory']} | Exportadas: {report['ok']} | Errores: {report['errors']}")
            return 2 if report['errors'] else 0
        result = prepare(args.input,opt)
        summary = result.summary()
        simulation_axis = result.axis or args.simulation_axis
        summary["simulacion"] = args.simulation
        if protocol: summary["protocolo"] = asdict(protocol)
        if args.inspect and simulation:
            build_simulation(result.mesh,result.surfaces,simulation_axis,protocol=protocol)
        if not args.inspect:
            path = write_feb(args.output,result.mesh,result.surfaces,model,values,args.overwrite,
                             simulation=simulation,simulation_axis=simulation_axis,protocol=protocol)
            summary["salida"] = str(path)
        if args.json:
            print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:
            print(f"Entrada: {summary['entrada']} | Nodos: {summary['nodos']} | Elementos: {summary['elementos']}")
            print(f"Bounding box (m): {summary['bounding_box_m']}")
            if result.axis:
                print(f"Eje del cilindro: {result.axis}")
            for surface in result.surfaces:
                print(f"{surface.name}: {len(surface.faces)} caras, {len(surface.nodes)} nodos")
            for message in summary["advertencias"]:
                print("Aviso: " + message)
            if not args.inspect:
                detail = "Incluye el ensayo de compresión y mantenimiento." if simulation else "Geometría preparada; faltan condiciones y pasos para simular."
                print(f"Guardado: {args.output}. {detail}")
        return 0
    except (MeshError, OSError) as exc:
        print(f"Error: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
