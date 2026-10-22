"""Bloques FEBio 4.0 basados en el ejemplo autorizado del usuario."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import xml.etree.ElementTree as ET

from .materials import validate_material
from .model import MeshError

BLOCK_ORDER = ("Module", "Globals", "Material", "Mesh", "MeshDomains", "Boundary",
               "Loads", "Step", "LoadData", "Output")
TEMPLATE_BLOCKS = {"Boundary", "Loads", "Step", "LoadData", "Output"}


def number(value):
    return format(float(value), ".17g")


def build_material(model, values):
    values = validate_material(model, values)
    block = ET.Element("Material")
    material = ET.SubElement(block,"material",id="1",name="material_1",type=model["type"])
    for key,value in values.items():
        ET.SubElement(material,key).text = number(value)
    return block


def build_mesh(mesh, surfaces, extra_node_sets=None):
    block = ET.Element("Mesh")
    nodes = ET.SubElement(block,"Nodes",name="scaffold")
    for i,xyz in enumerate(mesh.points,1):
        ET.SubElement(nodes,"node",id=str(i)).text = ",".join(number(v) for v in xyz)
    element_id = 1
    domains = []
    for index,cell_block in enumerate(mesh.blocks,1):
        name = f"solid_{cell_block.kind}_{index}"
        domains.append(name)
        elements = ET.SubElement(block,"Elements",type=cell_block.kind,name=name)
        for cell in cell_block.data:
            ET.SubElement(elements,"elem",id=str(element_id)).text = ",".join(str(int(n)+1) for n in cell)
            element_id += 1
    names = set()
    for surface in surfaces:
        if not surface.faces:
            raise MeshError(f"La superficie {surface.name} está vacía.")
        if surface.name in names:
            raise MeshError("Los nombres de superficies deben ser únicos.")
        names.add(surface.name)
        ET.SubElement(block,"NodeSet",name=surface.name).text = ",".join(str(n+1) for n in surface.nodes)
    for name,ids in (extra_node_sets or {}).items():
        if name in names or not ids or min(ids)<0 or max(ids)>=len(mesh.points):
            raise MeshError(f"NodeSet auxiliar inválido: {name}")
        ET.SubElement(block,"NodeSet",name=name).text = ",".join(str(int(n)+1) for n in ids)
        names.add(name)
    for surface in surfaces:
        group = ET.SubElement(block,"Surface",name=surface.name)
        for face_id,face in enumerate(surface.faces,1):
            if min(face.nodes) < 0 or max(face.nodes) >= len(mesh.points):
                raise MeshError("Una superficie referencia nodos inexistentes.")
            ET.SubElement(group,face.kind,id=str(face_id)).text = ",".join(str(n+1) for n in face.nodes)
    return block, domains


def build_domains(names):
    block = ET.Element("MeshDomains")
    for name in names:
        ET.SubElement(block,"SolidDomain",name=name,mat="material_1")
    return block


def build_output():
    block = ET.Element("Output")
    plot = ET.SubElement(block,"plotfile",type="febio")
    for name in ("displacement", "stress", "relative volume"):
        ET.SubElement(plot,"var",type=name)
    return block


def load_template(path):
    """Punto de extensión de fase 2; no se invoca desde la GUI ni la CLI."""
    root = ET.parse(Path(path)).getroot()
    if root.tag != "febio_fragments":
        raise MeshError("La plantilla debe tener raíz febio_fragments.")
    blocks = {}
    for child in root:
        if child.tag not in TEMPLATE_BLOCKS or child.tag in blocks:
            raise MeshError(f"Bloque de plantilla no permitido o duplicado: {child.tag}")
        blocks[child.tag] = deepcopy(child)
    return blocks


def build_document(mesh, surfaces, model, values, extra_blocks=None, simulation=None, simulation_axis="z", output_stem="simulacion", protocol=None):
    simulation_blocks,extra_sets = {},{}
    if simulation:
        from .simulations import SIMULATION_KEY,build_simulation
        if simulation != SIMULATION_KEY:
            raise MeshError(f"Simulación desconocida: {simulation}")
        if extra_blocks:
            raise MeshError("No se puede combinar una simulación con bloques XML externos.")
        simulation_blocks,extra_sets = build_simulation(mesh,surfaces,simulation_axis,output_stem,protocol)
    root = ET.Element("febio_spec",version="4.0")
    root.append(ET.Comment(" Compresión y mantenimiento del ejemplo, adaptada a la malla. SI. " if simulation else
                           " Geometría y material en SI. Configurar condiciones y pasos antes de resolver. "))
    module = ET.Element("Module",type="solid")
    ET.SubElement(module,"units").text = "SI"
    mesh_xml, names = build_mesh(mesh,surfaces,extra_sets)
    material = build_material(model,values)
    blocks = {"Module": module, "Material": material,
              "Mesh": mesh_xml, "MeshDomains": build_domains(names), "Output": build_output()}
    blocks.update(simulation_blocks)
    for name,element in (extra_blocks or {}).items():
        if name not in TEMPLATE_BLOCKS or element.tag != name:
            raise MeshError(f"Bloque de extensión no permitido: {name}")
        blocks[name] = deepcopy(element)
    for name in BLOCK_ORDER:
        if name in blocks:
            root.append(blocks[name])
    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def write_feb(path, mesh, surfaces, model, values, overwrite=False, extra_blocks=None, simulation=None, simulation_axis="z", protocol=None):
    path = Path(path)
    if path.suffix.lower() != ".feb":
        raise MeshError("El archivo de salida debe terminar en .feb.")
    if mesh.source and path.resolve() == mesh.source.resolve():
        raise MeshError("La salida no puede sobrescribir la malla original.")
    document = build_document(mesh,surfaces,model,values,extra_blocks,simulation,simulation_axis,path.stem,protocol)
    if not path.parent.is_dir():
        raise MeshError(f"La carpeta de salida no existe: {path.parent}")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix=".tmp",delete=False) as f:
            temp = Path(f.name)
            document.write(f, encoding="utf-8",xml_declaration=True)
        if overwrite:
            os.replace(temp,path)
        else:
            # Crear el destino de manera exclusiva evita reemplazos accidentales.
            with path.open("xb") as output, temp.open("rb") as source:
                import shutil
                shutil.copyfileobj(source,output)
    except FileExistsError:
        raise MeshError(f"El archivo ya existe: {path.name}. Elige otro nombre o autoriza sobrescribir.") from None
    except OSError as exc:
        raise MeshError(f"No se pudo guardar {path.name}: {exc}") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return path
