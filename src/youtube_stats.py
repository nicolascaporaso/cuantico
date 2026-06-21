"""Métricas de YouTube del canal de nico.

Reutiliza el token OAuth de calendario.py (los scopes YT ya están en calendario.SCOPES).
Si esto falla por scopes, hay que borrar state/google_token.json y re-autorizar en el Mac.
"""
from __future__ import annotations

import datetime as dt
from googleapiclient.discovery import build

import config
import calendario

_yt_data = None          # YouTube Data API v3 (canal, vídeos)
_yt_analytics = None     # YouTube Analytics API v2 (métricas)
_channel_id: str | None = None


def inicializar() -> bool:
    global _yt_data, _yt_analytics, _channel_id
    try:
        creds = calendario.obtener_credenciales()
        _yt_data = build("youtube", "v3", credentials=creds, cache_discovery=False)
        _yt_analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

        if config.YOUTUBE_CHANNEL_ID:
            _channel_id = config.YOUTUBE_CHANNEL_ID
        else:
            r = _yt_data.channels().list(part="id,snippet,statistics", mine=True).execute()
            items = r.get("items", [])
            if not items:
                raise RuntimeError("Ningún canal asociado a esta cuenta")
            _channel_id = items[0]["id"]
            nombre = items[0]["snippet"]["title"]
            subs = items[0]["statistics"].get("subscriberCount", "?")
            print(f"📹 YouTube: canal '{nombre}' ({subs} subs) listo.")
        return True
    except Exception as e:
        print(f"⚠️ YouTube no disponible: {e}")
        _yt_data = _yt_analytics = None
        return False


_PERIODOS = {
    "hoy": 0, "24h": 1, "7d": 7, "semana": 7,
    "28d": 28, "mes": 28, "mensual": 28, "30d": 30,
}


def _rango(periodo: str) -> tuple[str, str]:
    dias = _PERIODOS.get(periodo.lower().strip(), 7)
    fin = dt.date.today()
    inicio = fin - dt.timedelta(days=max(1, dias))
    return inicio.isoformat(), fin.isoformat()


def analiticas(periodo: str = "7d") -> dict:
    if not _yt_analytics:
        raise RuntimeError("YouTube Analytics no inicializado")
    inicio, fin = _rango(periodo)
    r = _yt_analytics.reports().query(
        ids=f"channel=={_channel_id}",
        startDate=inicio,
        endDate=fin,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost",
    ).execute()
    fila = r.get("rows", [[0, 0, 0, 0]])[0] if r.get("rows") else [0, 0, 0, 0]
    views, minutos, subs_ganados, subs_perdidos = (int(v) for v in fila)

    top = _yt_analytics.reports().query(
        ids=f"channel=={_channel_id}",
        startDate=inicio,
        endDate=fin,
        metrics="views",
        dimensions="video",
        maxResults=5,
        sort="-views",
    ).execute()
    top_ids = [row[0] for row in top.get("rows", [])]
    titulos_por_id: dict[str, str] = {}
    if top_ids:
        det = _yt_data.videos().list(part="snippet", id=",".join(top_ids)).execute()
        for item in det.get("items", []):
            titulos_por_id[item["id"]] = item["snippet"]["title"]
    top_videos = [
        {"titulo": titulos_por_id.get(row[0], row[0]), "views": int(row[1])}
        for row in top.get("rows", [])
    ]

    return {
        "periodo": f"{inicio} → {fin}",
        "views": views,
        "watch_time_horas": round(minutos / 60, 1),
        "subs_netos": subs_ganados - subs_perdidos,
        "top_videos": top_videos,
    }


def videos_recientes(n: int = 5) -> list[dict]:
    if not _yt_data:
        raise RuntimeError("YouTube Data no inicializado")
    r = _yt_data.search().list(
        part="id,snippet",
        channelId=_channel_id,
        maxResults=n,
        order="date",
        type="video",
    ).execute()
    ids = [i["id"]["videoId"] for i in r.get("items", []) if i["id"].get("videoId")]
    if not ids:
        return []
    det = _yt_data.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
    out = []
    for item in det.get("items", []):
        s = item.get("statistics", {})
        out.append({
            "titulo": item["snippet"]["title"],
            "publicado": item["snippet"]["publishedAt"][:10],
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
            "comentarios": int(s.get("commentCount", 0)),
        })
    return out
