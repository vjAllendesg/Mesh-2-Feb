# Mallas a FEBio

Aplicación Python para preparar mallas de andamios cúbicos y cilíndricos y exportar geometría, material y superficies a **FEBio 4.0**, en **m, N, Pa, s y kg/m³**. La fase 0 está documentada en `../NOTAS.md`.

La salida se abre en FEBio Studio. Puedes exportar solo geometría o añadir **Compresión y mantenimiento — ejemplo**, el protocolo de la fase 2 extraído del FEB de referencia. El material siempre es el elegido en la interfaz; el selector de simulación no lo sustituye.

## Instalación

Se requiere Python 3.10 o posterior, de 64 bits. Ejecuta los comandos desde esta carpeta. Se recomienda un entorno virtual independiente.

Windows, PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scaffold_feb
```

Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scaffold_feb
```

Si la distribución no incluye Tkinter o venv, instala los paquetes de Python correspondientes con su gestor de paquetes. En Debian/Ubuntu suelen llamarse `python3-tk` y `python3-venv`. Tkinter se eligió porque viene con muchas distribuciones de Python, permite los dos paneles requeridos y evita una dependencia Qt. Las operaciones de lectura, mallado y escritura se ejecutan en otro proceso para mantener disponible la ventana.

También puedes instalar el paquete con `python -m pip install .` y utilizar los comandos `scaffold-feb` y `scaffold-feb-gui`. El núcleo utiliza `pathlib` y no tiene rutas absolutas ni dependencias específicas de Windows. La comprobación realizada en esta entrega es en Windows; Linux requiere validación en ese sistema.

## Uso de la ventana

1. Pulsa **Añadir mallas…** y selecciona uno o varios archivos VTK, VTU o STL. Puedes añadir más archivos después y quitar filas seleccionadas.
2. Indica el factor de coordenadas a metros. **1 conserva los números**; **0.001 convierte milímetros a metros**. Estos archivos no permiten inferir de forma fiable la unidad física: revisa el bounding box mostrado.
3. Ajusta la tolerancia de fusión en metros. El valor 0 une únicamente coincidencias exactas. Si el archivo es superficial, indica también el tamaño nominal de tetraedro en metros.
4. Selecciona una fila y pulsa **Preparar geometría** para revisar esa malla. El resumen distingue volumen existente de superficie tetraedralizada, muestra nodos, elementos, bounding box y avisos. El lote prepara automáticamente cada archivo al exportar.
5. Elige el material y edita sus propiedades. Los valores iniciales son ilustrativos; no constituyen una caracterización del andamio.
6. Selecciona Cubo o Cilindro y marca las superficies deseadas. En cilindros puedes elegir X, Y o Z si el eje automático es ambiguo. No se admiten cilindros inclinados respecto de esos ejes.
7. En **Simulación**, elige **Compresión y mantenimiento — ejemplo**, o deja **Sin simulación (solo geometría)**. El ensayo necesita las dos tapas. En cubos utiliza Z; en cilindros utiliza el eje detectado o elegido.
8. Configura los campos del protocolo y pulsa **Exportar .feb** o **Exportar lote…**. Con el ensayo seleccionado se exportan también sus condiciones, dos pasos, curva de carga y salidas.

## Simulación: compresión y mantenimiento

Los valores iniciales reproducen el ejemplo: desplazamiento absoluto **−0.1 m**, rampa de 0.1 s y pasos de 1 s y 7 s con incrementos de 0.01 s. **Restablecer ejemplo** recupera esos valores. Puedes elegir uno de tres controles excluyentes:

- **Desplazamiento (m):** introduce la magnitud positiva; se aplica en sentido de compresión.
- **Compresión (%):** se calcula para cada geometría a partir de la distancia axial entre las coordenadas medias de los nodos de sus dos tapas. El mismo porcentaje puede producir desplazamientos diferentes en piezas de distinta altura.
- **Fuerza total (N):** fuerza compresiva total sobre la tapa superior, mediante la carga superficial `force` de FEBio. No es fuerza por nodo ni presión. En este modo no se prescribe la compresión resultante; la determina el solver con el material y la geometría.

Puedes editar la duración de la rampa, la duración de cada paso y sus incrementos de tiempo. El primer paso incluye la rampa y, si sobra tiempo, un mantenimiento; el segundo mantiene la magnitud alcanzada. La duración total es la suma de ambos pasos. Cada duración debe ser múltiplo entero de su incremento; la rampa debe coincidir con un incremento del primer paso y terminar dentro de él. El programa valida estos valores antes de exportar.

La base queda restringida axialmente; un nodo inferior queda fijo y un nodo superior se restringe transversalmente. Los anclajes se eligen cerca del centro de cada tapa, con separación transversal para evitar una rotación axial libre. La base usa desplazamiento prescrito cero para que FEBio registre sus reacciones; el apoyo tiene el mismo efecto cinemático que el del ejemplo. Se requiere una sola pieza conectada. En control de desplazamiento, la compresión debe ser menor que la separación entre tapas; el porcentaje debe estar entre 0 y 100, sin incluir extremos.

El material y sus parámetros son independientes del ensayo. Los tres materiales actuales son elásticos/hiperelásticos; mantener el desplazamiento no implica por sí solo relajación viscoelástica. El material viscoelástico anidado del FEB original no se introduce automáticamente.

Las salidas incluyen desplazamiento, tensión, volumen relativo y fuerzas de reacción. Los archivos de texto de fuerza/tensión se limitan a los nodos o elementos adyacentes de cada tapa y llevan el nombre del FEB como prefijo. Contienen valores por nodo/elemento; las reacciones de la base deben sumarse para obtener la fuerza total. En control por fuerza, la tapa superior recibe una carga externa y sus reacciones no representan esa carga. El programa genera el ensayo; su ejecución se hace en FEBio Studio o con el solver FEBio.

```bash
python -m scaffold_feb geometria.vtu resultado.feb --shape cylinder --axis z --plane-tolerance 0.002 --simulation compresion-mantenimiento --material "neo-Hookean" --param E=100
```

La CLI permite `--simulation-axis x|y|z` para cubos; los cilindros usan el eje de sus tapas. La tolerancia 0.002 corresponde a la geometría revisada, no es universal. Los parámetros se editan con `--control displacement|percent|force`, `--displacement`, `--compression-percent`, `--force`, `--ramp-time`, `--step1-duration`, `--step1-dt`, `--step2-duration` y `--step2-dt`.

## Exportación en lote

Con varias filas, **Exportar lote…** solicita una carpeta de destino y crea una subcarpeta como `FEB_2026-10-21_15-30`: fecha y hora hasta minutos. Si ya existe, añade `_2`, `_3`, etc. Todos los archivos reciben una instantánea del mismo material, protocolo, forma exterior, escala y tolerancias. El eje automático se resuelve por geometría; si mezclas formas o unidades distintas, sepáralas en lotes adecuados. La vista previa corresponde únicamente a la malla seleccionada.

Cada FEB conserva el nombre de su geometría, sin prefijo numérico. Si dos entradas tienen el mismo nombre, la segunda añade `_2`. El procesamiento es secuencial para limitar el uso de memoria. Un error de lectura, selección o exportación queda registrado y el lote continúa con el siguiente archivo. No se reemplazan lotes anteriores. El informe incluye:

- `parametros.json`: material, protocolo y ajustes comunes utilizados.
- `resumen.csv`: ruta de entrada, salida, estado y error de cada archivo.
- `resultados.jsonl`: detalle por geometría, incluidos conteos y desplazamiento aplicado cuando corresponde; se actualiza tras cada archivo.

La exportación en lote genera los FEB. En la pestaña **Ejecutar en FEBio** puedes ejecutarlos inmediatamente o activar la ejecución automática al terminar de exportar. El lote utiliza una combinación común de material y protocolo por exportación.

```bash
python -m scaffold_feb --batch pieza1.vtu pieza2.vtu --output-dir salidas --shape cylinder --axis z --plane-tolerance 0.002 --simulation compresion-mantenimiento --control percent --compression-percent 10 --ramp-time 0.1 --step1-duration 1 --step1-dt 0.01 --step2-duration 7 --step2-dt 0.01
```

La CLI devuelve código 2 si algún archivo falla y conserva todas las salidas correctas y sus informes.

## Ejecutar el lote en FEBio

La pestaña **Ejecutar en FEBio** llama directamente al solver. Detecta `febio4` en PATH y la instalación habitual de FEBio Studio en Windows; también puedes seleccionar manualmente `febio4.exe` o el ejecutable `febio4` de Linux. Se necesita el solver instalado, además de FEBio Studio.

1. Exporta el lote con un protocolo de simulación seleccionado.
2. Abre **Ejecutar en FEBio** y pulsa **Cargar último lote**. Ese botón utiliza la última exportación de la sesión actual. También puedes usar **Añadir FEB…** o **Añadir carpeta…** para recuperar archivos anteriores; la carpeta se lee sin recorrer subcarpetas.
3. Revisa la ruta del solver y elige la carpeta de resultados.
4. Pulsa **Iniciar lote**. Se ejecuta una simulación a la vez, con estado y tiempo transcurrido por archivo, avance del lote y un tramo reciente del registro en vivo.

Si marcas **Ejecutar automáticamente al terminar de exportar un lote**, los FEB exportados correctamente pasan al solver cuando finaliza la exportación. Esta opción debe activarse en la pestaña del solver antes de exportar el lote.

Cada ejecución crea una subcarpeta como `SIM_2026-10-21_15-30`, con otra carpeta que lleva el nombre de cada geometría. Si hay coincidencias se añade `_2`, `_3`, etc. Allí se guarda una copia del FEB utilizado, `resultados.xplt`, `solver.log`, `consola.txt` y los registros abreviados `F_inf.txt`, `F_sup.txt`, `S_inf.txt` y `S_sup.txt` (fuerza/tensión en la tapa inferior/superior). En el FEB exportado, estos registros llevan además el nombre de la pieza como prefijo para distinguirlos si se ejecutan manualmente en la misma carpeta. Los FEB de entrada se conservan. El ejecutor está preparado para los FEB autónomos que genera esta aplicación; los archivos externos con recursos adicionales pueden requerir revisar sus rutas.

Solo se marca **Completada** si el proceso devuelve código 0 y el registro confirma **Normal termination**. Un modelo que falla se marca **Error** y el lote continúa. Selecciona una fila terminada para consultar su registro. `resumen.csv`, `resumen.json` y `resultados.jsonl` guardan los estados, códigos, tiempos y rutas de cada simulación.

**Detener lote** termina el solver de la simulación actual y cancela las pendientes. Los resultados ya completados se conservan; una simulación cancelada puede dejar resultados parciales en su carpeta. Si cierras la aplicación durante una ejecución, se ofrece detener el proceso antes de cerrar.

La opción **Conservar solo la pieza principal** elimina fragmentos desconectados y conserva la pieza de mayor volumen material. Está desactivada inicialmente. Dos piezas que se tocan solo por un vértice o una arista se consideran separadas: la conectividad se establece por caras completas.

Los controles se pueden desplazar con la barra vertical si la pantalla es pequeña. El botón de exportación permanece visible. Los avisos se pueden consultar desplazando el cuadro de texto.

La vista 3D es opcional y se abre en otro proceso:

```bash
python -m pip install -r requirements-preview.txt
```

Sin PyVista se puede preparar y exportar normalmente. En la vista, las caras tri6 se subdividen para dibujarlas; el FEB conserva los seis nodos originales.

## Línea de comandos

En los ejemplos siguientes, `python` representa el Python del entorno virtual.

```bash
python -m scaffold_feb examples/cubo.vtu cubo.feb --material "neo-Hookean" --param E=1000 --param v=0.3 --param density=1000
python -m scaffold_feb examples/cilindro_binario.stl cilindro.feb --shape cylinder --axis z --element-size 0.4
python -m scaffold_feb examples/cubo_ascii.vtk --inspect --json
python -m scaffold_feb examples/cubo.vtu tapas.feb --surfaces Z-,Z+ --scale 0.001
```

Opciones adicionales: `--merge-tolerance`, `--plane-tolerance`, `--largest`, `--catalog`, `--surfaces none` y `--overwrite`. La CLI no reemplaza archivos existentes salvo que se indique `--overwrite`. Los errores de entrada devuelven código 2 y un mensaje explicativo. `python -m scaffold_feb --help` muestra todas las opciones.

## Formatos y geometría

| Entrada | Tratamiento |
| --- | --- |
| VTK legacy ASCII/binario; VTU | Se conservan los elementos volumétricos tet4, tet10 y hex8. Si solo hay superficie cerrada, se tetraedraliza. |
| VTK_VOXEL | Se reordena `[0,1,3,2,4,5,7,6]` antes de tratarlo como hex8. |
| STL ASCII/binario | Se detecta por estructura; un binario que comienza por `solid` sigue siendo binario. Se unen vértices y se tetraedraliza con TetGen. |

Las convenciones tetra/tetra10/hexahedron de VTK y FEBio coinciden para los tipos admitidos; se corrige la orientación cuando es necesario, incluyendo los nodos de arista de tet10. Los tipos volumétricos no soportados se rechazan. Las celdas auxiliares superficiales se omiten cuando el archivo ya contiene volumen, con aviso. Solo se exportan geometría y material uniforme: no se trasladan campos de resultados ni etiquetas de materiales del archivo de entrada.

Se eliminan nodos huérfanos, se rechazan celdas degeneradas y se corrigen elementos con orientación global invertida. Los Jacobianos de tet10 y hex8 se verifican en una cuadrícula y puntos de integración; este muestreo detecta inversiones locales habituales, pero no es una demostración de positividad en todo elemento curvo muy distorsionado.

Para STL se exige una superficie cerrada. No se tapan agujeros automáticamente. Se conservan poros pasantes y cavidades cerradas mediante clasificación por paridad del dominio. El tamaño nominal `h` controla el volumen máximo pedido a TetGen mediante `h³/(6√2)`; no garantiza aristas de longitud exactamente `h`. Una malla muy fina puede necesitar bastante memoria. TetGen aplica su propia licencia; revísala antes de redistribuir el programa comercialmente.

Las superficies se construyen con caras pertenecientes a un solo elemento, orientadas hacia fuera del material. Se seleccionan únicamente si **todos sus nodos** están a la distancia permitida del plano extremo; también se comprueban los nodos intermedios de tri6. Por eso los poros no se rellenan con una tapa rectangular. Se requiere una malla volumétrica conforme, con interfaces compartidas por caras compatibles.

La tolerancia de plano predeterminada es `diagonal × 1e-6`, en metros. Una selección vacía informa del problema; puedes desmarcar esa superficie o revisar la tolerancia. Si no quieres superficies, desmarca todas.

Si las tapas están ligeramente deformadas o desplazadas respecto del plano extremo, aumenta la tolerancia con cuidado. Una tolerancia grande puede seleccionar también paredes dentro de esa banda. El resumen muestra el intervalo real de coordenadas de cada selección y avisa si supera el 1 % de la dimensión axial; ese umbral es un aviso para revisar, no un criterio de validez geométrica.

En FEBio Studio, `T3` es una cara triangular de tres nodos; es la superficie correcta de un volumen `tet4`. Cada nombre aparece dos veces en Named Selections porque se exportan un NodeSet (nodos) y una Surface (caras). El aviso **Named selection … is not used** indica que la selección todavía no se usa en una condición, carga u otro componente. Con el ensayo seleccionado, las superficies de las tapas se usan en condiciones; los NodeSets equivalentes y otras superficies pueden seguir sin utilizarse. No significa que la superficie falte. Para cargas superficiales elige la selección de tipo **face selection**; para condiciones nodales usa la selección compatible. Ver [validador de selecciones de FEBio Studio](https://github.com/febiosoftware/FEBioStudio/blob/develop/FEBioStudio/ModelTree.cpp).

## Catálogo y estructura

`scaffold_feb/materials.json` contiene materiales y parámetros escalares. Para añadir uno, agrega su nombre exacto de FEBio en `type`, una etiqueta única en `label` y sus `parameters` con `name`, `label`, `default`, `unit` y límites opcionales `min`, `max`, `min_exclusive`, `max_exclusive`. La GUI genera los campos sin modificar código. El material debe existir en FEBio; este catálogo no valida modelos nuevos contra su motor. Los modelos con bloques anidados necesitan una futura ampliación del esquema.

| Archivo | Responsabilidad |
| --- | --- |
| `model.py`, `pipeline.py` | Datos y flujo común |
| `readers.py` | Formatos, vóxeles y tetraedralización |
| `geometry.py` | Fusión, limpieza y Jacobianos |
| `surfaces.py` | Borde, componentes y planos |
| `materials.py`, `materials.json` | Catálogo y validación de parámetros |
| `writer.py` | Bloques XML independientes y escritura protegida |
| `gui.py`, `cli.py`, `preview.py` | Ventana, consola y vista opcional |
| `examples/`, `tests/` | Mallas de demostración y pruebas |
| `reference/` | Copia identificada del FEB aportado |
| `simulations.py`, `scaffold_feb/templates/` | Adaptación y plantilla del ensayo del ejemplo |

El escritor sigue la estructura observada en el FEB aportado: Module con SI, Material, Mesh, MeshDomains y Output. Numeración desde 1, elementos con identificadores globales, caras numeradas dentro de cada Surface y NodeSet con lista de identificadores. El ensayo añade Globals, Boundary, Step y LoadData, los NodeSets de apoyo y un Output específico. La API también permite inyectar bloques XML externos, sin combinarlos con el ensayo integrado.

## Ejemplos y comprobaciones

`examples/` contiene cubo y cilindro en VTK ASCII/binario, VTU y STL ASCII/binario, además de un cubo tet10, uno hex8 y otro con poro. Sus dimensiones son deliberadamente sencillas y se interpretan en metros con factor 1. Los archivos `.feb` generados están en `examples/feb/` y su resumen en `examples/feb/resumen.json`.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas cubren conteos, normales, inversiones, nodos intermedios, fusión, unidades, componentes, vóxeles, poros pasantes, cavidades y entradas inválidas. Los ejemplos se pueden regenerar con `python -m scaffold_feb.examples otra_carpeta`. Consulta `VALIDACION.md` para el resultado y los límites de la verificación de esta entrega.

Referencias técnicas: [meshio](https://github.com/nschloe/meshio), [TetGen para Python](https://tetgen.pyvista.org/), [documentación de FEBio](https://help.febio.org/). La identificación concreta del FEB usado está en `reference/README.md` y su análisis en `../NOTAS.md`.
