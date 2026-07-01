"""Timers, recordatorios y tareas programadas persistentes.

Un único scheduler con `heapq` dispara eventos persistidos en `state/timers.json`.
Cada item puede ser un timer clásico, una alarma, un recordatorio hablado o una
tarea con payload para que `main.py` decida qué hacer al vencer.
"""
import heapq
import json
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import config

_RUTA = Path(config.STATE_DIR) / "timers.json"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"
_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_heap: list[tuple[float, str]] = []
_timers: dict[str, dict] = {}
_thread: threading.Thread | None = None
_cerrar = False
_callback = None


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
        _timers[id_] = {
            "tipo": d["tipo"],
            "vence": vence,
            "etiqueta": d.get("etiqueta", ""),
            "payload": d.get("payload") or {},
        }
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


def _dt_local(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    tzinfo = _ahora_local().tzinfo
    return datetime(year, month, day, hour, minute, second=0, microsecond=0, tzinfo=tzinfo)


def _parsear_duracion_relativa(texto: str) -> int:
    total_segundos = 0.0
    for valor_txt, unidad in re.findall(r"(\d+(?:[.,]\d+)?)\s*(segundos?|segs?|seg|minutos?|mins?|min|horas?|hora|hs?|dias?|dia)\b", texto):
        valor = float(valor_txt.replace(",", "."))
        if unidad.startswith("seg"):
            total_segundos += valor
        elif unidad.startswith("min"):
            total_segundos += valor * 60
        elif unidad.startswith(("hora", "hs", "h")):
            total_segundos += valor * 3600
        elif unidad.startswith("dia"):
            total_segundos += valor * 86400
    return max(0, int(total_segundos))


def _extraer_fecha(texto: str) -> tuple[dict | None, str]:
    ahora = _ahora_local()

    match = re.search(r"\bpasado manana\b", texto)
    if match:
        base = (ahora + timedelta(days=2)).date()
        resto = (texto[:match.start()] + " " + texto[match.end():]).strip()
        return {"year": base.year, "month": base.month, "day": base.day, "year_explicit": True}, resto

    match = re.search(r"\bmanana\b", texto)
    if match:
        base = (ahora + timedelta(days=1)).date()
        resto = (texto[:match.start()] + " " + texto[match.end():]).strip()
        return {"year": base.year, "month": base.month, "day": base.day, "year_explicit": True}, resto

    match = re.search(r"\bhoy\b", texto)
    if match:
        base = ahora.date()
        resto = (texto[:match.start()] + " " + texto[match.end():]).strip()
        return {"year": base.year, "month": base.month, "day": base.day, "year_explicit": True}, resto

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", texto)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_txt = match.group(3)
        year = int(year_txt) if year_txt else ahora.year
        if year_txt and len(year_txt) == 2:
            year += 2000
        resto = (texto[:match.start()] + " " + texto[match.end():]).strip()
        return {"year": year, "month": month, "day": day, "year_explicit": bool(year_txt)}, resto

    meses = "|".join(_MESES)
    match = re.search(rf"\b(\d{{1,2}})\s+de\s+({meses})(?:\s+de\s+(\d{{4}}))?\b", texto)
    if match:
        day = int(match.group(1))
        month = _MESES[match.group(2)]
        year_txt = match.group(3)
        year = int(year_txt) if year_txt else ahora.year
        resto = (texto[:match.start()] + " " + texto[match.end():]).strip()
        return {"year": year, "month": month, "day": day, "year_explicit": bool(year_txt)}, resto

    return None, texto


def _extraer_hora(texto: str) -> tuple[int | None, int | None, bool]:
    match = re.search(r"\b(?:a\s*las?\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", texto)
    if not match:
        return None, None, False
    hora = int(match.group(1))
    minuto = int(match.group(2) or "0")
    ampm = match.group(3)
    if ampm:
        if not 1 <= hora <= 12:
            raise ValueError("hora fuera de rango para formato am/pm")
        if ampm == "am":
            hora = 0 if hora == 12 else hora
        else:
            hora = 12 if hora == 12 else hora + 12
    if hora > 23 or minuto > 59:
        raise ValueError("hora fuera de rango")
    return hora, minuto, True


def resolver_fecha_hora_desde_texto(cuando: str, default_hour: int = 9, default_minute: int = 0) -> dict:
    bruto = (cuando or "").strip()
    if not bruto:
        raise ValueError("faltó la descripción temporal")
    texto = _normalizar_texto(bruto)

    segundos = _parsear_duracion_relativa(texto)
    if segundos > 0:
        objetivo = _ahora_local() + timedelta(seconds=segundos)
        return {
            "modo": "relativo",
            "segundos": segundos,
            "objetivo": objetivo,
            "vence_iso": objetivo.isoformat(),
        }

    fecha_info, resto = _extraer_fecha(texto)
    hora, minuto, tiene_hora = _extraer_hora(resto)
    ahora = _ahora_local()

    if fecha_info:
        if not tiene_hora:
            hora, minuto = default_hour, default_minute
        objetivo = _dt_local(fecha_info["year"], fecha_info["month"], fecha_info["day"], hora, minuto)
        if not fecha_info["year_explicit"] and objetivo <= ahora:
            objetivo = _dt_local(fecha_info["year"] + 1, fecha_info["month"], fecha_info["day"], hora, minuto)
        return {
            "modo": "absoluto",
            "objetivo": objetivo,
            "hora": objetivo.strftime("%H:%M"),
            "vence_iso": objetivo.isoformat(),
        }

    if not tiene_hora:
        raise ValueError("no pude interpretar cuándo debe sonar")

    objetivo = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if objetivo <= ahora:
        objetivo += timedelta(days=1)
    return {
        "modo": "absoluto",
        "objetivo": objetivo,
        "hora": objetivo.strftime("%H:%M"),
        "vence_iso": objetivo.isoformat(),
    }


def _registrar_programacion(tipo: str, vence: float, etiqueta: str = "", payload: dict | None = None) -> str:
    id_ = _corto_id()
    with _cond:
        _timers[id_] = {
            "tipo": tipo,
            "vence": vence,
            "etiqueta": etiqueta or "",
            "payload": payload or {},
        }
        heapq.heappush(_heap, (vence, id_))
        _persistir()
        _cond.notify()
    return id_


def _resumen_evento(id_: str, tipo: str, objetivo: datetime, etiqueta: str = "", segundos: int | None = None, payload: dict | None = None) -> dict:
    info = {
        "id": id_,
        "tipo": tipo,
        "etiqueta": etiqueta or "",
        "hora": objetivo.strftime("%H:%M"),
        "vence_iso": objetivo.isoformat(),
        "payload": payload or {},
    }
    if segundos is not None:
        info["segundos"] = segundos
    return info


def programar_desde_texto(cuando: str, etiqueta: str = "") -> dict:
    info = resolver_fecha_hora_desde_texto(cuando)
    if info["modo"] == "relativo":
        id_ = crear_timer(info["segundos"], etiqueta)
        return {"tipo": "timer", "id": id_, "segundos": info["segundos"], "vence_iso": info["vence_iso"]}
    objetivo = info["objetivo"]
    id_ = _registrar_programacion("alarma", objetivo.timestamp(), etiqueta)
    _debug_emit("alarm-created", {"id": id_, "time": info["hora"], "label": etiqueta or "", "due_ts": objetivo.timestamp()})
    return _resumen_evento(id_, "alarma", objetivo, etiqueta)


def programar_tarea_desde_texto(cuando: str, tipo: str, etiqueta: str = "", payload: dict | None = None, default_hour: int = 9, default_minute: int = 0) -> dict:
    info = resolver_fecha_hora_desde_texto(cuando, default_hour=default_hour, default_minute=default_minute)
    return programar_tarea_para_datetime(
        info["objetivo"],
        tipo=tipo,
        etiqueta=etiqueta,
        payload=payload,
        segundos=info.get("segundos"),
    )


def programar_tarea_para_datetime(objetivo: datetime, tipo: str, etiqueta: str = "", payload: dict | None = None, segundos: int | None = None) -> dict:
    if objetivo.tzinfo is None:
        objetivo = objetivo.replace(tzinfo=_ahora_local().tzinfo)
    id_ = _registrar_programacion(tipo, objetivo.timestamp(), etiqueta, payload=payload)
    _debug_emit("task-created", {
        "id": id_,
        "type": tipo,
        "label": etiqueta or "",
        "due_ts": objetivo.timestamp(),
        "payload": payload or {},
    })
    return _resumen_evento(id_, tipo, objetivo, etiqueta, segundos=segundos, payload=payload)


def _texto_fallback(info: dict) -> str:
    tipo = info["tipo"]
    etiqueta = info.get("etiqueta") or "sin nombre"
    payload = info.get("payload") or {}
    if tipo == "alarma":
        return f"Alarma, brodi: {etiqueta}. Despabila."
    if tipo == "recordatorio":
        return payload.get("mensaje") or f"Recordatorio, chabón: {etiqueta}."
    if tipo == "musica":
        query = payload.get("query") or etiqueta
        return f"Tarea de música disparada: {query}"
    return f"El tiempo de '{etiqueta}' se acabó, pringao. Muévete."


def _disparar(id_: str):
    info = _timers.pop(id_, None)
    if not info:
        _debug_emit("timer-fire-missing", {"id": id_})
        return
    evento = {
        "id": id_,
        "tipo": info["tipo"],
        "etiqueta": info.get("etiqueta", ""),
        "vence": info.get("vence"),
        "vence_iso": datetime.fromtimestamp(info["vence"], tz=_ahora_local().tzinfo).isoformat(),
        "payload": info.get("payload") or {},
    }
    _debug_emit("timer-fired", {
        "id": id_,
        "type": evento["tipo"],
        "label": evento["etiqueta"] or "sin nombre",
        "due_ts": info.get("vence"),
        "payload": evento["payload"],
    })
    if _callback:
        try:
            _debug_emit("timer-callback-start", {"id": id_, "type": evento["tipo"]})
            _callback(evento)
            _debug_emit("timer-callback-end", {"id": id_, "type": evento["tipo"]})
        except Exception as e:
            _debug_emit("timer-callback-error", {"id": id_, "type": evento["tipo"], "error": str(e)})
            print(f"⚠️ timers: callback ha petado: {e}")
    else:
        texto = _texto_fallback(evento)
        _debug_emit("timer-no-callback", {"id": id_, "type": evento["tipo"], "text_preview": texto[:160]})
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
                heapq.heappop(_heap)
                continue
            espera = vence - time.time()
            if espera > 0:
                _cond.wait(timeout=espera)
                continue
            heapq.heappop(_heap)
        _disparar(id_)


def inicializar(callback_alarma):
    """Arranca el scheduler. callback_alarma(evento_dict) se llama al vencer."""
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
    segundos = max(1, int(segundos))
    objetivo = _ahora_local() + timedelta(seconds=segundos)
    id_ = _registrar_programacion("timer", objetivo.timestamp(), etiqueta)
    _debug_emit("timer-created", {"id": id_, "seconds": segundos, "label": etiqueta or "", "due_ts": objetivo.timestamp()})
    return id_


def crear_alarma(hora_hhmm: str, etiqueta: str = "") -> str:
    hora_hhmm = hora_hhmm.strip().replace(".", ":")
    h, m = hora_hhmm.split(":")
    objetivo = _ahora_local().replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if objetivo <= _ahora_local():
        objetivo += timedelta(days=1)
    id_ = _registrar_programacion("alarma", objetivo.timestamp(), etiqueta)
    _debug_emit("alarm-created", {"id": id_, "time": hora_hhmm, "label": etiqueta or "", "due_ts": objetivo.timestamp()})
    return id_


def listar() -> list[dict]:
    ahora = time.time()
    out = []
    with _cond:
        for id_, info in _timers.items():
            out.append({
                "id": id_,
                "tipo": info["tipo"],
                "vence_en_seg": max(0, int(info["vence"] - ahora)),
                "vence_iso": datetime.fromtimestamp(info["vence"], tz=_ahora_local().tzinfo).isoformat(),
                "etiqueta": info.get("etiqueta", ""),
                "payload": info.get("payload") or {},
            })
    out.sort(key=lambda d: d["vence_en_seg"])
    return out


def cancelar(id_o_etiqueta: str) -> bool:
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
