# -*- coding: utf-8 -*-
"""Ranking ELO interno, ricostruito dai risultati nel DB.

Niente fonti esterne: l'ELO viene calcolato scorrendo cronologicamente le
partite giocate della competizione (K-factor con moltiplicatore per lo scarto
gol, vantaggio campo nei campionati, campo neutro nelle coppe). Con
`before_date` il rating è quello ALLA VIGILIA della partita: il backtest
resta out-of-sample anche sull'ELO.
"""

from . import config

# cache per (chiave lega, generato, cutoff): il DB cambia solo quando
# l'updater rigenera il file, quindi la coppia identifica lo stato
_CACHE: dict[tuple, dict] = {}
_CACHE_MAX = 512


def _expected(delta: float) -> float:
    """Probabilità attesa di vittoria dal divario ELO."""
    return 1.0 / (1.0 + 10.0 ** (-delta / 400.0))


def league_elo(league: dict, before_date: str | None = None) -> dict[str, float]:
    """Rating ELO per squadra dalla storia dei risultati della competizione.

    - campionati: vantaggio campo ELO_HOME_ADV per la squadra di casa;
    - coppe (tipo="cup"): campo considerato neutro;
    - scarto gol: K moltiplicato per sqrt(|diff|) (una manita pesa più di
      un 1-0, con rendimenti decrescenti).
    """
    meta = league.get("meta") or {}
    key = (meta.get("key"), meta.get("generato"), (before_date or "")[:10])
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    is_cup = meta.get("tipo") == "cup"
    home_adv = 0.0 if is_cup else config.ELO_HOME_ADV
    cutoff = (before_date or "9999")[:10]

    played = [fx for fx in league.get("fixtures", [])
              if fx.get("finished") and fx.get("gh") is not None
              and (fx.get("date") or "")[:10] < cutoff
              and fx["home"]["name"] != "?" and fx["away"]["name"] != "?"]
    played.sort(key=lambda f: f.get("date") or "")

    rating: dict[str, float] = {}
    games: dict[str, int] = {}
    for fx in played:
        h, a = fx["home"]["name"], fx["away"]["name"]
        rh = rating.get(h, config.ELO_START)
        ra = rating.get(a, config.ELO_START)
        gh, ga = fx["gh"], fx["ga"]
        score_h = 1.0 if gh > ga else (0.0 if gh < ga else 0.5)
        exp_h = _expected(rh + home_adv - ra)
        margin = max(abs(gh - ga), 1) ** 0.5          # 1-0→1, 3-0→1.73, 5-0→2.24
        delta = config.ELO_K * margin * (score_h - exp_h)
        rating[h] = rh + delta
        rating[a] = ra - delta
        games[h] = games.get(h, 0) + 1
        games[a] = games.get(a, 0) + 1

    # sotto le 3 gare il rating è quasi solo rumore: shrink verso 1500
    out = {}
    for team, r in rating.items():
        n = games[team]
        w = n / (n + 3.0)
        out[team] = round(config.ELO_START + w * (r - config.ELO_START), 1)

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = out
    return out
