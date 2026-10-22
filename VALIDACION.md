# Comprobación del 21 de octubre de 2026

Entorno: Windows, Python 3.12, FEBio 4.10.0.

Actualización de nombres: 25 pruebas focalizadas aprobadas, incluidas coincidencias dentro del mismo minuto y registros con nombres repetidos o reservados. Las carpetas nuevas usan `FEB_fecha_hora-minuto` y `SIM_fecha_hora-minuto`; se conservan los resultados existentes.

- 66 pruebas pytest aprobadas: formatos, geometría, selección de superficies, materiales, protocolo configurable, lotes y ejecución del solver.
- El ejecutor se comprobó con terminación correcta, error con código de salida 0, entradas XML inválidas, cancelación del proceso propio y cancelación de pendientes. Se verificó el aislamiento de salidas y que las ejecuciones repetidas crean carpetas nuevas.
- Integración de la pestaña del solver con FEBio 4.10 aprobada: dos simulaciones reales completadas y un FEB sin protocolo rechazado entre ambas, con continuidad, ejecución automática y estados finales correctos. Script: `validation_outputs/check_solver_gui.py`; resultados en `validation_outputs/solver_gui_check/`.
- Integración del lote en Tkinter aprobada: dos exportaciones, una malla inválida registrada, avance por archivo, eliminación de filas y parámetros fijados al iniciar aunque se editen después. Script: `validation_outputs/check_gui_batch.py`.
- FEBio 4.10 completó las pruebas de control por fuerza (1 N) y por porcentaje (12 %) con tiempos personalizados y terminación normal. La suma de las reacciones de la base fue 1 N para la carga de 1 N. Registros: `validation_outputs/control_fuerza_reacciones.log` y `validation_outputs/control_porcentaje.log`.
- Se verificaron lotes con archivos del mismo nombre en carpetas distintas, continuidad tras una entrada inválida, exportaciones repetidas sin reemplazar salidas anteriores y compresión porcentual adaptada a alturas diferentes.
- Prueba de integración Tkinter aprobada: selección del ensayo, bloqueo si falta una tapa, conservación de los parámetros Mooney-Rivlin al cambiar de simulación y exportación correcta mediante el proceso separado. Script: `validation_outputs/check_gui_phase2.py`.
- El ensayo generado sobre el cubo de seis tet4 completó los 800 incrementos, hasta 8 s, con `NORMAL TERMINATION` en FEBio. Registro: `validation_outputs/compresion_solver.log`.
- Se comprobaron las referencias a Surface y NodeSet, los anclajes y grados de libertad para X/Y/Z; la conservación exacta de los bloques Control y LoadData respecto al ejemplo; el desplazamiento fijo −0.1 m en una pieza de altura 2 m; y que el material elegido no cambia al activar el ensayo.
- Se cubren el rechazo de tapas ausentes, compresión mayor o igual a la separación y piezas desconectadas, y la exportación de solo geometría sin condiciones.
- Se generó `salidas/SPINODOID_GRF_compresion_mantenimiento.feb` con la malla del usuario, eje Z, tolerancia de plano 0.002 m y material neo-Hookeano del catálogo. No se ejecutó el ensayo completo sobre esa malla de 48.579 tetraedros; la convergencia de cada geometría y material debe comprobarse al resolverla.
- La vista PyVista se instaló y comprobó mediante un render del cubo. Linux no se ha ejecutado en este entorno.

Los resultados del cubo validan la exportación y ejecución, no la validez experimental de los parámetros del material ni la convergencia de todas las geometrías.
