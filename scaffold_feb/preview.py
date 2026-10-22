"""Vista opcional ejecutada en un proceso independiente de la interfaz."""
from pathlib import Path
import sys
import numpy as np


def main(path):
    try:
        import pyvista as pv
    except ImportError:
        raise SystemExit("Vista previa opcional: instala requirements-preview.txt.")
    with np.load(Path(path),allow_pickle=False) as data:
        points = data["points"]
        plotter = pv.Plotter(title="Superficies para FEBio")
        plotter.set_background("#f4f6f8")
        plotter.add_mesh(pv.PolyData(points,data["boundary"]),color="#bdc8d1",opacity=0.2,show_edges=False)
        colors = ["#195f9b", "#c45524", "#24835d", "#a24b85", "#86772c", "#7d5db0"]
        for i,name in enumerate(data["names"].tolist()):
            plotter.add_mesh(pv.PolyData(points,data[f"surface_{i}"]),color=colors[i%len(colors)],label=name,show_edges=True)
        if len(data["names"]):
            plotter.add_legend()
        plotter.add_axes()
        plotter.show_grid(xtitle="X (m)",ytitle="Y (m)",ztitle="Z (m)")
        plotter.show()


def face_stream(faces):
    records = []
    for face in faces:
        n = face.nodes
        if face.kind == "tri6":
            # La vista subdivide cada tri6; el FEB conserva la cara cuadrática.
            for tri in ((n[0],n[3],n[5]),(n[3],n[1],n[4]),(n[5],n[4],n[2]),(n[3],n[4],n[5])):
                records.extend((3,*tri))
        else:
            records.extend((len(n),*n))
    return np.asarray(records,dtype=np.int64)


if __name__ == "__main__":
    main(sys.argv[1])
