# -*- coding: utf-8 -*-
"""Orchestratore: partita (DB) → profili → meteo → Monte Carlo.

Dati reali gratuiti: risultati/classifiche/calendari da football-data.org,
micro-eventi da FBref/Understat (agganciati dall'updater). Le quote bookmaker
non sono disponibili tra le sorgenti gratuite: la sezione value bets resta
vuota, ma il modello espone comunque le proprie probabilità e quote fair.
Il risultato completo è messo in cache 60 minuti.
"""

import time
from datetime import datetime, timezone

from . import config
from . import db
from .cache import cache_get, cache_set
from .engine import run_simulation
from .stats import match_motivation, team_profile
from .weather import weather_for


def fixture_meta(league: dict, fx: dict) -> dict:
    lg = league["meta"]
    return {
        "fixture_id": fx["fixture_id"], "date": fx["date"],
        "status": fx["status"], "venue": fx.get("venue"), "city": fx.get("city"),
        "league": lg["nome"], "league_key": lg["key"],
        "season": lg["season_label"], "round": fx.get("round"),
        "home": {"id": fx["home"]["id"], "name": fx["home"]["name"],
                 "logo": fx["home"].get("logo")},
        "away": {"id": fx["away"]["id"], "name": fx["away"]["name"],
                 "logo": fx["away"].get("logo")},
        "goals": {"home": fx.get("gh"), "away": fx.get("ga")},
    }


_PROFILE_KEYS = ("name", "played", "gf", "ga", "form", "shots_pg", "sot_pg",
                 "corners_pg", "fouls_pg", "yellow_pg", "red_pg", "save_rate",
                 "keeper", "players_mode", "tournament_games", "recent_sample",
                 "elo", "xg_pg", "xga_pg", "rest_days", "motivation")


def full_analysis(fixture_id: int, players_mode: str = "season") -> dict:
    """Analisi completa del match, cache 60 minuti."""
    cache_key = f"analysis:{fixture_id}:{players_mode}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit

    league_key, fx = db.find_fixture(fixture_id)
    league = db.read_league(league_key)
    is_cup = league["meta"]["tipo"] == "cup"

    meta = fixture_meta(league, fx)
    before = fx.get("date")
    home = team_profile(league, fx["home"]["name"], fx["home"], players_mode,
                        is_cup=is_cup, before_date=before)
    away = team_profile(league, fx["away"]["name"], fx["away"], players_mode,
                        is_cup=is_cup, before_date=before)
    home["motivation"] = away["motivation"] = match_motivation(league, fx)
    meteo = weather_for(meta["city"], meta["date"])

    t0 = time.perf_counter()
    sim = run_simulation(home, away, meteo, is_cup=is_cup,
                         knockout=bool(fx.get("knockout")))
    compute_ms = round((time.perf_counter() - t0) * 1000, 1)

    result = {
        "generato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "compute_ms": compute_ms,
        "meta": meta,
        "meteo": meteo,
        "profili": {
            "home": {k: home[k] for k in _PROFILE_KEYS},
            "away": {k: away[k] for k in _PROFILE_KEYS},
        },
        "sim": sim,
        # quote bookmaker non disponibili tra le sorgenti gratuite
        "odds": {"bookmaker": None, "markets": {}},
        "value_bets": [],
    }
    cache_set(cache_key, result, config.CACHE_TTL)
    return result
