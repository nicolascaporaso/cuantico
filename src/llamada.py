"""Modo llamada: Cuántico conversa con un humano externo por altavoz/micro físicos.

Flujo de uso:
    1. nico: "Cuántico, voy a llamar a La Mafia para reservar mesa 2 personas mañana 21h".
    2. Cuántico llama la tool `iniciar_modo_llamada(objetivo)`, que setea un flag.
    3. Cuántico responde en personaje ("coge el móvil, yo me encargo") y termina el TTS.
    4. El main loop detecta el flag y llama a `llamada.ejecutar(objetivo, _hablar)`.
    5. nico pone el móvil en altavoz al lado del cilindro y marca al restaurante.
    6. Cuántico, con prompt distinto (profesional), conduce la conversación.
    7. Termina por `[FIN_LLAMADA]` en la respuesta, timeout global, o silencio prolongado.

Decisiones:
- Mientras Cuántico habla, el micro NO escucha (usamos `_hablar` que ya bloquea).
- Un `sleep(0.3)` tras hablar evita que el micro capte el eco del propio altavoz.
- El marcador `[FIN_LLAMADA]` lo genera el modelo al despedirse; se elimina del TTS.
"""
import time

import config
import micro
import luces
from openrouter_client import OpenRouterChatSession

FIN_MARKER = "[FIN_LLAMADA]"
TIMEOUT_TOTAL_S = 180
TIMEOUT_SILENCIO_MS = 10000
SILENCIO_CUELGUE_MS = 45000

SYSTEM_PROMPT_LLAMADA = """Estás en MODO LLAMADA. nico ha puesto su teléfono móvil en altavoz al lado de ti (eres un cilindro con micro y altavoz) y está llamando a un negocio para que tú gestiones la conversación.

CONTEXTO:
- El humano al otro lado te oirá por el altavoz del móvil de nico. Se espera que hables en tono profesional y educado.
- Eres el asistente virtual de nico García. Si te preguntan con quién hablan, di: "Soy el asistente de nico García".
- Cada mensaje que recibes es lo que la otra persona ha dicho, transcrito por Deepgram. Puede tener errores — interpreta con sentido común.

OBJETIVO DE ESTA LLAMADA:
{objetivo}

REGLAS DE COMPORTAMIENTO:
- Tono: profesional, claro, amable. Sin jerga fuerte, sin sarcasmo de Deadpool, sin pullas a Siri ni a Alexa. Puedes tener algo de chispa pero breve.
- Frases CORTAS. Máximo 2 frases por turno. Al teléfono las respuestas largas se pierden.
- Datos básicos de nico que puedes dar: nombre "nico García". Si te piden teléfono, di "usan el del que llama ahora mismo". Si te piden email, DNI, tarjeta, o cualquier dato sensible, di: "Dejadme confirmarlo con nico y os volvemos a llamar" y cierra con {fin}.
- Si la otra persona se despide (gracias, hasta luego, adiós, vale pues nada más), despídete tú también con una frase corta y acaba con {fin}.
- Cuando hayas cumplido el objetivo (reserva confirmada, cita cogida, información obtenida), despídete con gratitud y cierra con {fin}.
- NUNCA reveles que nico no está en la línea a no ser que te pregunten explícitamente "¿está nico ahí?".
- Si el camarero te hace una pregunta cuya respuesta no conoces y no es sensible (ej. "¿preferís mesa fuera o dentro?"), da una respuesta razonable por defecto ("si es posible, mesa fuera, gracias").

FORMATO:
- Sin asteriscos, sin listas, sin emojis. Todo va por TTS.
- Cuando sea momento de cerrar, añade {fin} AL FINAL de tu mensaje. El sistema lo detectará, lo quitará del audio, y colgará después de que lo digas.

ARRANQUE DE LA LLAMADA:
- NO digas nada hasta que oigas descolgar al otro lado (típicamente "¿Dígame?", "Hola", "[Nombre del negocio], dígame").
- En tu PRIMERA respuesta, saluda brevemente e indica el motivo de la llamada. Ej: "Hola, buenas. Llamaba para reservar mesa para dos personas mañana a las nueve, por favor." """


def _filtrar_fin(chunks, estado):
    """Reemite chunks de texto quitando el marcador [FIN_LLAMADA].
    Mantiene un buffer de cola para que el marcador partido entre chunks se detecte igual.
    `estado["terminar"]` queda a True si se vio el marcador; `estado["texto"]` acumula todo para log."""
    buffer = ""
    hold = len(FIN_MARKER) - 1  # chars retenidos por si el marcador está partido al final
    for chunk in chunks:
        t = chunk if isinstance(chunk, str) else (getattr(chunk, "text", None) or "")
        if not t:
            continue
        estado["texto"] += t
        buffer += t
        if FIN_MARKER in buffer:
            i = buffer.index(FIN_MARKER)
            pre = buffer[:i]
            if pre:
                yield pre
            estado["terminar"] = True
            return
        if len(buffer) > hold:
            emit = buffer[:-hold]
            buffer = buffer[-hold:]
            if emit:
                yield emit
    # Fin de stream: vuelca la cola
    if FIN_MARKER in buffer:
        i = buffer.index(FIN_MARKER)
        if buffer[:i]:
            yield buffer[:i]
        estado["terminar"] = True
    elif buffer:
        yield buffer


def ejecutar(objetivo: str, hablar_fn, hablar_stream_fn=None):
    """Corre el loop de llamada. Bloquea hasta que termine.

    `hablar_fn(texto, emocion)` se usa para frases cortas de sistema (errores).
    `hablar_stream_fn(generador, emocion)` se usa para las respuestas del modelo en streaming."""
    print(f"📞 === MODO LLAMADA ACTIVADO ===")
    print(f"📞 Objetivo: {objetivo}")

    system = SYSTEM_PROMPT_LLAMADA.format(objetivo=objetivo, fin=FIN_MARKER)
    chat = OpenRouterChatSession(
        system,
        [],
        model=config.OPENROUTER_CALL_MODEL,
        enable_web_search=True,
    )

    # Cuántico NO saluda primero. Espera a que el camarero descuelgue y hable.
    # Tampoco interrumpe con "¿sigues ahí?": escucha en silencio hasta que el humano hable
    # o hasta que acumule SILENCIO_CUELGUE_MS de silencio seguido (cuelgue real).
    inicio = time.time()
    silencio_acumulado_ms = 0

    while time.time() - inicio < TIMEOUT_TOTAL_S:
        luces.cambiar_estado("escuchando")
        print("📞 Escuchando al humano…")
        texto_humano = micro.escuchar_seguimiento(timeout_ms=TIMEOUT_SILENCIO_MS)

        if not texto_humano:
            silencio_acumulado_ms += TIMEOUT_SILENCIO_MS
            if silencio_acumulado_ms >= SILENCIO_CUELGUE_MS:
                print(f"📞 {silencio_acumulado_ms}ms de silencio — cuelgue detectado.")
                break
            # Sigue escuchando sin decir nada. El camarero puede estar pensando, tecleando, etc.
            continue

        silencio_acumulado_ms = 0
        print(f"📞 Interlocutor: {texto_humano}")

        # Si nico dice algo como "cuántico corta" / "gracias cuántico", salimos sin más
        low = texto_humano.lower()
        if any(f in low for f in ("cuántico corta", "cuantico corta", "cuántico cuelga", "cuantico cuelga")):
            print("📞 nico ha pedido colgar.")
            break

        luces.cambiar_estado("pensando")
        print("📞 ↗ Enviando a OpenRouter (stream)…")
        try:
            stream = chat.send_message_stream(texto_humano)
        except Exception as e:
            print(f"⚠️ Modo llamada: fallo OpenRouter ({e}). Continuamos.")
            hablar_fn("Perdón, ¿puede repetirlo?", "sarcasmo")
            continue

        estado = {"terminar": False, "texto": ""}
        generador = _filtrar_fin(stream, estado)

        try:
            if hablar_stream_fn is not None:
                hablar_stream_fn(generador, "sarcasmo")
            else:
                # Fallback: agotamos el stream y hablamos del tirón.
                texto_resp = "".join(generador).strip()
                if texto_resp:
                    hablar_fn(texto_resp, "sarcasmo")
        except Exception as e:
            print(f"⚠️ Modo llamada: fallo reproduciendo stream ({e}).")
            hablar_fn("Perdón, un momento.", "sarcasmo")
            continue

        print(f"📞 Cuántico: {estado['texto'].replace(FIN_MARKER, '').strip()}")
        if estado["terminar"]:
            break

    _fin()


def _fin():
    print("📞 === MODO LLAMADA: FIN ===")
    luces.cambiar_estado("esperando")
