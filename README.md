# Cuántico

[![Cuántico](hardware/cuantico.png)](https://youtu.be/RmWtU8Pogws)

> 🎬 **Mira el vídeo de la build en YouTube:** [youtu.be/RmWtU8Pogws](https://youtu.be/RmWtU8Pogws)

Asistente de voz hardware con personalidad. Vive dentro de un cilindro de aluminio sobre tu mesa, con un anillo de NeoPixels que cambia de color según su estado de ánimo, y se cree el mejor — habla como Deadpool pasado por España, odia a Alexa y te vacila con cariño.

Es un proyecto **open source y replicable** por unos **50 €** en componentes. Corre en una Raspberry Pi, usa Gemini como cerebro, Deepgram para entenderte, ElevenLabs para hablar, y se integra con Spotify, Govee, Google Calendar y YouTube.

> **No es un asistente serio.** Si quieres uno educado, pon Alexa. Cuántico está hecho para tener carácter.

---

## Qué sabe hacer

- **Conversación natural** con wake word (sin pulsar nada).
- **Casa**: encender/apagar luces Govee, cambiar color y brillo.
- **Música**: Spotify por canción, artista, género o ambiente. Pausar, saltar, volumen.
- **Timers y alarmas** persistentes (sobreviven a reinicios).
- **Calendario**: ver tu agenda, crear eventos.
- **YouTube**: analíticas del canal y últimos vídeos.
- **Memoria**: recuerda hechos sobre ti entre conversaciones (SQLite).
- **Modo llamada**: conversa con un humano por teléfono en altavoz (reservar mesa, pedir cita).
- **Búsqueda web** integrada (grounding de Gemini).

---

## Hardware

### Lista de materiales

| Componente | Modelo / specs | Notas |
|---|---|---|
| SBC | **Raspberry Pi Zero 2W** | Cerebro. Cualquier Pi con GPIO vale, pero el Zero 2W cabe en el cilindro. |
| Tarjeta SD | **microSD 32GB Clase 10** (ej: Netac A1 U1 V10) | Para Raspberry Pi OS Lite. |
| Micrófono | **INMP441** (módulo MEMS I2S omnidireccional, 24-bit) | Comunicación I2S, no USB. |
| Amplificador audio | **MAX98357A** (I2S → altavoz, mono, 3.2W) | Necesario para sacar audio I2S al altavoz analógico. |
| Altavoz | **3W 4Ω** con conector JST-PH2.0 (ej: QUARKZMAN) | Va al amplificador, no directo a la Pi. |
| Anillo LED | **WS2812B / NeoPixel, 12 LEDs, 50mm, 5V** | Anillo del "reactor". |
| Tornillería | Kit de **separadores hex M2.5 macho-hembra de latón** | Para montar la Pi y las placas dentro del cilindro. |
| Cableado | **Cable 26 AWG** | Suficiente para señal I2S y alimentación a estos consumos. |
| Fijación | **Cinta de doble cara** | Para pegar las placas al chasis interno. |
| Carcasa | Cilindro de aluminio aeroespacial (opcional) | Lo que tengas a mano: PVC, impresión 3D, lata. |

**Coste total aproximado: ~50 €** con la carcasa impresa en 3D. Si optas por mecanizar el cilindro en aluminio (CNC) el coste sube bastante según el taller.

Opcional (no son parte del hardware central, pero los usa el software):

- Bombillas **Govee** compatibles con la Developer API v1.

---

## Esquema de conexiones

> Todos los números son la **posición física del pin** en la cabecera GPIO de la Pi Zero 2W (1–40), no el número GPIO BCM.

### 🎤 Micrófono INMP441 (I2S)

| Pin del INMP441 | Pin físico Pi | Función |
|---|---|---|
| VDD | **1** (3.3V) | Alimentación |
| GND | **39** | Tierra |
| L/R | (puenteado al GND del propio módulo) | Selección de canal (izquierdo) |
| SCK | **12** | Bit clock (BCLK) |
| WS  | **35** | Word select (LRCLK) |
| SD  | **38** | Datos (entrada al Pi) |

### 🔊 Amplificador MAX98357A (I2S)

| Pin del MAX98357A | Pin físico Pi | Función |
|---|---|---|
| VIN / VDD | **4** (5V) | Alimentación |
| GND | **34** | Tierra |
| BCLK | **12** | Bit clock (compartido con el micro) |
| LRC  | **35** | Word select (compartido con el micro) |
| DIN  | **40** | Datos (salida del Pi) |
| SD   | **36** | Mute / control de silencio |

### 🔈 Altavoz

| Cable del altavoz | Conexión |
|---|---|
| Positivo (+) | Salida **OUT+** del MAX98357A |
| Negativo (−) | Salida **OUT−** del MAX98357A |

### 🌈 Anillo NeoPixel (WS2812B, 12 LEDs)

| Pin del anillo | Pin físico Pi |
|---|---|
| 5V (VCC)  | **2** (mismo riel de 5V que la alimentación general) |
| GND       | **6** |
| DIN (datos) | **32** |

> **Nota I2S:** Para que el micro y el amplificador funcionen, hay que activar el overlay `i2s-mmap` en `/boot/firmware/config.txt` (o `/boot/config.txt` en Raspberry Pi OS antiguos). Consulta la guía de Adafruit del MAX98357A y del INMP441 para los pasos concretos de configuración del kernel.

---

## Carcasa imprimible en 3D

Las piezas están en [`hardware/`](hardware/), separadas por método de fabricación:

**Impresión 3D** — `hardware/3d printing/`:

| Pieza | Para qué |
|---|---|
| `Base_Cuantico.stl` | Base inferior del cilindro. |
| `Intermedio_Cuantico.stl` | Cuerpo central — sujeta el amplificador, el micro y el altavoz. |
| `Tapa_Cuantico.stl` | Tapa superior. La Raspberry Pi se pega con cinta de doble cara en su cara interior. |
| `Luces_Base.stl` | Soporte del anillo NeoPixel. |
| `Luces_Tapa.stl` | Difusor translúcido del anillo (imprime en filamento blanco/transparente). |

**Mecanizado CNC** — `hardware/CNC/` (formato STEP, para mecanizar las piezas estructurales del cilindro de aluminio):

- `Base.stp`, `Intermedio.stp`, `Tapa.stp`

> Si solo vas a imprimir en 3D, usa los `.stl`. Los `.stp` son para mecanizar en aluminio si quieres el acabado original.

**Recomendaciones de impresión:**

- Material: **PLA** o **PETG**, 0.2 mm de altura de capa.
- `Luces_Tapa.stl`: imprime en filamento blanco/translúcido y con relleno bajo (~10–15%) para que difunda bien la luz del NeoPixel.
- El resto de piezas: 20% de relleno y soportes solo donde la pieza lo necesite (revisa en tu slicer).
- Ensamblaje con los separadores M2.5 indicados en la lista de materiales.

---

## Arquitectura

```
                ┌──────────────────────────────────────┐
                │  Raspberry Pi  (src/main.py)         │
                │                                      │
   wake word →  │  micro.py  →  Deepgram (STT)         │
                │      ↓                               │
                │  Gemini 3 Flash (LLM + tools + web)  │
                │      ↓                               │
                │  altavoz.py  →  ElevenLabs (TTS)     │
                │      ↓                               │
                │  luces.py  →  NeoPixel ring          │
                └────────┬─────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         Govee API    Spotify    Google APIs
                    (Raspotify)
```

---

## Setup rápido

### 1. Flashea Raspberry Pi OS Lite

Usa **Raspberry Pi Imager** y elige *Raspberry Pi OS Lite (64-bit)*. En el menú de configuración previo:

- Activa **SSH** (con autenticación por contraseña o por clave).
- Configura tu **red Wi-Fi** y la **zona horaria** (Europe/Madrid).
- Pon `cuantico` como **hostname** (esto coincide con el `DEVICE_HINTS` de Raspotify del proyecto).

### 2. Activa I2S, NeoPixel y dependencias del sistema

Conéctate por SSH a la Pi y ejecuta:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip sox alsa-utils tmux
# Raspotify (Spotify Connect)
curl -sSL https://dtcooper.github.io/raspotify/install.sh | sh
```

Edita `/boot/firmware/config.txt` (o `/boot/config.txt` en versiones antiguas) y añade al final:

```ini
# Audio I2S (INMP441 mic + MAX98357A amp)
dtparam=i2s=on
dtoverlay=googlevoicehat-soundcard

# Desactivar audio analógico interno (libera GPIO y evita conflictos)
dtparam=audio=off
```

Reinicia la Pi (`sudo reboot`). Verifica que ALSA ve el dispositivo I2S:

```bash
arecord -l   # debe listar el snd_rpi_simple_card o similar
aplay -l
```

### 3. Clona y prepara el entorno

```bash
git clone <tu-fork>.git Cuantico
cd Cuantico
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y rellena las API keys (todos los enlaces para conseguirlas están en el propio `.env.example`).

### 5. Wake word

Cuántico usa [openWakeWord](https://github.com/dscripka/openWakeWord). El repo incluye **`cuantico.onnx`** ya entrenado para responder a la palabra "Cuántico" — apunta `WAKE_MODEL_PATH` en tu `.env` a su ruta absoluta y listo:

```bash
WAKE_MODEL_PATH=/home/<tu_usuario>/Cuantico/cuantico.onnx
```

Si prefieres otra palabra de activación:

- **Entrena el tuyo** (~30 min en Colab gratis): sigue la [guía oficial](https://github.com/dscripka/openWakeWord/blob/main/docs/custom_models.md). Genera tu propio `.onnx` y reemplaza el del repo.
- **Usa uno pre-entrenado** del repo de openWakeWord (`hey_jarvis`, `alexa`, etc.).

### 6. OAuth de Google (Calendar + YouTube)

1. Ve a [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
2. Crea un proyecto, activa **Calendar API**, **YouTube Data API v3** y **YouTube Analytics API**.
3. Crea credenciales **OAuth 2.0 client ID** tipo **Desktop app**.
4. Descarga el JSON y guárdalo como `state/google_client.json`.
5. Lanza Cuántico **una vez en el Mac** (no en la Pi, no tiene navegador): se abrirá el navegador, autoriza, y se generará `state/google_token.json`.
6. Copia `state/google_token.json` a la Pi vía `scp`.

### 7. Spotify

1. Crea una app en [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. En "Edit settings" añade `http://127.0.0.1:8888/callback` como Redirect URI.
3. Copia Client ID y Secret a `.env`.
4. Raspotify ya lo instalaste en el paso 2 — se publicará como dispositivo Spotify Connect con el hostname de la Pi (`cuantico`).
5. Primera ejecución: abrirá un navegador para que apruebes los scopes. En la Pi sin pantalla, ejecuta primero en el Mac y copia `.spotify_cache` con `scp`.

### 8. Govee

1. Solicita una API key en [developer.govee.com](https://developer.govee.com) (te llega por email en ~1 día).
2. Pégala en `.env` como `GOVEE_API_KEY`.

### 9. Lanza Cuántico

```bash
sudo .venv/bin/python3 src/main.py
```

> `sudo` es **obligatorio en la Pi** porque NeoPixel necesita acceso a `/dev/mem`. En el Mac (sin LEDs físicos) no hace falta.

---

## Ejecutar como servicio en la Pi

```bash
cp cuantico.service.example cuantico.service
# edita cuantico.service y reemplaza <USER> por tu usuario y la ruta por la real
sudo cp cuantico.service /etc/systemd/system/cuantico.service
sudo systemctl daemon-reload
sudo systemctl enable --now cuantico
journalctl -u cuantico -f   # ver logs
```

---

## Personalización

### Cambia la personalidad

Edita `SYSTEM_PROMPT` en `src/main.py`. Es el alma de Cuántico — su tono, sus rivalidades, cómo se refiere a ti, qué hace en cada situación. Está pensado para Deadpool en español, pero puedes cambiarlo entero.

### Cambia la voz

En `.env` cambia `ELEVENLABS_VOICE_ID` por el ID de cualquier voz de tu librería de ElevenLabs (puedes clonar la tuya o usar las públicas).

### Cambia el wake word

Entrena un `.onnx` nuevo en Colab con la palabra que quieras y apunta `WAKE_MODEL_PATH` a él.

### Añade tools

Define una función Python con docstring claro en `src/main.py` y añádela a la lista `TOOLS`. Gemini la descubre automáticamente vía function calling.

---

## Estructura del repo

```
.
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example
├── cuantico.service.example  # systemd unit para la Pi
├── hardware/
│   ├── 3d printing/          # STL para impresión 3D
│   ├── CNC/                  # STEP para mecanizar el cilindro de aluminio
│   └── cuantico.png          # foto de referencia del montaje final
└── src/
    ├── main.py              # entry point — system prompt + tools + loop principal
    ├── config.py            # carga centralizada de .env
    ├── micro.py             # captura audio + wake word + STT (Deepgram)
    ├── altavoz.py           # TTS (ElevenLabs) con streaming
    ├── luces.py             # animaciones del NeoPixel ring
    ├── govee.py             # control de bombillas Govee
    ├── spotify.py           # Spotify Connect vía Raspotify
    ├── timers.py            # timers/alarmas persistentes
    ├── calendario.py        # Google Calendar (OAuth Desktop)
    ├── youtube_stats.py     # YouTube Analytics (mismo OAuth)
    ├── recuerdos.py         # memoria persistente en SQLite
    └── llamada.py           # modo llamada (humano por móvil en altavoz)
```

---

## Troubleshooting

- **"sudo es obligatorio"** → la Pi necesita `/dev/mem` para los NeoPixels. En Mac dev sin LEDs, comenta el `import luces` o stubea el módulo.
- **`arecord -l` no lista el INMP441** → revisa que añadiste `dtparam=i2s=on` y el overlay correcto en `/boot/firmware/config.txt` y que reiniciaste. Verifica también que el cable del pin L/R va a GND (selecciona canal izquierdo).
- **Audio del altavoz distorsionado o muy bajo** → ajusta los filtros de `sox` en `src/altavoz.py` (líneas con `highpass`, `bass`, `treble`, `gain`). El altavoz de 3W 4Ω rinde mejor recortando los graves.
- **Spotify "no device available"** → arranca Raspotify (`sudo systemctl start raspotify`) y verifica que aparece en `src/spotify.py` con el nombre que tenga (ajusta `DEVICE_HINTS`).
- **Govee "ninguna luz controlable"** → solo bombillas con la **Developer API v1** funcionan; algunos modelos modernos solo van con la API v2 (no soportada todavía).
- **Wake word no responde** → baja `WAKE_THRESHOLD` en `src/micro.py` (default 0.3). Mira los logs `score wake=…` para calibrar.
- **OAuth falla en la Pi** → la Pi no puede abrir navegador. Autoriza primero en el Mac y copia `state/google_token.json` con scp.
- **NeoPixels no se encienden** → asegúrate de lanzar con `sudo` y de que `dtparam=audio=off` está activo (el chip de audio de la Pi comparte timer con el WS2812B).

---

## Stack y créditos

- **LLM**: [Google Gemini 3 Flash](https://ai.google.dev/) (function calling + grounding)
- **STT**: [Deepgram Nova 3](https://deepgram.com/)
- **TTS**: [ElevenLabs Turbo v2.5](https://elevenlabs.io/)
- **Wake word**: [openWakeWord](https://github.com/dscripka/openWakeWord)
- **VAD**: [webrtcvad](https://github.com/wiseman/py-webrtcvad)

---

## Licencia

Ver `LICENSE`.
