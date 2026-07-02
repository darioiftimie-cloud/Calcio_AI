# -*- coding: utf-8 -*-
"""Database JSON del progetto.

L'updater offline (`updater.py`) scarica i dati reali da football-data.org e
FBref e li salva in `data/`. Gli endpoint serverless leggono solo da qui: a
runtime nessuna chiamata API né scraping (compatibile con il filesystem in sola
lettura di Vercel, dove i file di `data/` vengono inclusi nel deploy).

Struttura:
  data/index.json        → elenco competizioni + stato generazione
  data/<league_key>.json → meta, classifica, calendario/risultati, marcatori,
                            profili micro-evento squadra (da FBref)
"""

import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(_BASE, "..", "..", "data"))


class DBError(Exception):
    """Dato non presente nel database (updater non ancora eseguito)."""


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def write_json(name: str, obj) -> None:
    ensure_dir()
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def read_json(name: str):
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ lettura
def read_index() -> dict:
    idx = read_json("index.json")
    if idx is None:
        raise DBError("database non inizializzato: esegui `python updater.py`")
    return idx


def read_league(key: str) -> dict:
    data = read_json(f"{key}.json")
    if data is None:
        raise DBError(f"competizione '{key}' non presente nel database: "
                      f"esegui `python updater.py`")
    return data


def find_fixture(fixture_id: int) -> tuple[str, dict]:
    """Cerca una partita per id in tutte le competizioni del database."""
    idx = read_index()
    for lg in idx.get("leagues", []):
        data = read_json(f"{lg['key']}.json")
        if not data:
            continue
        for fx in data.get("fixtures", []):
            if fx.get("fixture_id") == fixture_id:
                return lg["key"], fx
    raise DBError(f"partita {fixture_id} non trovata nel database")


def team_micro(league: dict, team_name: str) -> dict | None:
    """Profilo micro-evento (FBref) di una squadra, se disponibile."""
    return (league.get("teams") or {}).get(team_name)


# ------------------------------------------------------------- scrittura
def write_index(obj) -> None:
    write_json("index.json", obj)


def write_league(key: str, obj) -> None:
    write_json(f"{key}.json", obj)
