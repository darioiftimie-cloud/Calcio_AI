# -*- coding: utf-8 -*-
"""Client API-Football v3 usato SOLO dall'updater offline.

Copre le competizioni assenti dal piano gratuito di football-data.org:
Europa League (id 3) e Nations League (id 5). Il piano gratuito API-Football
(100 richieste/giorno, 10/minuto) consente le stagioni fino al 2024, quindi
l'updater ripiega automaticamente sull'ultima edizione accessibile.
"""

import time

import requests

from . import config


class ApiFootballError(Exception):
    """Errore restituito da API-Football (chiave, piano, rate limit...)."""


_last_call = 0.0
_MIN_INTERVAL = 6.5  # 10 richieste/minuto sul piano gratuito


def apif_get(path: str, params: dict | None = None) -> list:
    """GET verso API-Football. Ritorna `response` (lista). Riprova sul rate
    limit al minuto; solleva ApiFootballError sugli altri errori."""
    global _last_call
    if not config.API_FOOTBALL_KEY:
        raise ApiFootballError(
            "API_FOOTBALL_KEY mancante: impostala nel file .env "
            "(serve solo per Europa League e Nations League).")

    headers = {"x-apisports-key": config.API_FOOTBALL_KEY}
    url = config.APIF_BASE + path

    for attempt in range(3):
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()

        r = requests.get(url, params=params or {}, headers=headers,
                         timeout=config.HTTP_TIMEOUT)
        try:
            data = r.json()
        except ValueError as exc:
            raise ApiFootballError(f"risposta non valida (HTTP {r.status_code})") from exc

        errors = data.get("errors") or {}
        if isinstance(errors, dict) and errors:
            msg = " · ".join(f"{k}: {v}" for k, v in errors.items())
            if "rateLimit" in errors and attempt < 2:
                time.sleep(21)
                continue
            raise ApiFootballError(msg)
        return data.get("response") or []
    raise ApiFootballError("rate limit API-Football (10 req/min)")


# ---------------------------------------------------------------- endpoint
def league_fixtures(league_id: int, season: int) -> list[dict]:
    """Tutte le partite della lega per la stagione (una sola chiamata)."""
    return apif_get("/fixtures", {"league": league_id, "season": season})


def league_standings(league_id: int, season: int) -> list[list[dict]]:
    """Classifiche a gironi (lista di tabelle, una per girone)."""
    resp = apif_get("/standings", {"league": league_id, "season": season})
    if not resp:
        return []
    return (resp[0].get("league") or {}).get("standings") or []


def league_topscorers(league_id: int, season: int) -> list[dict]:
    """Capocannonieri della competizione (max 20)."""
    try:
        return apif_get("/players/topscorers",
                        {"league": league_id, "season": season})
    except ApiFootballError:
        return []


def resolve_season(league_id: int, fallbacks: list[int]) -> tuple[int, list[dict]]:
    """Prima stagione dei fallback con partite disponibili sul piano corrente.

    Ritorna (stagione, fixtures) riusando la chiamata già fatta. Le stagioni
    bloccate dal piano gratuito rispondono con un errore o lista vuota."""
    for season in dict.fromkeys(fallbacks):
        try:
            fixtures = league_fixtures(league_id, season)
        except ApiFootballError as exc:
            print(f"    · stagione {season} non accessibile: {exc}")
            continue
        if fixtures:
            return season, fixtures
    raise ApiFootballError(
        f"nessuna stagione accessibile per la lega {league_id} "
        f"(provate: {fallbacks})")
