"""Lectura meshio y tetraedralización de superficies cerradas con TetGen."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import threading

import meshio
import numpy as np

from .geometry import merge_points
from .model import CellBlock, Mesh, MeshError

MESHIO_TYPES = {"tetra": "tet4", "tetra10": "tet10", "hexahedron": "hex8"}
LOWER_TYPES = {"vertex", "line", "line3", "triangle", "triangle6", "quad", "quad8", "quad9", "polygon", "pixel"}
_READ_LOCK = threading.Lock()


@contextmanager
def voxel_support():
    """Adaptación temporal de meshio 5.3.5; no modifica paquetes instalados."""
    import meshio._vtk_common as common
    import meshio.vtk._vtk_42 as legacy
    original_type = common.vtk_to_meshio_type.get(11)
    original_common = common.vtk_to_meshio_order
    original_legacy = legacy.vtk_to_meshio_order
    original_count = legacy.vtk_type_to_numnodes[11]
    seen = []

    def order(cell_type, dtype=int):
        if cell_type == 11:
            seen.append(True)
            return np.array([0,1,3,2,4,5,7,6], dtype=dtype)
        return original_common(cell_type, dtype)

    common.vtk_to_meshio_type[11] = "hexahedron"
    common.vtk_to_meshio_order = order
    legacy.vtk_to_meshio_order = order
    legacy.vtk_type_to_numnodes[11] = 8
    try:
        yield seen
    finally:
        if original_type is None:
            common.vtk_to_meshio_type.pop(11, None)
        else:
            common.vtk_to_meshio_type[11] = original_type
        common.vtk_to_meshio_order = original_common
        legacy.vtk_to_meshio_order = original_legacy
        legacy.vtk_type_to_numnodes[11] = original_count


def read_stl(path):
    """Reconoce binarios por longitud y contador, incluso con encabezado solid."""
    from meshio.stl._stl import _read_ascii, _read_binary
    with path.open("rb") as stream:
        header = stream.read(84)
        count = int.from_bytes(header[80:84],"little") if len(header)==84 else 0
        if len(header)==84 and 84+50*count==path.stat().st_size:
            return _read_binary(stream,count)
        stream.seek(0)
        # Validar el esqueleto antes del lector ASCII rápido de meshio.
        state, vertices, facets = "solid", 0, 0
        for line in stream:
            tokens = line.strip().split()
            if not tokens:
                continue
            if state=="solid" and tokens[0]==b"solid":
                state="facet"
            elif state=="facet" and tokens[:2]==[b"facet",b"normal"] and len(tokens)==5:
                tuple(map(float,tokens[2:]))
                state="loop"
            elif state=="loop" and tokens==[b"outer",b"loop"]:
                state,vertices="vertices",0
            elif state=="vertices" and tokens[0]==b"vertex" and len(tokens)==4:
                tuple(map(float,tokens[1:]))
                vertices += 1
                if vertices==3:
                    state="endloop"
            elif state=="endloop" and tokens==[b"endloop"]:
                state="endfacet"
            elif state=="endfacet" and tokens==[b"endfacet"]:
                state="facet"
                facets += 1
            elif state=="facet" and tokens[0]==b"endsolid":
                state="solid"
            else:
                raise MeshError("STL inválido: no coincide con la estructura binaria ni con la sintaxis ASCII.")
        if state!="solid" or facets==0:
            raise MeshError("STL vacío o incompleto: faltan facetas o su cierre.")
        stream.seek(0)
        return _read_ascii(line for line in stream if line.strip())


def tetrahedralize(points, triangles, size, warnings):
    if size is None or not np.isfinite(size) or size <= 0:
        raise MeshError("Se detectó una malla superficial. Indica un tamaño de elemento mayor que cero, en metros, para tetraedralizar.")
    try:
        import tetgen
        import trimesh
        import rtree  # necesario para verificar interior/exterior sin rellenar cavidades
    except ImportError as exc:
        raise MeshError("La entrada es superficial. Instala tetgen, trimesh y rtree con requirements.txt.") from exc
    if not len(triangles):
        raise MeshError("La superficie no contiene triángulos.")
    if np.any(np.diff(np.sort(triangles, axis=1), axis=1) == 0):
        raise MeshError("La superficie contiene triángulos colapsados; reduce la tolerancia o repara el archivo.")
    xyz = points[triangles]
    if np.any(np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0], xyz[:,2]-xyz[:,0]), axis=1) == 0):
        raise MeshError("La superficie contiene triángulos de área cero.")
    if len(np.unique(np.sort(triangles,axis=1),axis=0)) != len(triangles):
        raise MeshError("La superficie contiene triángulos duplicados.")
    # Escalar al tamaño de la caja mejora la robustez de los predicados geométricos.
    origin = points.min(axis=0)
    length = float(np.ptp(points, axis=0).max())
    if length <= 0:
        raise MeshError("La superficie tiene tamaño cero.")
    normalized = (points-origin)/length
    shell = trimesh.Trimesh(vertices=normalized, faces=triangles, process=False)
    if not shell.is_watertight:
        raise MeshError("La superficie no está cerrada o tiene aristas no manifold. Cierra la malla antes de tetraedralizar; no se rellenan agujeros automáticamente.")
    # Ajustar sentidos de giro no mueve puntos ni rellena poros.
    trimesh.repair.fix_normals(shell, multibody=True)
    try:
        generator = tetgen.TetGen(np.asarray(shell.vertices), np.asarray(shell.faces,dtype=np.int32))
        max_volume = (size/length)**3 / (6*np.sqrt(2))
        result = generator.tetrahedralize(order=1, quality=True, minratio=1.5,
                                          fixedvolume=True, maxvolume=max_volume,
                                          steinerleft=-1, quiet=True)
        nodes, cells = np.asarray(result[0]), np.asarray(result[1],dtype=int)
        if not len(cells):
            raise MeshError("TetGen no produjo elementos de volumen.")
        # Una PLC puede contener cavidades cerradas sin semillas de agujero.
        # Sus caras son restricciones: quitar las regiones con paridad exterior
        # conserva tanto huecos internos como poros comunicados con el exterior.
        keep = np.empty(len(cells), dtype=bool)
        for start in range(0,len(cells),2000):
            centers = nodes[cells[start:start+2000]].mean(axis=1)
            keep[start:start+len(centers)] = shell.contains(centers)
        discarded = int((~keep).sum())
        cells = cells[keep]
        if not len(cells):
            raise MeshError("No se encontró volumen dentro de la superficie. Revisa cierre y autointersecciones.")
        if discarded:
            warnings.append(f"Se excluyeron {discarded} tetraedros de cavidades o regiones exteriores.")
        actual_volume = np.abs(np.linalg.det(np.stack((nodes[cells[:,1]]-nodes[cells[:,0]],
                         nodes[cells[:,2]]-nodes[cells[:,0]], nodes[cells[:,3]]-nodes[cells[:,0]]),axis=2)))/6
        if np.any(actual_volume > max_volume * 1.02):
            warnings.append("TetGen produjo elementos mayores que el volumen objetivo; revisa la calidad y reduce el tamaño si hace falta.")
        warnings.append(f"Entrada superficial tetraedralizada con TetGen; tamaño nominal {size:g} m (volumen máximo objetivo h³/(6√2)).")
        return nodes*length+origin, cells
    except MeshError:
        raise
    except Exception as exc:
        raise MeshError(f"No se pudo tetraedralizar la superficie: {exc}. Revisa cierre, autointersecciones y tamaño.") from exc


def read_mesh(path, scale=1.0, merge_tolerance=0.0, element_size=None):
    path = Path(path)
    if path.suffix.lower() not in (".vtk", ".vtu", ".stl"):
        raise MeshError("Selecciona una malla .vtk, .vtu o .stl.")
    if not path.is_file():
        raise MeshError(f"No existe el archivo: {path}")
    if not np.isfinite(scale) or scale <= 0:
        raise MeshError("El factor de escala debe ser finito y mayor que cero.")
    captured = StringIO()
    try:
        with _READ_LOCK, voxel_support() as voxels, redirect_stdout(captured), redirect_stderr(captured):
            raw = read_stl(path) if path.suffix.lower()==".stl" else meshio.read(path, file_format=path.suffix.lower()[1:])
    except (Exception, SystemExit) as exc:
        detail = captured.getvalue().strip() or str(exc) or "estructura inválida"
        raise MeshError(f"No se pudo leer {path.name}: {detail}") from None
    diagnostics = captured.getvalue().strip()
    if "cannot handle" in diagnostics:
        raise MeshError("El lector detectó celdas que no puede interpretar; se detuvo para evitar perder elementos. " + diagnostics)
    warnings = [diagnostics] if diagnostics else []
    if voxels:
        warnings.append("Se convirtió VTK_VOXEL a hex8 reordenando 0,1,3,2,4,5,7,6.")
    points = np.asarray(raw.points, dtype=float)*scale
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise MeshError("La entrada necesita coordenadas 3D finitas.")
    volume, triangles, ignored = [], [], {}
    for block in raw.cells:
        data = np.asarray(block.data)
        if not len(data):
            continue
        if data.dtype.kind not in "iu" or data.min() < 0 or data.max() >= len(points):
            raise MeshError("La conectividad referencia nodos inexistentes o no enteros.")
        if block.type in MESHIO_TYPES:
            volume.append(CellBlock(MESHIO_TYPES[block.type], data.copy()))
        elif block.type in LOWER_TYPES:
            ignored[block.type] = ignored.get(block.type,0)+len(data)
            if block.type == "triangle":
                triangles.append(data)
            elif block.type == "quad":
                triangles.extend((data[:,[0,1,2]], data[:,[0,2,3]]))
        else:
            raise MeshError(f"Tipo de celda no compatible: {block.type}. Se admiten tet4, tet10 y hex8.")
    if raw.point_data or raw.cell_data:
        warnings.append("Los atributos PointData/CellData no se convierten en propiedades físicas; se asigna un material a todo el sólido.")
    if scale != 1:
        warnings.append(f"Coordenadas multiplicadas por {scale:g} para expresarlas en metros.")
    if volume:
        if ignored:
            warnings.append(f"Se usan las celdas volumétricas y se reconstruye su frontera; celdas auxiliares omitidas: {ignored}.")
        return Mesh(points, volume, warnings, path, "volumen")
    if not triangles or any(k not in {"triangle", "quad", "vertex", "line"} for k in ignored):
        raise MeshError("No hay volumen ni una superficie lineal de triángulos/cuadriláteros apta para tetraedralizar.")
    points, blocks, merged = merge_points(points, [CellBlock("tri3",np.concatenate(triangles))], merge_tolerance)
    if merged:
        warnings.append(f"Se fusionaron {merged} vértices de la superficie antes del mallado.")
    nodes, cells = tetrahedralize(points, blocks[0].data, element_size, warnings)
    return Mesh(nodes, [CellBlock("tet4",cells)], warnings, path, "superficie → TetGen")
