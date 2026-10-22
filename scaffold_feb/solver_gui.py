"""Pestaña de ejecución: el solver se supervisa fuera del hilo de Tkinter."""
from pathlib import Path
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .model import MeshError
from .solver import SolverBatch, find_solver, tail_text

STATES = {"ok":"Completada", "error":"Error", "cancelled":"Cancelada"}


class SolverTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=16)
        self.paths = []
        self.results = {}
        self.last_export = []
        self.runner = None
        self.events = Queue()
        self.solver = tk.StringVar(value=find_solver())
        self.destination = tk.StringVar()
        self.auto_run = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Carga el último lote exportado o añade archivos FEB.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=2)
        self.rowconfigure(6, weight=3)
        executable = ttk.Frame(self)
        executable.grid(row=0, column=0, sticky="ew")
        executable.columnconfigure(1, weight=1)
        ttk.Label(executable, text="Solver FEBio").grid(row=0, column=0, sticky="w", padx=(0,10))
        self.solver_entry = ttk.Entry(executable, textvariable=self.solver)
        self.solver_entry.grid(row=0, column=1, sticky="ew")
        self.solver_browse = ttk.Button(executable, text="Buscar…", command=self._browse_solver)
        self.solver_browse.grid(row=0, column=2, padx=(8,0))
        tools = ttk.Frame(self)
        tools.grid(row=1, column=0, sticky="ew", pady=10)
        self.load_button = ttk.Button(tools, text="Cargar último lote", command=self.load_last)
        self.load_button.pack(side="left")
        self.add_button = ttk.Button(tools, text="Añadir FEB…", command=self._browse_inputs)
        self.add_button.pack(side="left", padx=8)
        self.folder_button = ttk.Button(tools, text="Añadir carpeta…", command=self._browse_folder)
        self.folder_button.pack(side="left")
        self.remove_button = ttk.Button(tools, text="Quitar seleccionados", command=self._remove)
        self.remove_button.pack(side="left", padx=8)
        ttk.Checkbutton(self, text="Ejecutar automáticamente al terminar de exportar un lote",
                        variable=self.auto_run).grid(row=2, column=0, sticky="w", pady=(0,8))
        table = ttk.Frame(self)
        table.grid(row=3, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("status","time"), selectmode="extended", height=7)
        self.tree.heading("#0", text="Archivo FEB")
        self.tree.heading("status", text="Estado")
        self.tree.heading("time", text="Tiempo transcurrido")
        self.tree.column("#0", width=550, stretch=True)
        self.tree.column("status", width=150, stretch=False)
        self.tree.column("time", width=150, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _:self.show_log())
        destination = ttk.Frame(self)
        destination.grid(row=4, column=0, sticky="ew", pady=10)
        destination.columnconfigure(1, weight=1)
        ttk.Label(destination, text="Resultados").grid(row=0, column=0, padx=(0,10))
        self.destination_entry = ttk.Entry(destination, textvariable=self.destination)
        self.destination_entry.grid(row=0, column=1, sticky="ew")
        self.destination_button = ttk.Button(destination, text="Elegir carpeta…", command=self._browse_destination)
        self.destination_button.grid(row=0, column=2, padx=(8,0))
        ttk.Label(self, text="Cada ejecución crea una carpeta nueva con copias de los FEB, resultados XPLT, registros y resumen.",
                  wraplength=850, style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(0,8))
        logs = ttk.Frame(self)
        logs.grid(row=6, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log = tk.Text(logs, height=12, wrap="word", font=("TkFixedFont",9), state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll_log = ttk.Scrollbar(logs, orient="vertical", command=self.log.yview)
        scroll_log.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll_log.set)
        footer = ttk.Frame(self)
        footer.grid(row=7, column=0, sticky="ew", pady=(12,0))
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0,12))
        self.run_button = ttk.Button(footer, text="Iniciar lote", style="Primary.TButton", command=self.start)
        self.run_button.grid(row=0, column=1)
        self.stop_button = ttk.Button(footer, text="Detener lote", state="disabled", command=self.cancel)
        self.stop_button.grid(row=0, column=2, padx=(8,0))
        ttk.Label(self, textvariable=self.status, wraplength=850).grid(row=8, column=0, sticky="w", pady=(8,0))

    @property
    def running(self):
        return self.runner is not None and self.runner.running

    def _set_busy(self, busy):
        for widget in (self.solver_entry,self.solver_browse,self.load_button,self.add_button,self.folder_button,
                       self.remove_button,self.destination_entry,self.destination_button,self.run_button):
            widget.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def _browse_solver(self):
        path = filedialog.askopenfilename(title="Seleccionar el solver FEBio", filetypes=[("Ejecutable FEBio","*.exe"),("Todos","*")])
        if path: self.solver.set(path)

    def _browse_inputs(self):
        paths = filedialog.askopenfilenames(title="Añadir simulaciones FEB", filetypes=[("FEBio","*.feb")])
        if paths: self.add_inputs(paths)

    def _browse_folder(self):
        directory = filedialog.askdirectory(title="Carpeta que contiene los archivos FEB")
        if directory:
            paths = sorted(Path(directory).glob("*.feb"))
            if paths: self.add_inputs(paths)
            else: messagebox.showinfo("Carpeta vacía", "La carpeta no contiene archivos .feb.")

    def _browse_destination(self):
        path = filedialog.askdirectory(title="Carpeta para los resultados del solver")
        if path: self.destination.set(path)

    def add_inputs(self, paths, replace=False):
        if self.running: return
        self.paths = list(dict.fromkeys([*(() if replace else self.paths),*(str(Path(p).resolve()) for p in paths)]))
        self.results = {}
        for item in self.tree.get_children(): self.tree.delete(item)
        for i,path in enumerate(self.paths): self.tree.insert("","end",iid=str(i),text=path,values=("Pendiente","—"))
        if self.paths and not self.destination.get(): self.destination.set(str(Path(self.paths[0]).parent))
        self.progress.configure(value=0, maximum=max(1,len(self.paths)))
        self.status.set(f"{len(self.paths)} archivos preparados para ejecutar.")

    def _remove(self):
        if self.running: return
        remove = {int(i) for i in self.tree.selection()}
        self.add_inputs([p for i,p in enumerate(self.paths) if i not in remove], replace=True)

    def load_last(self):
        if self.last_export: self.add_inputs(self.last_export, replace=True)
        else: messagebox.showinfo("Sin lote exportado", "Exporta primero un lote o añade los FEB desde una carpeta.")

    def exported(self, paths):
        self.last_export = list(map(str,paths))
        if self.auto_run.get() and self.last_export and not self.running:
            self.load_last()
            self.start()

    def start(self):
        if self.running: return
        try:
            if not self.destination.get().strip():
                raise MeshError("Selecciona la carpeta de resultados.")
            self.runner = SolverBatch(self.solver.get().strip(), self.paths, self.destination.get(), self.events.put)
            directory = self.runner.start()
            self.results = {}
            for i in range(len(self.paths)): self.tree.item(str(i),values=("Pendiente","—"))
            self.progress.configure(value=0, maximum=len(self.paths))
            self._write(f"Resultados: {directory}\n", replace=True)
            self.status.set("Iniciando FEBio…")
            self._set_busy(True)
            self.after(100,self._poll)
        except (MeshError,OSError) as exc:
            messagebox.showerror("No se pudo iniciar FEBio",str(exc))

    def cancel(self):
        if self.running:
            self.runner.cancel()
            self.stop_button.configure(state="disabled")
            self.status.set("Deteniendo la simulación actual y cancelando las pendientes…")

    def _write(self, text, replace=False):
        self.log.configure(state="normal")
        if replace: self.log.delete("1.0","end")
        self.log.insert("end",text)
        # La ventana conserva un tramo reciente; el archivo guarda el registro completo.
        if int(self.log.index("end-1c").split(".")[0])>2000: self.log.delete("1.0","1000.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_log(self):
        selected = self.tree.selection()
        if selected:
            row = self.results.get(int(selected[0]))
            if row:
                self._write(f"{row['message']}\nCarpeta: {row['directory']}\n\n"+tail_text(row['log']), replace=True)

    def _poll(self):
        final = False
        for _ in range(100):
            try: event = self.events.get_nowait()
            except Empty: break
            kind = event['kind']
            index = event.get('index',0)
            if kind=="started":
                self.tree.item(str(index),values=("Ejecutando","0 s"))
                self.tree.see(str(index))
                self.status.set(f"{index+1}/{len(self.paths)}: {Path(event['input']).name}")
                self._write(f"Ejecutando: {event['input']}\nCarpeta: {event['directory']}\n", replace=True)
            elif kind=="heartbeat":
                self.tree.item(str(index),values=("Ejecutando",f"{event['seconds']:.0f} s"))
            elif kind=="output":
                self._write(event['text'], replace=event.get('replace',False))
            elif kind=="finished_job":
                row = event['result']
                self.results[index] = row
                self.tree.item(str(index),values=(STATES[row['status']],f"{row['seconds']:.1f} s"))
                self.progress.configure(value=index+1)
                self._write(f"\n{STATES[row['status']]}: {row['message']}\n")
            elif kind=="done":
                report = event['report']
                self.status.set(f"Finalizado: {report['ok']} completadas, {report['errors']} con error, {report['cancelled']} canceladas.")
                self._write(f"\n{self.status.get()}\nResumen: {report['directory']}\n")
                final = True
            elif kind=="error":
                self.status.set("La ejecución se interrumpió: "+event['message'])
                self._write(f"\n{self.status.get()}\nCarpeta: {event['directory']}\n")
                final = True
        if final:
            self._set_busy(False)
        elif self.running or not self.events.empty():
            self.after(100,self._poll)
        else:
            self._set_busy(False)
