"""Ejecución secuencial de FEBio en carpetas nuevas, con cancelación propia."""
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

from .model import MeshError
from .names import run_directory, new_directory, reserve_filename, short_log_name


def find_solver():
    for name in ("febio4", "febio"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            path = Path(base)/"FEBioStudio"/"bin"/"febio4.exe"
            if path.is_file():
                return str(path)
    return ""


def tail_text(path, limit=65536):
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def normal_termination(path):
    # Se exige confirmación del solver: hay errores FEBio con código de salida 0.
    return "NORMALTERMINATION" in re.sub(r"\s+", "", tail_text(path, 131072)).upper()


def prepare_input(source, directory):
    source = Path(source)
    tree = ET.parse(source)
    root = tree.getroot()
    if root.tag != "febio_spec":
        raise MeshError("El archivo no tiene raíz febio_spec.")
    if root.find("Step") is None and root.find("Control") is None:
        raise MeshError("El FEB contiene solo geometría. Exporta con un protocolo de simulación.")
    for element in root.iter():
        if element.get("from"):
            included = Path(element.get("from"))
            if not included.is_absolute():
                element.set("from", str((source.parent/included).resolve()))
    used = {name.casefold() for name in (source.name,"solver.log","consola.txt","resultados.xplt","comando.json")}
    for element in root.findall("Output/logfile/*"):
        filename = element.get("file")
        if filename:
            # Todos los registros propios de esta ejecución quedan en su carpeta.
            element.set("file",reserve_filename(short_log_name(filename),used))
    target = directory/source.name
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


class SolverBatch:
    """Un hilo supervisa un único proceso FEBio a la vez."""
    def __init__(self, solver, inputs, output_directory, callback=None):
        self.command = [str(solver)] if isinstance(solver, (str, Path)) else list(map(str, solver))
        self.inputs = list(dict.fromkeys(Path(path).resolve() for path in inputs))
        self.output_directory = Path(output_directory)
        self.callback = callback or (lambda event: None)
        self.stop = threading.Event()
        self.thread = None
        self.process = None
        self.directory = None
        self.report = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.thread is not None:
            raise MeshError("Esta ejecución ya se inició.")
        executable = shutil.which(self.command[0]) or self.command[0]
        if not Path(executable).is_file():
            raise MeshError("Selecciona el ejecutable del solver FEBio (febio4.exe o febio4).")
        if not self.inputs:
            raise MeshError("Añade al menos un archivo FEB para ejecutar.")
        if not self.output_directory.is_dir():
            raise MeshError("Selecciona una carpeta de resultados existente.")
        self.command[0] = str(Path(executable).resolve())
        self.directory = run_directory(self.output_directory,"SIM")
        self.thread = threading.Thread(target=self._run, name="FEBio-batch", daemon=True)
        self.thread.start()
        return self.directory

    def cancel(self):
        self.stop.set()

    def emit(self, kind, **data):
        self.callback(dict(kind=kind, **data))

    def _job(self, index, source):
        directory = new_directory(self.directory,source.stem)
        log = directory/"solver.log"
        console = directory/"consola.txt"
        row = dict(input=str(source), directory=str(directory), log=str(log),
                   status="error", returncode=None, seconds=0., message="")
        started = time.monotonic()
        self.emit("started", index=index, input=str(source), directory=str(directory), log=str(log))
        try:
            if source.suffix.lower() != ".feb":
                raise MeshError("La entrada debe tener extensión .feb.")
            target = prepare_input(source, directory)
            command = [*self.command, "-i", str(target.resolve()), "-o", str(log.resolve()),
                       "-p", str((directory/"resultados.xplt").resolve()), "-silent"]
            (directory/"comando.json").write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8")
            with console.open("wb") as output:
                kwargs = {"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
                self.process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                                stdout=output, stderr=subprocess.STDOUT, **kwargs)
                offset = 0
                while self.process.poll() is None:
                    if self.stop.wait(.15):
                        self.process.terminate()
                        try:
                            self.process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            self.process.kill()
                            self.process.wait(timeout=3)
                        row.update(status="cancelled", message="Detenida por el usuario.")
                        break
                    if log.is_file():
                        try:
                            with log.open("rb") as stream:
                                stream.seek(offset)
                                chunk = stream.read(65536)
                                offset += len(chunk)
                            if chunk:
                                self.emit("output", index=index, text=chunk.decode("utf-8", errors="replace"))
                        except OSError:
                            pass
                    self.emit("heartbeat", index=index, seconds=time.monotonic()-started)
                row["returncode"] = self.process.wait()
            if row["status"] != "cancelled":
                if row["returncode"]==0 and normal_termination(log):
                    row.update(status="ok", message="Terminación normal confirmada por FEBio.")
                else:
                    row["message"] = f"FEBio no confirmó terminación normal (código {row['returncode']}). Consulta solver.log y consola.txt."
            self.emit("output", index=index, text=tail_text(log) or tail_text(console), replace=True)
        except Exception as exc:
            row["message"] = str(exc)
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process = None
            row["seconds"] = round(time.monotonic()-started, 3)
        return row

    def _run(self):
        rows = []
        try:
            for index, source in enumerate(self.inputs):
                if self.stop.is_set():
                    row = dict(input=str(source), directory="", log="", status="cancelled", returncode=None,
                               seconds=0., message="No iniciada: lote detenido.")
                else:
                    row = self._job(index, source)
                rows.append(row)
                with (self.directory/"resultados.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False)+"\n")
                self.emit("finished_job", index=index, result=row)
            report = dict(directory=str(self.directory), ok=sum(r["status"]=="ok" for r in rows),
                          errors=sum(r["status"]=="error" for r in rows),
                          cancelled=sum(r["status"]=="cancelled" for r in rows), results=rows)
            (self.directory/"resumen.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            with (self.directory/"resumen.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["input","directory","status","returncode","seconds","message","log"])
                writer.writeheader()
                writer.writerows(rows)
            self.report = report
            self.emit("done", report=report)
        except Exception as exc:
            self.emit("error", message=str(exc), directory=str(self.directory))
