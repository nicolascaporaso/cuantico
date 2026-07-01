"""Cliente ligero para OpenRouter con tools locales y búsqueda web.

Mantiene un historial de mensajes estilo OpenAI/OpenRouter y ejecuta function
calling local en bucle hasta obtener una respuesta final de texto.
"""
from __future__ import annotations

import inspect
import json
import time
import urllib.request
from dataclasses import dataclass
from types import NoneType
from typing import Any, Iterable, get_args, get_origin
from pathlib import Path

import requests

import config

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOOL_LOOPS = 8
_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"


# #region debug-point C:llm-runtime
def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "C",
        "location": "openrouter_client.py",
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
        req = urllib.request.Request(debug_url, data=line.encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=0.8).read()
    except Exception:
        pass
# #endregion


@dataclass
class ChatResult:
    text: str


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Cuantico",
    }
    if config.OPENROUTER_HTTP_REFERER:
        headers["HTTP-Referer"] = config.OPENROUTER_HTTP_REFERER
    return headers


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _tipo_json(annotation: Any) -> str:
    if annotation in (inspect.Signature.empty, Any):
        return "string"

    origin = get_origin(annotation)
    if origin is not None:
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if args:
            return _tipo_json(args[0])

    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is str:
        return "string"
    return "string"


def _schema_funcion(fn) -> dict[str, Any]:
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for nombre, parametro in sig.parameters.items():
        if parametro.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        properties[nombre] = {
            "type": _tipo_json(parametro.annotation),
        }
        if parametro.default is inspect.Signature.empty:
            required.append(nombre)

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": inspect.getdoc(fn) or fn.__name__,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _normalizar_contenido(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        trozos: list[str] = []
        for item in content:
            if isinstance(item, str):
                trozos.append(item)
            elif isinstance(item, dict):
                texto = item.get("text") or item.get("content") or ""
                if texto:
                    trozos.append(str(texto))
        return "".join(trozos)
    return str(content)


def _parsear_json_seguro(texto: str) -> dict[str, Any]:
    if not texto:
        return {}
    try:
        dato = json.loads(texto)
    except json.JSONDecodeError:
        return {}
    return dato if isinstance(dato, dict) else {}


def _serializar_resultado(valor: Any) -> str:
    if isinstance(valor, str):
        return valor
    try:
        return json.dumps(valor, ensure_ascii=False)
    except Exception:
        return str(valor)


def _request_chat(payload: dict[str, Any], *, stream: bool = False, timeout: int = 90):
    _debug_emit("openrouter-request", {"stream": stream, "timeout": timeout, "model": payload.get("model"), "message_count": len(payload.get("messages") or []), "tool_count": len(payload.get("tools") or [])})
    return requests.post(
        API_URL,
        headers=_headers(),
        json=payload,
        timeout=timeout,
        stream=stream,
    )


class OpenRouterChatSession:
    def __init__(
        self,
        system_prompt: str,
        funciones: Iterable,
        *,
        model: str | None = None,
        enable_web_search: bool = True,
        max_tool_loops: int = MAX_TOOL_LOOPS,
    ):
        self.model = model or config.OPENROUTER_MODEL
        self.max_tool_loops = max_tool_loops
        self.funciones = {fn.__name__: fn for fn in funciones}
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        self.tools = [_schema_funcion(fn) for fn in funciones]
        if enable_web_search:
            self.tools.append(
                {
                    "type": "openrouter:web_search",
                    "parameters": {
                        "max_results": 5,
                        "max_total_results": 10,
                        "search_context_size": "medium",
                    },
                }
            )

    def _payload(self, *, stream: bool = False) -> dict[str, Any]:
        return _strip_none(
            {
                "model": self.model,
                "messages": self.messages,
                "tools": self.tools or None,
                "tool_choice": "auto" if self.tools else None,
                "parallel_tool_calls": True if self.tools else None,
                "stream": stream or None,
                "temperature": 0.7,
            }
        )

    def _ejecutar_tool(self, nombre: str, argumentos: dict[str, Any]) -> str:
        fn = self.funciones.get(nombre)
        if fn is None:
            _debug_emit("tool-missing", {"tool_name": nombre})
            return f'fallo: tool desconocida "{nombre}"'
        try:
            _debug_emit("tool-execute", {"tool_name": nombre, "arguments": argumentos})
            resultado = _serializar_resultado(fn(**argumentos))
            _debug_emit("tool-result", {"tool_name": nombre, "result_preview": resultado[:240]})
            return resultado
        except Exception as e:
            _debug_emit("tool-exception", {"tool_name": nombre, "arguments": argumentos, "error": str(e)})
            return f"fallo: {e}"

    def _completar(self, *, intentos: int = 2, espera_seg: int = 8) -> dict[str, Any]:
        for intento in range(intentos):
            r = _request_chat(self._payload(), timeout=120)
            if r.ok:
                _debug_emit("openrouter-response-ok", {"status": r.status_code})
                return r.json()

            texto = r.text[:400]
            es_429 = r.status_code == 429
            _debug_emit("openrouter-response-failed", {"status": r.status_code, "body_preview": texto})
            if es_429 and intento < intentos - 1:
                print(f"⏳ Límite de OpenRouter alcanzado, reintentando en {espera_seg}s…")
                time.sleep(espera_seg)
                continue
            raise RuntimeError(f"OpenRouter {r.status_code}: {texto}")
        raise RuntimeError("OpenRouter no devolvió respuesta")

    def send_message(self, texto: str) -> ChatResult:
        self.messages.append({"role": "user", "content": texto})
        _debug_emit("chat-send-message", {"text_preview": texto[:160]})

        for _ in range(self.max_tool_loops):
            data = self._completar()
            message = data["choices"][0]["message"]
            assistant_message = {
                "role": "assistant",
                "content": message.get("content"),
            }
            tool_calls = message.get("tool_calls") or []
            _debug_emit("chat-message-received", {"tool_call_count": len(tool_calls), "has_content": bool(message.get("content"))})
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            self.messages.append(assistant_message)

            if not tool_calls:
                _debug_emit("chat-final-text", {"text_preview": _normalizar_contenido(message.get("content"))[:160]})
                return ChatResult(_normalizar_contenido(message.get("content")).strip())

            for tool_call in tool_calls:
                if tool_call.get("type") != "function":
                    continue
                function_data = tool_call.get("function") or {}
                nombre = function_data.get("name", "")
                argumentos = _parsear_json_seguro(function_data.get("arguments", ""))
                resultado = self._ejecutar_tool(nombre, argumentos)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": resultado,
                    }
                )

        raise RuntimeError("Demasiadas llamadas de tools encadenadas")

    def send_message_stream(self, texto: str):
        self.messages.append({"role": "user", "content": texto})
        _debug_emit("chat-send-message-stream", {"text_preview": texto[:160]})
        payload = self._payload(stream=True)
        r = _request_chat(payload, stream=True, timeout=300)
        if not r.ok:
            _debug_emit("openrouter-stream-failed", {"status": r.status_code, "body_preview": r.text[:400]})
            raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:400]}")

        acumulado: list[str] = []

        def _generador():
            try:
                for raw_line in r.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    if not raw_line.startswith("data: "):
                        continue
                    data = raw_line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choice = (payload.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    contenido = delta.get("content")
                    if contenido:
                        acumulado.append(contenido)
                        yield contenido
            finally:
                r.close()
                _debug_emit("openrouter-stream-finished", {"text_preview": "".join(acumulado)[:200]})
                self.messages.append({"role": "assistant", "content": "".join(acumulado).strip()})

        return _generador()
