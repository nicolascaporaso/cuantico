"""Memoria persistente de Cuántico: hechos sobre Fran, su vida y su entorno.

SQLite en state/recuerdos.db. Al arrancar cada conversación nueva, todos los
recuerdos se inyectan en el SYSTEM_PROMPT como un bloque "RECUERDOS DE FRAN"
para que Gemini pueda vacilar con cosas de ayer, mencionar a personas por
nombre sin que Fran repita, acordarse de gustos, etc.

No es un chat history — son HECHOS ATEMPORALES. Cuántico decide qué merece
guardarse a través de la tool `recordar`. Fran puede pedir borrar con `olvidar`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

import config

_RUTA = Path(config.STATE_DIR) / "recuerdos.db"
_conn: sqlite3.Connection | None = None


def _conectar():
    global _conn
    _conn = sqlite3.connect(str(_RUTA), check_same_thread=False)
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS recuerdos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texto TEXT NOT NULL,
            categoria TEXT DEFAULT '',
            creado_en TEXT NOT NULL
        )"""
    )
    _conn.commit()


def inicializar():
    _conectar()
    assert _conn is not None
    total = _conn.execute("SELECT COUNT(*) FROM recuerdos").fetchone()[0]
    print(f"🧠 Memoria persistente: {total} recuerdo(s) cargado(s).")


def añadir(texto: str, categoria: str = "") -> int:
    texto = texto.strip()
    if not texto or _conn is None:
        return 0
    # Antiduplicados básico (case-insensitive, texto exacto)
    existe = _conn.execute(
        "SELECT id FROM recuerdos WHERE LOWER(texto)=LOWER(?)", (texto,)
    ).fetchone()
    if existe:
        return int(existe[0])
    cur = _conn.execute(
        "INSERT INTO recuerdos (texto, categoria, creado_en) VALUES (?, ?, ?)",
        (texto, (categoria or "").strip(), datetime.now().isoformat()),
    )
    _conn.commit()
    return int(cur.lastrowid or 0)


def borrar_por_coincidencia(frag: str) -> int:
    frag = (frag or "").strip().lower()
    if not frag or _conn is None:
        return 0
    filas = _conn.execute(
        "SELECT id FROM recuerdos WHERE LOWER(texto) LIKE ? OR LOWER(categoria) LIKE ?",
        (f"%{frag}%", f"%{frag}%"),
    ).fetchall()
    for (rid,) in filas:
        _conn.execute("DELETE FROM recuerdos WHERE id = ?", (rid,))
    _conn.commit()
    return len(filas)


def listar(limite: int = 100) -> list[dict]:
    if _conn is None:
        return []
    filas = _conn.execute(
        "SELECT id, texto, categoria FROM recuerdos ORDER BY creado_en DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [{"id": r[0], "texto": r[1], "categoria": r[2]} for r in filas]


def buscar(substr: str, limite: int = 20) -> list[dict]:
    if _conn is None or not substr.strip():
        return []
    key = f"%{substr.strip().lower()}%"
    filas = _conn.execute(
        "SELECT id, texto, categoria FROM recuerdos WHERE LOWER(texto) LIKE ? OR LOWER(categoria) LIKE ? LIMIT ?",
        (key, key, limite),
    ).fetchall()
    return [{"id": r[0], "texto": r[1], "categoria": r[2]} for r in filas]


def formatear_para_prompt(limite: int = 80) -> str:
    """Bloque de texto listo para concatenar al SYSTEM_PROMPT. Vacío si no hay recuerdos."""
    items = listar(limite)
    if not items:
        return ""
    lineas = []
    for r in items:
        cat = f" [{r['categoria']}]" if r["categoria"] else ""
        lineas.append(f"- {r['texto']}{cat}")
    return "RECUERDOS DE FRAN (cosas que ya sabes de él de conversaciones anteriores; úsalas para vacilarle con cariño y referirte a su vida sin que tenga que repetir):\n" + "\n".join(lineas)


def cerrar():
    global _conn
    if _conn:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
