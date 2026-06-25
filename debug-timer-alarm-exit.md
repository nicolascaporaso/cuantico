[OPEN] timer-alarm-exit

## Objetivo
- Corregir el manejo de timers/alarmas relativas y absolutas.
- Ajustar la zona horaria interna a America/Argentina/Buenos_Aires.
- Agregar logs y manejo de excepciones alrededor del scheduler/callback para capturar fallas reales cuando vence una alarma.

## Sintomas
- Pedidos como "en 60 segundos" a veces terminan yendo por `crear_alarma_hora`.
- La hora interna de referencia sigue orientada a Europe/Madrid.
- El usuario reporta cierre del proceso cuando una alarma vence y habla.

## Hipotesis
1. El modelo elige la tool equivocada por docstrings/prompt insuficientemente precisos para diferenciar duracion relativa vs hora absoluta.
2. El scheduler dispara bien, pero el callback de alarma rompe el proceso durante `_hablar()` o TTS.
3. La zona horaria usada por Cuantico deforma la interpretacion de horas y empeora la seleccion de tools.
4. `timers.py` carece de instrumentacion suficiente y por eso el error real del callback queda oculto.
5. La configuracion del servicio systemd no es la causa principal, aunque tiene un warning aparte.

## Evidencia Actual
- Logs muestran que "Poné una alarma para dentro de 60 segundos" llamo `crear_alarma_hora("02:34")` en vez de `crear_temporizador(...)`.
- `timers.py` programa alarmas HH:MM para hoy o manana si ya paso.
- No hay aun evidencia completa del cierre al vencer una alarma porque faltan logs explicitos en `timers.py`.

## Instrumentacion Aplicada
- `timers.py` ahora emite:
  - `timers-init`
  - `timer-created`
  - `alarm-created`
  - `timer-fired`
  - `timer-callback-start`
  - `timer-callback-end`
  - `timer-callback-error`
- `main.py` ahora emite:
  - `alarm-callback-enter`
  - `alarm-callback-exit`
  - `alarm-callback-error`

## Fix Aplicado
1. Se agrego `programar_aviso(cuando, etiqueta)` como tool unificada para lenguaje natural:
   - segundos
   - minutos
   - horas
   - dias
   - hoy/manana a HH:MM
   - am/pm
2. Se reforzaron docstrings y prompt para preferir esa tool en pedidos temporales.
3. La zona horaria interna se cambio a `America/Argentina/Buenos_Aires`.
4. `timers.py` ahora calcula alarmas absolutas con hora local de Buenos Aires.
5. `calendario.py`, `recuerdos.py` y referencias temporales del prompt usan la nueva zona horaria.
6. `cuantico.service` se corrigio para usar la ruta real y mover `StartLimitIntervalSec/StartLimitBurst` a `[Unit]`.

## Plan
1. Instrumentar `timers.py` y el callback de alarma con logs y excepciones controladas.
2. Verificar como se construye el contexto temporal del modelo.
3. Implementar soporte robusto para segundos/minutos/horas relativos y horas absolutas.
4. Ajustar zona horaria de referencia a Buenos Aires.
5. Validar con compilacion y dejar guia de prueba.
