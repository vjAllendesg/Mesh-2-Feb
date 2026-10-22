import xml.etree.ElementTree as ET

import meshio
import numpy as np
import pytest

from scaffold_feb.examples import cube, cylinder, quadratic, hex_grid, surface_triangles
from scaffold_feb.geometry import clean_mesh, element_volumes, REFLECTION
from scaffold_feb.materials import load_catalog, defaults
from scaffold_feb.model import Mesh, CellBlock, MeshError, Options
from scaffold_feb.pipeline import prepare
from scaffold_feb.readers import read_mesh
from scaffold_feb.surfaces import extract_boundary, select_surfaces, face_normal
from scaffold_feb.writer import write_feb


def test_cube_faces_normals_and_nodes():
    mesh = clean_mesh(cube())
    faces = extract_boundary(mesh)
    surfaces,_,_ = select_surfaces(mesh,faces)
    assert len(mesh.points)==8 and mesh.element_count==6 and len(faces)==12
    assert len(surfaces)==6
    for surface in surfaces:
        assert len(surface.faces)==2 and len(surface.nodes)==4
        axis = "XYZ".index(surface.name[0])
        sign = -1 if surface.name[1]=="-" else 1
        assert all(sign*face_normal(mesh.points,f)[axis] > 0 for f in surface.faces)


@pytest.mark.parametrize("kind",["tet4","tet10","hex8"])
def test_inverted_elements(kind):
    mesh = cube() if kind=="tet4" else quadratic(cube()) if kind=="tet10" else Mesh(cube().points,[CellBlock("hex8",np.arange(8)[None,:])])
    mesh.blocks[0].data = mesh.blocks[0].data[:,REFLECTION[kind]]
    clean_mesh(mesh)
    assert any("orientación" in s for s in mesh.warnings)
    assert element_volumes(mesh).sum()==pytest.approx(1.)
    faces = extract_boundary(mesh)
    assert all(np.dot(face_normal(mesh.points,f),mesh.points[list(f.nodes[:3])].mean(axis=0)-0.5)>0 for f in faces)


def test_curved_tet10_is_not_checked_only_at_corners():
    mesh = quadratic(Mesh(cube().points[:4].copy(),[CellBlock("tet4",np.array([[0,1,2,3]]))]))
    # Tetra no coplanar, con nodo de arista movido a una posición que pliega el mapa.
    p = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],dtype=float)
    mesh = quadratic(Mesh(p,[CellBlock("tet4",np.array([[0,1,2,3]]))]))
    mesh.points[4] = [-2,0,0]
    with pytest.raises(MeshError,match="Jacobiano"):
        clean_mesh(mesh)


def test_tet10_mid_nodes_and_planar_filter():
    mesh = clean_mesh(quadratic(cube()))
    faces = extract_boundary(mesh)
    assert all(f.kind=="tri6" and len(f.nodes)==6 for f in faces)
    surfaces,_,_ = select_surfaces(mesh,faces)
    assert all(len(s.nodes)==9 for s in surfaces)
    face = next(f for f in faces if np.all(mesh.points[list(f.nodes),2]==0))
    mesh.points[face.nodes[3],2] = 0.001
    from scaffold_feb.surfaces import plane_faces
    assert face not in plane_faces(mesh,faces,2,0,1e-6)


def test_duplicates_orphans_and_degeneracy():
    mesh = cube()
    mesh.points = np.vstack((mesh.points,mesh.points[0]+[1e-8,0,0],[9,9,9]))
    mesh.blocks[0].data[0,0] = 8
    clean_mesh(mesh,1e-7)
    assert len(mesh.points)==8
    assert any("fusionaron" in s for s in mesh.warnings)
    assert any("huérfanos" in s for s in mesh.warnings)
    with pytest.raises(MeshError,match="repetidos"):
        clean_mesh(cube(),2.)


def test_largest_uses_volume_not_cell_count():
    small = cube()
    points = np.vstack((small.points*0.1,small.points+[3,0,0]))
    blocks = [small.blocks[0],CellBlock("hex8",np.arange(8,16)[None,:])]
    mesh = clean_mesh(Mesh(points,blocks))
    extract_boundary(mesh,True)
    assert mesh.element_count==1
    assert mesh.blocks[0].kind=="hex8"
    assert element_volumes(mesh).sum()==pytest.approx(1)


@pytest.mark.parametrize("axis",[0,1,2])
def test_cylinder_axis_and_caps(axis):
    mesh = cylinder()
    mesh.points[:,[axis,2]] = mesh.points[:,[2,axis]]
    clean_mesh(mesh)
    faces = extract_boundary(mesh)
    surfaces,detected,_ = select_surfaces(mesh,faces,"cylinder")
    assert detected=="XYZ"[axis]
    assert len(surfaces)==2 and all(len(s.faces)==16 for s in surfaces)


def test_porous_plane_is_not_filled():
    mesh = clean_mesh(hex_grid())
    surfaces,_,_ = select_surfaces(mesh,extract_boundary(mesh),selected=("Z-","Z+"))
    assert [len(s.faces) for s in surfaces]==[8,8]
    assert element_volumes(mesh).sum()==pytest.approx(8)


def test_writer_reference_structure_and_indices(tmp_path):
    mesh = clean_mesh(quadratic(cube()))
    surfaces,_,_ = select_surfaces(mesh,extract_boundary(mesh))
    model = load_catalog()["neo-Hookean"]
    out = tmp_path/"model.feb"
    write_feb(out,mesh,surfaces,model,defaults(model))
    root = ET.parse(out).getroot()
    assert root.attrib=={"version":"4.0"}
    assert root.findtext("Module/units")=="SI"
    assert root.find("Step") is None and root.find("Boundary") is None
    assert len(root.findall("Mesh/Nodes/node"))==len(mesh.points)
    assert len(root.findall("Mesh/Elements/elem"))==6
    for surface in surfaces:
        node_set = root.find(f"Mesh/NodeSet[@name='{surface.name}']")
        exported = root.find(f"Mesh/Surface[@name='{surface.name}']")
        assert set(map(int,node_set.text.split(',')))=={n+1 for n in surface.nodes}
        assert [f.tag for f in exported]==["tri6","tri6"]
        assert [int(f.get("id")) for f in exported]==[1,2]
    with pytest.raises(MeshError,match="ya existe"):
        write_feb(out,mesh,surfaces,model,defaults(model))


@pytest.mark.parametrize("bad",[b"",b"not a mesh",b"solid bad\nendsolid bad\n"])
def test_invalid_file(tmp_path,bad):
    path = tmp_path/"bad.stl"
    path.write_bytes(bad)
    with pytest.raises(MeshError):
        read_mesh(path,element_size=0.5)


def test_scale_and_negative_tolerance(tmp_path):
    mesh = cube()
    p = tmp_path/"mm.vtu"
    meshio.write(p,meshio.Mesh(mesh.points*1000,[("tetra",mesh.blocks[0].data)]))
    assert prepare(p,Options(scale=0.001)).mesh.bounds[1].tolist()==[1,1,1]
    with pytest.raises(MeshError,match="tolerancia"):
        prepare(p,Options(merge_tolerance=-1))
