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

## Evidencia Recolectada
- Hipotesis 1 confirmada.
- La wake word se detecto correctamente (`score` 0.445 / 0.886), pero el proceso cayo antes de pasar a reconocimiento de voz.
- La excepcion exacta fue:
  - `TypeError: Object of type float32 is not JSON serializable`
  - origen: `micro.py` en `_debug_emit("wake-detected", {"score": round(mejor, 4), ...})`
- El cierre no vino del flujo de negocio sino del logger de instrumentacion.

## Fix Minimo Aplicado
1. Se agrego serializacion segura para tipos numpy en `micro.py`.
2. Se fuerza `score` y `threshold` a `float` nativo al registrar `wake-detected`.

## Estado
- Listo para reintentar reproduccion con la misma instrumentacion.
