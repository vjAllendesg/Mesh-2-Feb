import struct
import xml.etree.ElementTree as ET

import meshio
import numpy as np
import pytest

from scaffold_feb.examples import cube, cylinder, hex_grid, surface_triangles
from scaffold_feb.geometry import element_volumes
from scaffold_feb.materials import load_catalog, defaults
from scaffold_feb.model import Options, MeshError
from scaffold_feb.pipeline import prepare
from scaffold_feb.readers import read_mesh
from scaffold_feb.writer import write_feb


@pytest.mark.parametrize("shape",["cube","cylinder"])
@pytest.mark.parametrize("fmt,binary",[("vtk",False),("vtk",True),("vtu",False),("vtu",True),("stl",False),("stl",True)])
def test_all_formats_export(tmp_path,shape,fmt,binary):
    mesh = cube() if shape=="cube" else cylinder()
    kind = "triangle" if fmt=="stl" else "tetra"
    data = surface_triangles(mesh) if fmt=="stl" else mesh.blocks[0].data
    path = tmp_path/f"input.{fmt}"
    meshio.write(path,meshio.Mesh(mesh.points,[(kind,data)]),file_format=fmt,binary=binary)
    if fmt=="stl" and binary:
        payload = bytearray(path.read_bytes())
        payload[:80] = b"solid looks ASCII but is binary".ljust(80,b" ")
        path.write_bytes(payload)
    result = prepare(path,Options(shape=shape,element_size=0.6))
    assert len(result.surfaces)==(6 if shape=="cube" else 2)
    assert all(s.faces for s in result.surfaces)
    assert element_volumes(result.mesh).sum()==pytest.approx(element_volumes(mesh).sum(),rel=1e-6)
    model = load_catalog()["isotropic elastic"]
    out = tmp_path/"model.feb"
    write_feb(out,result.mesh,result.surfaces,model,defaults(model))
    assert len(ET.parse(out).findall("Mesh/Surface"))==len(result.surfaces)


@pytest.mark.parametrize("fmt",["vtu","vtk_ascii","vtk_binary"])
def test_voxel_order(fmt,tmp_path):
    points = cube().points[[0,1,3,2,4,5,7,6]]
    path = tmp_path/("voxel.vtu" if fmt=="vtu" else "voxel.vtk")
    if fmt=="vtu":
        path.write_text('''<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian"><UnstructuredGrid><Piece NumberOfPoints="8" NumberOfCells="1"><Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">'''+
            ' '.join(map(str,points.ravel()))+'''</DataArray></Points><Cells><DataArray type="Int32" Name="connectivity" format="ascii">0 1 2 3 4 5 6 7</DataArray><DataArray type="Int32" Name="offsets" format="ascii">8</DataArray><DataArray type="UInt8" Name="types" format="ascii">11</DataArray></Cells></Piece></UnstructuredGrid></VTKFile>''')
    elif fmt=="vtk_ascii":
        path.write_text('# vtk DataFile Version 3.0\nvoxel\nASCII\nDATASET UNSTRUCTURED_GRID\nPOINTS 8 double\n'+
                        ' '.join(map(str,points.ravel()))+'\nCELLS 1 9\n8 0 1 2 3 4 5 6 7\nCELL_TYPES 1\n11\n')
    else:
        path.write_bytes(b'# vtk DataFile Version 3.0\nvoxel\nBINARY\nDATASET UNSTRUCTURED_GRID\nPOINTS 8 double\n'+
                         points.astype('>f8').tobytes()+b'\nCELLS 1 9\n'+np.array([8,0,1,2,3,4,5,6,7],dtype='>i4').tobytes()+
                         b'\nCELL_TYPES 1\n'+struct.pack('>i',11)+b'\n')
    result = prepare(path)
    assert result.mesh.blocks[0].kind=="hex8"
    assert element_volumes(result.mesh).sum()==pytest.approx(1)
    assert all(len(s.faces)==1 for s in result.surfaces)
    assert any("VTK_VOXEL" in w for w in result.mesh.warnings)


@pytest.mark.parametrize("closed_cavity",[False,True])
def test_tetgen_preserves_voids(tmp_path,closed_cavity):
    mesh = hex_grid(layers=3 if closed_cavity else 1,cavity=closed_cavity)
    path = tmp_path/"porous.stl"
    meshio.write(path,meshio.Mesh(mesh.points,[("triangle",surface_triangles(mesh))]))
    result = prepare(path,Options(element_size=1.5,selected=("Z-","Z+")))
    expected = 26 if closed_cavity else 8
    assert element_volumes(result.mesh).sum()==pytest.approx(expected,rel=1e-6)
    centers = result.mesh.points[result.mesh.blocks[0].data].mean(axis=1)
    inside = np.all((centers[:,:2]>1)&(centers[:,:2]<2),axis=1)
    if closed_cavity:
        inside &= (centers[:,2]>1)&(centers[:,2]<2)
    assert not inside.any()


def test_open_stl_and_missing_size(tmp_path):
    mesh = cube()
    path = tmp_path/"open.stl"
    meshio.write(path,meshio.Mesh(mesh.points,[("triangle",surface_triangles(mesh)[:-1])]))
    with pytest.raises(MeshError,match="superficial"):
        read_mesh(path)
    with pytest.raises(MeshError,match="cerrada"):
        read_mesh(path,element_size=0.5)
