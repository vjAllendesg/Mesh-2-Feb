"""Limpieza, orientación y comprobación geométrica de elementos sólidos."""
from itertools import product

import numpy as np
from scipy.spatial import cKDTree

from .model import CellBlock, Mesh, MeshError, CELL_NODES

# Orden VTK/meshio y FEBio: 4 vértices, aristas 01,12,20,03,13,23.
TET_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
HEX_SIGNS = np.array(list(((-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1),
                          (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1))), dtype=float)
REFLECTION = {"tet4": [1,0,2,3], "tet10": [1,0,2,3,4,6,5,8,7,9],
              "hex8": [1,0,3,2,5,4,7,6]}


class UnionFind:
    def __init__(self, size):
        self.parent = np.arange(size)

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = int(self.parent[i])
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a,b)] = min(a,b)


def merge_points(points, blocks, tolerance):
    """Fusiona por distancia euclídea; usa el primer punto de cada grupo."""
    if not np.isfinite(tolerance) or tolerance < 0:
        raise MeshError("La tolerancia de fusión debe ser un número finito mayor o igual a cero.")
    unique, first, inverse = np.unique(points, axis=0, return_index=True, return_inverse=True)
    if tolerance > 0 and len(unique) > 1:
        tree = cKDTree(unique)
        groups = UnionFind(len(unique))
        # Consultas por punto evitan construir una matriz de pares cuadrática.
        for i, point in enumerate(unique):
            for j in tree.query_ball_point(point, tolerance):
                if j > i:
                    groups.union(i, j)
        roots = np.array([groups.find(i) for i in range(len(unique))])
        _, compact = np.unique(roots, return_inverse=True)
        keep = np.full(compact.max() + 1, len(points), dtype=int)
        np.minimum.at(keep, compact, first)
        representative = points[keep]
        # No unir cadenas que desplacen un vértice más que la tolerancia elegida.
        if np.any(np.linalg.norm(unique - representative[compact], axis=1) > tolerance * (1 + 1e-10)):
            raise MeshError("La fusión forma una cadena mayor que la tolerancia. Reduce la tolerancia de fusión.")
        inverse = compact[inverse]
        unique = representative
    mapped = [CellBlock(b.kind, inverse[b.data]) for b in blocks]
    return unique, mapped, len(points) - len(unique)


def remove_orphans(mesh):
    used = np.unique(np.concatenate([b.data.ravel() for b in mesh.blocks]))
    removed = len(mesh.points) - len(used)
    remap = np.full(len(mesh.points), -1, dtype=int)
    remap[used] = np.arange(len(used))
    mesh.points = mesh.points[used]
    mesh.blocks = [CellBlock(b.kind, remap[b.data]) for b in mesh.blocks]
    return removed


def validate_arrays(mesh):
    p = np.asarray(mesh.points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not len(p) or not np.isfinite(p).all():
        raise MeshError("La malla necesita coordenadas 3D finitas y al menos un nodo.")
    mesh.points = p
    if not mesh.blocks or not mesh.element_count:
        raise MeshError("La malla no contiene elementos de volumen.")
    seen = set()
    for b in mesh.blocks:
        if b.kind not in CELL_NODES:
            raise MeshError(f"Elemento no compatible: {b.kind}. Se admiten tet4, tet10 y hex8.")
        if b.data.ndim != 2 or b.data.shape[1] != CELL_NODES[b.kind] or b.data.dtype.kind not in "iu":
            raise MeshError(f"Conectividad inválida en {b.kind}.")
        if b.data.size and (b.data.min() < 0 or b.data.max() >= len(p)):
            raise MeshError(f"{b.kind}: se hace referencia a nodos inexistentes.")
        if np.any(np.diff(np.sort(b.data, axis=1), axis=1) == 0):
            raise MeshError(f"{b.kind}: hay nodos repetidos en un elemento; revisa la tolerancia de fusión.")
        for row in b.data:
            key = (b.kind, *sorted(row.tolist()))
            if key in seen:
                raise MeshError("Hay elementos volumétricos duplicados. Corrige la malla de entrada.")
            seen.add(key)


def shape_gradients(kind, q):
    """Derivadas respecto de las coordenadas naturales, según el orden FEBio."""
    r, s, t = q
    if kind == "tet4":
        return np.array([[-1.,-1.,-1.], [1.,0.,0.], [0.,1.,0.], [0.,0.,1.]])
    if kind == "tet10":
        bary = np.array([1-r-s-t, r, s, t])
        base = shape_gradients("tet4", q)
        grad = np.empty((10, 3))
        grad[:4] = (4*bary[:,None]-1)*base
        for k, (i,j) in enumerate(TET_EDGES):
            grad[k+4] = 4*(bary[i]*base[j] + bary[j]*base[i])
        return grad
    grad = np.empty((8, 3))
    natural = np.array(q)
    for a in range(3):
        other = [i for i in range(3) if i != a]
        grad[:,a] = HEX_SIGNS[:,a] * np.prod(1 + HEX_SIGNS[:,other]*natural[other], axis=1)/8
    return grad


def sample_points(kind):
    if kind == "tet4":
        return [(0.25,0.25,0.25)]
    if kind == "tet10":
        # Lattice de grado 4 más puntos de integración tetraédricos.
        pts = [(i/4,j/4,k/4) for i in range(5) for j in range(5-i) for k in range(5-i-j)]
        a, b = 0.5854101966249685, 0.1381966011250105
        return pts + [(b,b,b), (a,b,b), (b,a,b), (b,b,a)]
    g = 1/np.sqrt(3)
    return list(product((-1.,0.,1.), repeat=3)) + list(product((-g,g), repeat=3))


def jacobian_limits(points, kind, data):
    xyz = points[data]
    xyz = xyz - xyz[:, :1]
    low = np.full(len(data), np.inf)
    high = np.full(len(data), -np.inf)
    for q in sample_points(kind):
        det = np.linalg.det(np.einsum("eni,nj->eij", xyz, shape_gradients(kind, q)))
        low = np.minimum(low, det)
        high = np.maximum(high, det)
    scale = np.max(np.ptp(xyz, axis=1), axis=1)
    return low, high, np.maximum(scale**3 * 1e-12, np.finfo(float).tiny)


def orient_and_validate(mesh):
    corrected = 0
    for block in mesh.blocks:
        # Acotar memoria en mallas grandes, especialmente tet10.
        for start in range(0, len(block.data), 20000):
            data = block.data[start:start+20000]
            low, high, tol = jacobian_limits(mesh.points, block.kind, data)
            inverted = high < -tol
            data[inverted] = data[inverted][:, REFLECTION[block.kind]]
            corrected += int(inverted.sum())
            if inverted.any():
                low, high, tol = jacobian_limits(mesh.points, block.kind, data)
            bad = (~np.isfinite(low)) | (low <= tol)
            if bad.any():
                first = (np.flatnonzero(bad)[:5] + start + 1).tolist()
                raise MeshError(f"{block.kind}: Jacobiano no positivo o degenerado en elementos {first}. "
                                "Una permutación no repara un elemento plegado; revisa la malla.")
    if corrected:
        mesh.warnings.append(f"Se corrigió la orientación de {corrected} elementos.")
    if any(b.kind != "tet4" for b in mesh.blocks):
        mesh.warnings.append("Jacobianos comprobados en nodos y puntos interiores; el muestreo no es una certificación global de elementos curvos.")


def element_volumes(mesh):
    volumes = []
    for block in mesh.blocks:
        xyz = mesh.points[block.data]
        xyz = xyz - xyz[:, :1]
        if block.kind == "tet4":
            v = np.linalg.det(np.einsum("eni,nj->eij", xyz, shape_gradients("tet4", (0,0,0))))/6
        elif block.kind == "hex8":
            g = 1/np.sqrt(3)
            v = sum(np.linalg.det(np.einsum("eni,nj->eij", xyz, shape_gradients("hex8", q)))
                    for q in product((-g,g), repeat=3))
        else:
            # Regla de grado 3 exacta para el determinante cúbico de tet10.
            qs = [(0.25,0.25,0.25), (1/6,1/6,1/6), (0.5,1/6,1/6),
                  (1/6,0.5,1/6), (1/6,1/6,0.5)]
            ws = [-2/15, 3/40, 3/40, 3/40, 3/40]
            v = sum(w*np.linalg.det(np.einsum("eni,nj->eij", xyz, shape_gradients("tet10", q)))
                    for q,w in zip(qs,ws))
        volumes.append(v)
    return np.concatenate(volumes)


def clean_mesh(mesh, tolerance=0.0):
    validate_arrays(mesh)
    mesh.points, mesh.blocks, merged = merge_points(mesh.points, mesh.blocks, tolerance)
    if merged:
        mesh.warnings.append(f"Se fusionaron {merged} nodos duplicados (tolerancia {tolerance:g} m).")
    validate_arrays(mesh)
    removed = remove_orphans(mesh)
    if removed:
        mesh.warnings.append(f"Se eliminaron {removed} nodos huérfanos.")
    orient_and_validate(mesh)
    return mesh
