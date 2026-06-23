[OPEN] Debug Session: unexpected-process-exit

## Resumen
- Sintoma: Cuantico "se cuelga", pero en realidad el proceso Python se cierra mientras la Raspberry sigue encendida.
- Objetivo: recolectar evidencia de runtime para identificar por que el proceso termina.

## Hipotesis Iniciales
1. Una excepcion no capturada fuera del loop principal termina el proceso.
2. Un subproceso de audio/TTS/STT falla y arrastra el cierre del proceso.
3. Un fallo de red o I/O queda oculto y dispara una salida fatal.
4. Un hilo secundario (luces, timers, micro) lanza una excepcion relevante.
5. Existe una ruta de salida no intencional en el flujo principal.

## Plan
1. Agregar instrumentacion de arranque, ciclo principal y cierres.
2. Agregar trazas en puntos criticos: audio, micro, timers, modo llamada, OpenRouter.
3. Reproducir la caida y observar el ultimo bloque de logs.
4. Confirmar o descartar hipotesis con evidencia.
5. Aplicar fix minimo cuando la causa este probada.
