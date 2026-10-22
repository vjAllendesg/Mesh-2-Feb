"""Estructuras compartidas por el núcleo, la CLI y la interfaz."""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


class MeshError(ValueError):
    """Error de entrada o geometría que se puede mostrar al usuario."""


CELL_NODES = {"tet4": 4, "tet10": 10, "hex8": 8}
CORNER_COUNT = {"tet4": 4, "tet10": 4, "hex8": 8}


@dataclass
class CellBlock:
    kind: str
    data: np.ndarray


@dataclass
class Mesh:
    points: np.ndarray
    blocks: list[CellBlock]
    warnings: list[str] = field(default_factory=list)
    source: Path | None = None
    input_kind: str = "volumen"

    @property
    def element_count(self):
        return sum(len(b.data) for b in self.blocks)

    @property
    def bounds(self):
        return np.stack((self.points.min(axis=0), self.points.max(axis=0)))

    def summary(self):
        counts = {}
        for block in self.blocks:
            counts[block.kind] = counts.get(block.kind, 0) + len(block.data)
        return {"entrada": self.input_kind, "nodos": len(self.points),
                "elementos": counts, "bounding_box_m": self.bounds.tolist(),
                "advertencias": self.warnings.copy()}


@dataclass
class Face:
    kind: str
    nodes: tuple[int, ...]
    owner: int


@dataclass
class Surface:
    name: str
    faces: list[Face]

    @property
    def nodes(self):
        return sorted({n for face in self.faces for n in face.nodes})


@dataclass
class Options:
    scale: float = 1.0
    merge_tolerance: float = 0.0
    largest_component: bool = False
    element_size: float | None = None
    shape: str = "cube"
    axis: str = "auto"
    plane_tolerance: float | None = None
    selected: tuple[str, ...] | None = None
