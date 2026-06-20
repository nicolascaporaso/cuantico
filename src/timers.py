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
import secrets
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

import config

_RUTA = Path(config.STATE_DIR) / "timers.json"

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_heap: list[tuple[float, str]] = []          # (timestamp_unix, id)
_timers: dict[str, dict] = {}                # id -> {tipo, vence, etiqueta}
_thread: threading.Thread | None = None
_cerrar = False
_callback = None                             # fn(texto, emocion)


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


def _disparar(id_: str):
    info = _timers.pop(id_, None)
    if not info:
        return
    etiqueta = info.get("etiqueta") or "sin nombre"
    tipo = info["tipo"]
    if tipo == "alarma":
        texto = f"Alarma, brodi: {etiqueta}. Despabila."
    else:
        texto = f"El tiempo de '{etiqueta}' se acabó, pringao. Muévete."
    if _callback:
        try:
            _callback(texto, "cachondeo")
        except Exception as e:
            print(f"⚠️ timers: callback ha petado: {e}")
    else:
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
    if activos:
        print(f"⏰ Timers: {activos} activo(s) cargado(s) de disco.")


def crear_timer(segundos: int, etiqueta: str = "") -> str:
    """Programa un timer relativo. Devuelve id corto."""
    segundos = max(1, int(segundos))
    id_ = _corto_id()
    vence = time.time() + segundos
    with _cond:
        _timers[id_] = {"tipo": "timer", "vence": vence, "etiqueta": etiqueta or ""}
        heapq.heappush(_heap, (vence, id_))
        _persistir()
        _cond.notify()
    return id_


def crear_alarma(hora_hhmm: str, etiqueta: str = "") -> str:
    """Programa una alarma a hora 'HH:MM' (hoy, o mañana si ya pasó). Devuelve id."""
    hora_hhmm = hora_hhmm.strip().replace(".", ":")
    h, m = hora_hhmm.split(":")
    objetivo = datetime.now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if objetivo <= datetime.now():
        objetivo += timedelta(days=1)
    id_ = _corto_id()
    vence = objetivo.timestamp()
    with _cond:
        _timers[id_] = {"tipo": "alarma", "vence": vence, "etiqueta": etiqueta or ""}
        heapq.heappush(_heap, (vence, id_))
        _persistir()
        _cond.notify()
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
