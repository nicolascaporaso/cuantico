import threading
import time
from typing import Callable

import config
import luces

try:
    import RPi.GPIO as GPIO
except Exception:  # pragma: no cover - en desarrollo local puede no existir GPIO
    GPIO = None


BUTTON_SINGLE_CLICK = "BUTTON_SINGLE_CLICK"
BUTTON_DOUBLE_CLICK = "BUTTON_DOUBLE_CLICK"
BUTTON_TRIPLE_CLICK = "BUTTON_TRIPLE_CLICK"
BUTTON_LONG_PRESS = "BUTTON_LONG_PRESS"
BUTTON_QUAD_CLICK = "BUTTON_QUAD_CLICK"

_EVENT_NAMES = {
    1: BUTTON_SINGLE_CLICK,
    2: BUTTON_DOUBLE_CLICK,
    3: BUTTON_TRIPLE_CLICK,
    4: BUTTON_QUAD_CLICK,
}

_BUTTON_FEEDBACK_COLORS = {
    1: (0, 255, 70),
    2: (255, 140, 0),
    3: (170, 80, 255),
    4: (80, 180, 255),
}


class ButtonController:
    def __init__(
        self,
        pin_bcm: int,
        debounce_ms: int = 50,
        group_window_ms: int = 450,
    ):
        self.pin_bcm = int(pin_bcm)
        self.debounce_ms = int(debounce_ms)
        self.group_window_ms = int(group_window_ms)
        self._callbacks: list[Callable[[str, dict], None]] = []
        self._lock = threading.RLock()
        self._click_count = 0
        self._timer: threading.Timer | None = None
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._using_polling = False
        self._last_press_ts = 0.0

    def register_callback(self, callback: Callable[[str, dict], None]):
        with self._lock:
            self._callbacks.append(callback)

    def start(self) -> bool:
        if GPIO is None:
            return False
        with self._lock:
            if self._running:
                return True
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            try:
                GPIO.remove_event_detect(self.pin_bcm)
            except Exception:
                pass
            try:
                GPIO.cleanup(self.pin_bcm)
            except Exception:
                pass
            GPIO.setup(self.pin_bcm, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
            self._running = True
            self._using_polling = False
            self._last_press_ts = 0.0
            try:
                GPIO.add_event_detect(
                    self.pin_bcm,
                    GPIO.FALLING,
                    callback=self._gpio_falling_edge,
                    bouncetime=self.debounce_ms,
                )
                print(f"🔘 Botón GPIO {self.pin_bcm}: interrupción activada")
            except RuntimeError as e:
                # En algunas Raspberry o tras reinicios bruscos RPi.GPIO puede
                # rechazar edge detection aunque el pin esté bien cableado.
                # Caemos a polling para no tumbar todo Cuántico.
                print(f"⚠️ Botón GPIO {self.pin_bcm}: falló add_event_detect ({e}); uso polling.")
                self._using_polling = True
                self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="button-poll")
                self._poll_thread.start()
        return True

    def close(self):
        with self._lock:
            timer = self._timer
            self._timer = None
            self._click_count = 0
            self._running = False
            self._using_polling = False
            poll_thread = self._poll_thread
            self._poll_thread = None
        if timer:
            timer.cancel()
        if GPIO is not None:
            try:
                GPIO.remove_event_detect(self.pin_bcm)
            except Exception:
                pass
            try:
                GPIO.cleanup(self.pin_bcm)
            except Exception:
                pass
        if poll_thread and poll_thread.is_alive():
            poll_thread.join(timeout=0.3)

    def _gpio_falling_edge(self, _channel: int):
        now = time.monotonic()
        if (now - self._last_press_ts) * 1000.0 < self.debounce_ms:
            return
        self._last_press_ts = now
        with self._lock:
            if not self._running:
                return
            self._click_count += 1
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.group_window_ms / 1000.0, self._flush_clicks)
            self._timer.daemon = True
            self._timer.start()

    def _poll_loop(self):
        was_high = True
        while True:
            with self._lock:
                if not self._running or not self._using_polling:
                    return
            try:
                level = bool(GPIO.input(self.pin_bcm))
            except Exception:
                time.sleep(0.02)
                continue
            if was_high and not level:
                self._gpio_falling_edge(self.pin_bcm)
            was_high = level
            time.sleep(min(0.01, max(0.001, self.debounce_ms / 4000.0)))

    def _flush_clicks(self):
        with self._lock:
            count = self._click_count
            self._click_count = 0
            self._timer = None
            callbacks = list(self._callbacks)
        if count <= 0:
            return
        event_name = _EVENT_NAMES.get(count, f"BUTTON_{count}_CLICK")
        luces.reproducir_animacion_boton(_BUTTON_FEEDBACK_COLORS.get(count, (255, 255, 255)))
        payload = {
            "count": count,
            "pin_bcm": self.pin_bcm,
            "debounce_ms": self.debounce_ms,
            "group_window_ms": self.group_window_ms,
            "ts": time.time(),
        }
        for callback in callbacks:
            try:
                callback(event_name, payload)
            except Exception:
                pass


_controller: ButtonController | None = None


def inicializar() -> bool:
    global _controller
    if not config.BUTTON_CONTROLLER_ENABLED:
        return False
    if _controller is None:
        _controller = ButtonController(
            pin_bcm=config.BUTTON_GPIO_BCM,
            debounce_ms=config.BUTTON_DEBOUNCE_MS,
            group_window_ms=config.BUTTON_GROUP_WINDOW_MS,
        )
    return _controller.start()


def registrar_callback(callback: Callable[[str, dict], None]):
    if _controller is None:
        return
    _controller.register_callback(callback)


def cerrar():
    if _controller is not None:
        _controller.close()
