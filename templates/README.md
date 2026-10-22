# Plantillas de simulación

El ensayo integrado se almacena en `../scaffold_feb/templates/compresion_relajacion.xml`, dentro del paquete para que funcione también después de instalarlo con pip. Contiene Globals, Boundary, Step, LoadData y Output extraídos de `../reference/ejemplo.feb`.

`simulations.py` adapta superficies, anclajes, grados de libertad y archivos de salida. `protocol.py` define los parámetros editables: desplazamiento, porcentaje o fuerza total, rampa, duraciones e incrementos. Los valores iniciales recuperan −0.1 m y los tiempos del ejemplo. La base usa desplazamiento prescrito cero para registrar reacciones. No se importa Material: se usa el material elegido.

El escritor mantiene `extra_blocks` y `load_template(path)` como API para futuras plantillas externas con raíz `febio_fragments`. No se combinan con el ensayo integrado ni se cargan desde la ventana.
