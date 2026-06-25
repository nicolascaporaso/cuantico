import colorsys
import math
import random
import threading
import time

import board
import neopixel

import cuantico_profiles as profile

NUM_PIXELS = 16
PIN_LEDS = board.D12
BRIGHTNESS = 0.2

pixels = neopixel.NeoPixel(PIN_LEDS, NUM_PIXELS, brightness=BRIGHTNESS, auto_write=False)

_estado = "esperando"
_hilo_luces = None


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(value)))


def _scale_color(color, factor: float):
    return tuple(_clamp_channel(channel * factor) for channel in color)


def _fill(color):
    pixels.fill(tuple(_clamp_channel(channel) for channel in color))
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
    _estado = profile.resolve_state_name(nuevo_estado)


def _animar():
    global _estado
    while True:
        if _render_state(_estado):
            break


def encender_reactor():
    global _hilo_luces
    _hilo_luces = threading.Thread(target=_animar, daemon=True)
    _hilo_luces.start()


def apagar_reactor():
    cambiar_estado("apagado")
    if _hilo_luces:
        _hilo_luces.join(timeout=1.0)
