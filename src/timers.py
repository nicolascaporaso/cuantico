"""Timers y alarmas persistentes.

Un único thread scheduler con heapq. Al vencer un timer se invoca un callback
que Cuántico usa para hablar (con encolado si está hablando justo en ese
momento, para no solapar audio).

Persistencia: state/timers.json se reescribe tras cada mutación. Al arrancar,
los timers cuya hora ya pasó se disparan inmediatamente con mensaje "mientras
no estabas".
"""
import heapq
import json
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta

import config

_RUTA = Path(config.STATE_DIR) / "timers.json"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_heap: list[tuple[float, str]] = []          # (timestamp_unix, id)
_timers: dict[str, dict] = {}                # id -> {tipo, vence, etiqueta}
_thread: threading.Thread | None = None
_cerrar = False
_callback = None                             # fn(texto, emocion)


# #region debug-point timers-runtime
def _json_safe(value):
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "T",
        "location": "timers.py",
        "msg": f"[DEBUG] {msg}",
        "data": data or {},
        "ts": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False, default=_json_safe)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
# #endregion


def _persistir():
    try:
        datos = [_timers[id_] | {"id": id_} for _, id_ in _heap if id_ in _timers]
        _RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"⚠️ timers: no he podido persistir: {e}")


def _cargar():
    if not _RUTA.exists():
        return
    try:
        datos = json.loads(_RUTA.read_text())
    except Exception as e:
        print(f"⚠️ timers.json corrupto, lo ignoro: {e}")
        try:
            _RUTA.rename(_RUTA.with_suffix(".json.bak"))
        except Exception:
            pass
        return
    ahora = time.time()
    vencidos = []
    for d in datos:
        id_ = d["id"]
        vence = float(d["vence"])
        _timers[id_] = {"tipo": d["tipo"], "vence": vence, "etiqueta": d.get("etiqueta", "")}
        heapq.heappush(_heap, (vence, id_))
        if vence <= ahora:
            vencidos.append(d.get("etiqueta") or id_)
    if vencidos:
        print(f"⏰ timers: {len(vencidos)} vencidos mientras estaba apagado → los disparo al arrancar.")


def _corto_id() -> str:
    return secrets.token_hex(3)


def _ahora_local() -> datetime:
    return config.now_local()


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.split())


def _registrar_programacion(tipo: str, vence: float, etiqueta: str = "") -> str:
    id_ = _corto_id()
    with _cond:
        _timers[id_] = {"tipo": tipo, "vence": vence, "etiqueta": etiqueta or ""}
        heapq.heappush(_heap, (vence, id_))
        _persistir()
        _cond.notify()
    return id_


def _parsear_duracion_relativa(texto: str) -> int:
    total_segundos = 0.0
    for valor_txt, unidad in re.findall(r"(\d+(?:[.,]\d+)?)\s*(segundos?|segs?|seg|minutos?|mins?|min|horas?|hora|hs?|dias?|dia)\b", texto):
        valor = float(valor_txt.replace(",", "."))
        if unidad.startswith(("seg",)):
            total_segundos += valor
        elif unidad.startswith(("min",)):
            total_segundos += valor * 60
        elif unidad.startswith(("hora", "hs", "h")):
            total_segundos += valor * 3600
        elif unidad.startswith(("dia",)):
            total_segundos += valor * 86400
    return max(0, int(total_segundos))


def _parsear_hora_absoluta(texto: str) -> datetime | None:
    match = re.search(r"\b(?:(hoy|manana)\s*)?(?:a\s*las?\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", texto)
    if not match:
        return None
    dia_ref, hora_txt, minuto_txt, ampm = match.groups()
    hora = int(hora_txt)
    minuto = int(minuto_txt or "0")
    if ampm:
        if not 1 <= hora <= 12:
            raise ValueError("hora fuera de rango para formato am/pm")
        if ampm == "am":
            hora = 0 if hora == 12 else hora
        else:
            hora = 12 if hora == 12 else hora + 12
    if hora > 23 or minuto > 59:
        raise ValueError("hora fuera de rango")

    ahora = _ahora_local()
    objetivo = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if dia_ref == "manana":
        objetivo += timedelta(days=1)
    elif dia_ref != "hoy" and objetivo <= ahora:
        objetivo += timedelta(days=1)
    return objetivo


def programar_desde_texto(cuando: str, etiqueta: str = "") -> dict:
    bruto = (cuando or "").strip()
    if not bruto:
        raise ValueError("faltó la descripción temporal")
    texto = _normalizar_texto(bruto)

    segundos = _parsear_duracion_relativa(texto)
    if segundos > 0:
        id_ = crear_timer(segundos, etiqueta)
        return {"tipo": "timer", "id": id_, "segundos": segundos}

    objetivo = _parsear_hora_absoluta(texto)
    if objetivo is None:
        raise ValueError("no pude interpretar cuándo debe sonar")
    hora_hhmm = objetivo.strftime("%H:%M")
    id_ = _registrar_programacion("alarma", objetivo.timestamp(), etiqueta)
    _debug_emit("alarm-created", {"id": id_, "time": hora_hhmm, "label": etiqueta or "", "due_ts": objetivo.timestamp()})
    return {"tipo": "alarma", "id": id_, "hora": hora_hhmm, "vence_iso": objetivo.isoformat()}


def _disparar(id_: str):
    info = _timers.pop(id_, None)
    if not info:
        _debug_emit("timer-fire-missing", {"id": id_})
        return
    etiqueta = info.get("etiqueta") or "sin nombre"
    tipo = info["tipo"]
    _debug_emit("timer-fired", {"id": id_, "type": tipo, "label": etiqueta, "due_ts": info.get("vence")})
    if tipo == "alarma":
        texto = f"Alarma, brodi: {etiqueta}. Despabila."
    else:
        texto = f"El tiempo de '{etiqueta}' se acabó, pringao. Muévete."
    if _callback:
        try:
            _debug_emit("timer-callback-start", {"id": id_, "type": tipo, "emotion": "cachondeo", "text_preview": texto[:160]})
            _callback(texto, "cachondeo")
            _debug_emit("timer-callback-end", {"id": id_, "type": tipo})
        except Exception as e:
            _debug_emit("timer-callback-error", {"id": id_, "type": tipo, "error": str(e)})
            print(f"⚠️ timers: callback ha petado: {e}")
    else:
        _debug_emit("timer-no-callback", {"id": id_, "type": tipo, "text_preview": texto[:160]})
        print(f"⏰ (sin callback) {texto}")
    _persistir()


def _loop():
    while True:
        with _cond:
            if _cerrar:
                return
            if not _heap:
                _cond.wait(timeout=3600)
                continue
            vence, id_ = _heap[0]
            if id_ not in _timers:
                # Cancelado: descartar y seguir
                heapq.heappop(_heap)
                continue
            espera = vence - time.time()
            if espera > 0:
                _cond.wait(timeout=espera)
                continue
            heapq.heappop(_heap)
            # Disparamos fuera del lock para no bloquear crear/cancelar
        _disparar(id_)


def inicializar(callback_alarma):
    """Arranca el thread scheduler. callback_alarma(texto, emocion) se llama al vencer."""
    global _callback, _thread
    _callback = callback_alarma
    _cargar()
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name="timers-scheduler")
    _thread.start()
    activos = len(_timers)
    _debug_emit("timers-init", {"active_count": activos})
    if activos:
        print(f"⏰ Timers: {activos} activo(s) cargado(s) de disco.")


def crear_timer(segundos: int, etiqueta: str = "") -> str:
    """Programa un timer relativo. Devuelve id corto."""
    segundos = max(1, int(segundos))
    vence = time.time() + segundos
    id_ = _registrar_programacion("timer", vence, etiqueta)
    _debug_emit("timer-created", {"id": id_, "seconds": segundos, "label": etiqueta or "", "due_ts": vence})
    return id_


def crear_alarma(hora_hhmm: str, etiqueta: str = "") -> str:
    """Programa una alarma a hora 'HH:MM' (hoy, o mañana si ya pasó). Devuelve id."""
    hora_hhmm = hora_hhmm.strip().replace(".", ":")
    h, m = hora_hhmm.split(":")
    objetivo = _ahora_local().replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if objetivo <= _ahora_local():
        objetivo += timedelta(days=1)
    vence = objetivo.timestamp()
    id_ = _registrar_programacion("alarma", vence, etiqueta)
    _debug_emit("alarm-created", {"id": id_, "time": hora_hhmm, "label": etiqueta or "", "due_ts": vence})
    return id_


def listar() -> list[dict]:
    """Devuelve timers/alarmas activos: [{id, tipo, vence_en_seg, etiqueta}, ...]"""
    ahora = time.time()
    out = []
    with _cond:
        for id_, info in _timers.items():
            out.append({
                "id": id_,
                "tipo": info["tipo"],
                "vence_en_seg": max(0, int(info["vence"] - ahora)),
                "etiqueta": info.get("etiqueta", ""),
            })
    out.sort(key=lambda d: d["vence_en_seg"])
    return out


def cancelar(id_o_etiqueta: str) -> bool:
    """Cancela por id exacto o por match en la etiqueta (case-insensitive)."""
    clave = id_o_etiqueta.strip().lower()
    borrados = 0
    with _cond:
        ids_a_borrar = []
        for id_, info in _timers.items():
            if id_ == clave or clave in info.get("etiqueta", "").lower():
                ids_a_borrar.append(id_)
        for id_ in ids_a_borrar:
            _timers.pop(id_, None)
            borrados += 1
        if borrados:
            _persistir()
            _cond.notify()
    return borrados > 0


def cerrar():
    global _cerrar
    with _cond:
        _cerrar = True
        _cond.notify_all()
