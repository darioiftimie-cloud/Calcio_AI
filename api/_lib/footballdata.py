# -*- coding: utf-8 -*-
"""Client football-data.org v4 usato dall'updater offline.

Piano gratuito: 10 richieste/minuto, competizioni limitate (Big 5 + Champions).
Il client rispetta il rate limit (attesa tra le chiamate) e riprova sul 429.
Non viene usato a runtime dagli endpoint Vercel: quelli leggono il DB JSON già
popolato dall'updater.
"""

import time

import requests

from . import config


class FootballDataError(Exception):
    """Errore restituito da football-data.org (chiave, piano, rate limit...)."""


_last_call = 0.0


def fd_get(path: str, params: dict | None = None, *, throttle: bool = True) -> dict:
    """GET verso football-data.org. Ritorna il JSON completo (dict).

    `throttle=True` rispetta l'intervallo minimo tra chiamate (rate limit del
    piano gratuito). Riprova automaticamente sul 429."""
    global _last_call
    if not config.FOOTBALL_DATA_KEY:
        raise FootballDataError(
            "FOOTBALL_DATA_KEY mancante: impostala nel file .env (locale) "
            "o nelle Environment Variables di Vercel.")

    headers = {"X-Auth-Token": config.FOOTBALL_DATA_KEY}
    url = config.FD_BASE + path

    for attempt in range(4):
        if throttle:
            wait = config.FD_MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
        _last_call = time.monotonic()

        r = requests.get(url, params=params or {}, headers=headers,
                         timeout=config.HTTP_TIMEOUT)
        if r.status_code == 429:
            # limite al minuto: attendi la finestra indicata (o 60s) e riprova
            reset = r.headers.get("X-RequestCounter-Reset")
            delay = int(reset) + 1 if reset and reset.isdigit() else 60
            if attempt < 3:
                time.sleep(min(delay, 65))
                continue
            raise FootballDataError("rate limit football-data.org (10 req/min)")
        try:
            data = r.json()
        except ValueError as exc:
            raise FootballDataError(
                f"risposta non valida (HTTP {r.status_code})") from exc
        if r.status_code == 403:
            raise FootballDataError(
                f"accesso negato (piano): {data.get('message', path)}")
        if r.status_code == 404:
            raise FootballDataError(f"risorsa inesistente: {path}")
        if r.status_code >= 400:
            raise FootballDataError(data.get("message") or f"HTTP {r.status_code}")
        return data
    raise FootballDataError("rate limit football-data.org")


# ---------------------------------------------------------------- endpoint
def competition_matches(code: str, season: int) -> list[dict]:
    """Tutte le partite della competizione per la stagione (anno d'inizio)."""
    try:
        data = fd_get(f"/competitions/{code}/matches", {"season": season})
    except FootballDataError:
        return []
    return data.get("matches", []) or []


def competition_standings(code: str, season: int) -> dict:
    """Classifica completa (dict grezzo football-data.org)."""
    return fd_get(f"/competitions/{code}/standings", {"season": season})


def competition_scorers(code: str, season: int, limit: int = 30) -> list[dict]:
    """Capocannonieri della competizione (gol, assist, rigori, presenze)."""
    try:
        data = fd_get(f"/competitions/{code}/scorers",
                      {"season": season, "limit": limit})
    except FootballDataError:
        return []
    return data.get("scorers", []) or []


_FINISHED = ("FINISHED", "AWARDED")


def resolve_result_season(code: str, fallbacks: list[int] | None = None) -> dict:
    """Determina la stagione dei risultati e quella del calendario.

    - `results`: la prima stagione dei fallback con partite giocate (dati reali).
    - `calendar`: la stagione preferita (config.SEASON) usata per le prossime
      partite, se ha partite in calendario; altrimenti coincide con `results`.
    Ritorna anche le liste di partite già scaricate per riuso (niente doppie call).
    """
    fallbacks = fallbacks or config.SEASON_FALLBACKS
    matches_by_season: dict[int, list] = {}
    results_season = None
    for season in dict.fromkeys(fallbacks):
        ms = competition_matches(code, season)
        matches_by_season[season] = ms
        played = [m for m in ms if m.get("status") in _FINISHED]
        if played and results_season is None:
            results_season = season
        # basta appena abbiamo i risultati e il calendario preferito: evita
        # chiamate inutili sul rate limit del piano gratuito
        if results_season is not None and config.SEASON in matches_by_season:
            break
    if results_season is None:  # nessuna stagione con partite giocate
        results_season = fallbacks[0]

    calendar_season = config.SEASON
    if not matches_by_season.get(calendar_season):
        calendar_season = results_season
    return {
        "results": results_season,
        "calendar": calendar_season,
        "matches": matches_by_season,
    }
