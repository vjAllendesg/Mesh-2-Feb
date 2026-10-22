"""Flujo compartido: preparar malla y seleccionar superficies."""
from dataclasses import dataclass

from .geometry import clean_mesh
from .model import Mesh, Options, Surface, Face
from .readers import read_mesh
from .surfaces import extract_boundary, select_surfaces


@dataclass
class Prepared:
    mesh: Mesh
    boundary: list[Face]
    surfaces: list[Surface]
    axis: str | None
    plane_tolerance: float

    def summary(self):
        result = self.mesh.summary()
        details = {}
        for surface in self.surfaces:
            points = self.mesh.points[surface.nodes]
            low, high = points.min(axis=0), points.max(axis=0)
            details[surface.name] = {"caras":len(surface.faces), "nodos":len(surface.nodes),
                                     "bounding_box_m":[low.tolist(),high.tolist()],
                                     "tipos_cara":sorted({f.kind for f in surface.faces})}
            axis = "XYZ".index(self.axis if self.axis else surface.name[0])
            span = self.mesh.bounds[1,axis] - self.mesh.bounds[0,axis]
            fraction = float((high[axis] - low[axis]) / span)
            if fraction > 0.01:
                result["advertencias"].append(
                    f"{surface.name}: la selección ocupa {fraction:.1%} de la dimensión "
                    f"en {'XYZ'[axis]}; puede incluir paredes laterales. Reduce la tolerancia "
                    "del plano y revisa la vista 3D si buscas solo la tapa.")
        result.update({"caras_exteriores": len(self.boundary), "eje_cilindro": self.axis,
                       "tolerancia_plano_m": self.plane_tolerance,
                       "superficies": details})
        return result


def prepare(path, options=None):
    opt = options or Options()
    mesh = read_mesh(path, opt.scale, opt.merge_tolerance, opt.element_size)
    clean_mesh(mesh, opt.merge_tolerance)
    boundary = extract_boundary(mesh, opt.largest_component)
    selected, axis, tolerance = select_surfaces(mesh, boundary, opt.shape, opt.axis,
                                               opt.plane_tolerance, opt.selected)
    return Prepared(mesh, boundary, selected, axis, tolerance)
