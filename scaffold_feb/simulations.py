"""Ensayo de compresión y mantenimiento adaptado del FEB del usuario."""
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .model import MeshError
from .surfaces import topology
from .protocol import Protocol
from .names import short_log_name

SIMULATION_KEY = "compresion-mantenimiento"
SIMULATION_LABEL = "Compresión y mantenimiento — ejemplo"
NONE_LABEL = "Sin simulación (solo geometría)"
DESCRIPTION = ("Configura el control y los tiempos; se aplican a todas las geometrías. "
               "La fuerza es total sobre la tapa y actúa en compresión. Usa el material elegido.")


def simulation_geometry(mesh, surfaces, axis="z", protocol=None):
    """Resuelve tapas y anclajes sin reutilizar IDs de otra malla."""
    axis = axis.lower()
    if axis not in ("x","y","z"):
        raise MeshError("La simulación necesita un eje X, Y o Z definido.")
    a = "xyz".index(axis)
    by_name = {surface.name:surface for surface in surfaces}
    names = ("inferior","superior") if "inferior" in by_name or "superior" in by_name else (axis.upper()+"-",axis.upper()+"+")
    if any(name not in by_name for name in names):
        raise MeshError(f"Para la simulación debes seleccionar ambas tapas: {names[0]} y {names[1]}.")
    bottom,top = (by_name[name] for name in names)
    low,high = bottom.nodes,top.nodes
    if len(low)<3 or len(high)<3 or set(low)&set(high):
        raise MeshError("Las tapas deben tener al menos tres nodos y no compartir nodos.")
    height = float(mesh.points[high,a].mean()-mesh.points[low,a].mean())
    if height<=0 or not np.isfinite(height):
        raise MeshError("La tapa superior debe estar por encima de la inferior en el eje del ensayo.")
    (protocol or Protocol()).displacement_for(height)
    transverse = [i for i in range(3) if i!=a]
    center = mesh.bounds.mean(axis=0)[transverse]
    def ordered(ids):
        distances = np.linalg.norm(mesh.points[ids][:,transverse]-center,axis=1)
        return np.asarray(ids)[np.argsort(distances,kind="stable")]
    anchor = int(ordered(low)[0])
    candidates = ordered(high)
    separation = np.linalg.norm(mesh.points[candidates][:,transverse]-mesh.points[anchor,transverse],axis=1)
    transverse_scale = float(np.linalg.norm(np.ptp(mesh.points[:,transverse],axis=0)))
    usable = candidates[separation > transverse_scale*1e-8]
    if not len(usable):
        raise MeshError("No se puede definir el segundo anclaje sin dejar libre la rotación axial.")
    return bottom,top,anchor,int(usable[0]),height


def build_simulation(mesh, surfaces, axis="z", output_stem="simulacion", protocol=None):
    protocol = (protocol or Protocol()).validate()
    bottom,top,anchor,guide,height = simulation_geometry(mesh,surfaces,axis,protocol)
    displacement = protocol.displacement_for(height)
    _,labels = topology(mesh)
    if len(np.unique(labels)) != 1:
        raise MeshError("Esta simulación requiere una sola pieza conectada. Activa «Conservar solo la pieza principal» y prepara de nuevo.")
    axis = axis.lower()
    root = ET.parse(Path(__file__).with_name("templates")/"compresion_relajacion.xml").getroot()
    blocks = {child.tag:child for child in root}
    sets = {"sim_apoyo_inferior":[anchor],"sim_guia_superior":[guide]}
    if set(sets)&{s.name for s in surfaces}:
        raise MeshError("Un nombre de superficie coincide con un anclaje reservado de la simulación.")
    bottom_refs = {"ZeroDisplacement1","ZeroDisplacement2","ZeroDisplacement4"}
    top_refs = {"PrescribedDisplacement4","PrescribedDisplacement5"}
    anchor_refs = {"ZeroDisplacement6","ZeroDisplacement7","ZeroDisplacement8"}
    guide_refs = {"ZeroDisplacement9","ZeroDisplacement11"}
    # Permutación de coordenadas: el eje Z del ensayo pasa a X, Y o Z.
    axes = {"z":("x","y","z"),"x":("y","z","x"),"y":("z","x","y")}[axis]
    for block in (blocks["Boundary"],blocks["Step"]):
        for bc in block.iter("bc"):
            name = bc.get("node_set").removeprefix("@surface:")
            if name in bottom_refs: target = "@surface:"+bottom.name
            elif name in top_refs: target = "@surface:"+top.name
            elif name in anchor_refs: target = "sim_apoyo_inferior"
            elif name in guide_refs: target = "sim_guia_superior"
            else: raise MeshError(f"Referencia desconocida en la plantilla: {name}")
            bc.set("node_set",target)
            flags = [bc.findtext(f"{old}_dof") for old in "xyz"]
            for new,value in zip(axes,flags):
                if value is not None: bc.find(f"{new}_dof").text = value
            if bc.get("type")=="prescribed displacement":
                bc.find("dof").text = axis
                if displacement is not None:
                    bc.find("value").text = format(-displacement,".17g")
    for index,step in enumerate(blocks["Step"]):
        duration,dt = ((protocol.step1_duration,protocol.step1_dt),
                       (protocol.step2_duration,protocol.step2_dt))[index]
        step.find("Control/time_steps").text = str(round(duration/dt))
        step.find("Control/step_size").text = str(dt)
        if protocol.mode=="force":
            boundary = step.find("Boundary")
            for bc in list(boundary):
                if bc.get("type")=="prescribed displacement": boundary.remove(bc)
            loads = ET.SubElement(step,"Loads")
            load = ET.SubElement(loads,"surface_load",name=f"Compresion_fuerza_{index+1}",type="force",surface=top.name)
            scale = ET.SubElement(load,"scale",**({"lc":"1"} if index==0 else {}))
            scale.text = "1"
            vector = [0.,0.,0.]; vector["xyz".index(axis)] = -protocol.force
            ET.SubElement(load,"force").text = ",".join(format(v,".17g") for v in vector)
    # FEBio calcula reacciones en grados prescritos. Una prescripción cero
    # mantiene el apoyo original y permite registrar la fuerza de la base.
    for bc in blocks["Boundary"]:
        if bc.get("node_set")=="@surface:"+bottom.name:
            bc.set("type","prescribed displacement")
            for child in list(bc): bc.remove(child)
            ET.SubElement(bc,"dof").text = axis
            ET.SubElement(bc,"value").text = "0"
            ET.SubElement(bc,"relative").text = "0"
    for step in blocks["Step"]:
        boundary = step.find("Boundary")
        for bc in list(boundary):
            if bc.get("node_set")=="@surface:"+bottom.name: boundary.remove(bc)
    for block in (blocks["Boundary"],blocks["Step"]):
        for bc in block.iter("bc"):
            if bc.get("node_set")=="sim_apoyo_inferior":
                bc.find(axis+"_dof").text = "0"
    # La plantilla original se conserva literalmente para los tiempos iniciales.
    if (protocol.ramp_time,protocol.step1_duration,protocol.step2_duration)!=(.1,1.,7.):
        points = blocks["LoadData"].find("load_controller/points")
        points.clear()
        ET.SubElement(points,"pt").text = "0,0"
        ET.SubElement(points,"pt").text = f"{protocol.ramp_time:.17g},1"
        ET.SubElement(points,"pt").text = f"{protocol.step1_duration+protocol.step2_duration:.17g},1"
    for entry in blocks["Output"].find("logfile"):
        surface = bottom if "inferior" in entry.get("file") else top
        entry.set("file",f"{output_stem}_{short_log_name(entry.get('file'))}")
        if entry.tag=="node_data":
            entry.set("data","R"+axis)
            entry.text = ",".join(str(n+1) for n in surface.nodes)
        else:
            entry.set("data","s"+axis)
            entry.text = ",".join(str(n+1) for n in sorted({f.owner for f in surface.faces}))
    return blocks,sets
