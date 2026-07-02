# -*- coding: utf-8 -*-
"""Helper per gli handler serverless Vercel (BaseHTTPRequestHandler)."""

import json
import traceback
from urllib.parse import urlsplit, parse_qs

from .db import DBError
from .footballdata import FootballDataError


def query(handler) -> dict:
    """Query string → dict (primo valore per chiave)."""
    qs = parse_qs(urlsplit(handler.path).query)
    return {k: v[0] for k, v in qs.items()}


def send_json(handler, obj, status: int = 200, smaxage: int = 300) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if status == 200 and smaxage:
        # cache edge di Vercel: riduce invocazioni e crediti API
        handler.send_header("Cache-Control",
                            f"s-maxage={smaxage}, stale-while-revalidate=120")
    handler.end_headers()
    handler.wfile.write(body)


def send_pdf(handler, data: bytes, filename: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/pdf")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "s-maxage=3600")
    handler.end_headers()
    handler.wfile.write(data)


def run_safe(handler, fn) -> None:
    """Esegue l'endpoint traducendo gli errori in JSON puliti."""
    try:
        fn()
    except DBError as exc:
        send_json(handler, {"errore": f"dati non disponibili: {exc}"}, 503, smaxage=0)
    except FootballDataError as exc:
        send_json(handler, {"errore": f"football-data.org: {exc}"}, 502, smaxage=0)
    except (KeyError, ValueError, TypeError) as exc:
        send_json(handler, {"errore": f"richiesta non valida: {exc}"}, 400, smaxage=0)
    except Exception:
        send_json(handler, {"errore": "errore interno",
                            "dettaglio": traceback.format_exc(limit=3)},
                  500, smaxage=0)
