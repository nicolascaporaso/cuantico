import colorsys
import math
import random
import threading
import time

import board
import neopixel

import cuantico_profiles as profile
import wiz_controller

NUM_PIXELS = 16
PIN_LEDS = board.D12
BRIGHTNESS = 0.2

pixels = neopixel.NeoPixel(PIN_LEDS, NUM_PIXELS, brightness=BRIGHTNESS, auto_write=False)

_estado = "esperando"
_hilo_luces = None
_animaciones_pendientes = []
_animaciones_lock = threading.Lock()
_OUTER_BUTTON_PIXELS = [0, 1, 2, 3, 7, 11, 15, 14, 13, 12, 8, 4]
_INNER_BUTTON_PIXELS = [5, 6, 10, 9]


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(value)))


def _scale_color(color, factor: float):
    return tuple(_clamp_channel(channel * factor) for channel in color)


def _fill(color):
    pixels.fill(tuple(_clamp_channel(channel) for channel in color))
    pixels.show()


def _show_partial(indices, color):
    pixels.fill((0, 0, 0))
    rgb = tuple(_clamp_channel(channel) for channel in color)
    for idx in indices:
        pixels[idx] = rgb
    pixels.show()


def _apply_pulse(cfg, now: float):
    val = (math.sin(now * cfg.get("speed", 2.0)) + 1) / 2
    min_factor = cfg.get("min_factor", 0.15)
    max_factor = cfg.get("max_factor", 1.0)
    factor = min_factor + ((max_factor - min_factor) * val)
    _fill(_scale_color(cfg.get("color", (255, 255, 255)), factor))


def _apply_spinner(cfg, now: float):
    pixels.fill(tuple(cfg.get("background", (0, 0, 0))))
    speed = cfg.get("speed", 15.0)
    head = int(now * speed) % NUM_PIXELS
    trail = max(1, int(cfg.get("trail", 3)))
    tail_factor = cfg.get("tail_factor", 0.35)
    color = cfg.get("color", (255, 255, 255))
    for offset in range(trail):
        idx = (head - offset) % NUM_PIXELS
        factor = max(0.1, 1.0 - (offset * tail_factor))
        pixels[idx] = _scale_color(color, factor)
    pixels.show()


def _apply_flicker(cfg, _now: float):
    _fill(cfg.get("color", (255, 0, 0)))
    time.sleep(random.uniform(cfg.get("min_sleep_s", 0.02), cfg.get("max_sleep_s", 0.08)))
    _fill(cfg.get("background", (10, 0, 0)))
    time.sleep(random.uniform(cfg.get("min_sleep_s", 0.02), cfg.get("max_sleep_s", 0.08)))


def _apply_rainbow(cfg, now: float):
    speed = cfg.get("speed", 1.0)
    randomness = cfg.get("randomness", 0.0)
    base_hue = (now * speed) % 1.0
    for i in range(NUM_PIXELS):
        hue = (base_hue + (i / NUM_PIXELS)) % 1.0
        sat = 1.0
        val = 1.0
        if randomness:
            val = max(0.45, min(1.0, 0.75 + random.uniform(-randomness, randomness)))
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        pixels[i] = (_clamp_channel(r * 255), _clamp_channel(g * 255), _clamp_channel(b * 255))
    pixels.show()


def _apply_blink(cfg, now: float):
    speed = cfg.get("speed", 1.5)
    on = int(now * speed * 2) % 2 == 0
    _fill(cfg.get("color", (255, 255, 0)) if on else cfg.get("background", (0, 0, 0)))


def _apply_alternate(cfg, now: float):
    colors = cfg.get("colors", [(255, 255, 255), (0, 0, 0)])
    speed = cfg.get("speed", 4.0)
    phase = int(now * speed)
    for i in range(NUM_PIXELS):
        pixels[i] = tuple(colors[(i + phase) % len(colors)])
    pixels.show()


def _render_state(state_name: str):
    cfg = profile.get_light_state(state_name)
    effect = cfg.get("effect", "pulse")
    now = time.time()
    if effect == "off":
        _fill((0, 0, 0))
        return True
    if effect == "pulse":
        _apply_pulse(cfg, now)
    elif effect == "spinner":
        _apply_spinner(cfg, now)
    elif effect == "flicker":
        _apply_flicker(cfg, now)
        return False
    elif effect == "rainbow":
        _apply_rainbow(cfg, now)
    elif effect == "blink":
        _apply_blink(cfg, now)
    elif effect == "alternate":
        _apply_alternate(cfg, now)
    else:
        _fill(cfg.get("color", (255, 255, 255)))
    time.sleep(cfg.get("sleep_s", 0.03))
    return False


def cambiar_estado(nuevo_estado):
    global _estado
    _estado = nuevo_estado if nuevo_estado in {"esperando", "escuchando", "pensando", "apagado"} else profile.resolve_state_name(nuevo_estado)
    wiz_controller.sincronizar_estado_si_activo(_estado)


def reproducir_animacion_boton(color: tuple[int, int, int], hold_ms: int = 120):
    with _animaciones_lock:
        _animaciones_pendientes.append(
            {
                "color": tuple(color),
                "hold_ms": int(hold_ms),
            }
        )


def _tomar_animacion_pendiente():
    with _animaciones_lock:
        if not _animaciones_pendientes:
            return None
        return _animaciones_pendientes.pop(0)


def _animar_feedback_boton(animacion: dict):
    color = tuple(animacion.get("color", (255, 255, 255)))
    hold_s = max(0.02, animacion.get("hold_ms", 120) / 1000.0)
    _show_partial(_OUTER_BUTTON_PIXELS, color)
    time.sleep(0.04)
    pixels.fill((0, 0, 0))
    for idx in _OUTER_BUTTON_PIXELS:
        pixels[idx] = tuple(_clamp_channel(channel) for channel in color)
    for idx in _INNER_BUTTON_PIXELS:
        pixels[idx] = tuple(_clamp_channel(channel) for channel in color)
    pixels.show()
    time.sleep(hold_s)
    for step in range(6, -1, -1):
        factor = step / 6.0
        pixels.fill((0, 0, 0))
        scaled = _scale_color(color, factor)
        for idx in _OUTER_BUTTON_PIXELS + _INNER_BUTTON_PIXELS:
            pixels[idx] = scaled
        pixels.show()
        time.sleep(0.02)


def _animar():
    global _estado
    while True:
        try:
            animacion = _tomar_animacion_pendiente()
            if animacion:
                _animar_feedback_boton(animacion)
                continue
            if _render_state(_estado):
                break
        except Exception:
            # Si una emoción o configuración de perfil llega mal, el reactor no debe morir.
            _estado = "esperando"
            time.sleep(0.05)


def encender_reactor():
    global _hilo_luces
    _hilo_luces = threading.Thread(target=_animar, daemon=True)
    _hilo_luces.start()


def apagar_reactor():
    cambiar_estado("apagado")
    if _hilo_luces:
        _hilo_luces.join(timeout=1.0)
