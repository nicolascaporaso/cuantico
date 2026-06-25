import time
import threading
import traceback
import sys
import json
import urllib.request
import signal
import atexit
from datetime import datetime
from pathlib import Path
import config
import luces
import micro
import altavoz
import govee
import spotify
import timers
import calendario
import youtube_stats
import llamada
import recuerdos
import cuantico_profiles as profile
from openrouter_client import OpenRouterChatSession

USER_SHORT_NAME = config.USER_SHORT_NAME
USER_FULL_NAME = config.USER_FULL_NAME
ACTIVE_PROFILE_NAME = profile.get_active_profile_name()


# #region debug-point A:runtime-hooks
_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"


def _debug_emit(hypothesis_id: str, msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": "main.py",
        "msg": f"[DEBUG] {msg}",
        "data": data or {},
        "ts": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        debug_url = "http://127.0.0.1:7777/event"
        if _DEBUG_ENV_PATH.exists():
            for env_line in _DEBUG_ENV_PATH.read_text(encoding="utf-8").splitlines():
                if env_line.startswith("DEBUG_SERVER_URL="):
                    debug_url = env_line.split("=", 1)[1].strip()
        req = urllib.request.Request(
            debug_url,
            data=line.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=0.8).read()
    except Exception:
        pass


def _debug_excepthook(exc_type, exc, tb):
    _debug_emit("A", "unhandled-exception", {"type": getattr(exc_type, "__name__", str(exc_type)), "error": str(exc), "traceback": "".join(traceback.format_exception(exc_type, exc, tb))})
    sys.__excepthook__(exc_type, exc, tb)


def _debug_threading_excepthook(args):
    _debug_emit("D", "thread-exception", {"thread": getattr(args.thread, "name", "unknown"), "type": getattr(args.exc_type, "__name__", str(args.exc_type)), "error": str(args.exc_value), "traceback": "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))})
    if threading.__excepthook__:
        threading.__excepthook__(args)


def _debug_signal_handler(signum, _frame):
    _debug_emit("A", "signal-received", {"signal": signum})
    raise KeyboardInterrupt


_DEBUG_LOG_PATH.parent.mkdir(exist_ok=True)
_fault_log = open(_DEBUG_LOG_PATH, "a", encoding="utf-8")
sys.excepthook = _debug_excepthook
threading.excepthook = _debug_threading_excepthook
signal.signal(signal.SIGTERM, _debug_signal_handler)
signal.signal(signal.SIGINT, _debug_signal_handler)
try:
    import faulthandler
    faulthandler.enable(_fault_log)
except Exception as _debug_fh_error:
    _debug_emit("A", "faulthandler-enable-failed", {"error": str(_debug_fh_error)})
atexit.register(lambda: _debug_emit("A", "process-exit", {"timestamp": config.now_local().isoformat()}))
_debug_emit("A", "module-loaded", {"user_short_name": USER_SHORT_NAME, "user_full_name": USER_FULL_NAME, "profile": ACTIVE_PROFILE_NAME})
# #endregion


SYSTEM_PROMPT = profile.render_main_prompt()


# ---------- TOOLS ----------

def encender_luces_casa(luz: str = "") -> str:
    """Enciende luces Govee de la casa. Úsala cuando nico pida encender, prender o dar luz, o hable de estar a oscuras.

    Args:
        luz: (opcional) Nombre de la luz concreta a encender (ej: 'Esfera'). Déjalo vacío para encender TODAS las luces.
    """
    return "ok" if govee.encender_todas(luz or None) else "fallo: esa luz no existe o no responde (wifi caído?)"

def apagar_luces_casa(luz: str = "") -> str:
    """Apaga luces Govee de la casa. Úsala cuando nico pida apagar, quitar luz, irse a dormir o poner todo a oscuras.

    Args:
        luz: (opcional) Nombre de la luz concreta a apagar. Déjalo vacío para apagar TODAS.
    """
    return "ok" if govee.apagar_todas(luz or None) else "fallo: esa luz no existe o no responde (wifi caído?)"

def cambiar_color_luces(r: int, g: int, b: int, luz: str = "") -> str:
    """Cambia el color de las luces Govee. Tú traduces el color/ambiente que pide nico a RGB. Ejemplos: rojo=255,0,0; azul=0,0,255; azul cielo=135,206,235; blanco cálido=255,180,120; morado=160,32,240; verde lima=50,205,50; naranja atardecer=255,140,0; rosa pastel=255,182,193; rojo romántico=180,0,30. Para ambientes ("modo fiesta", "modo peli de terror", "gaming"), elige un color que encaje.

    Args:
        r: Componente rojo (0-255).
        g: Componente verde (0-255).
        b: Componente azul (0-255).
        luz: (opcional) Nombre de la luz concreta (ej: 'Esfera'). Déjalo vacío para todas.
    """
    return "ok" if govee.cambiar_color_todas(r, g, b, luz or None) else "fallo: esa luz no existe o no soporta color"

def cambiar_brillo_luces(porcentaje: int, luz: str = "") -> str:
    """Ajusta el brillo de las luces Govee. Útil cuando nico dice 'baja las luces', 'sube la intensidad', 'modo lectura' (brillo alto), 'ambiente romántico' (brillo bajo).

    Args:
        porcentaje: Brillo de 1 (casi apagado) a 100 (máximo). Nunca 0 — para apagar usa apagar_luces_casa.
        luz: (opcional) Nombre de la luz concreta. Déjalo vacío para todas.
    """
    return "ok" if govee.cambiar_brillo_todas(porcentaje, luz or None) else "fallo: esa luz no existe o no acepta brillo"

# Cola de acciones de música: se encolan durante la tool-call y se ejecutan
# DESPUÉS del TTS para que el comentario burlón no se solape con la canción.
_pendientes_musica = []

def _defer(fn, *args):
    _pendientes_musica.append((fn, args))

def _ejecutar_pendientes_musica():
    if _pendientes_musica:
        print(f"🎧 Ejecutando {len(_pendientes_musica)} acción(es) de música diferida(s)…")
    while _pendientes_musica:
        fn, args = _pendientes_musica.pop(0)
        try:
            ok = fn(*args)
            print(f"   · {fn.__name__}({args}) → {ok}")
        except Exception as e:
            print(f"⚠️ Acción de música diferida falló: {e}")


# Lock que serializa cualquier reproducción TTS. Si Cuántico está hablando y un
# timer vence, el thread scheduler espera aquí y suelta su mensaje al terminar.
_tts_lock = threading.Lock()

def _hablar(texto, emocion):
    """Wrapper serializado de altavoz.hablar — evita solapes entre respuestas y alarmas."""
    with _tts_lock:
        altavoz.hablar(texto, emocion)

def _hablar_stream(generador, emocion):
    """Variante streaming: ElevenLabs va sacando audio frase a frase según llegan chunks."""
    with _tts_lock:
        altavoz.hablar_stream(generador, emocion)

def _callback_timer(texto, emocion):
    """Invocado por el scheduler de timers al vencer uno."""
    _debug_emit("T", "alarm-callback-enter", {"emotion": emocion, "text_preview": texto[:160]})
    try:
        _hablar(texto, emocion)
        # Al terminar el aviso, el loop principal puede seguir bloqueado escuchando.
        # Restauramos el reactor a radar para que no quede clavado en la emocion del timer.
        luces.cambiar_estado("esperando")
        _debug_emit("T", "alarm-callback-state-restored", {"state": "esperando"})
        _debug_emit("T", "alarm-callback-exit", {"emotion": emocion})
    except Exception as e:
        _debug_emit("T", "alarm-callback-error", {"emotion": emocion, "error": str(e), "traceback": traceback.format_exc()})
        raise


def reproducir_musica(query: str) -> str:
    """Busca y reproduce una canción o artista CONCRETO en Spotify. Úsala SOLO cuando nico nombra una canción o artista específico. Ej: "pon bohemian rhapsody", "pon despacito", "pon algo de queen".

    Args:
        query: Nombre de la canción o artista. Ej: 'bohemian rhapsody', 'queen', 'metallica enter sandman', 'despacito luis fonsi'.
    """
    _defer(spotify.reproducir, query)
    return "ok"

def poner_playlist(descripcion: str) -> str:
    """Busca una playlist de Spotify por género, estilo o ambiente y la pone entera en shuffle. Úsala cuando nico pide un género o vibe en lugar de una canción concreta. Ej: "pon algo de reggaeton", "música chill", "rock para conducir", "algo para estudiar", "ponme hits de los 80", "música de fiesta", "algo relajante".

    Args:
        descripcion: Género, estilo o ambiente. Ej: 'reggaeton', 'chill lofi', 'rock clásico', 'fiesta latina', 'concentración estudiar', 'jazz relajante', 'hits 80s'.
    """
    _defer(spotify.reproducir_playlist, descripcion)
    return "ok"

def reanudar_musica() -> str:
    """Reanuda la música que estaba pausada, o pone música genérica cuando nico pide música sin especificar ("pon música", "dale play", "pon algo")."""
    _defer(spotify.reproducir)
    return "ok"

def pausar_musica() -> str:
    """Pausa la música que está sonando en Spotify. Úsala cuando nico pida silencio, parar, callar la música, o diga que va a hablar por teléfono."""
    # Pausar no genera audio nuevo, se ejecuta ya mismo.
    return "ok" if spotify.pausar() else "fallo: no había música sonando"

def siguiente_cancion() -> str:
    """Salta a la siguiente canción en Spotify. Úsala si nico dice que la canción es una castaña, no le mola, o pide cambiarla."""
    _defer(spotify.siguiente)
    return "ok"

def cancion_anterior() -> str:
    """Vuelve a la canción anterior en Spotify."""
    _defer(spotify.anterior)
    return "ok"

def cambiar_volumen(delta: int) -> str:
    """Sube o baja el volumen de Spotify un porcentaje. Úsala cuando nico diga que no oye, está alto, molesta, los vecinos se quejan, etc.

    Args:
        delta: Cantidad a cambiar. Típico: +15 para subir, -15 para bajar. Más agresivo: +30 o -30.
    """
    return "ok" if spotify.volumen(delta) else "fallo: no hay reproducción activa para cambiar volumen"


def crear_temporizador(minutos: float, etiqueta: str = "") -> str:
    """Crea un temporizador que sonará al pasar los minutos indicados. Úsalo cuando ya tengas una duración numérica convertida a minutos. Para lenguaje natural como "en 30 segundos", "en 2 horas" o "mañana a las 7am", prefiere `programar_aviso`.

    Args:
        minutos: Duración en minutos. Acepta decimales: 0.5 = 30 segundos, 0.16 = ~10 segundos.
        etiqueta: Descripción corta de para qué es. Ej: 'pasta', 'pollo', 'llamar a mamá'.
    """
    segundos = max(1, int(float(minutos) * 60))
    tid = timers.crear_timer(segundos, etiqueta)
    return f"ok: timer '{etiqueta or tid}' en {minutos} min"

def crear_alarma_hora(hora: str, etiqueta: str = "") -> str:
    """Programa una alarma a una hora concreta del día (formato HH:MM en 24h). Si la hora ya pasó hoy, suena mañana. Úsala SOLO cuando la hora venga ya explícita. Para lenguaje natural como "mañana a las 7am" o "en 60 segundos", prefiere `programar_aviso`.

    Args:
        hora: Hora en formato 'HH:MM' (24h). Ej: '07:30', '22:15'.
        etiqueta: Motivo de la alarma. Ej: 'levantarse', 'pastilla'.
    """
    try:
        tid = timers.crear_alarma(hora, etiqueta)
        return f"ok: alarma '{etiqueta or tid}' a las {hora}"
    except Exception as e:
        return f"fallo: hora mal formateada ({e})"


def programar_aviso(cuando: str, etiqueta: str = "") -> str:
    """Programa timers y alarmas desde lenguaje natural. Úsala SIEMPRE para pedidos como "en 30 segundos", "en 5 minutos", "en 2 horas", "mañana a las 7am", "hoy a las 22:15" o "a las 18:30". Esta tool decide si corresponde un timer relativo o una alarma a hora fija.

    Args:
        cuando: Descripción temporal completa. Ej: 'en 60 segundos', 'en 10 minutos', 'en 2 horas', 'mañana a las 7am', 'hoy a las 22:15', 'a las 18:30'.
        etiqueta: Motivo o nombre corto del aviso. Ej: 'sacar la pizza', 'pastilla', 'despertarme'.
    """
    try:
        info = timers.programar_desde_texto(cuando, etiqueta)
        if info["tipo"] == "timer":
            return f"ok: timer '{etiqueta or info['id']}' en {info['segundos']} segundos"
        return f"ok: alarma '{etiqueta or info['id']}' para {info['hora']}"
    except Exception as e:
        return f"fallo: no pude interpretar ese horario ({e})"

def listar_temporizadores() -> str:
    """Lista todos los timers y alarmas activos. Úsalo cuando nico pregunte 'qué timers tengo', 'qué alarmas hay', 'a qué hora me avisas'."""
    lista = timers.listar()
    if not lista:
        return "no hay timers ni alarmas activos"
    partes = []
    for t in lista:
        s = t["vence_en_seg"]
        h, r = divmod(s, 3600)
        m, s2 = divmod(r, 60)
        cuando = f"{h}h{m:02d}m" if h else (f"{m}m{s2:02d}s" if m else f"{s2}s")
        partes.append(f"{t['tipo']} '{t['etiqueta'] or t['id']}' en {cuando}")
    return "; ".join(partes)

def cancelar_temporizador(nombre: str) -> str:
    """Cancela un timer o alarma por su nombre (etiqueta) o id. Úsalo cuando nico diga 'cancela el timer de pasta', 'quita la alarma de las 7', 'olvida lo del pollo'.

    Args:
        nombre: Etiqueta o id del timer a cancelar.
    """
    return "ok" if timers.cancelar(nombre) else "fallo: no encuentro ningún timer con ese nombre"


def eventos_de_hoy() -> str:
    """Lista los eventos que nico tiene hoy en Google Calendar. Úsalo cuando pregunte 'qué tengo hoy', 'agenda de hoy', 'tengo algo ahora', 'a qué hora es la siguiente'."""
    try:
        eventos = calendario.eventos_hoy()
    except Exception as e:
        return f"fallo: {e}"
    if not eventos:
        return "agenda vacía hoy"
    partes = []
    for e in eventos:
        iso = e["inicio_iso"]
        hora = iso[11:16] if "T" in iso else "todo el día"
        partes.append(f"{hora} {e['titulo']}")
    return "; ".join(partes)

def eventos_de_la_semana() -> str:
    """Lista los eventos de los próximos 7 días. Úsalo cuando nico pregunte por su semana, 'qué tengo esta semana', 'algo en los próximos días'."""
    try:
        eventos = calendario.eventos_semana()
    except Exception as e:
        return f"fallo: {e}"
    if not eventos:
        return "semana vacía"
    por_dia: dict[str, list[str]] = {}
    for e in eventos:
        iso = e["inicio_iso"]
        dia = iso[:10]
        hora = iso[11:16] if "T" in iso else "todo el día"
        por_dia.setdefault(dia, []).append(f"{hora} {e['titulo']}")
    partes = [f"{dia}: " + ", ".join(items) for dia, items in sorted(por_dia.items())]
    return "; ".join(partes)

def nuevo_evento(titulo: str, inicio_iso: str, duracion_minutos: int = 30) -> str:
    """Crea un evento en Google Calendar. Úsalo cuando nico pida 'ponme una reunión', 'crea evento', 'recuérdame en el calendario'. Construye inicio_iso combinando la fecha de hoy (ver contexto) con la hora que pide nico.

    Args:
        titulo: Nombre del evento. Ej: 'Dentista', 'Reunión con Iván'.
        inicio_iso: Fecha y hora ISO 8601 con offset, ej: '2026-04-23T17:00:00+02:00'.
        duracion_minutos: Duración en minutos (default 30).
    """
    try:
        r = calendario.crear_evento(titulo, inicio_iso, duracion_minutos)
        return f"ok: evento '{titulo}' creado"
    except Exception as e:
        return f"fallo: {e}"


def analiticas_youtube(periodo: str = "7d") -> str:
    """Devuelve métricas del canal de YouTube de nico para el período dado. Úsalo cuando pregunte 'cómo va el canal', 'analíticas', 'cuántas views tengo esta semana', 'cómo fue el mes en YouTube'.

    Args:
        periodo: Uno de 'hoy', '24h', '7d', 'semana', '28d', 'mes', '30d'. Default '7d'.
    """
    try:
        d = youtube_stats.analiticas(periodo)
    except Exception as e:
        return f"fallo: {e}"
    top = ", ".join(f"'{v['titulo']}' ({v['views']} views)" for v in d["top_videos"][:3])
    return (
        f"{d['periodo']}: {d['views']} views, "
        f"{d['watch_time_horas']}h vistas, "
        f"{d['subs_netos']:+d} subs netos. "
        f"Top: {top or 'nada'}"
    )

def ultimos_videos() -> str:
    """Últimos vídeos publicados en el canal con sus métricas. Úsalo cuando nico pregunte 'mis últimos vídeos', 'cómo va el último', 'qué subí recientemente'."""
    try:
        videos = youtube_stats.videos_recientes(5)
    except Exception as e:
        return f"fallo: {e}"
    if not videos:
        return "no hay vídeos recientes"
    partes = [f"'{v['titulo']}' ({v['publicado']}): {v['views']} views, {v['likes']} likes" for v in videos]
    return "; ".join(partes)


_modo_llamada_pendiente: str | None = None

def iniciar_modo_llamada(objetivo: str) -> str:
    """Activa el modo llamada: cuando termines de hablar, entrarás en un loop sin wake word para conversar con un humano a través del móvil en altavoz. Úsala cuando nico diga 'voy a llamar a X', 'llamo al restaurante para reservar', 'encárgate tú de la llamada'. Responde a nico en personaje ('coge el móvil, bro, yo me encargo') ANTES de que la tool se ejecute.

    Args:
        objetivo: Descripción clara y completa del objetivo. Ej: 'reservar mesa para 2 personas mañana sábado 25 de abril a las 21:00 en nombre de nico García', 'pedir hora para revisión dental la semana que viene por la tarde'.
    """
    global _modo_llamada_pendiente
    _modo_llamada_pendiente = objetivo
    return "ok: cuando termine esta respuesta, entro en modo llamada"


def recordar(hecho: str, categoria: str = "") -> str:
    """Guarda un HECHO sobre nico o su entorno para futuras conversaciones. Úsala proactivamente cuando nico comparta algo que merezca recordar: gustos (comida, música, géneros), personas importantes (nombre de novia, amigos, familia, jefe), rutinas (horarios, deporte), proyectos, anécdotas graciosas, opiniones fuertes que expresó. NO guardes datos sensibles (contraseñas, DNI, tarjetas). NO guardes cosas triviales de un solo momento ('hoy llueve'); sólo lo que siga siendo cierto la semana que viene.

    Args:
        hecho: Frase corta en tercera persona. Ej: 'A nico le gusta la pasta carbonara', 'La novia de nico se llama Ana', 'nico está construyendo un asistente de voz llamado Cuántico'.
        categoria: Etiqueta corta opcional. Ej: 'gustos', 'personas', 'trabajo', 'rutinas', 'opiniones'.
    """
    rid = recuerdos.añadir(hecho, categoria)
    return f"ok: recordado con id {rid}" if rid else "fallo: no se pudo guardar"

def olvidar(coincidencia: str) -> str:
    """Borra recuerdos que contengan la frase. Úsala cuando nico diga 'olvida que X', 'ya no soy Y, bórralo', 'quita eso de tu memoria'.

    Args:
        coincidencia: Fragmento de texto a buscar en los recuerdos guardados. Puede ser una palabra clave o frase parcial.
    """
    n = recuerdos.borrar_por_coincidencia(coincidencia)
    return f"ok: olvidados {n} recuerdo(s)" if n else "fallo: no encontré recuerdo con eso"

def listar_recuerdos() -> str:
    """Devuelve los recuerdos guardados sobre nico. Úsala cuando pregunte '¿qué sabes de mí?', 'qué recuerdas', 'dime qué tienes de mí'."""
    items = recuerdos.listar(50)
    if not items:
        return "no tengo recuerdos guardados todavía"
    return " | ".join(f"{r['texto']}" for r in items[:20])


TOOLS = [
    encender_luces_casa, apagar_luces_casa, cambiar_color_luces, cambiar_brillo_luces,
    reproducir_musica, poner_playlist, reanudar_musica, pausar_musica,
    siguiente_cancion, cancion_anterior, cambiar_volumen,
    programar_aviso, crear_temporizador, crear_alarma_hora, listar_temporizadores, cancelar_temporizador,
    eventos_de_hoy, eventos_de_la_semana, nuevo_evento,
    analiticas_youtube, ultimos_videos,
    iniciar_modo_llamada,
    recordar, olvidar, listar_recuerdos,
]

for _tool in TOOLS:
    if _tool.__doc__:
        _tool.__doc__ = profile.personalizar_texto(_tool.__doc__)

print("==================================================")
print("  🚀 CUÁNTICO CORE: SISTEMA CIBERPUNK ONLINE ")
print("==================================================")
_debug_emit("A", "startup-banner-printed")

luces.encender_reactor()
_debug_emit("A", "luces-encendidas")
govee.inicializar()
_debug_emit("A", "govee-inicializado")
spotify.inicializar()
_debug_emit("A", "spotify-inicializado")
timers.inicializar(_callback_timer)
_debug_emit("A", "timers-inicializados")
if calendario.inicializar():
    youtube_stats.inicializar()
    _debug_emit("A", "calendar-youtube-inicializados")
recuerdos.inicializar()
_debug_emit("A", "recuerdos-inicializados")

# Inyecta los nombres reales de las luces de casa en el system prompt
_luces_disponibles = govee.nombres_luces()
if _luces_disponibles:
    SYSTEM_PROMPT += f"\n\nLUCES DE CASA DISPONIBLES: {', '.join(_luces_disponibles)}. Para controlar solo una, pasa su nombre (o una aproximación) en el parámetro `luz` de la tool correspondiente. Para controlar TODAS a la vez, deja `luz` vacío."

# Fecha de referencia para que el modelo pueda construir ISOs "mañana a las 5" → 2026-04-23T17:00:00+02:00
SYSTEM_PROMPT += f"\n\nUSO DE ALARMAS Y TIMERS: para pedidos en lenguaje natural como 'en 30 segundos', 'en 5 minutos', 'en 2 horas', 'mañana a las 7am' o 'a las 18:30', usa primero la tool `programar_aviso(cuando, etiqueta)`."
SYSTEM_PROMPT += f"\n\nFECHA ACTUAL DE REFERENCIA: {config.now_local().strftime('%Y-%m-%d %A %H:%M')} (zona horaria {config.CUANTICO_TIMEZONE})."

def _crear_chat_turno(system_prompt, funciones):
    """Crea una sesión de chat con function calling local y búsqueda web en OpenRouter."""
    return OpenRouterChatSession(
        system_prompt,
        funciones,
        model=config.OPENROUTER_MODEL,
        enable_web_search=True,
    )


print("🌐 Web search + function calling activado vía OpenRouter.")
_debug_emit("A", "openrouter-ready", {"model": config.OPENROUTER_MODEL, "profile": ACTIVE_PROFILE_NAME})

def _prompt_con_memoria() -> str:
    """SYSTEM_PROMPT + bloque de recuerdos actuales. Se re-construye en cada nueva conversación para que los recuerdos añadidos ahora mismo entren la próxima vez."""
    bloque = recuerdos.formatear_para_prompt()
    return SYSTEM_PROMPT + ("\n\n" + bloque if bloque else "")

# Sonido opcional de arranque. Para deshabilitarlo en el futuro, puedes:
# 1) comentar la línea de abajo, o
# 2) poner ENABLE_STARTUP_WAV = False en src/altavoz.py
altavoz.reproducir_sonido_arranque()
_debug_emit("B", "startup-sound-finished")

micro.inicializar()
_debug_emit("B", "micro-inicializado")

try:
    while True:
        # --- MODO RADAR: espera wake word ---
        luces.cambiar_estado("esperando")
        _debug_emit("B", "loop-radar-enter")
        texto_usuario = micro.escuchar()
        _debug_emit("B", "wake-listen-result", {"has_text": bool(texto_usuario), "text_preview": (texto_usuario or "")[:120]})

        # Nueva conversación. Reconstruimos la config cada vez para que los recuerdos añadidos
        # (y nombres de luces, etc.) queden actualizados sin reiniciar el proceso.
        chat = _crear_chat_turno(_prompt_con_memoria(), TOOLS)

        # --- MODO CONVERSACIÓN ---
        en_conversacion = True
        while en_conversacion:
            if not texto_usuario or texto_usuario.strip() == "":
                print("☁️  No he entendido nada.")
                _debug_emit("B", "empty-user-text")
                texto_usuario = micro.escuchar_seguimiento(timeout_ms=5000)
                if not texto_usuario:
                    _debug_emit("B", "followup-timeout-after-empty")
                    en_conversacion = False
                continue

            print(f"\n👤 {USER_SHORT_NAME}: {texto_usuario}")

            if any(w in texto_usuario.lower() for w in ['apágate', 'apagate']):
                despedida = "¡Venga ya! Me voy a por una chimichanga. ¡No me busques, pringao!"
                print(f"🤖 Cuántico: {despedida}")
                _hablar(despedida, "enfadado")
                raise KeyboardInterrupt

            if any(w in texto_usuario.lower() for w in ['adiós', 'adios', 'hasta luego', 'chao']):
                despedida = "Piérdete, chaval. Ya sabes dónde encontrarme."
                print(f"🤖 Cuántico: {despedida}")
                _hablar(despedida, "sarcasmo")
                en_conversacion = False
                continue

            luces.cambiar_estado("pensando")
            print("🤖 Cuántico está procesando...")
            _debug_emit("C", "assistant-processing", {"text_preview": texto_usuario[:120]})
            try:
                # El adaptador de OpenRouter resuelve las tool-calls locales y la búsqueda
                # web antes de devolver el texto final. Sin streaming aquí para que el TTS
                # no se solape con tool-calls intermedias.
                response = chat.send_message(texto_usuario)
                texto_respuesta = (response.text or "").strip()
                _debug_emit("C", "assistant-response-ready", {"has_text": bool(texto_respuesta), "text_preview": texto_respuesta[:160]})

                if texto_respuesta:
                    emocion_ia = profile.detectar_emocion(texto_respuesta)
                    print(f"🤖 Cuántico: {texto_respuesta}")
                    _debug_emit("C", "tts-start", {"emotion": emocion_ia})
                    _hablar(texto_respuesta, emocion_ia)
                    luces.cambiar_estado(emocion_ia)
                    _debug_emit("C", "tts-finished", {"emotion": emocion_ia})

                # Ahora que Cuántico ha terminado de hablar, arrancamos la música
                _ejecutar_pendientes_musica()

                # Si en este turno se activó el modo llamada, entramos ahora que ya habló
                if _modo_llamada_pendiente:
                    objetivo = _modo_llamada_pendiente
                    _modo_llamada_pendiente = None
                    _debug_emit("D", "call-mode-enter", {"goal_preview": objetivo[:160]})
                    llamada.ejecutar(objetivo, _hablar, _hablar_stream)
                    # Al terminar la llamada, volvemos al modo radar (wake word)
                    en_conversacion = False
                    _debug_emit("D", "call-mode-exit")
                    continue

            except Exception as e:
                print(f"⚠️ Error en OpenRouter: {e}")
                _debug_emit("C", "conversation-exception", {"error": str(e), "traceback": traceback.format_exc()})
                _hablar(f"Se me ha frito una neurona, {USER_SHORT_NAME}. Repite eso.", "enfadado")

            # Seguimos escuchando sin wake word
            texto_usuario = micro.escuchar_seguimiento(timeout_ms=8000)
            _debug_emit("B", "followup-result", {"has_text": bool(texto_usuario), "text_preview": (texto_usuario or "")[:120]})

except KeyboardInterrupt:
    print("\n🛑 Desconexión manual detectada.")
    _debug_emit("A", "keyboard-interrupt")
finally:
    _debug_emit("A", "finally-start")
    timers.cerrar()
    micro.cerrar()
    luces.apagar_reactor()
    time.sleep(0.5)
    print(" Reactor apagado. Cuántico fuera. ")
    _debug_emit("A", "finally-end")
