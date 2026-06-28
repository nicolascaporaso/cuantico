# Cuántico

[![Cuántico](hardware/cuantico.png)](https://youtu.be/RmWtU8Pogws)

> 🎬 Video de la build: [youtu.be/RmWtU8Pogws](https://youtu.be/RmWtU8Pogws)

Cuántico es un asistente de voz con hardware, personalidad configurable y herramientas reales. Corre en una Raspberry Pi, escucha con wake word, habla por ElevenLabs, razona con OpenRouter y controla luces, música, calendario, YouTube, timers, memoria persistente y audio Bluetooth.

No está pensado para sonar neutro. Está pensado para tener carácter, cambiar de actitud con LEDs y sentirse más criatura de taller que producto pulido.

## Estado actual

- Backend LLM: OpenRouter, no Gemini.
- STT: Deepgram.
- TTS: ElevenLabs.
- Wake word: openWakeWord.
- Salida principal: I2S/VoiceHAT con fallback y soporte para parlantes Bluetooth.
- Personalidad, emociones y luces: perfiles editables en JSON.
- Timers, estado Bluetooth, recuerdos y tokens: persistentes en `state/`.

## Qué hace hoy

- Conversación por voz con wake word.
- Seguimiento sin wake word durante unos segundos después de cada respuesta.
- Búsqueda web integrada para datos actuales.
- Function calling local con tools Python.
- Control de luces Govee: on/off, color y brillo.
- Spotify: canción, playlist por vibe, play/pause, siguiente, anterior, volumen.
- Timers y alarmas persistentes, incluyendo lenguaje natural:
  - `en 30 segundos`
  - `en 5 minutos`
  - `en 2 horas`
  - `mañana a las 7am`
  - `a las 18:30`
- Google Calendar: ver hoy, ver semana, crear eventos.
- YouTube Analytics: métricas y últimos videos.
- Memoria persistente con SQLite.
- Modo llamada por altavoz/micro físico.
- Perfiles de personalidad y reactor LED configurables.
- Audio Bluetooth por voz:
  - buscar
  - listar
  - conectar
  - desconectar
  - consultar cuál está activo
  - volver al altavoz integrado

## Arquitectura

```text
Wake word / VAD / audio
    micro.py
        ↓
Deepgram STT
        ↓
main.py
  - loop principal
  - tools
  - memoria
  - timers
  - modo llamada
        ↓
openrouter_client.py
  - chat
  - tool calling
  - web search
        ↓
altavoz.py
  - ElevenLabs TTS
  - ruta I2S o Bluetooth
        ↓
luces.py
  - reactor LED según estado/emoción
```

Servicios y módulos auxiliares:

- `govee.py`: Developer API v1
- `spotify.py`: Spotify Connect / Raspotify
- `calendario.py`: Google Calendar
- `youtube_stats.py`: YouTube Data + Analytics
- `recuerdos.py`: SQLite
- `timers.py`: scheduler persistente
- `bluetooth_audio.py`: BlueZ + BlueALSA
- `cuantico_profiles.py` + `cuantico_profiles.json`: prompts, emociones y luces

## Hardware

### BOM base

| Componente | Modelo / idea | Notas |
|---|---|---|
| SBC | Raspberry Pi Zero 2 W | La build original apunta a esta. |
| microSD | 16–32 GB clase 10 | Mejor si es decente; Cuántico genera logs y estado persistente. |
| Micrófono | INMP441 I2S | Captura principal. |
| Amplificador | MAX98357A I2S | Salida mono al parlante. |
| Parlante | 3W 4Ω | Conectado al MAX98357A. |
| LEDs | NeoPixel / WS2812B | Reactor visual. |
| Bluetooth | Integrado en la Pi | Para parlantes BT opcionales. |

### Cableado usado en el proyecto

> Los números son pines físicos del header, no BCM.

#### INMP441

| Pin | Pi | Función |
|---|---|---|
| VDD | 1 | 3.3V |
| GND | 39 | GND |
| L/R | a GND | Canal izquierdo |
| SCK | 12 | BCLK |
| WS | 35 | LRCLK |
| SD | 38 | Datos |

#### MAX98357A

| Pin | Pi | Función |
|---|---|---|
| VIN / VDD | 4 | 5V |
| GND | 34 | GND |
| BCLK | 12 | I2S clock |
| LRC | 35 | I2S word select |
| DIN | 40 | Datos hacia el ampli |
| SD | 36 | Mute |

#### NeoPixel

| Pin | Pi |
|---|---|
| 5V | 2 |
| GND | 6 |
| DIN | 32 |

### Carcasa

El repo incluye piezas en `hardware/` para impresión 3D y CNC. Si solo te interesa replicar software, puedes ignorarlo.

## Dependencias del sistema

En Raspberry Pi OS Lite:

```bash
sudo apt update
sudo apt install -y \
  git python3-venv python3-pip \
  sox libsox-fmt-mp3 alsa-utils tmux \
  mpv yt-dlp \
  bluez bluez-alsa-utils
```

Spotify Connect opcional:

```bash
curl -sSL https://dtcooper.github.io/raspotify/install.sh | sh
```

### Overlay de audio recomendado

En `/boot/firmware/config.txt` o `/boot/config.txt`:

```ini
dtparam=i2s=on
dtoverlay=googlevoicehat-soundcard
dtparam=audio=off
```

Reinicia:

```bash
sudo reboot
```

Comprueba:

```bash
arecord -l
aplay -l
```

## Instalación

### 1. Clona el repo

```bash
git clone <tu-repo> ~/cuantico
cd ~/cuantico
```

### 2. Crea el entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Crea `.env`

```bash
cp .env.example .env
```

### 4. Rellena variables mínimas

Variables imprescindibles para arrancar:

- `OPENROUTER_API_KEY`
- `ELEVENLABS_API_KEY`
- `DEEPGRAM_API_KEY`
- `GOVEE_API_KEY`
- `WAKE_MODEL_PATH`

Variables muy recomendables:

- `CUANTICO_PROFILE`
- `CUANTICO_TIMEZONE`
- `USER_SHORT_NAME`
- `USER_FULL_NAME`

Variables opcionales:

- Spotify
- Google Calendar / YouTube
- Bluetooth
- `OPENROUTER_HTTP_REFERER`

## Variables de entorno

### Identidad y perfil

```env
USER_SHORT_NAME=Nico
USER_FULL_NAME=Nicolas
CUANTICO_PROFILE=argentino
CUANTICO_TIMEZONE=America/Argentina/Buenos_Aires
```

### LLM

```env
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_CALL_MODEL=openai/gpt-4o-mini
OPENROUTER_HTTP_REFERER=
```

### Audio

```env
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb
ALSA_PLAYBACK_DEVICE=plughw:0,0
BLUETOOTH_AUTO_ROUTE=true
BLUETOOTH_AUDIO_PROFILE=a2dp
BLUETOOTH_SCAN_SECONDS=8
```

### STT y wake word

```env
DEEPGRAM_API_KEY=
WAKE_MODEL_PATH=/home/nicolas/cuantico/cuantico.onnx
```

También puedes usar un modelo preentrenado de openWakeWord, por ejemplo `hey_jarvis`, si apuntas la ruta correcta dentro de tu entorno.

### Govee

```env
GOVEE_API_KEY=
```

### Spotify

```env
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
MUSIC_BACKEND_DEFAULT=spotify
YT_DLP_COMMAND=yt-dlp
MPV_COMMAND=mpv
YOUTUBE_AUDIO_SEARCH_LIMIT=5
YOUTUBE_PLAYLIST_SEARCH_LIMIT=8
```

### Google / YouTube

```env
GOOGLE_CLIENT_SECRETS_PATH=state/google_client.json
GOOGLE_TOKEN_PATH=state/google_token.json
YOUTUBE_CHANNEL_ID=
```

## Wake word

Cuántico usa `openwakeword`. En el repo hay un modelo `cuantico.onnx`, pero también puedes usar uno preentrenado o entrenar el tuyo.

Ejemplo:

```env
WAKE_MODEL_PATH=/home/nicolas/cuantico/cuantico.onnx
```

## Primer arranque manual

En la Raspberry:

```bash
sudo .venv/bin/python3 src/main.py
```

> En la Pi el `sudo` es importante por NeoPixel y acceso a hardware. En un entorno sin LEDs físicos no siempre hace falta.

## Spotify

`spotify.py` usa `spotipy` y busca un dispositivo cuyo nombre contenga `raspotify` o `cuantico`.

Flujo real:

- si Spotify no está configurado, se desactiva solo
- si está configurado, intenta descubrir el dispositivo Connect
- si no lo encuentra, deja warning en consola

Primera autorización:

- Spotipy usa flujo OAuth con `open_browser=False`
- en consola te mostrará una URL
- debes abrirla, autorizar y pegar la URL final redirigida

Se guarda en:

- `.spotify_cache`

## Musica Por YouTube

Cuántico también puede reproducir música sin Premium usando:

- `yt-dlp` para buscar y resolver audio
- `mpv` para reproducir y controlar play/pause/siguiente/anterior/volumen

Este backend usa la misma ruta de audio activa que el TTS:

- I2S / VoiceHAT local
- parlante Bluetooth si está conectado y activo

Estado persistente:

- `state/music_backend.json`

Variables útiles:

```env
MUSIC_BACKEND_DEFAULT=spotify
YT_DLP_COMMAND=yt-dlp
MPV_COMMAND=mpv
YOUTUBE_AUDIO_SEARCH_LIMIT=5
YOUTUBE_PLAYLIST_SEARCH_LIMIT=8
```

Frases útiles:

- `usá youtube para la música`
- `usá spotify para la música`
- `qué sistema de música estás usando`
- `poné Soda Stereo por youtube`
- `poneme algo chill por youtube`

Notas reales:

- si el backend activo es `youtube`, los comandos generales de música salen por `yt-dlp + mpv`
- si el backend activo es `spotify`, siguen saliendo por Spotify Connect / Raspotify
- cambiar el backend por voz actualiza la preferencia persistente para los próximos pedidos

## Google Calendar y YouTube

`calendario.py` y `youtube_stats.py` comparten el mismo token OAuth.

Primera autorización:

1. Crea un OAuth Client tipo Desktop en Google Cloud.
2. Guarda el JSON como `state/google_client.json`.
3. Ejecuta una vez en una máquina con navegador.
4. Se generará `state/google_token.json`.
5. Copia ese token a la Pi.

Si cambias scopes:

- borra `state/google_token.json`
- vuelve a autorizar

## Timers y alarmas

Cuántico soporta dos tipos:

- timer relativo
- alarma absoluta

Internamente todo se persiste en:

- `state/timers.json`

El scheduler:

- sobrevive a reinicios
- carga timers existentes al arrancar
- dispara callbacks de voz al vencer
- si algo venció mientras estaba apagado, lo levanta al iniciar

Ejemplos de frases soportadas:

- `avisame en 30 segundos`
- `poné una alarma en 5 minutos`
- `avisame en 2 horas`
- `poné una alarma mañana a las 7am`
- `poné una alarma a las 18:30`

## Memoria persistente

La memoria no es historial de chat. Son hechos persistentes.

Se guarda en:

- `state/recuerdos.db`

Sirve para:

- gustos
- personas importantes
- proyectos
- datos estables del usuario

No debería usarse para:

- secretos
- contraseñas
- datos de tarjeta
- cosas efímeras que dejan de ser verdad enseguida

## Audio

### Ruta local

La reproducción local usa:

- `sox` para filtrar/normalizar
- `aplay` para sacar el audio
- GPIO16 para mutear/desmutear el ampli de la VoiceHAT

### Sonido de arranque

Si existe `test.wav` en la raíz del repo, Cuántico puede reproducirlo al arrancar.

### Bluetooth

El control Bluetooth está en `src/bluetooth_audio.py` y usa:

- `bluetoothctl`
- BlueZ
- BlueALSA

Estado persistente:

- `state/bluetooth_audio.json`

Funciones soportadas:

- buscar dispositivos
- listar dispositivos
- conectar uno por nombre o MAC
- desconectar uno concreto
- consultar cuál está activo
- volver al altavoz integrado
- recordar el parlante Bluetooth preferido

Frases útiles:

- `buscá parlantes bluetooth`
- `listá los parlantes bluetooth`
- `conectá el JBL Flip`
- `desconectá el JBL Flip`
- `qué parlante bluetooth está conectado`
- `volvé al altavoz integrado`

Si el parlante BT no está conectado en el momento de hablar:

- Cuántico vuelve al `ALSA_PLAYBACK_DEVICE` local

## Reactor LED y emociones

`luces.py` no tiene efectos fijos hardcodeados por personalidad. El reactor se alimenta desde `cuantico_profiles.json`.

Estados base del sistema:

- `esperando`
- `escuchando`
- `pensando`
- `apagado`

Estados emocionales:

- dependen del perfil activo
- se detectan por triggers en la respuesta de Cuántico
- controlan color, patrón y velocidad

Efectos soportados:

- `pulse`
- `spinner`
- `flicker`
- `rainbow`
- `blink`
- `alternate`
- `off`

## Perfiles, prompts y personalidad

Los prompts ya no viven en `main.py`. Viven en:

- `src/cuantico_profiles.json`
- `src/cuantico_profiles.py`

Un perfil define:

- `label`
- `main_prompt`
- `call_prompt`
- `default_emotion`
- `emotion_rules`
- `light_states`
- alias de estados si hace falta

Perfiles incluidos hoy:

- `argentino`
- `espanol`
- `tanguero`

Selección:

```env
CUANTICO_PROFILE=tanguero
```

Para crear uno nuevo:

1. Duplica un perfil en `src/cuantico_profiles.json`
2. Ponle una nueva clave
3. Cambia `CUANTICO_PROFILE`
4. Reinicia Cuántico

## Modo llamada

`llamada.py` monta un modo especial para hablar con otra persona por teléfono usando el móvil en altavoz al lado del dispositivo.

Flujo:

1. El usuario activa la intención de llamada.
2. Cuántico responde normal.
3. Al terminar de hablar entra en modo llamada.
4. Usa un prompt específico, más profesional.
5. Escucha y responde por streaming.
6. Sale por:
   - marcador `[FIN_LLAMADA]`
   - silencio largo
   - timeout global
   - orden explícita de colgar

## Servicio systemd

El repo incluye:

- `cuantico.service`

Instalación:

```bash
sudo cp ~/cuantico/cuantico.service /etc/systemd/system/cuantico.service
sudo systemctl daemon-reload
sudo systemctl enable --now cuantico
```

Comandos útiles:

```bash
systemctl status cuantico
journalctl -u cuantico -f
sudo systemctl restart cuantico
sudo systemctl stop cuantico
```

El servicio actual:

- arranca tras red, sonido y Bluetooth
- corre como `root`
- usa `/home/nicolas/cuantico` como ejemplo de ruta

Ajústalo si tu usuario o ruta son distintos.

## Logs y depuración

Además de `journalctl`, Cuántico escribe trazas estructuradas en:

- `state/unexpected-process-exit.log`

Se instrumentan, entre otras cosas:

- arranque y cierre
- excepciones no manejadas
- excepciones de threads
- señales
- wake word
- Deepgram
- OpenRouter
- TTS
- timers
- callbacks de alarma
- Bluetooth

Archivos de ayuda incluidos:

- `debug-unexpected-process-exit.md`
- `debug-timer-alarm-exit.md`

## Estado persistente generado

Durante el uso se crean o actualizan estos archivos:

- `state/recuerdos.db`
- `state/timers.json`
- `state/bluetooth_audio.json`
- `state/music_backend.json`
- `state/google_client.json`
- `state/google_token.json`
- `state/unexpected-process-exit.log`

Y también:

- `.spotify_cache`

## Estructura del repo

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example
├── cuantico.service
├── cuantico.onnx
├── cuantico.onnx.data
├── debug-timer-alarm-exit.md
├── debug-unexpected-process-exit.md
├── hardware/
└── src/
    ├── altavoz.py
    ├── bluetooth_audio.py
    ├── calendario.py
    ├── config.py
    ├── cuantico_profiles.json
    ├── cuantico_profiles.py
    ├── govee.py
    ├── llamada.py
    ├── luces.py
    ├── main.py
    ├── music_router.py
    ├── music_youtube.py
    ├── micro.py
    ├── openrouter_client.py
    ├── recuerdos.py
    ├── spotify.py
    ├── timers.py
    └── youtube_stats.py
```

## Troubleshooting

### No suena la voz pero `test.wav` sí

Te falta casi seguro:

```bash
sudo apt install -y libsox-fmt-mp3
```

### El micro no abre a 16 kHz

Es normal en algunos devices I2S/VoiceHAT. `micro.py` ya hace fallback a 48 kHz y remuestrea a 16 kHz.

### Spotify no aparece

- verifica que `raspotify` esté corriendo
- revisa el nombre del dispositivo Connect
- ajusta `DEVICE_HINTS` en `src/spotify.py` si hace falta

### YouTube no reproduce musica

- instala `mpv` y `yt-dlp`
- revisa que `YT_DLP_COMMAND` y `MPV_COMMAND` apunten a binarios válidos
- si usás Bluetooth, verifica que `state/bluetooth_audio.json` apunte al parlante correcto
- si `spotify` te da `403`, cambia temporalmente el backend con `usá youtube para la música`

### Govee da 401 o no controla nada

- revisa tu API key
- no todos los modelos sirven con la Developer API v1

### Wake word responde mal

Revisa en `src/micro.py`:

- `WAKE_THRESHOLD`
- `GANANCIA_MIC`

Y mira los logs `score wake=...`.

### Se cayó la Pi o perdió SSH

Cuando vuelva:

```bash
journalctl -b -1 -n 200 --no-pager
journalctl -k -b -1 -n 200 --no-pager
dmesg -T | tail -n 120
```

### La base SQLite quedó readonly

Si corriste Cuántico con `sudo`, puede que `state/` quede propiedad de `root`.

Corrígelo si quieres inspeccionarla manualmente:

```bash
sudo chown -R nicolas:nicolas state
```

### Bluetooth no conecta

Comprueba:

```bash
sudo systemctl status bluetooth
bluetoothctl devices
bluetoothctl info <MAC>
```

Y asegúrate de tener:

```bash
sudo apt install -y bluez bluez-alsa-utils
```

## Stack

- LLM gateway: [OpenRouter](https://openrouter.ai/)
- STT: [Deepgram](https://deepgram.com/)
- TTS: [ElevenLabs](https://elevenlabs.io/)
- Wake word: [openWakeWord](https://github.com/dscripka/openWakeWord)
- VAD: [webrtcvad](https://github.com/wiseman/py-webrtcvad)
- Spotify: [spotipy](https://spotipy.readthedocs.io/)
- Google APIs: Calendar + YouTube
- LEDs: NeoPixel / `rpi_ws281x`

## Licencia

Ver `LICENSE`.
