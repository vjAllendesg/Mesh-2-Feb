"""Catálogo extensible de materiales escalares, sin listas de tipos en código."""
import json
import math
from pathlib import Path
import re

from .model import MeshError


def load_catalog(path=None):
    path = Path(path) if path else Path(__file__).with_name("materials.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["materials"]
        if not isinstance(items, list) or not items:
            raise ValueError("falta la lista materials")
        catalog = {}
        labels = set()
        for item in items:
            name = item["type"]
            if not isinstance(name,str) or not name.strip() or name in catalog:
                raise ValueError("tipo de material vacío o duplicado")
            if not isinstance(item["label"],str) or not isinstance(item["parameters"],list):
                raise ValueError("label o parameters inválido")
            if not item["label"].strip() or item["label"] in labels:
                raise ValueError("etiqueta de material vacía o duplicada")
            labels.add(item["label"])
            names = []
            for spec in item["parameters"]:
                key = spec["name"]
                if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*",key):
                    raise ValueError("nombre de parámetro XML inválido")
                if key in names:
                    raise ValueError("parámetro duplicado")
                names.append(key)
                for field in ("label", "unit", "default"):
                    if field not in spec:
                        raise ValueError(f"falta {field} en {key}")
            catalog[name] = item
            validate_material(item, defaults(item))
        return catalog
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MeshError(f"Catálogo de materiales inválido ({path.name}): {exc}") from exc


def defaults(model):
    return {spec["name"]: spec["default"] for spec in model["parameters"]}


def validate_material(model, values):
    expected = {p["name"] for p in model["parameters"]}
    if set(values) != expected:
        raise MeshError("Los parámetros no coinciden con el material elegido: " + ", ".join(sorted(expected)))
    result = {}
    for spec in model["parameters"]:
        name = spec["name"]
        try:
            if isinstance(values[name],bool):
                raise ValueError()
            value = float(values[name])
        except (ValueError, TypeError):
            raise MeshError(f"{name} debe ser un número. Usa punto para los decimales.") from None
        if not math.isfinite(value):
            raise MeshError(f"{name} debe ser finito.")
        for key,invalid,description in (("min",lambda v,b:v<b,"mayor o igual a"),
                ("max",lambda v,b:v>b,"menor o igual a"),
                ("min_exclusive",lambda v,b:v<=b,"mayor que"),
                ("max_exclusive",lambda v,b:v>=b,"menor que")):
            if key in spec and invalid(value,float(spec[key])):
                raise MeshError(f"{name} debe ser {description} {spec[key]} {spec['unit']}.")
        result[name] = value
    return result
