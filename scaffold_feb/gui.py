"""Interfaz Tkinter: geometría/material y superficies, con trabajo en proceso aparte."""
import importlib.util
import multiprocessing as mp
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np

from .materials import load_catalog, defaults, validate_material
from .model import MeshError, Options
from .pipeline import prepare
from .surfaces import select_surfaces
from .writer import write_feb
from .simulations import SIMULATION_KEY, SIMULATION_LABEL, NONE_LABEL, DESCRIPTION, simulation_geometry
from .protocol import Protocol
from .batch import export_batch
from .solver_gui import SolverTab

CONTROL_MODES = {"Desplazamiento (m)":"displacement", "Compresión (%)":"percent", "Fuerza total (N)":"force"}


def _worker(connection, action, args):
    try:
        if action=="batch":
            result = export_batch(*args,progress=lambda i,n,path,status:connection.send(("progress",(i,n,path,status))))
        else:
            result = prepare(*args) if action == "prepare" else write_feb(*args)
        connection.send((True,result))
    except Exception as exc:
        connection.send((False,str(exc)))
    finally:
        connection.close()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Mallas a FEBio")
        self.root.geometry("1120x850")
        self.root.minsize(940,760)
        self.catalog = load_catalog()
        self.prepared = None
        self.process = None
        self.connection = None
        self.revision = 0
        self.preview_jobs = []
        self.batch_paths = []
        self.path = tk.StringVar()
        self.scale = tk.StringVar(value="1")
        self.merge = tk.StringVar(value="0")
        self.size = tk.StringVar(value="")
        self.largest = tk.BooleanVar(value=False)
        self.shape = tk.StringVar(value="Cubo")
        self.axis = tk.StringVar(value="Automático")
        self.tolerance = tk.StringVar(value="")
        self.material = tk.StringVar(value="Neo-Hookeano")
        self.simulation = tk.StringVar(value=NONE_LABEL)
        self.control_mode = tk.StringVar(value="Desplazamiento (m)")
        self.protocol_values = {name:tk.StringVar(value=str(value)) for name,value in vars(Protocol()).items() if name!="mode"}
        self.status = tk.StringVar(value="Selecciona una malla VTK, VTU o STL para comenzar.")
        self.stats = tk.StringVar(value="La malla todavía no está preparada.")
        self.params = {}
        self.choices = {}
        self.count_labels = {}
        self._style()
        self._layout()
        self._material_fields()
        self._surface_controls()
        for var in (self.path,self.scale,self.merge,self.size,self.largest):
            var.trace_add("write",self._invalidate)
        for var in (self.axis,self.tolerance):
            var.trace_add("write",lambda *_: self._select())
        for var in self.protocol_values.values():
            var.trace_add("write",lambda *_: self._select())
        self.root.protocol("WM_DELETE_WINDOW",self._close)

    def _style(self):
        self.root.configure(bg="#f4f6f8")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".",font=("TkDefaultFont",10),background="#f4f6f8",foreground="#243746")
        style.configure("TEntry",fieldbackground="white",padding=5)
        style.configure("TCombobox",padding=5)
        style.configure("TButton",padding=(12,8))
        style.configure("Primary.TButton",background="#1b5c83",foreground="white",padding=(16,9))
        style.map("Primary.TButton",background=[("active","#164c6d"),("disabled","#c7d3db")])
        style.configure("Title.TLabel",font=("TkDefaultFont",21,"bold"))
        style.configure("Section.TLabel",font=("TkDefaultFont",13,"bold"))
        style.configure("Muted.TLabel",foreground="#526678")
        style.configure("TLabelframe",borderwidth=1,relief="solid")
        style.configure("TLabelframe.Label",font=("TkDefaultFont",12,"bold"))

    def _layout(self):
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both",expand=True)
        self.setup_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.setup_tab,text="Preparar geometrías y protocolo")
        self.solver_tab = SolverTab(self.tabs)
        self.tabs.add(self.solver_tab,text="Ejecutar en FEBio")
        outer = ttk.Frame(self.setup_tab,padding=18)
        outer.pack(fill="both",expand=True)
        outer.columnconfigure(0,weight=1)
        outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text="Mallas a FEBio",style="Title.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="Prepara el sólido, asigna su material y elige las superficies de trabajo.",
                  style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(4,10))
        viewport = ttk.Frame(outer)
        viewport.grid(row=2,column=0,sticky="nsew")
        viewport.columnconfigure(0,weight=1)
        viewport.rowconfigure(0,weight=1)
        canvas = tk.Canvas(viewport,background="#f4f6f8",highlightthickness=0)
        self.content_canvas = canvas
        canvas.grid(row=0,column=0,sticky="nsew")
        scrollbar = ttk.Scrollbar(viewport,orient="vertical",command=canvas.yview)
        scrollbar.grid(row=0,column=1,sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas)
        content_id = canvas.create_window((0,0),window=content,anchor="nw")
        content.bind("<Configure>",lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda event: canvas.itemconfigure(content_id,width=event.width))
        content.columnconfigure(0,weight=3)
        content.columnconfigure(1,weight=2)
        content.rowconfigure(1,weight=1)
        simulation_frame = ttk.LabelFrame(content,text="Simulación",padding=12)
        simulation_frame.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,12))
        simulation_frame.columnconfigure(0,weight=1)
        simulation_box = ttk.Combobox(simulation_frame,textvariable=self.simulation,
                                     values=[NONE_LABEL,SIMULATION_LABEL],state="readonly")
        simulation_box.grid(row=0,column=0,sticky="ew")
        simulation_box.bind("<<ComboboxSelected>>",lambda _:self._simulation_changed())
        ttk.Label(simulation_frame,text=DESCRIPTION,wraplength=850,style="Muted.TLabel").grid(
            row=1,column=0,sticky="w",pady=(6,0))
        self.protocol_frame = ttk.Frame(simulation_frame)
        self.protocol_frame.grid(row=2,column=0,sticky="ew",pady=(8,0))
        controls = ttk.Combobox(self.protocol_frame,textvariable=self.control_mode,
                                values=list(CONTROL_MODES),state="readonly",width=23)
        controls.grid(row=0,column=0,sticky="w",padx=(0,12))
        controls.bind("<<ComboboxSelected>>",lambda _:self._protocol_controls())
        self.magnitude_entry = ttk.Entry(self.protocol_frame,textvariable=self.protocol_values['displacement'],width=14)
        self.magnitude_entry.grid(row=0,column=1,sticky="w")
        for index,(name,label) in enumerate((("ramp_time","Rampa (s)"),
                ("step1_duration","Duración paso 1 (s)"),("step1_dt","Incremento paso 1 (s)"),
                ("step2_duration","Duración paso 2 (s)"),("step2_dt","Incremento paso 2 (s)"))):
            row,col = 1+index//2,2*(index%2)
            ttk.Label(self.protocol_frame,text=label).grid(row=row,column=col,sticky="w",padx=(0,8),pady=4)
            ttk.Entry(self.protocol_frame,textvariable=self.protocol_values[name],width=12).grid(row=row,column=col+1,sticky="w",padx=(0,18),pady=4)
        ttk.Button(self.protocol_frame,text="Restablecer ejemplo",command=self._reset_protocol).grid(row=0,column=2,columnspan=2,sticky="e")
        self.protocol_frame.grid_remove()
        left = ttk.LabelFrame(content,text="Geometría y material",padding=16)
        left.grid(row=1,column=0,sticky="nsew",padx=(0,16))
        left.columnconfigure(0,weight=1)
        ttk.Label(left,text="Archivo de malla").grid(row=0,column=0,sticky="w")
        file_row = ttk.Frame(left)
        file_row.grid(row=1,column=0,sticky="ew",pady=(4,12))
        file_row.columnconfigure(0,weight=1)
        ttk.Entry(file_row,textvariable=self.path).grid(row=0,column=0,sticky="ew")
        self.browse = ttk.Button(file_row,text="Añadir mallas…",command=self._browse)
        self.browse.grid(row=0,column=1,padx=(8,0))
        self.queue = ttk.Treeview(file_row,columns=("state",),height=4,selectmode="extended")
        self.queue.heading("#0",text="Geometrías del lote")
        self.queue.heading("state",text="Estado")
        self.queue.column("#0",width=220,stretch=True)
        self.queue.column("state",width=125,stretch=False)
        self.queue.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(8,0))
        queue_scroll = ttk.Scrollbar(file_row,orient="vertical",command=self.queue.yview)
        queue_scroll.grid(row=1,column=2,sticky="ns",pady=(8,0))
        self.queue.configure(yscrollcommand=queue_scroll.set)
        self.queue.bind("<<TreeviewSelect>>",lambda _:self._queue_select())
        self.remove_button = ttk.Button(file_row,text="Quitar seleccionadas",command=self._remove_files)
        self.remove_button.grid(row=2,column=0,columnspan=2,sticky="w",pady=(4,0))
        ttk.Label(file_row,text="Selecciona una fila y prepara su geometría para revisarla.\nLos ajustes se aplican a todas las mallas al exportar el lote.",
                  style="Muted.TLabel",wraplength=480).grid(row=3,column=0,columnspan=2,sticky="w",pady=(4,0))
        settings = ttk.Frame(left)
        settings.grid(row=2,column=0,sticky="ew")
        settings.columnconfigure(1,weight=1)
        for row,label,var in ((0,"Factor de coordenadas a metros",self.scale),
                              (1,"Tolerancia de fusión (m)",self.merge),
                              (2,"Tamaño para mallar superficie (m)",self.size)):
            ttk.Label(settings,text=label).grid(row=row,column=0,sticky="w",padx=(0,12),pady=4)
            ttk.Entry(settings,textvariable=var,width=14).grid(row=row,column=1,sticky="ew",pady=4)
        ttk.Label(left,text="Factor 1 conserva los valores; usa 0.001 si están en mm.\nEl tamaño solo se necesita si el archivo no tiene volumen.",
                  style="Muted.TLabel",wraplength=500).grid(row=3,column=0,sticky="w",pady=(4,10))
        ttk.Checkbutton(left,text="Conservar solo la pieza principal (mayor volumen)",
                        variable=self.largest).grid(row=4,column=0,sticky="w")
        self.prepare_button = ttk.Button(left,text="Preparar geometría",command=self._prepare)
        self.prepare_button.grid(row=5,column=0,sticky="w",pady=(12,12))
        ttk.Separator(left).grid(row=6,column=0,sticky="ew",pady=(0,12))
        ttk.Label(left,text="Material").grid(row=7,column=0,sticky="w")
        selector = ttk.Combobox(left,textvariable=self.material,values=[m["label"] for m in self.catalog.values()],state="readonly")
        selector.grid(row=8,column=0,sticky="ew",pady=(4,8))
        selector.bind("<<ComboboxSelected>>",lambda _:self._material_fields())
        self.material_frame = ttk.Frame(left)
        self.material_frame.grid(row=9,column=0,sticky="ew")
        ttk.Label(left,text="Valores iniciales de ejemplo: introduce las propiedades de tu material.",
                  style="Muted.TLabel",wraplength=480).grid(row=10,column=0,sticky="w",pady=(8,0))

        right = ttk.LabelFrame(content,text="Superficies",padding=16)
        right.grid(row=1,column=1,sticky="nsew")
        right.columnconfigure(1,weight=1)
        ttk.Label(right,text="Forma exterior").grid(row=0,column=0,sticky="w",padx=(0,10))
        form = ttk.Combobox(right,textvariable=self.shape,values=["Cubo","Cilindro"],state="readonly",width=15)
        form.grid(row=0,column=1,sticky="ew")
        form.bind("<<ComboboxSelected>>",lambda _:self._surface_controls())
        ttk.Label(right,text="Eje del cilindro").grid(row=1,column=0,sticky="w",pady=10)
        self.axis_box = ttk.Combobox(right,textvariable=self.axis,values=["Automático","X","Y","Z"],state="disabled",width=15)
        self.axis_box.grid(row=1,column=1,sticky="ew",pady=10)
        ttk.Label(right,text="Tolerancia del plano (m)").grid(row=2,column=0,sticky="w",padx=(0,10))
        ttk.Entry(right,textvariable=self.tolerance,width=15).grid(row=2,column=1,sticky="ew")
        ttk.Label(right,text="Vacío: 0.0001 % de la diagonal. Se incluyen solo caras cuyos nodos están sobre el plano.",
                  style="Muted.TLabel",wraplength=335).grid(row=3,column=0,columnspan=2,sticky="w",pady=(8,14))
        self.surface_frame = ttk.Frame(right)
        self.surface_frame.grid(row=4,column=0,columnspan=2,sticky="ew")
        ttk.Separator(right).grid(row=5,column=0,columnspan=2,sticky="ew",pady=12)
        ttk.Label(right,textvariable=self.stats,justify="left",wraplength=340).grid(row=6,column=0,columnspan=2,sticky="w")
        self.preview_button = ttk.Button(right,text="Vista 3D de las superficies",command=self._preview,state="disabled")
        self.preview_button.grid(row=7,column=0,columnspan=2,sticky="w",pady=(14,4))
        ttk.Label(right,text="En FEBio, cada nombre aparece como selección de nodos y de caras. El aviso «is not used» indica que aún no tiene una condición asignada. T3 corresponde a una cara triangular.",
                  style="Muted.TLabel",wraplength=335).grid(row=8,column=0,columnspan=2,sticky="w")

        ttk.Label(outer,text="Resumen y avisos",style="Section.TLabel").grid(row=3,column=0,sticky="w",pady=(10,6))
        self.log = tk.Text(outer,height=3,wrap="word",font=("TkFixedFont",9),background="white",
                           foreground="#334e63",relief="solid",borderwidth=1,padx=10,pady=8)
        self.log.grid(row=4,column=0,sticky="ew")
        self.log.insert("1.0","Las coordenadas y tolerancias de salida se expresan en metros.\nElige una simulación para exportar también sus condiciones, pasos y curva de carga.")
        self.log.configure(state="disabled")
        footer = ttk.Frame(outer)
        footer.grid(row=5,column=0,sticky="ew",pady=(10,0))
        self.progress = ttk.Progressbar(footer,mode="indeterminate",length=100)
        self.progress.pack(side="left",padx=(0,12))
        ttk.Label(footer,textvariable=self.status,wraplength=650).pack(side="left",fill="x",expand=True)
        self.export_button = ttk.Button(footer,text="Exportar .feb",style="Primary.TButton",command=self._export,state="disabled")
        self.export_button.pack(side="right",padx=(12,0))

    def _model(self):
        return next(m for m in self.catalog.values() if m["label"] == self.material.get())

    def _simulation_changed(self):
        if self.simulation.get()==SIMULATION_LABEL:
            self.protocol_frame.grid()
            required = ("inferior","superior") if self.shape.get()=="Cilindro" else ("Z-","Z+")
            for name in required:
                if name in self.choices:
                    self.choices[name].set(True)
        else:
            self.protocol_frame.grid_remove()
        self.root.after_idle(lambda:self.content_canvas.yview_moveto(0))
        self._select()

    def _protocol_controls(self):
        name = {"displacement":"displacement","percent":"compression_percent","force":"force"}[CONTROL_MODES[self.control_mode.get()]]
        self.magnitude_entry.configure(textvariable=self.protocol_values[name])
        self._select()

    def _reset_protocol(self):
        self.control_mode.set("Desplazamiento (m)")
        for name,var in self.protocol_values.items(): var.set(str(getattr(Protocol(),name)))
        self._protocol_controls()

    def _protocol(self):
        mode = CONTROL_MODES[self.control_mode.get()]
        active = {"displacement":"displacement","percent":"compression_percent","force":"force"}[mode]
        values = vars(Protocol()).copy()
        values['mode'] = mode
        for name,var in self.protocol_values.items():
            if name in ("displacement","compression_percent","force") and name!=active: continue
            values[name] = self._float(var.get(),name)
        return Protocol(**values).validate()

    def _material_fields(self):
        for child in self.material_frame.winfo_children():
            child.destroy()
        self.params = {}
        self.material_frame.columnconfigure(1,weight=1)
        for row,spec in enumerate(self._model()["parameters"]):
            ttk.Label(self.material_frame,text=f"{spec['label']} ({spec['name']})").grid(row=row,column=0,sticky="w",padx=(0,12),pady=4)
            var = tk.StringVar(value=str(spec["default"]))
            self.params[spec["name"]] = var
            ttk.Entry(self.material_frame,textvariable=var,width=14).grid(row=row,column=1,sticky="ew",pady=4)
            ttk.Label(self.material_frame,text=spec["unit"]).grid(row=row,column=2,sticky="w",padx=(8,0))

    def _surface_controls(self):
        for child in self.surface_frame.winfo_children():
            child.destroy()
        self.choices, self.count_labels = {}, {}
        cylinder = self.shape.get() == "Cilindro"
        self.axis_box.configure(state="readonly" if cylinder else "disabled")
        names = ["inferior","superior"] if cylinder else ["X-","X+","Y-","Y+","Z-","Z+"]
        self.surface_frame.columnconfigure(1,weight=1)
        for row,name in enumerate(names):
            var = tk.BooleanVar(value=True)
            self.choices[name] = var
            ttk.Checkbutton(self.surface_frame,text=name,variable=var,command=self._select).grid(row=row,column=0,sticky="w",pady=4)
            label = ttk.Label(self.surface_frame,text="—",style="Muted.TLabel")
            label.grid(row=row,column=1,sticky="e",pady=4)
            self.count_labels[name] = label
        self._select()

    def _invalidate(self,*_):
        self.revision += 1
        self.prepared = None
        self.export_button.configure(state="normal" if len(self.batch_paths)>1 and not self.process else "disabled")
        self.preview_button.configure(state="disabled")
        self.stats.set("Prepara la malla con estos ajustes.")
        for label in self.count_labels.values():
            label.configure(text="—")
        if not self.process:
            self.status.set(f"{len(self.batch_paths)} geometrías listas para exportar. Preparar revisa solo la seleccionada."
                            if len(self.batch_paths)>1 else "Los ajustes cambiaron. Pulsa Preparar geometría.")

    def _browse(self):
        paths = filedialog.askopenfilenames(title="Añadir geometrías",filetypes=[("Mallas","*.vtk *.vtu *.stl"),("Todos","*.*")])
        if paths: self._add_files(paths)

    def _add_files(self,paths):
        if self.process: return
        self.batch_paths = list(dict.fromkeys([*self.batch_paths,*(str(Path(p).resolve()) for p in paths)]))
        self._sync_queue()

    def _sync_queue(self):
        for item in self.queue.get_children(): self.queue.delete(item)
        for i,path in enumerate(self.batch_paths): self.queue.insert("","end",iid=str(i),text=Path(path).name,values=("Pendiente",))
        self.queue.heading("#0",text=f"Geometrías del lote ({len(self.batch_paths)})")
        self.export_button.configure(text="Exportar lote…" if len(self.batch_paths)>1 else "Exportar .feb")
        self.path.set(self.batch_paths[0] if self.batch_paths else "")

    def _queue_select(self):
        if self.process: return
        selected=self.queue.selection()
        if selected:
            path=self.batch_paths[int(selected[0])]
            if path!=self.path.get(): self.path.set(path)

    def _remove_files(self):
        if self.process: return
        remove={int(i) for i in self.queue.selection()}
        self.batch_paths=[p for i,p in enumerate(self.batch_paths) if i not in remove]
        self._sync_queue()

    def _options(self):
        return Options(scale=self._float(self.scale.get(),"Factor de escala"),
                       merge_tolerance=self._float(self.merge.get(),"Tolerancia de fusión"),
                       largest_component=self.largest.get(),element_size=self._float(self.size.get(),"Tamaño de elemento",True),
                       shape="cylinder" if self.shape.get()=="Cilindro" else "cube",
                       axis="auto" if self.axis.get()=="Automático" else self.axis.get().lower(),
                       plane_tolerance=self._float(self.tolerance.get(),"Tolerancia del plano",True),
                       selected=tuple(name for name,var in self.choices.items() if var.get()))

    @staticmethod
    def _float(value,label,optional=False):
        if optional and not value.strip():
            return None
        try:
            result = float(value)
            if not np.isfinite(result):
                raise ValueError()
            return result
        except ValueError:
            raise MeshError(f"{label}: introduce un número finito usando punto decimal.") from None

    def _prepare(self):
        try:
            if not self.path.get():
                raise MeshError("Selecciona primero una malla VTK, VTU o STL.")
            opt = Options(scale=self._float(self.scale.get(),"Factor de escala"),
                          merge_tolerance=self._float(self.merge.get(),"Tolerancia de fusión"),
                          largest_component=self.largest.get(),
                          element_size=self._float(self.size.get(),"Tamaño de elemento",True),selected=())
            self.request_revision = self.revision
            self.prepared = None
            self._start("prepare",(self.path.get(),opt),"Leyendo y preparando la geometría…")
        except MeshError as exc:
            messagebox.showerror("Revisa los datos",str(exc))

    def _start(self,action,args,status):
        if self.process:
            return
        context = mp.get_context("spawn")
        self.connection, sender = context.Pipe(duplex=False)
        self.action = action
        self.process = context.Process(target=_worker,args=(sender,action,args),daemon=True)
        self.process.start()
        sender.close()
        for button in (self.prepare_button,self.browse,self.remove_button,self.export_button,self.preview_button):
            button.configure(state="disabled")
        self.progress.start(12)
        self.status.set(status)
        self.root.after(100,self._poll)

    def _poll(self):
        if not self.process:
            return
        result = None
        try:
            if self.connection.poll():
                result = self.connection.recv()
            elif not self.process.is_alive():
                result = (False,"El proceso de conversión terminó inesperadamente. Revisa la malla y sus autointersecciones.")
        except EOFError:
            result = (False,"El proceso de conversión se cerró sin resultado.")
        if result is None:
            self.root.after(100,self._poll)
            return
        if result[0]=="progress":
            i,n,path,status = result[1]
            self.status.set(f"{i}/{n}: {Path(path).name} — {status}")
            if self.queue.exists(str(i-1)):
                self.queue.item(str(i-1),values=(status,))
            self.root.after(50,self._poll)
            return
        self.process.join(timeout=0.2)
        self.connection.close()
        self.process = self.connection = None
        self.progress.stop()
        self.prepare_button.configure(state="normal")
        self.browse.configure(state="normal")
        self.remove_button.configure(state="normal")
        ok,value = result
        if not ok:
            self.status.set("No se completó la operación.")
            self._log([str(value)])
            messagebox.showerror("No se pudo completar",str(value))
            if self.prepared:
                self._select()
            elif len(self.batch_paths)>1:
                self.export_button.configure(state="normal")
        elif self.action=="batch":
            self.export_button.configure(state="normal")
            self.status.set(f"Lote terminado: {value['ok']} exportadas, {value['errors']} con error.")
            self._log([self.status.get(),value['directory'],*(r['input']+': '+r['message'] for r in value['results'] if r['status']=='error')])
            self.solver_tab.exported([r['output'] for r in value['results'] if r['status']=='ok'])
            if self.solver_tab.running: self.tabs.select(self.solver_tab)
            messagebox.showinfo("Lote terminado",f"{value['ok']} exportadas; {value['errors']} con error.\n\n{value['directory']}\n\nConsulta resumen.csv para el detalle.")
        elif self.action == "prepare":
            if self.request_revision != self.revision:
                self.status.set("Los ajustes cambiaron durante la lectura. Prepara de nuevo la geometría.")
                return
            self.prepared = value
            self._select()
        else:
            self._select()
            self.status.set(f"Guardado: {Path(value).name}")
            self.solver_tab.last_export = [str(value)]
            detail = ("Incluye el material elegido y el ensayo de compresión y mantenimiento: condiciones, pasos y curva."
                      if self.export_simulation else "Contiene geometría, material y superficies. Configura las condiciones y pasos antes de simular.")
            messagebox.showinfo("FEB guardado",f"{value}\n\n{detail}")

    def _select(self):
        if not self.prepared or self.process:
            return
        try:
            result = self.prepared
            selected = tuple(name for name,var in self.choices.items() if var.get())
            tol = self._float(self.tolerance.get(),"Tolerancia del plano",True)
            result.surfaces,result.axis,result.plane_tolerance = select_surfaces(
                result.mesh,result.boundary,"cylinder" if self.shape.get()=="Cilindro" else "cube",
                "auto" if self.axis.get()=="Automático" else self.axis.get().lower(),tol,selected)
            counts = {s.name:len(s.faces) for s in result.surfaces}
            for name,label in self.count_labels.items():
                label.configure(text=f"{counts[name]:,} caras" if name in counts else "Sin exportar")
            summary = result.summary()
            self.stats.set(f"{summary['nodos']:,} nodos\n" + ", ".join(f"{n:,} {kind}" for kind,n in summary["elementos"].items()) +
                           f"\n{len(result.boundary):,} caras exteriores" + (f"\nEje detectado: {result.axis}" if result.axis else ""))
            lines = [f"Entrada: {summary['entrada']}",f"Bounding box (m): {summary['bounding_box_m']}",
                     f"Tolerancia de plano: {result.plane_tolerance:g} m"]
            for name,info in summary["superficies"].items():
                axis = "XYZ".index(result.axis if result.axis else name[0])
                low,high = info["bounding_box_m"]
                lines.append(f"{name}: {info['caras']} caras, {info['nodos']} nodos; "
                             f"{'XYZ'[axis]} entre {low[axis]:.6g} y {high[axis]:.6g} m.")
            lines.extend(summary["advertencias"])
            self._log(lines)
            self.export_button.configure(state="normal")
            self.preview_button.configure(state="normal")
            self.status.set("Geometría preparada. Revisa el material y las superficies antes de exportar.")
            if self.simulation.get()==SIMULATION_LABEL:
                protocol=self._protocol()
                simulation_geometry(result.mesh,result.surfaces,result.axis or "z",protocol)
                self.status.set(protocol.description())
        except (MeshError,ValueError) as exc:
            self.export_button.configure(state="disabled")
            self.preview_button.configure(state="disabled")
            self.status.set(str(exc))
            for label in self.count_labels.values():
                label.configure(text="Revisar selección")
        finally:
            if len(self.batch_paths)>1 and not self.process:
                self.export_button.configure(state="normal")

    def _log(self,lines):
        self.log.configure(state="normal")
        self.log.delete("1.0","end")
        self.log.insert("1.0","\n".join(lines))
        self.log.configure(state="disabled")

    def _export(self):
        if len(self.batch_paths)>1:
            self._export_batch()
            return
        if not self.prepared:
            return
        try:
            model = self._model()
            values = validate_material(model,{k:v.get() for k,v in self.params.items()})
            protocol=self._protocol() if self.simulation.get()==SIMULATION_LABEL else None
            path = filedialog.asksaveasfilename(title="Guardar FEBio",defaultextension=".feb",
                       initialfile=Path(self.path.get()).stem+".feb",filetypes=[("FEBio","*.feb")],confirmoverwrite=True)
            if path:
                result = self.prepared
                self.export_simulation = SIMULATION_KEY if self.simulation.get()==SIMULATION_LABEL else None
                self._start("export",(path,result.mesh,result.surfaces,model,values,Path(path).exists(),
                                      None,self.export_simulation,result.axis or "z",protocol),"Guardando FEBio…")
        except MeshError as exc:
            messagebox.showerror("Revisa el material",str(exc))

    def _export_batch(self):
        try:
            model=self._model()
            values=validate_material(model,{k:v.get() for k,v in self.params.items()})
            simulation=SIMULATION_KEY if self.simulation.get()==SIMULATION_LABEL else None
            protocol=self._protocol() if simulation else None
            options=self._options()
            directory=filedialog.askdirectory(title="Carpeta de salida del lote (se creará una subcarpeta nueva)")
            if directory:
                self._start("batch",(list(self.batch_paths),directory,options,model,values,simulation,"z",protocol),"Exportando lote…")
        except (MeshError,OSError) as exc:
            messagebox.showerror("Revisa los ajustes",str(exc))

    def _preview(self):
        if importlib.util.find_spec("pyvista") is None:
            messagebox.showinfo("Vista opcional", "La exportación está disponible. Para la vista 3D instala:\n\npython -m pip install -r requirements-preview.txt")
            return
        from .preview import face_stream
        result = self.prepared
        temp = tempfile.TemporaryDirectory(prefix="scaffold_preview_")
        path = Path(temp.name)/"preview.npz"
        data = {"points": result.mesh.points,"boundary": face_stream(result.boundary),
                "names": np.asarray([s.name for s in result.surfaces],dtype=str)}
        data.update({f"surface_{i}":face_stream(s.faces) for i,s in enumerate(result.surfaces)})
        np.savez_compressed(path,**data)
        process = subprocess.Popen([sys.executable,"-m","scaffold_feb.preview",str(path)])
        self.preview_jobs.append((process,temp))
        self.root.after(1000,self._reap_previews)

    def _reap_previews(self):
        active = []
        for process,temp in self.preview_jobs:
            if process.poll() is None:
                active.append((process,temp))
            else:
                temp.cleanup()
        self.preview_jobs = active
        if active:
            self.root.after(1000,self._reap_previews)

    def _close(self):
        if self.solver_tab.running:
            if not messagebox.askyesno("Solver en ejecución","¿Detener el lote de FEBio y cerrar la aplicación?"):
                return
            self.solver_tab.cancel()
            self.root.after(100,self._close_after_solver)
            return
        if self.process:
            if not messagebox.askyesno("Operación en curso","¿Cancelar la operación y cerrar?"):
                return
            self.process.terminate()
            self.process.join(timeout=1)
            self.connection.close()
        for process,temp in self.preview_jobs:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            temp.cleanup()
        self.root.destroy()

    def _close_after_solver(self):
        if self.solver_tab.running:
            self.root.after(100,self._close_after_solver)
        else:
            self._close()


def main():
    root = tk.Tk()
    try:
        App(root)
        root.mainloop()
    except MeshError as exc:
        messagebox.showerror("No se pudo iniciar",str(exc))
        root.destroy()


if __name__ == "__main__":
    mp.freeze_support()
    main()
