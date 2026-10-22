"""Nombres breves y legibles, con sufijo numérico solo si hay coincidencias."""
from datetime import datetime
from pathlib import Path


def new_directory(parent, name):
    parent = Path(parent)
    number = 1
    while True:
        candidate = parent/(name if number==1 else f"{name}_{number}")
        try:
            candidate.mkdir()
            return candidate.resolve()
        except FileExistsError:
            number += 1


def run_directory(parent, prefix, when=None):
    date = (when or datetime.now()).strftime("%Y-%m-%d_%H-%M")
    return new_directory(parent, f"{prefix}_{date}")


def reserve_filename(name, used):
    path = Path(name)
    candidate = name
    number = 2
    while candidate.casefold() in used:
        candidate = f"{path.stem}_{number}{path.suffix}"
        number += 1
    used.add(candidate.casefold())
    return candidate


def short_log_name(filename):
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    for suffix, short in (("fuerza_inferior.txt","F_inf.txt"), ("fuerza_superior.txt","F_sup.txt"),
                          ("stress_inferior.txt","S_inf.txt"), ("stress_superior.txt","S_sup.txt"),
                          ("F_inf.txt","F_inf.txt"), ("F_sup.txt","F_sup.txt"),
                          ("S_inf.txt","S_inf.txt"), ("S_sup.txt","S_sup.txt")):
        if name.casefold().endswith(suffix.casefold()):
            return short
    return name or "datos.txt"
