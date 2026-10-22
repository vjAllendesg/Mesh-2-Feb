"""Caras exteriores, componentes conexas y selección de planos."""
import numpy as np

from .geometry import UnionFind, element_volumes, remove_orphans
from .model import CellBlock, Face, MeshError, Surface, CORNER_COUNT

# Sentido exterior para un elemento con Jacobiano positivo.
LOCAL_FACES = {
    "tet4": ("tri3", ((0,2,1), (0,1,3), (1,2,3), (2,0,3))),
    "tet10": ("tri6", ((0,2,1,6,5,4), (0,1,3,4,8,7),
                       (1,2,3,5,9,8), (2,0,3,6,7,9))),
    "hex8": ("quad4", ((0,3,2,1), (4,5,6,7), (0,1,5,4),
                       (1,2,6,5), (2,3,7,6), (3,0,4,7))),
}
FACE_CORNERS = {"tri3": 3, "tri6": 3, "quad4": 4}
FACE_FLIP = {"tri3": [0,2,1], "tri6": [0,2,1,5,4,3], "quad4": [0,3,2,1]}


def _signature(face):
    if face.kind != "tri6":
        return (face.kind,)
    a,b,c,ab,bc,ca = face.nodes
    return face.kind, tuple(sorted(((min(i,j),max(i,j),m) for i,j,m in
                                   ((a,b,ab),(b,c,bc),(c,a,ca)))))


def topology(mesh):
    """La clave sin orientación solo cuenta incidencias; nunca se exporta."""
    records = {}
    groups = UnionFind(mesh.element_count)
    owner = 0
    for block in mesh.blocks:
        kind, local = LOCAL_FACES[block.kind]
        for cell in block.data:
            for indices in local:
                nodes = tuple(int(cell[i]) for i in indices)
                face = Face(kind, nodes, owner)
                key = tuple(sorted(nodes[:FACE_CORNERS[kind]]))
                if key not in records:
                    records[key] = [face, 1]
                else:
                    previous, count = records[key]
                    if count >= 2:
                        raise MeshError("La malla no es manifold: una cara pertenece a más de dos elementos.")
                    if _signature(previous) != _signature(face):
                        raise MeshError("Dos elementos comparten esquinas pero no la misma cara de orden superior.")
                    groups.union(previous.owner, owner)
                    records[key][1] += 1
            owner += 1
    boundary = [face for face,count in records.values() if count == 1]
    labels = np.array([groups.find(i) for i in range(mesh.element_count)])
    return boundary, labels


def face_normal(points, face):
    xyz = points[list(face.nodes[:FACE_CORNERS[face.kind]])]
    if face.kind == "quad4":
        # Derivadas bilineales en el centro del cuadrilátero.
        return np.cross(xyz[1]+xyz[2]-xyz[0]-xyz[3], xyz[2]+xyz[3]-xyz[0]-xyz[1])/4
    return np.cross(xyz[1]-xyz[0], xyz[2]-xyz[0])


def orient_faces(mesh, faces):
    centers = np.concatenate([mesh.points[b.data[:,:CORNER_COUNT[b.kind]]].mean(axis=1) for b in mesh.blocks])
    result = []
    for face in faces:
        center = mesh.points[list(face.nodes[:FACE_CORNERS[face.kind]])].mean(axis=0)
        normal = face_normal(mesh.points, face)
        d = float(np.dot(normal, center - centers[face.owner]))
        if not np.isfinite(d) or d == 0:
            raise MeshError("Hay una cara degenerada o sin orientación exterior definida.")
        if d < 0:
            face = Face(face.kind, tuple(face.nodes[i] for i in FACE_FLIP[face.kind]), face.owner)
        result.append(face)
    return result


def extract_boundary(mesh, keep_largest=False):
    faces, labels = topology(mesh)
    distinct = np.unique(labels)
    if len(distinct) > 1:
        if keep_largest:
            volumes = element_volumes(mesh)
            totals = {int(label): float(volumes[labels == label].sum()) for label in distinct}
            largest = max(totals, key=totals.get)
            discarded = int(np.count_nonzero(labels != largest))
            blocks, offset = [], 0
            for b in mesh.blocks:
                selected = b.data[labels[offset:offset+len(b.data)] == largest]
                if len(selected):
                    blocks.append(CellBlock(b.kind, selected))
                offset += len(b.data)
            mesh.blocks = blocks
            removed = remove_orphans(mesh)
            mesh.warnings.append(f"Se conservaron los elementos de la pieza de mayor volumen; "
                                 f"se retiraron {len(distinct)-1} fragmentos, {discarded} elementos y {removed} nodos.")
            faces, _ = topology(mesh)
        else:
            mesh.warnings.append(f"Se detectaron {len(distinct)} componentes conectadas por caras; se conservan todas.")
    return orient_faces(mesh, faces)


def plane_faces(mesh, faces, axis, coordinate, tolerance):
    return [f for f in faces if np.all(np.abs(mesh.points[list(f.nodes),axis]-coordinate) <= tolerance)]


def detect_axis(mesh, faces, tolerance):
    """El par de planos extremos con mayor área común identifica las tapas."""
    bounds = mesh.bounds
    scores = []
    for axis in range(3):
        areas = []
        for coordinate in bounds[:,axis]:
            selected = plane_faces(mesh, faces, axis, coordinate, tolerance)
            areas.append(sum(np.linalg.norm(face_normal(mesh.points,f)) *
                             (0.5 if f.kind.startswith("tri") else 1) for f in selected))
        scores.append(min(areas))
    order = np.argsort(scores)
    best, second = scores[order[-1]], scores[order[-2]]
    if best <= 0 or best <= second * 1.05:
        raise MeshError("El eje del cilindro no se distingue con confianza. Elige X, Y o Z y revisa la tolerancia del plano.")
    return int(order[-1])


def select_surfaces(mesh, faces, shape="cube", axis="auto", tolerance=None, selected=None):
    bounds = mesh.bounds
    span = bounds[1]-bounds[0]
    if tolerance is None:
        tolerance = float(np.linalg.norm(span) * 1e-6)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise MeshError("La tolerancia del plano debe ser finita y mayor o igual a cero.")
    if shape not in ("cube", "cylinder"):
        raise MeshError("La forma debe ser cube o cylinder.")
    if axis.lower() not in ("auto", "x", "y", "z"):
        raise MeshError("El eje debe ser auto, X, Y o Z.")
    if shape == "cube":
        planes = [(f"{name}{sign}", i, bounds[j,i]) for i,name in enumerate("XYZ") for j,sign in enumerate("-+")]
        chosen_axis = None
    else:
        a = detect_axis(mesh, faces, tolerance) if axis.lower() == "auto" else "xyz".index(axis.lower())
        chosen_axis = "XYZ"[a]
        planes = [("inferior", a, bounds[0,a]), ("superior", a, bounds[1,a])]
    wanted = {name for name,_,_ in planes} if selected is None else set(selected)
    unknown = wanted - {name for name,_,_ in planes}
    if unknown:
        raise MeshError("Superficies desconocidas para la forma elegida: " + ", ".join(sorted(unknown)))
    output = []
    for name,a,coordinate in planes:
        if name not in wanted:
            continue
        if tolerance >= span[a]/4:
            raise MeshError(f"La tolerancia del plano es demasiado grande para el eje {'XYZ'[a]}.")
        found = plane_faces(mesh, faces, a, coordinate, tolerance)
        if not found:
            raise MeshError(f"La superficie {name} está vacía. Revisa el eje o la tolerancia; "
                            "todos los nodos de cada cara deben estar en el plano.")
        output.append(Surface(name, found))
    return output, chosen_axis, tolerance
