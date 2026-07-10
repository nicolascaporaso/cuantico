"""Carga perfiles editables de Cuantico desde JSON."""

from copy import deepcopy
import json
from pathlib import Path

import config

USER_SHORT_NAME = config.USER_SHORT_NAME
USER_FULL_NAME = config.USER_FULL_NAME

_LEGACY_REPLACEMENTS = (
    ("Fran Garcia", USER_FULL_NAME),
    ("Fran", USER_SHORT_NAME),
    ("nico Garcia", USER_FULL_NAME),
    ("nico", USER_SHORT_NAME),
    ("Nicolas", USER_FULL_NAME),
)
_PROFILES_JSON_PATH = Path(__file__).resolve().with_name("cuantico_profiles.json")
_ACTIVE_PROFILE_STATE_PATH = Path(config.STATE_DIR) / "active_profile.json"


def _load_profiles_config() -> dict:
    with open(_PROFILES_JSON_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError("cuantico_profiles.json debe contener un objeto JSON")
    if "profiles" not in data or not isinstance(data["profiles"], dict):
        raise RuntimeError("cuantico_profiles.json debe incluir la clave 'profiles'")
    return data


def _load_persisted_profile_name() -> str | None:
    try:
        if not _ACTIVE_PROFILE_STATE_PATH.exists():
            return None
        data = json.loads(_ACTIVE_PROFILE_STATE_PATH.read_text(encoding="utf-8"))
        nombre = (data.get("profile") or "").strip().lower()
        return nombre or None
    except Exception:
        return None


def _persist_profile_name(nombre: str):
    payload = {"profile": (nombre or "").strip().lower()}
    _ACTIVE_PROFILE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_PROFILE_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


_RAW_CONFIG = _load_profiles_config()
_BASE_STATE_ALIASES = _RAW_CONFIG.get("state_aliases", {})
_BASE_LIGHT_STATES = _RAW_CONFIG.get("base_light_states", {})
PROFILES = _RAW_CONFIG["profiles"]


def personalizar_texto(texto: str) -> str:
    for origen, destino in _LEGACY_REPLACEMENTS:
        texto = texto.replace(origen, destino)
    return texto


def _build_active_profile(requested_name: str) -> tuple[str, dict]:
    selected_name = (requested_name or "argentino").strip().lower()
    if selected_name not in PROFILES:
        selected_name = "argentino"
    raw = PROFILES[selected_name]
    merged = {
        "label": raw.get("label", selected_name),
        "default_emotion": raw.get("default_emotion", "sarcasmo"),
        "main_prompt": raw.get("main_prompt", ""),
        "call_prompt": raw.get("call_prompt", ""),
        "tts": deepcopy(raw.get("tts", {})),
        "emotion_rules": deepcopy(raw.get("emotion_rules", [])),
        "state_aliases": dict(_BASE_STATE_ALIASES),
        "light_states": deepcopy(_BASE_LIGHT_STATES),
    }
    merged["state_aliases"].update(raw.get("state_aliases", {}))
    merged["light_states"].update(deepcopy(raw.get("light_states", {})))
    return selected_name, merged


_requested = _load_persisted_profile_name() or config.CUANTICO_PROFILE
ACTIVE_PROFILE_NAME, ACTIVE_PROFILE = _build_active_profile(_requested)


def get_active_profile_name() -> str:
    return ACTIVE_PROFILE_NAME


def get_active_profile_label() -> str:
    return ACTIVE_PROFILE["label"]


def list_profiles() -> list[str]:
    return sorted(PROFILES.keys())


def set_active_profile(nombre: str, persist: bool = True) -> tuple[str, dict]:
    global ACTIVE_PROFILE_NAME, ACTIVE_PROFILE
    selected, cfg = _build_active_profile(nombre)
    ACTIVE_PROFILE_NAME = selected
    ACTIVE_PROFILE = cfg
    if persist:
        _persist_profile_name(selected)
    return ACTIVE_PROFILE_NAME, ACTIVE_PROFILE


def resolve_state_name(state_name: str) -> str:
    return ACTIVE_PROFILE["state_aliases"].get(state_name, state_name)


def get_light_state(state_name: str) -> dict:
    canonical = resolve_state_name(state_name)
    return ACTIVE_PROFILE["light_states"].get(canonical, ACTIVE_PROFILE["light_states"]["sarcasmo"])


def get_reactor_states_for_prompt() -> list[str]:
    system_states = {"esperando", "escuchando", "pensando", "apagado"}
    return [name for name in ACTIVE_PROFILE["light_states"] if name not in system_states]


def render_main_prompt() -> str:
    reactor_states = ", ".join(f"`{name}`" for name in get_reactor_states_for_prompt())
    prompt = ACTIVE_PROFILE["main_prompt"].format(
        user_short_name=USER_SHORT_NAME,
        user_full_name=USER_FULL_NAME,
        reactor_states=reactor_states,
    )
    return personalizar_texto(prompt)


def render_call_prompt(objetivo: str, fin: str) -> str:
    prompt = ACTIVE_PROFILE["call_prompt"].format(
        user_short_name=USER_SHORT_NAME,
        user_full_name=USER_FULL_NAME,
        objetivo=objetivo,
        fin=fin,
    )
    return personalizar_texto(prompt)


def detectar_emocion(texto: str) -> str:
    normalizado = (texto or "").lower()
    for rule in ACTIVE_PROFILE["emotion_rules"]:
        if any(trigger in normalizado for trigger in rule.get("triggers", [])):
            return rule["name"]
    return ACTIVE_PROFILE["default_emotion"]


def get_tts_provider() -> str:
    return (ACTIVE_PROFILE.get("tts") or {}).get("provider") or "elevenlabs"


def get_tts_model_id() -> str:
    return (ACTIVE_PROFILE.get("tts") or {}).get("model_id") or ""


def get_tts_language_code() -> str:
    return (ACTIVE_PROFILE.get("tts") or {}).get("language_code") or ""


def get_tts_voice_settings() -> dict:
    cfg = (ACTIVE_PROFILE.get("tts") or {}).get("voice_settings") or {}
    return dict(cfg)


def get_tts_voice_id() -> str:
    return (ACTIVE_PROFILE.get("tts") or {}).get("voice_id") or ""
