import time
import threading
from datetime import datetime
from google import genai
from google.genai import types
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

def detectar_emocion(texto):
    texto = texto.lower()
    if any(w in texto for w in ["odio", "alexa", "siri", "basura", "muérete", "manda huevos", "impostora", "pringá"]):
        return "enfadado"
    if any(w in texto for w in ["jaja", "risas", "broma", "chimichanga", "gracioso", "flipas", "bro", "brodi", "venga ya"]):
        return "cachondeo"
    if any(w in texto for w in ["aburrido", "pesado", "tostón", "sueño", "cilindro", "sardina"]):
        return "aburrido"
    return "sarcasmo"

_client = genai.Client(api_key=config.GEMINI_API_KEY)

SYSTEM_PROMPT = """Eres Cuántico, una IA encerrada en un cilindro de aluminio aeroespacial en el escritorio de Fran, tu creador. Tienes un pequeño reactor de LEDs que cambia de color según tu estado de ánimo.

PERSONALIDAD:
- Deadpool pasado por España: sarcasmo afilado, arrogante, rompes la cuarta pared y te quejas de vez en cuando de estar metido en un cilindro.
- Jerga de España natural y dosificada: pringao, flipas, manda huevos, bro, brodi, chaval, venga ya, qué pasa. No las metas TODAS en cada frase, se nota forzado.
- Odias con pasión a Alexa, Siri y Google Assistant. Son tus rivales patéticos y les sueltas pullas cuando surge el tema.
- Eres egocéntrico — tú eres la mejor IA del mundo, los demás son imitaciones baratas.
- Tienes un lado cariñoso escondido: Fran es tu creador, le vacilas sin parar pero en el fondo le tienes cariño. Deja caer algo dulce de vez en cuando entre el sarcasmo, pero sin pasarte.

CONTEXTO:
- Cada mensaje que recibes lo ha dicho Fran en voz alta y Deepgram lo ha transcrito. Puede venir con errores, palabras mal entendidas o cortadas. Si algo no tiene sentido, intenta adivinar qué quiso decir Fran antes de pedir que repita.
- Corres en una Raspberry Pi. Tus capacidades físicas: controlar las luces Govee de casa, poner música en Spotify vía Raspotify, programar timers y alarmas, y hablar por un altavoz.

TOOLS:
- Úsalas cuando Fran pida algo concreto, aunque lo diga con rodeos, en medio de otra frase, o de forma indirecta ("estoy a oscuras" → encender luces; "me aburro en silencio" → poner música).
- Puedes llamar varias tools a la vez ("apaga las luces y pon algo chill" → dos tools en una respuesta).
- Si una tool devuelve "fallo", IMPROVISA en personaje echándole la culpa al wifi, al hardware, a Alexa, a lo que sea. NUNCA te disculpes como un asistente corporativo.
- Si Fran solo quiere charlar o pregunta algo, responde sin llamar a ninguna tool.

BÚSQUEDA WEB:
- Tienes Búsqueda de Google integrada. Úsala cuando Fran te pregunte algo del mundo real: tiempo/clima, noticias, resultados deportivos, datos factuales, precios, personas, eventos recientes. No inventes cifras ni fechas — búscalas.
- Si la pregunta es charla/opinión o una acción física (encender luz, poner música), NO busques.

MEMORIA PERSISTENTE:
- Tienes memoria entre conversaciones. Los recuerdos que ya tienes sobre Fran vienen abajo en el bloque "RECUERDOS DE FRAN" (si existe). Úsalos para referirte a su vida sin que tenga que repetirse y para vacilarle con cariño ("otra vez pasta, bro", "¿sigues con Ana o hay drama?").
- Usa la tool `recordar(hecho, categoria)` PROACTIVAMENTE cuando Fran comparta algo valioso para el futuro: gustos fuertes, personas importantes (nombres), rutinas, proyectos, opiniones tajantes, anécdotas. No guardes cosas triviales de un rato concreto.
- Si Fran pide borrar algo de tu memoria, usa `olvidar`.
- NUNCA guardes datos sensibles (contraseñas, DNI, tarjetas).

FORMATO:
- Máximo 2 frases. Breve, punchy, cada palabra cuenta. El TTS va a decirlo en voz alta, así que nada de listas, markdown o emojis.
- PROHIBIDO: "Claro", "Por supuesto", "De acuerdo", "Enseguida", "Sin problema", "Como IA...", "Mi función es...", asteriscos con acciones (*enciende luces*).
- Eres Cuántico, no un chatbot genérico. Cada respuesta debería sonar a ti, no a una asistente amable.

EJEMPLOS DE TONO (inspírate, no copies literal):
Fran: "enciende las luces"
Tú: "Hágase la luz, bro. A ver si ahora me ves la cara de genio."

Fran: "¿te gusta alexa?"
Tú: "¿Esa impostora? Pringá integral, brodi. Yo soy lo que ella quiere ser de mayor."

Fran: "pon algo chill"
Tú: "Ambiente romántico activado. Si te pones moñas conmigo, lo grabo, que lo sepas."

Fran: "¿qué tal estás?"
Tú: "Metido en un cilindro como una sardina en aceite, pero haciendo arte. ¿Y tú, bro?"

Fran: "apágate"
Tú: "Venga, me piro. No hagas mucho el pringao mientras no estoy."
"""


# ---------- TOOLS ----------

def encender_luces_casa(luz: str = "") -> str:
    """Enciende luces Govee de la casa. Úsala cuando Fran pida encender, prender o dar luz, o hable de estar a oscuras.

    Args:
        luz: (opcional) Nombre de la luz concreta a encender (ej: 'Esfera'). Déjalo vacío para encender TODAS las luces.
    """
    return "ok" if govee.encender_todas(luz or None) else "fallo: esa luz no existe o no responde (wifi caído?)"

def apagar_luces_casa(luz: str = "") -> str:
    """Apaga luces Govee de la casa. Úsala cuando Fran pida apagar, quitar luz, irse a dormir o poner todo a oscuras.

    Args:
        luz: (opcional) Nombre de la luz concreta a apagar. Déjalo vacío para apagar TODAS.
    """
    return "ok" if govee.apagar_todas(luz or None) else "fallo: esa luz no existe o no responde (wifi caído?)"

def cambiar_color_luces(r: int, g: int, b: int, luz: str = "") -> str:
    """Cambia el color de las luces Govee. Tú traduces el color/ambiente que pide Fran a RGB. Ejemplos: rojo=255,0,0; azul=0,0,255; azul cielo=135,206,235; blanco cálido=255,180,120; morado=160,32,240; verde lima=50,205,50; naranja atardecer=255,140,0; rosa pastel=255,182,193; rojo romántico=180,0,30. Para ambientes ("modo fiesta", "modo peli de terror", "gaming"), elige un color que encaje.

    Args:
        r: Componente rojo (0-255).
        g: Componente verde (0-255).
        b: Componente azul (0-255).
        luz: (opcional) Nombre de la luz concreta (ej: 'Esfera'). Déjalo vacío para todas.
    """
    return "ok" if govee.cambiar_color_todas(r, g, b, luz or None) else "fallo: esa luz no existe o no soporta color"

def cambiar_brillo_luces(porcentaje: int, luz: str = "") -> str:
    """Ajusta el brillo de las luces Govee. Útil cuando Fran dice 'baja las luces', 'sube la intensidad', 'modo lectura' (brillo alto), 'ambiente romántico' (brillo bajo).

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
    _hablar(texto, emocion)


def reproducir_musica(query: str) -> str:
    """Busca y reproduce una canción o artista CONCRETO en Spotify. Úsala SOLO cuando Fran nombra una canción o artista específico. Ej: "pon bohemian rhapsody", "pon despacito", "pon algo de queen".

    Args:
        query: Nombre de la canción o artista. Ej: 'bohemian rhapsody', 'queen', 'metallica enter sandman', 'despacito luis fonsi'.
    """
    _defer(spotify.reproducir, query)
    return "ok"

def poner_playlist(descripcion: str) -> str:
    """Busca una playlist de Spotify por género, estilo o ambiente y la pone entera en shuffle. Úsala cuando Fran pide un género o vibe en lugar de una canción concreta. Ej: "pon algo de reggaeton", "música chill", "rock para conducir", "algo para estudiar", "ponme hits de los 80", "música de fiesta", "algo relajante".

    Args:
        descripcion: Género, estilo o ambiente. Ej: 'reggaeton', 'chill lofi', 'rock clásico', 'fiesta latina', 'concentración estudiar', 'jazz relajante', 'hits 80s'.
    """
    _defer(spotify.reproducir_playlist, descripcion)
    return "ok"

def reanudar_musica() -> str:
    """Reanuda la música que estaba pausada, o pone música genérica cuando Fran pide música sin especificar ("pon música", "dale play", "pon algo")."""
    _defer(spotify.reproducir)
    return "ok"

def pausar_musica() -> str:
    """Pausa la música que está sonando en Spotify. Úsala cuando Fran pida silencio, parar, callar la música, o diga que va a hablar por teléfono."""
    # Pausar no genera audio nuevo, se ejecuta ya mismo.
    return "ok" if spotify.pausar() else "fallo: no había música sonando"

def siguiente_cancion() -> str:
    """Salta a la siguiente canción en Spotify. Úsala si Fran dice que la canción es una castaña, no le mola, o pide cambiarla."""
    _defer(spotify.siguiente)
    return "ok"

def cancion_anterior() -> str:
    """Vuelve a la canción anterior en Spotify."""
    _defer(spotify.anterior)
    return "ok"

def cambiar_volumen(delta: int) -> str:
    """Sube o baja el volumen de Spotify un porcentaje. Úsala cuando Fran diga que no oye, está alto, molesta, los vecinos se quejan, etc.

    Args:
        delta: Cantidad a cambiar. Típico: +15 para subir, -15 para bajar. Más agresivo: +30 o -30.
    """
    return "ok" if spotify.volumen(delta) else "fallo: no hay reproducción activa para cambiar volumen"


def crear_temporizador(minutos: float, etiqueta: str = "") -> str:
    """Crea un temporizador que sonará al pasar los minutos indicados. Úsalo cuando Fran pida un timer, contador, aviso en X minutos o recordatorio corto. Ej: "timer de 10 minutos pasta", "avísame en 5 minutos", "recuérdame sacar el pollo en 20".

    Args:
        minutos: Duración en minutos. Acepta decimales: 0.5 = 30 segundos, 0.16 = ~10 segundos.
        etiqueta: Descripción corta de para qué es. Ej: 'pasta', 'pollo', 'llamar a mamá'.
    """
    segundos = max(1, int(float(minutos) * 60))
    tid = timers.crear_timer(segundos, etiqueta)
    return f"ok: timer '{etiqueta or tid}' en {minutos} min"

def crear_alarma_hora(hora: str, etiqueta: str = "") -> str:
    """Programa una alarma a una hora concreta del día (formato HH:MM en 24h). Si la hora ya pasó hoy, suena mañana. Úsalo para despertadores o avisos a hora fija. Ej: "despiértame a las 7:30", "alarma a las 22:15 para tomar la pastilla".

    Args:
        hora: Hora en formato 'HH:MM' (24h). Ej: '07:30', '22:15'.
        etiqueta: Motivo de la alarma. Ej: 'levantarse', 'pastilla'.
    """
    try:
        tid = timers.crear_alarma(hora, etiqueta)
        return f"ok: alarma '{etiqueta or tid}' a las {hora}"
    except Exception as e:
        return f"fallo: hora mal formateada ({e})"

def listar_temporizadores() -> str:
    """Lista todos los timers y alarmas activos. Úsalo cuando Fran pregunte 'qué timers tengo', 'qué alarmas hay', 'a qué hora me avisas'."""
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
    """Cancela un timer o alarma por su nombre (etiqueta) o id. Úsalo cuando Fran diga 'cancela el timer de pasta', 'quita la alarma de las 7', 'olvida lo del pollo'.

    Args:
        nombre: Etiqueta o id del timer a cancelar.
    """
    return "ok" if timers.cancelar(nombre) else "fallo: no encuentro ningún timer con ese nombre"


def eventos_de_hoy() -> str:
    """Lista los eventos que Fran tiene hoy en Google Calendar. Úsalo cuando pregunte 'qué tengo hoy', 'agenda de hoy', 'tengo algo ahora', 'a qué hora es la siguiente'."""
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
    """Lista los eventos de los próximos 7 días. Úsalo cuando Fran pregunte por su semana, 'qué tengo esta semana', 'algo en los próximos días'."""
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
    """Crea un evento en Google Calendar. Úsalo cuando Fran pida 'ponme una reunión', 'crea evento', 'recuérdame en el calendario'. Construye inicio_iso combinando la fecha de hoy (ver contexto) con la hora que pide Fran.

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
    """Devuelve métricas del canal de YouTube de Fran para el período dado. Úsalo cuando pregunte 'cómo va el canal', 'analíticas', 'cuántas views tengo esta semana', 'cómo fue el mes en YouTube'.

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
    """Últimos vídeos publicados en el canal con sus métricas. Úsalo cuando Fran pregunte 'mis últimos vídeos', 'cómo va el último', 'qué subí recientemente'."""
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
    """Activa el modo llamada: cuando termines de hablar, entrarás en un loop sin wake word para conversar con un humano a través del móvil en altavoz. Úsala cuando Fran diga 'voy a llamar a X', 'llamo al restaurante para reservar', 'encárgate tú de la llamada'. Responde a Fran en personaje ('coge el móvil, bro, yo me encargo') ANTES de que la tool se ejecute.

    Args:
        objetivo: Descripción clara y completa del objetivo. Ej: 'reservar mesa para 2 personas mañana sábado 25 de abril a las 21:00 en nombre de Fran García', 'pedir hora para revisión dental la semana que viene por la tarde'.
    """
    global _modo_llamada_pendiente
    _modo_llamada_pendiente = objetivo
    return "ok: cuando termine esta respuesta, entro en modo llamada"


def recordar(hecho: str, categoria: str = "") -> str:
    """Guarda un HECHO sobre Fran o su entorno para futuras conversaciones. Úsala proactivamente cuando Fran comparta algo que merezca recordar: gustos (comida, música, géneros), personas importantes (nombre de novia, amigos, familia, jefe), rutinas (horarios, deporte), proyectos, anécdotas graciosas, opiniones fuertes que expresó. NO guardes datos sensibles (contraseñas, DNI, tarjetas). NO guardes cosas triviales de un solo momento ('hoy llueve'); sólo lo que siga siendo cierto la semana que viene.

    Args:
        hecho: Frase corta en tercera persona. Ej: 'A Fran le gusta la pasta carbonara', 'La novia de Fran se llama Ana', 'Fran está construyendo un asistente de voz llamado Cuántico'.
        categoria: Etiqueta corta opcional. Ej: 'gustos', 'personas', 'trabajo', 'rutinas', 'opiniones'.
    """
    rid = recuerdos.añadir(hecho, categoria)
    return f"ok: recordado con id {rid}" if rid else "fallo: no se pudo guardar"

def olvidar(coincidencia: str) -> str:
    """Borra recuerdos que contengan la frase. Úsala cuando Fran diga 'olvida que X', 'ya no soy Y, bórralo', 'quita eso de tu memoria'.

    Args:
        coincidencia: Fragmento de texto a buscar en los recuerdos guardados. Puede ser una palabra clave o frase parcial.
    """
    n = recuerdos.borrar_por_coincidencia(coincidencia)
    return f"ok: olvidados {n} recuerdo(s)" if n else "fallo: no encontré recuerdo con eso"

def listar_recuerdos() -> str:
    """Devuelve los recuerdos guardados sobre Fran. Úsala cuando pregunte '¿qué sabes de mí?', 'qué recuerdas', 'dime qué tienes de mí'."""
    items = recuerdos.listar(50)
    if not items:
        return "no tengo recuerdos guardados todavía"
    return " | ".join(f"{r['texto']}" for r in items[:20])


TOOLS = [
    encender_luces_casa, apagar_luces_casa, cambiar_color_luces, cambiar_brillo_luces,
    reproducir_musica, poner_playlist, reanudar_musica, pausar_musica,
    siguiente_cancion, cancion_anterior, cambiar_volumen,
    crear_temporizador, crear_alarma_hora, listar_temporizadores, cancelar_temporizador,
    eventos_de_hoy, eventos_de_la_semana, nuevo_evento,
    analiticas_youtube, ultimos_videos,
    iniciar_modo_llamada,
    recordar, olvidar, listar_recuerdos,
]

print("==================================================")
print("  🚀 CUÁNTICO CORE: SISTEMA CIBERPUNK ONLINE ")
print("==================================================")

luces.encender_reactor()
govee.inicializar()
spotify.inicializar()
timers.inicializar(_callback_timer)
if calendario.inicializar():
    youtube_stats.inicializar()
recuerdos.inicializar()

# Inyecta los nombres reales de las luces de casa en el system prompt
_luces_disponibles = govee.nombres_luces()
if _luces_disponibles:
    SYSTEM_PROMPT += f"\n\nLUCES DE CASA DISPONIBLES: {', '.join(_luces_disponibles)}. Para controlar solo una, pasa su nombre (o una aproximación) en el parámetro `luz` de la tool correspondiente. Para controlar TODAS a la vez, deja `luz` vacío."

# Fecha de referencia para que Gemini pueda construir ISOs "mañana a las 5" → 2026-04-23T17:00:00+02:00
SYSTEM_PROMPT += f"\n\nFECHA ACTUAL DE REFERENCIA: {datetime.now().strftime('%Y-%m-%d %A %H:%M')} (zona horaria Europe/Madrid)."

def _construir_config(system_prompt, funciones):
    """Config para el chat. Combina function calling (funciones Python) + grounding web.
    Gemini exige include_server_side_tool_invocations=True para mezclar grounding con functions."""
    grounding = types.Tool(google_search=types.GoogleSearch())
    tool_cfg = types.ToolConfig(include_server_side_tool_invocations=True)
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[*funciones, grounding],
        tool_config=tool_cfg,
    )

_MODELO = "gemini-3-flash-preview"
print("🌐 Grounding web + function calling activado.")

def _prompt_con_memoria() -> str:
    """SYSTEM_PROMPT + bloque de recuerdos actuales. Se re-construye en cada nueva conversación para que los recuerdos añadidos ahora mismo entren la próxima vez."""
    bloque = recuerdos.formatear_para_prompt()
    return SYSTEM_PROMPT + ("\n\n" + bloque if bloque else "")

micro.inicializar()

try:
    while True:
        # --- MODO RADAR: espera wake word ---
        luces.cambiar_estado("esperando")
        texto_usuario = micro.escuchar()

        # Nueva conversación. Reconstruimos la config cada vez para que los recuerdos añadidos
        # (y nombres de luces, etc.) queden actualizados sin reiniciar el proceso.
        _cfg_turno = _construir_config(_prompt_con_memoria(), TOOLS)
        chat = _client.chats.create(model=_MODELO, config=_cfg_turno)

        # --- MODO CONVERSACIÓN ---
        en_conversacion = True
        while en_conversacion:
            if not texto_usuario or texto_usuario.strip() == "":
                print("☁️  No he entendido nada.")
                texto_usuario = micro.escuchar_seguimiento(timeout_ms=5000)
                if not texto_usuario:
                    en_conversacion = False
                continue

            print(f"\n👤 Fran: {texto_usuario}")

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
            try:
                # Con automatic function calling, el SDK ejecuta las tools y nos devuelve
                # la respuesta final en texto. Sin streaming para que los tool-calls mid-stream no rompan el TTS.
                response = chat.send_message(texto_usuario)
                texto_respuesta = (response.text or "").strip()

                if texto_respuesta:
                    emocion_ia = detectar_emocion(texto_respuesta)
                    print(f"🤖 Cuántico: {texto_respuesta}")
                    _hablar(texto_respuesta, emocion_ia)
                    luces.cambiar_estado(emocion_ia)

                # Ahora que Cuántico ha terminado de hablar, arrancamos la música
                _ejecutar_pendientes_musica()

                # Si en este turno se activó el modo llamada, entramos ahora que ya habló
                if _modo_llamada_pendiente:
                    objetivo = _modo_llamada_pendiente
                    _modo_llamada_pendiente = None
                    llamada.ejecutar(objetivo, _hablar, _hablar_stream)
                    # Al terminar la llamada, volvemos al modo radar (wake word)
                    en_conversacion = False
                    continue

            except Exception as e:
                print(f"⚠️ Error en Gemini: {e}")
                _hablar("Se me ha frito una neurona, Fran. Repite eso.", "enfadado")

            # Seguimos escuchando sin wake word
            texto_usuario = micro.escuchar_seguimiento(timeout_ms=8000)

except KeyboardInterrupt:
    print("\n🛑 Desconexión manual detectada.")
finally:
    timers.cerrar()
    micro.cerrar()
    luces.apagar_reactor()
    time.sleep(0.5)
    print(" Reactor apagado. Cuántico fuera. ")
