import time
import threading
import random
import neopixel
import board
import math

NUM_PIXELS = 16
PIN_LEDS = board.D12
BRIGHTNESS = 0.2

pixels = neopixel.NeoPixel(PIN_LEDS, NUM_PIXELS, brightness=BRIGHTNESS, auto_write=False)

_estado = "esperando"
_hilo_luces = None

_ALIASES_ESTADO = {
    "enfadado": "calenton",
    "cachondeo": "joda",
    "aburrido": "embolado",
}


def cambiar_estado(nuevo_estado):
    global _estado
    _estado = _ALIASES_ESTADO.get(nuevo_estado, nuevo_estado)

def _animar():

    
    global _estado
    while True:
        if _estado == "esperando":
            val = (math.sin(time.time() * 2) + 1) / 2
            pixels.fill((int(val * 100) + 10, 0, 0))
            pixels.show()
            time.sleep(0.02)

        elif _estado == "escuchando":
            val = (math.sin(time.time() * 4) + 1) / 2
            pixels.fill((0, int(val * 150) + 20, int(val * 200) + 40))
            pixels.show()
            time.sleep(0.02)

        elif _estado == "pensando":
            pixels.fill((0, 0, 0))
            for i in range(3):
                idx = (int(time.time() * 15) + i) % NUM_PIXELS
                pixels[idx] = (255, 100, 0)
            pixels.show()
            time.sleep(0.05)

        elif _estado == "sarcasmo":
            val = (math.sin(time.time() * 8) + 1) / 2
            pixels.fill((int(val * 180) + 60, int(val * 60) + 20, 0))
            pixels.show()
            time.sleep(0.02)

        elif _estado == "calenton":
            pixels.fill((random.randint(150, 255), 0, 0))
            pixels.show()
            time.sleep(random.uniform(0.02, 0.08))
            pixels.fill((10, 0, 0))
            pixels.show()
            time.sleep(random.uniform(0.02, 0.08))

        elif _estado == "joda":
            for i in range(NUM_PIXELS):
                hue = (int(time.time() * 100) + (i * 256 // NUM_PIXELS)) % 256
                pixels[i] = (
                    hue,
                    random.randint(80, 255),
                    random.randint(40, 180),
                )
            pixels.show()
            time.sleep(0.02)

        elif _estado == "embolado":
            val = (math.sin(time.time() * 1) + 1) / 2
            pixels.fill((0, int(val * 20), int(val * 70) + 20))
            pixels.show()
            time.sleep(0.05)

        elif _estado == "buena_onda":
            val = (math.sin(time.time() * 2.5) + 1) / 2
            pixels.fill((0, int(val * 180) + 50, int(val * 60) + 10))
            pixels.show()
            time.sleep(0.03)

        elif _estado == "chamuyero":
            val = (math.sin(time.time() * 1.5) + 1) / 2
            pixels.fill((int(val * 180) + 40, int(val * 120) + 30, 0))
            pixels.show()
            time.sleep(0.06)

        elif _estado == "modo_argentino":
            for i in range(NUM_PIXELS):
                pixels[i] = (120, 180, 255) if (i + int(time.time() * 5)) % 2 == 0 else (255, 255, 255)
            pixels.show()
            time.sleep(0.08)

        elif _estado == "apagado":
            pixels.fill((0, 0, 0))
            pixels.show()
            break

def encender_reactor():
    global _hilo_luces
    _hilo_luces = threading.Thread(target=_animar, daemon=True)
    _hilo_luces.start()

def apagar_reactor():
    cambiar_estado("apagado")
    if _hilo_luces:
        _hilo_luces.join(timeout=1.0)
