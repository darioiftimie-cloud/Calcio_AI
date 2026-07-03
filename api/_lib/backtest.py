# -*- coding: utf-8 -*-
"""Backtest del modello: "rigioca" le partite già disputate usando SOLO le
informazioni disponibili prima di ciascuna (profili cumulativi con
before_date, niente senno di poi) e confronta i pronostici con i risultati.

Metriche:
  - esatto_1x2_pct : % di partite in cui l'esito più probabile era quello vero
  - brier          : Brier score sulle probabilità 1X2 (0 = perfetto);
                     da confrontare con brier_caso (= 0.667, tirare a caso)
  - mae_gol_totali : errore medio assoluto sui gol totali attesi (xG somma)

Il meteo è neutro (niente chiamate HTTP: il backtest resta veloce) e le
simulazioni sono 2.000 a partita, sufficienti per stimare l'1X2.
"""

from . import db
from .cache import cache_get, cache_set
from .engine import run_simulation
from .stats import team_profile

_NEUTRAL_WEATHER = {"disponibile": False}
MIN_PRIOR_GAMES = 2      # sotto questo campione pre-partita il pronostico è aria
N_SIMS_BACKTEST = 2000


def league_accuracy(league_key: str, max_matches: int = 120) -> dict:
    cache_key = f"accuracy:{league_key}:{max_matches}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit

    league = db.read_league(league_key)
    is_cup = league["meta"]["tipo"] == "cup"
    fxs = [f for f in league.get("fixtures", [])
           if f.get("finished") and f.get("gh") is not None
           and f["home"]["name"] != "?" and f["away"]["name"] != "?"]
    fxs.sort(key=lambda f: f.get("date") or "")
    fxs = fxs[-max_matches:]

    rows, briers, briers_base, abs_err = [], [], [], []
    hits = skipped = 0
    for fx in fxs:
        before = fx.get("date")
        # is_cup=True forza il profilo cumulativo pre-partita anche nei
        # campionati: il backtest è out-of-sample ovunque
        h = team_profile(league, fx["home"]["name"], fx["home"],
                         is_cup=True, before_date=before)
        a = team_profile(league, fx["away"]["name"], fx["away"],
                         is_cup=True, before_date=before)
        if (h["tournament_games"] < MIN_PRIOR_GAMES
                or a["tournament_games"] < MIN_PRIOR_GAMES):
            skipped += 1
            continue

        sim = run_simulation(h, a, _NEUTRAL_WEATHER, is_cup=is_cup,
                             n=N_SIMS_BACKTEST)
        o = sim["outcomes"]
        gh, ga = fx["gh"], fx["ga"]
        actual = "1" if gh > ga else ("2" if ga > gh else "X")
        pred = max(("1", "X", "2"), key=lambda k: o[k])
        ok = pred == actual
        hits += ok

        p = {k: o[k] / 100.0 for k in ("1", "X", "2")}
        briers.append(sum((p[k] - (1.0 if k == actual else 0.0)) ** 2
                          for k in ("1", "X", "2")))
        briers_base.append(sum((1.0 / 3 - (1.0 if k == actual else 0.0)) ** 2
                               for k in ("1", "X", "2")))
        abs_err.append(abs(sim["xg"]["home"] + sim["xg"]["away"] - (gh + ga)))
        rows.append({
            "date": fx.get("date"), "round": fx.get("round"),
            "home": fx["home"]["name"], "away": fx["away"]["name"],
            "reale": f"{gh}-{ga}", "esito_reale": actual,
            "pronostico": pred, "corretto": ok,
            "prob": {"1": o["1"], "X": o["X"], "2": o["2"]},
            "xg": sim["xg"],
        })

    n_ok = len(rows)
    result = {
        "league": league_key,
        "partite_valutate": n_ok,
        "saltate_poco_campione": skipped,
        "esatto_1x2_pct": round(100.0 * hits / n_ok, 1) if n_ok else None,
        "brier": round(sum(briers) / n_ok, 4) if n_ok else None,
        "brier_caso": round(sum(briers_base) / n_ok, 4) if n_ok else None,
        "mae_gol_totali": round(sum(abs_err) / n_ok, 2) if n_ok else None,
        "matches": rows[::-1][:40],   # le più recenti prima
    }
    cache_set(cache_key, result, 3600)
    return result
