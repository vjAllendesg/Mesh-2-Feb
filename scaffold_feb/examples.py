"""Genera ejemplos pequeños reproducibles; no modifica geometrías del usuario."""
from pathlib import Path
import argparse

import meshio
import numpy as np

from .geometry import clean_mesh, TET_EDGES
from .model import Mesh, CellBlock
from .surfaces import extract_boundary


def cube():
    points = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],
                       [0,0,1],[1,0,1],[1,1,1],[0,1,1]],dtype=float)
    cells = np.array([[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6],[0,5,1,6]])
    return Mesh(points,[CellBlock("tet4",cells)])


def cylinder(segments=16):
    angles = np.arange(segments)*2*np.pi/segments
    ring = np.column_stack((0.5*np.cos(angles),0.5*np.sin(angles),np.zeros(segments)))
    lower = np.vstack(([0,0,0],ring))
    points = np.vstack((lower,lower+[0,0,1]))
    stride = segments+1
    cells = []
    for i in range(segments):
        a,b,c = 0,i+1,(i+1)%segments+1
        A,B,C = a+stride,b+stride,c+stride
        cells.extend(((a,b,c,C),(a,b,B,C),(a,A,B,C)))
    return clean_mesh(Mesh(points,[CellBlock("tet4",np.asarray(cells))]))


def quadratic(mesh):
    points = mesh.points.tolist()
    edge_nodes = {}
    blocks = []
    for block in mesh.blocks:
        cells = []
        for row in block.data:
            cell = row.tolist()
            for i,j in TET_EDGES:
                edge = tuple(sorted((int(row[i]),int(row[j]))))
                if edge not in edge_nodes:
                    edge_nodes[edge] = len(points)
                    points.append(((mesh.points[edge[0]]+mesh.points[edge[1]])/2).tolist())
                cell.append(edge_nodes[edge])
            cells.append(cell)
        blocks.append(CellBlock("tet10",np.asarray(cells)))
    return Mesh(np.asarray(points),blocks)


def hex_grid(n=3, layers=1, cavity=False):
    points = np.array([(x,y,z) for z in range(layers+1) for y in range(n+1) for x in range(n+1)],dtype=float)
    def node(x,y,z):
        return x+(n+1)*y+(n+1)**2*z
    cells = []
    for z in range(layers):
        for y in range(n):
            for x in range(n):
                if x==1 and y==1 and (not cavity or z==1):
                    continue
                cells.append([node(x,y,z),node(x+1,y,z),node(x+1,y+1,z),node(x,y+1,z),
                              node(x,y,z+1),node(x+1,y,z+1),node(x+1,y+1,z+1),node(x,y+1,z+1)])
    return Mesh(points,[CellBlock("hex8",np.asarray(cells))])


def surface_triangles(mesh):
    faces = extract_boundary(mesh)
    triangles = []
    for face in faces:
        n = face.nodes
        if face.kind == "quad4":
            triangles.extend(((n[0],n[1],n[2]),(n[0],n[2],n[3])))
        else:
            triangles.append(n[:3])
    return np.asarray(triangles)


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    paths = []
    for name,mesh in (("cubo",cube()),("cilindro",cylinder())):
        raw = meshio.Mesh(mesh.points,[("tetra",mesh.blocks[0].data)])
        for suffix,fmt,binary in (("ascii.vtk","vtk",False),("binario.vtk","vtk",True),(".vtu","vtu",True)):
            path = directory/(name+("" if suffix.startswith(".") else "_")+suffix)
            meshio.write(path,raw,file_format=fmt,binary=binary)
            paths.append(path)
        surface = meshio.Mesh(mesh.points,[("triangle",surface_triangles(mesh))])
        for suffix,binary in (("ascii",False),("binario",True)):
            path = directory/f"{name}_{suffix}.stl"
            meshio.write(path,surface,file_format="stl",binary=binary)
            if binary:
                payload = bytearray(path.read_bytes())
                payload[:80] = b"solid binary STL: comprobar estructura".ljust(80,b" ")
                path.write_bytes(payload)
            paths.append(path)
    q = quadratic(cube())
    path = directory/"cubo_tet10.vtu"
    meshio.write(path,meshio.Mesh(q.points,[("tetra10",q.blocks[0].data)]))
    paths.append(path)
    hex_mesh = meshio.Mesh(cube().points,[("hexahedron",np.arange(8)[None,:])])
    path = directory/"cubo_hex8.vtu"
    meshio.write(path,hex_mesh)
    paths.append(path)
    ring = hex_grid()
    path = directory/"cubo_con_poro.stl"
    meshio.write(path,meshio.Mesh(ring.points,[("triangle",surface_triangles(ring))]),binary=True)
    paths.append(path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generar ejemplos del conversor")
    parser.add_argument("directory",nargs="?",default="examples")
    for path in generate(parser.parse_args().directory):
        print(path)
