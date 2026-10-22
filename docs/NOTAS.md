# Conversor de mallas spinodoidales a FEBio — Fase 0

Fecha: 20 de octubre de 2026.

**Estado:** fase 0 completada, incluido el análisis del FEB proporcionado por el usuario. Se entrega este documento antes de comenzar la fase 1. La fase 2 queda fuera del alcance actual.

## 1. Alcance y decisiones confirmadas

El usuario confirmó durante esta revisión:

- El mallador de referencia es `01-TPMS-scaffolds-generator (copy)/`.
- El ejemplo autorizado es `../cilindro_neo2__t1-0.9_t2-0.8_g1-0.4_g2-0.3.feb`, proporcionado después de la primera entrega de estas notas.
- El destino es FEBio 4.x, con `febio_spec` 4.0.
- Las unidades serán **SI: metros, newtons, pascales y segundos; densidad en kg/m³**. Esto sustituye la propuesta inicial mm–N–MPa–s.

Las rutas `reference/...` del encargo no existían en la primera revisión. La aplicación conservará una copia identificada del ejemplo autorizado; el mallador permanece en su ubicación original. No se han proporcionado XML adicionales para la fase 2.

Las rutas citadas a continuación son relativas a la carpeta PID. Los números de línea corresponden a las fuentes leídas durante esta revisión.

Se realizó lectura estática del código, inspección de XML y de registros existentes. No se ejecutaron malladores, simulaciones ni pruebas de apertura en FEBio Studio.

## 2. Cómo trabaja el mallador TPMS

En esta sección, `src/` y `test/` se refieren al interior de `01-TPMS-scaffolds-generator (copy)/`.

### Lectura y representación de mallas

El mallador usa `meshio.Mesh`: coordenadas en `points` y conectividades agrupadas en bloques de celdas. `ScaffoldMesh` no implementa un lector general para todos los formatos solicitados.

Los ejemplos `test/compare_biocarriers.py:14–17,30–33` importan STL mediante `meshio.read`, asignan la malla a `tpms_mesh` y llaman a `repair_mesh`. El ejemplo antiguo `test/OLD/mark_periodic_bounds.py:17–21` lee VTU, pero obtiene `cells[0].data` sin comprobar el tipo de ese bloque.

No se encontró en este flujo una detección explícita del caso STL binario cuyo encabezado empieza por `solid`.

### Generación de superficie y volumen

| Operación | Implementación observada |
|---|---|
| Superficie de un campo implícito | `pygalmesh.generate_surface_mesh`, `src/scaffold.py:248–261` |
| Volumen de un campo implícito | `pygalmesh.generate_mesh`, `src/scaffold.py:263–275` |
| Volumen periódico | `pygalmesh.generate_periodic_mesh`, `src/scaffold.py:277–293` |
| Volumen desde imagen binaria | `pygalmesh.generate_from_array`, `src/scaffold.py:205–227` |
| Superficie a volumen | OFF temporal y `generate_volume_mesh_from_surface_mesh`, con `reorient=True`, `src/scaffold.py:127–144` |

El tamaño de malla se deriva de `target_size` y sus parámetros asociados. Este código utiliza pygalmesh/CGAL, no TetGen ni gmsh. Su instalación no debe convertirse en requisito del nuevo conversor: el encargo pide una alternativa instalable mediante pip para Windows y Linux.

`test/generate_spinodoid.py:16–18,26–30` ejemplifica un spinodoide cilíndrico, primero superficial y después volumétrico.

### Tipos de elemento y numeración

Los tipos explícitos del flujo revisado son `triangle` y `tetra`: triángulos de tres nodos y tetraedros de cuatro nodos. No se encontró soporte propio para tet10, hex8 o conversión de VTK_VOXEL.

`triangle_to_tetras`, en `src/helpers.py:539–557`, **no tetraedraliza una superficie**. Si encuentra triángulos, conserva el bloque tetraédrico ya existente y descarta los demás. Al reconstruir la malla tampoco conserva sus datos de puntos/celdas.

`reorganize_nodes`, en `src/helpers.py:559–589`, elimina nodos no utilizados y remapea la conectividad con índices consecutivos **desde cero**. Dentro de `triangle_to_tetras`, esta limpieza solo se ejecuta en la rama que encuentra un bloque `triangle`.

No existe una convención de IDs FEBio ni una adaptación VTK→FEBio en el mallador.

### Detección y clasificación de superficies

Hay dos mecanismos distintos:

1. `extract_triangular_surface`, en `src/metrics.py:222–254`, requiere que ya exista `mesh.cells_dict['triangle']`. Clasifica esos triángulos; no extrae las caras de un volumen sin superficie.
2. `find_boundary_triangles`, en `src/helpers.py:592–623`, enumera las cuatro caras de cada tetra4, cuenta sus apariciones y devuelve las que pertenecen a un solo elemento.

La primera función evalúa una envolvente implícita y etiqueta como exterior un triángulo cuando todos sus vértices cumplen `phi >= -1e-3`. Guarda dos grupos con `cell_data['I/O']`: interior y exterior. La tolerancia está fijada en el código.

La envolvente se obtiene de parámetros globales, no del bounding box importado. El cilindro presupone eje Z y coordenadas XY para el radio; su grupo exterior reúne tapas y pared lateral. El cubo tampoco se divide en seis superficies seleccionables (`src/metrics.py:187–218`, `src/parameters.py:5–15`).

La segunda función usa tuplas de índices **ordenadas numéricamente** tanto para contar como para devolver las caras. Ese orden sirve para identificar caras compartidas, pero pierde el sentido de giro geométrico. Por tanto, no garantiza normales exteriores. `find_boundary_nodes`, en `src/helpers.py:668–710`, reutiliza la idea de incidencia para obtener nodos de frontera.

`mark_boundaries` y `map_boundary_nodes` buscan parejas periódicas por traslación, con tolerancia fija `1e-4`, y guardan CSV. No generan `Surface` ni `NodeSet` de FEBio.

### Normales, orientación y limpieza

La normal triangular se calcula mediante `(p1-p0) × (p2-p0)`. Después de generar una superficie, se calcula su volumen firmado; si es negativo, se invierten todos los triángulos con la permutación `[0,2,1]` (`src/scaffold.py:258–261`). Esta comprobación global no demuestra que cada cara o cada componente esté orientada correctamente.

`repair_mesh`, en `src/scaffold.py:157–180`, solo trata mallas cuyo conjunto de tipos es exactamente `{'triangle'}`:

- Construye un `trimesh.Trimesh` con validación.
- Si no representa un volumen, voxeliza, rellena, reconstruye mediante marching cubes, suaviza y recupera el bounding box original.
- Aplica `fix_normals`, `fix_inversion`, `fill_holes`, `merge_vertices` y `remove_unreferenced_vertices`.

La reconstrucción por vóxeles puede modificar poros, espesores y geometría aunque mantenga la caja exterior. No debe copiarse como limpieza automática del nuevo conversor. Tampoco se expone aquí una tolerancia de fusión elegible por el usuario.

`surface_quality`, en `src/metrics.py:41–68`, informa cierre, orientación coherente, degenerados, duplicados, nodos huérfanos y número de cuerpos. No implementa la opción de conservar la componente mayor.

No se encontró validación ni corrección explícita de Jacobianos volumétricos. Existe `reorient_surface_triangles`, en `src/helpers.py:777–795`, pero no se encontraron llamadas en los `.py`; sus nombres de variables y comentario no coinciden con el signo de los desplazamientos evaluados. No constituye una garantía reutilizable de orientación.

### Escritura de archivos

`save_mesh`, en `src/scaffold.py:146–155`, delega en `meshio.Mesh.write`. Las extensiones predeterminadas son VTU y STL. La clasificación I/O también puede exportarse a VTK.

**No se encontró un escritor `.feb` en este mallador.** Las búsquedas en sus fuentes, Markdown y notebooks no localizaron `febio_spec`, `MeshDomains`, `NodeSet` ni un flujo de exportación FEBio. La estructura XML de referencia es la del ejemplo analizado en la sección 4.

## 3. Código relacionado ya existente en PID

Estos componentes son antecedentes útiles, no una aplicación que ya cumpla el nuevo encargo.

### `cli-febio/convertir.py`

- Lectores propios de VTU y VTK legacy, ASCII y binario (`:102`, `:167`, `:219`).
- Solo acepta VTK_TETRA, tipo 10, de cuatro nodos (`:283–295`).
- Comprueba finitud, índices y determinante. Corrige tetra4 invertidos intercambiando los nodos locales 0 y 1 (`:299–326`).
- Escribe XML 4.0 con ElementTree; nodos y elementos empiezan en 1 y las conectividades internas se exportan con `+1` (`:333–385`).
- Su demostración de compresión selecciona NodeSets inferior/superior por bandas Z, con ancho relativo predeterminado del 2 %. No extrae caras ni escribe `Surface`.
- Tiene una ruta Windows predeterminada al solver; no debe trasladarse al nuevo programa.

### `Predicción/conversion_feb.py`

Es la base parcial más cercana al lector y al escritor necesarios:

- Lee VTK/VTU mediante meshio y numpy, valida coordenadas y referencias, y avisa cuando omite celdas de dimensión inferior (`:128–189`).
- Declara tet4, tet10, hex8 y otros tipos fuera del alcance solicitado (`:56–66`).
- Rechaza entradas sin volumen; no lee STL ni tetraedraliza.
- `_feb_connectivity` deja tet4/tet10/hex8 en el orden recibido; adapta otros tipos. Esa conducta debe verificarse contra FEBio y el lector para cada tipo solicitado, no asumirse correcta por reutilizarla (`:251–258`).
- No contiene una conversión explícita de VTK_VOXEL. Debe comprobarse si el lector lo rechaza, conserva o transforma antes de definir una adaptación que evite reordenarlo dos veces.
- `_validate_corner_geometry` rechaza inversiones y degeneraciones, pero no corrige orientación. Para tet10 solo utiliza las cuatro esquinas; para hex8 muestrea ocho puntos de Gauss. No valida completamente la geometría curva de tet10 (`:261–310`, `:432–433`).
- No fusiona duplicados, elimina huérfanos, selecciona componentes ni genera `Surface` o `NodeSet`.
- La inspección devuelve nodos, cantidades por tipo y avisos, pero no bounding box (`:213–239`).
- Exporta Module, Material opcional, Mesh y MeshDomains. Agrupa elementos por tipo/material y asigna IDs globales desde 1. No incluye Control, Boundary, Loads, Step ni Output (`:339–443`).

El catálogo está embebido en Python. Incluye `isotropic elastic`, `neo-Hookean` y **`coupled Mooney-Rivlin`**, con densidad opcional; no tiene unidades y valores predeterminados estructurados en un JSON independiente.

La GUI `Predicción/interfaz_feb.py` usa Tkinter y separa el proceso lector, pero presenta tres pestañas diferentes del diseño solicitado y carece de superficies y vista previa. Contiene `os.startfile` para abrir la salida, que deberá sustituirse o evitarse para portabilidad.

### `codigo_mallador/seg2mesh.py`

Lee segmentaciones NIfTI y genera volumen con pygalmesh. Conserva tetra4 y escribe VTU ASCII, descartando los bloques superficiales. No es un conversor FEBio ni resuelve la extracción de superficies. Incluye rutas absolutas Windows.

## 4. Archivo FEBio de referencia

### Ejemplo autorizado: cilindro viscoelástico

Archivo original: `../cilindro_neo2__t1-0.9_t2-0.8_g1-0.4_g2-0.3.feb` (11.438.997 bytes). SHA-256: `36cee61384157a44333b1339c598c19762fcf5e3590dba5f9e6021b1d0d78f8d`.

Se pudo analizar como XML. Declara ISO-8859-1, `febio_spec="4.0"` y `<Module type="solid"><units>SI</units></Module>`. La lectura estructural no sustituye una apertura o ejecución actual en FEBio Studio.

| Sección raíz, en orden | Evidencia y contenido |
|---|---|
| Module | Líneas 3–5: solid, SI |
| Globals | Línea 6: constantes T, P, R y Fc |
| Material | Línea 14: Material1, tipo viscoelastic, con elastic neo-Hookean anidado |
| Mesh | Línea 36: Nodes, Elements, NodeSet y Surface |
| MeshDomains | Línea 178744: SolidDomain Part3 → Material1 |
| Boundary | Línea 178747: tres restricciones globales |
| Step | Línea 178764: Step01 y Step02; cada uno contiene Control y Boundary |
| LoadData | Línea 178908: controlador LC2, tipo loadcurve |
| Output | Línea 178919: plotfile y logfile |

No hay Control en la raíz ni secciones Loads, Contact, Rigid o MeshData. Las condiciones se aplican mediante desplazamientos prescritos, de modo que la ausencia de Loads no implica ausencia de solicitación.

La malla contiene **82.677 nodos y 76.800 hex8** en el bloque Part3. Los IDs nodales abarcan 1–82677 y los de elementos 1–76800. El bounding box es X=[−1,1], Y=[−1,1], Z=[0,1]. Con el SI declarado se interpretaría como diámetro 2 m y altura 1 m; la geometría por sí sola no demuestra que esas sean sus dimensiones físicas pretendidas.

Hay cinco Surface, cada una con 3.840 quad4 y numeración local desde 1:

- `ZeroDisplacement1`, `ZeroDisplacement2` y `ZeroDisplacement4` están en Z=0; los productos vectoriales examinados apuntan hacia −Z.
- `PrescribedDisplacement4` y `PrescribedDisplacement5` están en Z=1 y apuntan hacia +Z.

Las cinco superficies representan repetidamente las dos tapas para distintas condiciones/pasos. En la aplicación se generarán dos selecciones geométricas reutilizables. Se conservará el formato observado `<Surface name="..."><quad4 id="1">...</quad4></Surface>`.

Los cinco NodeSet contienen un solo ID: ZeroDisplacement6/7/8 usan el nodo 5; ZeroDisplacement9/11 usan el 4195. Se escriben como listas de texto, no como etiquetas node anidadas. Boundary también utiliza `node_set="@surface:..."`. Para satisfacer el nuevo encargo se crearán además NodeSets con todos los nodos de cada Surface y su mismo nombre.

El material del ejemplo es **viscoelastic**, con density=1, t1=0.9, t2=0.8, t3…t6=1, g0=1, g1=0.4, g2=0.3 y g3…g6=0; el bloque elastic interno es neo-Hookean con E=100 y v=0.3. No es un neo-Hookean simple. Esta referencia no cambia los tres materiales iniciales solicitados ni autoriza añadir ensayos viscoelásticos en fase 1.

Step01 declara 100 pasos de 0.01; Step02, 700 de 0.01. El desplazamiento prescrito es −0.1 en Z; el primer paso usa lc=1 y el segundo un valor fijo. LC2 contiene (0,0), (0.1,1), (5.1,1), interpolación LINEAR y extensión CONSTANT. Output pide displacement, stress, relative volume y reaction forces; sus archivos de registro corresponden al ensayo del ejemplo y no se copiarán a una exportación de geometría.

La fase 1 reutilizará la organización Module/Material/Mesh/MeshDomains y la sintaxis de selecciones. Boundary, Step y LoadData se reservarán para las plantillas futuras. Los parámetros físicos del ejemplo se documentan como evidencia, no como propiedades reales de todos los andamios.

### Comparación con archivos locales, sin adoptarlos como referencia

El inventario de `Ejemplos FEBio/jobs/`, `Febio_Pruebas/jobs/` y `cli-febio/examples/`, incluyendo subcarpetas, encontró 41 archivos `.feb`; todos declaran formato 4.0. Esto no demuestra que abran correctamente ni que deban servir de plantilla.

El archivo pequeño `cli-febio/examples/cubo.feb` permite observar una estructura concreta:

| Sección raíz, en orden | Contenido observado |
|---|---|
| Module | `type="solid"` |
| Control | Análisis estático, diez pasos, tamaño 0.1 y solver solid |
| Material | `neo-Hookean`, E=1000 y v=0.3; no declara unidades físicas |
| Mesh | Ocho nodos, seis tet4 y NodeSets `inferior`/`superior`, cuatro nodos cada uno |
| MeshDomains | SolidDomain `solid` asociado a `material_base` |
| Boundary | Desplazamiento nulo inferior y desplazamiento prescrito en Z superior |
| LoadData | Un controlador loadcurve |
| Output | Variables displacement y stress |

No contiene `Surface`, `Loads` ni `Step`. Sus IDs nodales y de elementos comienzan en 1. Los NodeSets son listas de IDs separadas por comas. Es una demostración de compresión, no el formato definitivo para la fase 1.

Otros archivos permiten contrastar las superficies y las diferencias entre sólidos y láminas:

| Archivo comparativo | Contenido observado |
|---|---|
| `Ejemplos FEBio/jobs/espinodoide compresion.feb` | 18.427 nodos; 61.624 tet4 y 1.000 hex8; seis Surface con tri3/quad4; sin NodeSet explícitos |
| `Ejemplos FEBio/jobs/PruebaTorsionDiamante.feb` | 24.200 nodos; 97.136 tri3 de lámina y un hex8; dos Surface; incluye ShellDomain y espesores en MeshData |
| `Febio_Pruebas/jobs/Ejemplo_Tensil.feb` | 756 nodos, 500 hex8, tres Surface con 25/50/25 quad4; material literal `Mooney-Rivlin` |

En el ejemplo de espinodoide las secciones raíz son Module, Globals, Material, Mesh, MeshDomains, Boundary, Rigid, Contact, Step, LoadData y Output. La malla empieza en la línea 30, los dominios en 95745 y Step en 95807. Los IDs de caras comienzan en 1 dentro de cada Surface. Las condiciones de borde usan referencias `node_set="@surface:..."` en vez de NodeSets explícitos; el nuevo encargo sí pide exportar ambos conjuntos.

El ejemplo de torsión contiene Module, Control, Globals, Material, Mesh, MeshDomains, MeshData, Boundary, Rigid, LoadData y Output. Sus tri3 son elementos físicos de lámina, no caras extraídas de tetraedros: no debe copiarse ese esquema para convertir un STL en un sólido.

El registro existente `cli-febio/examples/cubo.log` termina en `N O R M A L T E R M I N A T I O N`. Los registros existentes de `espinodoide compresion` y `PruebaTorsionDiamante` terminan con error y mencionan Jacobianos negativos durante la solución. Son evidencias históricas de ejecuciones, no una comprobación actual en Studio; tampoco se verificó su correspondencia exacta con el contenido actual de cada FEB. Un fallo de simulación no demuestra por sí mismo que su XML no pueda importarse.

## 5. Criterios técnicos para la fase 1

Esta sección deja decisiones y comprobaciones preparadas; no describe código implementado.

### Entrada, escala y limpieza

- Usar directamente el volumen cuando exista; informar claramente cuándo la entrada es superficial y necesita tetraedralización.
- Leer con meshio y comprobar el tratamiento real de STL ASCII/binario. Incluir expresamente un binario cuyo encabezado empiece por `solid`; no decidir el formato solo por esa palabra.
- Validar una superficie antes de tetraedralizar: cierre, conectividad y ausencia de degeneraciones que impidan definir el sólido. Evitar reparaciones que rellenen poros o cambien la geometría sin una decisión explícita.
- Seleccionar y verificar TetGen o gmsh al implementar esta etapa. Documentar qué significa el tamaño configurable y comprobar que el mallado respeta el sólido poroso.
- Fusionar duplicados con tolerancia configurable, remapear todas las referencias y volver a comprobar degeneraciones. Eliminar huérfanos después de filtrar elementos/componentes.
- Mostrar nodos, elementos por tipo, bounding box, cambios aplicados y advertencias.
- Las unidades de salida están confirmadas; **la unidad de las coordenadas de cada archivo de entrada no está demostrada por esa confirmación**. Los parámetros del mallador usan dimensiones numéricas como 0–1 sin declarar una unidad física.
- Antes de convertir mallas reales, aclarar si sus coordenadas ya son metros o necesitan una escala explícita. No inferir metros o milímetros por la magnitud del bounding box.

### Elementos, Jacobianos y superficies

- Trabajar internamente con índices desde cero y traducir a IDs desde uno al exportar.
- Verificar tablas de conectividad VTK/meshio/FEBio para tet4, tet10 y hex8, incluyendo el caso voxel. En tet10 una inversión debe permutar también los nodos intermedios de las aristas.
- Separar un elemento con conectividad invertida de uno degenerado o geométricamente plegado: intercambiar nodos no repara todos los casos.
- La validación de tet10 debe utilizar sus funciones de forma completas, no solo las cuatro esquinas. Documentar los puntos de evaluación y los límites de una comprobación por muestreo.
- Extraer caras por incidencia y conservar por separado el orden orientado y el elemento propietario. No exportar como conectividad la clave ordenada usada para contar caras.
- Orientar la normal hacia fuera del sólido usando la relación con el elemento propietario; esto incluye las paredes de los poros. Para elementos curvos, comprobar la orientación donde corresponda.
- Admitir tri3, tri6 y quad4 como caras de tet4, tet10 y hex8. Detectar incidencias no válidas y caras compartidas con conectividad incompatible.
- Seleccionar una cara por plano solo si **todos sus nodos**, incluidos los intermedios de tri6, satisfacen la tolerancia. No seleccionar únicamente por centroide ni construir un rectángulo/disco artificial.
- Crear cada NodeSet como la unión de los nodos de su Surface, con el mismo nombre. Nodos comunes a dos superficies son normales en aristas y esquinas.
- Para el cubo, usar los seis extremos del bounding box. Para el cilindro, separar únicamente las dos tapas a lo largo del eje elegido y permitir corregir la detección automática.

El usuario confirmó que basta con ejes X/Y/Z. La opción de retirar fragmentos quedará desactivada de inicio; al activarla se conservará la componente conectada por caras de mayor volumen y se informará lo descartado. Esto mantiene la pieza principal sin favorecer regiones que solo tengan una discretización más fina.

### Materiales y unidades

El catálogo JSON deberá guardar nombre visible, tipo exacto de FEBio, parámetros, unidades, restricciones y valores iniciales identificados como ejemplos.

| Material solicitado | Parámetros principales | Unidades SI |
|---|---|---|
| isotropic elastic | E, v, density | Pa, adimensional, kg/m³ |
| neo-Hookean | E, v, density | Pa, adimensional, kg/m³ |
| Mooney-Rivlin | c1, c2, k, density | Pa, Pa, Pa, kg/m³ |

El tipo literal `Mooney-Rivlin` solicitado es distinto de `coupled Mooney-Rivlin`, presente en el conversor anterior. La documentación oficial describe formulaciones diferentes. No se deben intercambiar sus nombres ni trasladar los valores de una formulación a la otra sin revisión: [Mooney-Rivlin](https://febiosoftware.github.io/febio-docs/features/features/solid_material_mooney-rivlin/) y [variante acoplada](https://febiosoftware.github.io/febio-docs/features/features/solid_material_coupled_mooney-rivlin/).

FEBio requiere que el usuario mantenga unidades coherentes. En el SI confirmado, los módulos se expresarán en Pa y la densidad en kg/m³. Los valores E=1000 y v=0.3 del cubo de demostración no permiten inferir el material físico de los andamios. Véase [unidades en FEBio](https://febiosoftware.github.io/febio-docs/user/chapter1/1.4-units-in-febio/).

### Interfaz y organización

Se elige **Tkinter con ttk** para esta interfaz pequeña: permite formularios y controles suficientes sin añadir PySide6. Tk está disponible para Windows y Linux; su instalación se comprobará con `python -m tkinter`, y el README deberá contemplar las distribuciones que lo empaquetan aparte. Referencia: [documentación de Tkinter](https://docs.python.org/3/library/tkinter.html).

La interfaz tendrá las dos secciones solicitadas: geometría/material y superficies. Lectura y mallado deberán ejecutarse sin bloquear el bucle de eventos. PyVista será opcional, con importación diferida y una ventana/proceso separado si facilita mantener la exportación independiente de la vista previa.

Separación propuesta:

| Componente | Responsabilidad |
|---|---|
| Lectura y modelo de malla | Formatos, puntos, conectividades y avisos |
| Limpieza y validación | Fusión, componentes, huérfanos, orientación y Jacobianos |
| Tetraedralización | Adaptador del backend elegido y control del tamaño |
| Superficies | Frontera, orientación, planos y NodeSets |
| Materiales | Lectura y validación del catálogo JSON |
| Escritor FEB | Bloques XML independientes y referencias consistentes |
| CLI | Ejecución reproducible del mismo núcleo |
| GUI | Selección de parámetros y presentación de resultados |

La aplicación se desarrollará en `spinodoid_feb/`, una carpeta independiente dentro de PID.

### Preparación para fase 2

El escritor deberá separar Mesh, Material, MeshDomains y Output, y dejar puntos de integración para Boundary, Loads y Step desde `templates/`. Cuando se añadan simulaciones también deberán coordinarse Control, LoadData y los IDs/nombres referenciados.

La fase 1 exportará geometría/material/superficies para configurar el modelo. No añadirá la demostración de compresión del CLI anterior. Al igual que el ejemplo autorizado, no necesita un Control raíz para almacenar la geometría; no se añadirá Step en fase 1. La importación de las salidas se verificará por separado.

La versión del programa FEBio y la versión `febio_spec` son numeraciones distintas. La forma de representar algunas secciones cambia entre formatos; no bastaría con cambiar el atributo de versión para ofrecer 3.0 o 2.5. El destino confirmado es únicamente 4.0. Referencias: [formato FEBio](https://febiosoftware.github.io/febio-docs/user/chapter3/3.1-free-format-overview/) y [Mesh, NodeSet y Surface](https://febiosoftware.github.io/febio-docs/user/chapter3/3.6-mesh-section/).

## 6. Validación prevista

Las pruebas solicitadas se implementarán en fase 1; no hay resultados de esa aplicación todavía.

- Cubo y cilindro en VTU, VTK legacy ASCII/binario y STL ASCII/binario; incluir el STL binario con encabezado `solid`.
- Cantidades conocidas de nodos y elementos, bounding box y caras por superficie. Como fixture disponible, el cubo del CLI tiene ocho nodos y seis tet4.
- Normales exteriores respecto del elemento propietario, caras interiores excluidas y NodeSets exactamente iguales a la unión de nodos de cada superficie.
- Casos tet10/tri6, hex8/quad4 y voxel, con comprobación de orden local y orientación.
- Duplicados con distintas tolerancias, huérfanos, fragmentos separados, elementos invertidos/degenerados y errores de conectividad.
- Poros que atraviesan las tapas, selección cerca del umbral de tolerancia y eje cilíndrico editable.
- XML con IDs únicos y referencias válidas, materiales correctos y preservación de coordenadas/escala.
- Errores legibles ante archivos corruptos, ausencia de volumen y superficies no aptas para mallar.
- Apertura real en FEBio Studio de las salidas representativas y comprobación en Windows y Linux.

Un XML bien formado, un test unitario aprobado o un registro histórico del CLI no sustituyen la prueba de apertura en Studio.

## 7. Cierre de fase 0

Se analizaron el mallador, los conversores locales y el ejemplo FEB autorizado. Quedaron documentados estructura XML, materiales, numeración, orientación, limitaciones y alcance de la fase 1.

Las coordenadas de los archivos de entrada se conservarán de forma predeterminada. Se ofrecerá un factor explícito para convertirlas a metros cuando se conozca la medida física; no se inferirá una unidad a partir de la extensión STL/VTK/VTU. La escala física de las mallas reales sigue siendo responsabilidad de la configuración de cada importación.

Con esta entrega se puede comenzar la fase 1. Permanecen fuera de alcance las condiciones de simulación de la fase 2.
