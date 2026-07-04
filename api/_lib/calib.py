# -*- coding: utf-8 -*-
"""Calibrazione statistica per competizione, stimata dai dati del DB.

1. Dispersione (α della Binomiale Negativa, Var = μ + α·μ²)
   Il conteggio reale di tiri/falli/corner in una partita varia più di una
   Poisson (overdispersion): l'α per ogni statistica viene stimato col
   metodo dei momenti sulle gare-squadra dei boxscore ESPN in cache.

2. ρ di Dixon-Coles (dipendenza sui punteggi bassi)
   La Poisson indipendente sbaglia sistematicamente 0-0, 1-0, 0-1 e 1-1.
   Il fattore τ di Dixon-Coles corregge quelle quattro celle; ρ è stimato
   per lega via massima verosimiglianza (grid search) sui risultati reali,
   con λ/μ per partita dal modello moltiplicativo attacco×difesa (stesse
   formule del motore). τ è auto-normalizzato: Σ τ·P = 1 per ogni ρ.

I risultati sono in cache di modulo: si ricalcolano solo quando cambia il
numero di eventi/partite nel DB della lega.
"""

import math

from . import config
from .espn import _xg_proxy

_cache: dict = {}


def _league_goals(league: dict) -> float | None:
    """Media gol per SQUADRA per gara della competizione. È la normalizzante
    L del modello moltiplicativo gf·ga/L: usare la media globale (1.40) al
    posto di quella di lega gonfia sistematicamente le leghe da tanti gol
    (Bundesliga ~1.75) e comprime quelle avare."""
    tot = n = 0
    for fx in league.get("fixtures", []):
        if fx.get("finished") and fx.get("gh") is not None:
            tot += fx["gh"] + fx["ga"]
            n += 1
    return round(tot / (2 * n), 3) if n >= 20 else None


def _xg_scale(league: dict) -> float:
    """Fattore che riallinea l'xG proxy shot-based alla media REALE dei gol
    della competizione: rende il proxy non distorto prima del blend 50/50
    (i coefficienti di letteratura non conoscono il contesto della lega)."""
    events = (league.get("espn") or {}).get("events") or {}
    goals = xg = 0.0
    rows = 0
    for ev in events.values():
        for st in (ev.get("teams") or {}).values():
            xg += _xg_proxy(st)
            goals += float(st.get("conceded") or 0.0)   # gol dell'avversaria
            rows += 1
    if rows < 40 or xg <= 0:
        return 1.0
    return round(min(max(goals / xg, 0.75), 1.30), 3)


def _dispersion(league: dict) -> dict:
    """α per statistica dal secondo momento delle gare-squadra ESPN."""
    events = (league.get("espn") or {}).get("events") or {}
    keys = ("sot", "shots", "fouls", "corners")
    vals: dict[str, list[float]] = {k: [] for k in keys}
    for ev in events.values():
        for st in (ev.get("teams") or {}).values():
            for k in keys:
                v = st.get(k)
                if v is not None:
                    vals[k].append(float(v))
    out = {}
    for k in keys:
        xs = vals[k]
        if len(xs) < 40:                      # campione scarso → fallback
            out[k] = config.NB_ALPHA_DEFAULT[k]
            continue
        n = len(xs)
        m = sum(xs) / n
        var = sum((x - m) ** 2 for x in xs) / (n - 1)
        alpha = (var - m) / (m * m) if m > 0 else 0.0
        out[k] = round(min(max(alpha, 0.0), config.NB_ALPHA_MAX), 3)
    return out


def _team_rates(league: dict) -> tuple[dict, float]:
    """Gol fatti/subiti per gara di ogni squadra (dalla classifica) e media
    di lega L. Servono per i λ/μ per-partita del fit di Dixon-Coles.
    Con lo STESSO shrinkage n/(n+5) del motore: se il baseline del fit fosse
    più estremo di quello simulato, il ρ assorbirebbe la differenza e la
    correzione risulterebbe gonfiata."""
    raw = {}
    tot_gf = tot_n = 0
    for g in league.get("standings", []):
        for r in g.get("rows", []):
            n = int(r.get("played") or 0)
            if n > 0:
                raw[r["team"]] = (r["gf"] / n, r["ga"] / n, n)
                tot_gf += r["gf"]
                tot_n += n
    L = max((tot_gf / tot_n) if tot_n else config.BASELINE["goals"], 0.5)
    rates = {}
    for team, (gf, ga, n) in raw.items():
        wgt = n / (n + 5.0)
        rates[team] = (L + wgt * (gf - L), L + wgt * (ga - L))
    return rates, L


def _tau_log(gh: int, ga: int, lam: float, mu: float, rho: float) -> float:
    """log τ(x,y) di Dixon-Coles; 0 fuori dalle quattro celle basse."""
    if gh == 0 and ga == 0:
        t = 1.0 - lam * mu * rho
    elif gh == 1 and ga == 0:
        t = 1.0 + mu * rho
    elif gh == 0 and ga == 1:
        t = 1.0 + lam * rho
    elif gh == 1 and ga == 1:
        t = 1.0 - rho
    else:
        return 0.0
    return math.log(max(t, 1e-6))


def _dixon_coles_rho(league: dict, is_cup: bool) -> float:
    """ρ di massima verosimiglianza (grid search, passo 0.005)."""
    rates, L = _team_rates(league)
    boost_h, boost_a = ((config.HOME_BOOST_CUP, config.AWAY_MALUS_CUP) if is_cup
                        else (config.HOME_BOOST_LEAGUE, config.AWAY_MALUS_LEAGUE))
    matches = []
    for fx in league.get("fixtures", []):
        if not (fx.get("finished") and fx.get("gh") is not None):
            continue
        gh, ga = int(fx["gh"]), int(fx["ga"])
        gf_h, ga_h = rates.get(fx["home"]["name"], (L, L))
        gf_a, ga_a = rates.get(fx["away"]["name"], (L, L))
        lam = min(max(gf_h * ga_a / L * boost_h, 0.15), 3.6)
        mu = min(max(gf_a * ga_h / L * boost_a, 0.15), 3.6)
        matches.append((gh, ga, lam, mu))
    if len(matches) < 60:                     # campione scarso → default
        return config.DC_RHO_DEFAULT

    lo, hi = config.DC_RHO_RANGE
    best_rho, best_ll = config.DC_RHO_DEFAULT, -math.inf
    steps = int(round((hi - lo) / 0.005))
    for i in range(steps + 1):
        rho = lo + 0.005 * i
        ll = sum(_tau_log(gh, ga, lam, mu, rho)
                 for gh, ga, lam, mu in matches)
        if ll > best_ll:
            best_ll, best_rho = ll, rho
    return round(best_rho, 3)


def league_calibration(league: dict) -> dict:
    """{dispersion: {stat: α}, rho: float} per la competizione, con cache."""
    meta = league.get("meta") or {}
    n_ev = len((league.get("espn") or {}).get("events") or {})
    n_fx = sum(1 for f in league.get("fixtures", []) if f.get("finished"))
    key = (meta.get("nome"), n_ev, n_fx)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    is_cup = meta.get("tipo") == "cup"
    result = {"dispersion": _dispersion(league),
              "rho": _dixon_coles_rho(league, is_cup),
              "league_goals": _league_goals(league),
              "xg_scale": _xg_scale(league)}
    _cache.clear()          # una entry per lega basta (evita crescita infinita)
    _cache[key] = result
    return result
