# -*- coding: utf-8 -*-
"""Motore Monte Carlo vettorizzato (NumPy) — 15.000 simulazioni < 100 ms.

Catena stocastica per ogni iterazione:
  tempo di gara (Gamma, media 1)
    → tiri in porta ~ Poisson(λ_SoT × tempo)
    → gol = Binomiale(SoT, conversione) dove la conversione ingloba il
      save rate del portiere avversario e la precisione meteo (-5% se estremo)
    → parate portiere = SoT subiti − gol subiti (binomiale sul save rate)
    → corner ~ Poisson accoppiata alla dominanza offensiva della singola sim
    → falli ~ Poisson (+10% con meteo estremo) → cartellini binomiali
    → marcatori: quote per giocatore con split minuti 1-70 / 70-90
      (impatto panchina: i super-sub pesano di più negli ultimi 20')
"""

import numpy as np

from . import config

LATE_GOAL_SHARE = 0.28   # quota storica di gol segnati al 70'-90'
SUPER_SUB_LATE_BOOST = 2.2
MAX_SCORE = 7            # oltre 7 gol i risultati finiscono nel bucket "7+"

# Shrinkage empirico-bayes: con un campione di poche partite (es. 4 gare di
# torneo) le medie osservate pesano w = n/(n+K) e vengono tirate verso la
# media di lega. Evita xG assurdi tipo "3.4" da 4 partite contro gironi deboli.
SHRINK_K = 5.0


def _shrink(value: float, played: int, league_avg: float) -> float:
    w = played / (played + SHRINK_K) if played and played > 0 else 0.0
    return league_avg + w * (value - league_avg)


def _dist(arr: np.ndarray, cap: int = 30) -> dict:
    vals = np.clip(arr, 0, cap).astype(np.int64)
    counts = np.bincount(vals, minlength=cap + 1)
    n = len(arr)
    return {int(k): round(100.0 * c / n, 2)
            for k, c in enumerate(counts) if c > 0}


def _over(arr: np.ndarray, line: float) -> float:
    return round(100.0 * float(np.mean(arr > line)), 2)


def _scorer_weights(profile: dict) -> list[dict]:
    """Potenziale realizzativo per giocatore + pesi early/late (panchina)."""
    rows = []
    for p in profile["players"]:
        minutes = max(p["minutes"], 45)
        rate = (p["goals"] + 0.30 * p["assists"] + 0.06 * p["shots_on"]) / minutes
        starter = p["lineups"] >= max(1, p["appearances"] * 0.5)
        is_super_sub = p["id"] in profile["super_sub_ids"]
        exp_min = 82 if starter else (24 if is_super_sub else 10)
        pot = rate * exp_min
        if p["id"] == profile["penalty_taker_id"]:
            pot *= 1.20  # bonus rigorista
        if pot <= 0:
            pot = 0.002  # probabilità residua minima
        late_pot = pot * (SUPER_SUB_LATE_BOOST if is_super_sub else 1.0)
        rows.append({**p, "starter": starter, "super_sub": is_super_sub,
                     "pot": pot, "late_pot": late_pot})
    return rows


def _scorer_table(rows: list[dict], goals: np.ndarray,
                  rng: np.random.Generator) -> list[dict]:
    """Probabilità marcatori calcolate sull'intera distribuzione simulata."""
    if not rows:
        return []
    g_late = rng.binomial(goals, LATE_GOAL_SHARE)
    g_early = goals - g_late

    tot_e = sum(r["pot"] for r in rows)
    tot_l = sum(r["late_pot"] for r in rows)
    out = []
    for r in rows:
        se = r["pot"] / tot_e
        sl = r["late_pot"] / tot_l
        none_e = (1.0 - se) ** g_early
        none_l = (1.0 - sl) ** g_late
        p0 = none_e * none_l
        # P(esattamente 1 gol del giocatore)
        with np.errstate(divide="ignore", invalid="ignore"):
            p1 = (g_early * se * np.where(g_early > 0, (1 - se) ** np.maximum(g_early - 1, 0), 0) * none_l
                  + none_e * g_late * sl * np.where(g_late > 0, (1 - sl) ** np.maximum(g_late - 1, 0), 0))
        anytime = 100.0 * float(1.0 - np.mean(p0))
        brace = max(0.0, 100.0 * float(1.0 - np.mean(p0) - np.mean(p1)))
        late_only = 100.0 * float(1.0 - np.mean(none_l))
        xg_sim = float(np.mean(g_early) * se + np.mean(g_late) * sl)
        out.append({
            "id": r["id"], "name": r["name"], "position": r["position"],
            "photo": r["photo"],
            "goals": r["goals"], "assists": r["assists"],
            "shots": r["shots"], "shots_on": r["shots_on"],
            "minutes": r["minutes"], "rating": r["rating"],
            "starter": r["starter"], "super_sub": r["super_sub"],
            "penalty_taker": False,  # impostato dal chiamante
            "anytime": round(anytime, 2), "brace": round(brace, 2),
            "late_20": round(late_only, 2),
            "xg_sim": round(xg_sim, 3),
            "fair_odds": round(100.0 / anytime, 2) if anytime > 0.05 else None,
        })
    out.sort(key=lambda r: -r["anytime"])
    return out


def run_simulation(home: dict, away: dict, weather: dict,
                   is_cup: bool = False, n: int = config.N_SIMS,
                   seed: int = 20260702) -> dict:
    """Esegue le n simulazioni e ritorna tutte le metriche aggregate."""
    rng = np.random.default_rng(seed)
    L = config.BASELINE["goals"]
    boost_h, boost_a = ((config.HOME_BOOST_CUP, config.AWAY_MALUS_CUP) if is_cup
                        else (config.HOME_BOOST_LEAGUE, config.AWAY_MALUS_LEAGUE))

    # xG dal modello moltiplicativo attacco × difesa avversaria × campo,
    # con shrinkage sulle medie osservate (campioni piccoli → più prudenza)
    gf_h = _shrink(home["gf"], home.get("played") or 0, L)
    ga_h = _shrink(home["ga"], home.get("played") or 0, L)
    gf_a = _shrink(away["gf"], away.get("played") or 0, L)
    ga_a = _shrink(away["ga"], away.get("played") or 0, L)
    xg_h = np.clip(gf_h * ga_a / L * boost_h, 0.15, 3.6)
    xg_a = np.clip(gf_a * ga_h / L * boost_a, 0.15, 3.6)

    precision = weather.get("precisione_tiri", 1.0)
    fouls_mult = weather.get("moltiplicatore_falli", 1.0)

    # Fattore difesa avversaria per i micro-eventi: contro una difesa che
    # concede poco si tira (e si guadagnano corner) meno della propria media,
    # contro una difesa permeabile di più. Prima i tiri/corner della squadra
    # ignoravano completamente chi c'era dall'altra parte.
    def_a = float(np.clip(ga_a / L, 0.70, 1.35))   # difesa ospite → attacco casa
    def_h = float(np.clip(ga_h / L, 0.70, 1.35))   # difesa casa → attacco ospite

    # λ tiri in porta: blend tra SoT osservati (aggiustati per l'avversario)
    # e SoT impliciti (xG / conversione, già opponent-aware)
    conv_base_h = np.clip(1.0 - away["save_rate"], 0.10, 0.50)
    conv_base_a = np.clip(1.0 - home["save_rate"], 0.10, 0.50)
    lam_sot_h = max(0.6 * xg_h / conv_base_h + 0.4 * home["sot_pg"] * def_a, 0.8)
    lam_sot_a = max(0.6 * xg_a / conv_base_a + 0.4 * away["sot_pg"] * def_h, 0.8)
    # conversione effettiva ricalibrata: E[gol] = xG × precisione meteo
    conv_h = np.clip(xg_h / lam_sot_h, 0.05, 0.65) * precision
    conv_a = np.clip(xg_a / lam_sot_a, 0.05, 0.65) * precision

    # Incertezza dei parametri (Monte Carlo gerarchico): la vera forza delle
    # squadre non è nota con esattezza, specie con poche gare. Le n sim sono
    # divise in blocchi; ogni blocco pesca un moltiplicatore d'attacco da una
    # Gamma con varianza ∝ 1/(gare giocate). Due effetti: code dei punteggi
    # più realistiche e intervalli di confidenza veri sugli esiti 1X2.
    n_blocks = 20 if n >= 2000 else max(n // 100, 1)
    per = n // n_blocks
    n = per * n_blocks
    k_h = 4.0 + 1.2 * (home.get("played") or 0)
    k_a = 4.0 + 1.2 * (away.get("played") or 0)
    mult_h = np.repeat(rng.gamma(k_h, 1.0 / k_h, n_blocks), per)
    mult_a = np.repeat(rng.gamma(k_a, 1.0 / k_a, n_blocks), per)

    tempo = rng.gamma(10.0, 0.1, n)

    sot_h = rng.poisson(lam_sot_h * mult_h * tempo)
    sot_a = rng.poisson(lam_sot_a * mult_a * tempo)
    goals_h = rng.binomial(sot_h, conv_h)
    goals_a = rng.binomial(sot_a, conv_a)
    saves_h = sot_a - goals_a       # parate del portiere di casa
    saves_a = sot_h - goals_h

    # tiri totali = tiri in porta + tiri fuori/bloccati (anch'essi
    # aggiustati per la difesa avversaria)
    off_target_h = max(home["shots_pg"] - home["sot_pg"], 2.0) * def_a
    off_target_a = max(away["shots_pg"] - away["sot_pg"], 2.0) * def_h
    shots_h = sot_h + rng.poisson(off_target_h * tempo)
    shots_a = sot_a + rng.poisson(off_target_a * tempo)

    # corner accoppiati alla dominanza offensiva della singola simulazione
    dom_h = np.clip(0.65 + 0.35 * sot_h / np.maximum(lam_sot_h * tempo, 0.5), 0.5, 1.7)
    dom_a = np.clip(0.65 + 0.35 * sot_a / np.maximum(lam_sot_a * tempo, 0.5), 0.5, 1.7)
    corners_h = rng.poisson(home["corners_pg"] * (def_a ** 0.5) * (0.5 + 0.5 * tempo) * dom_h)
    corners_a = rng.poisson(away["corners_pg"] * (def_h ** 0.5) * (0.5 + 0.5 * tempo) * dom_a)
    corners_t = corners_h + corners_a

    # falli e cartellini (meteo estremo: +10% falli)
    fouls_h = rng.poisson(home["fouls_pg"] * fouls_mult * (0.8 + 0.2 * tempo))
    fouls_a = rng.poisson(away["fouls_pg"] * fouls_mult * (0.8 + 0.2 * tempo))
    py_h = np.clip(home["yellow_pg"] / max(home["fouls_pg"], 4.0), 0.04, 0.45)
    py_a = np.clip(away["yellow_pg"] / max(away["fouls_pg"], 4.0), 0.04, 0.45)
    yellows_h = rng.binomial(fouls_h, py_h)
    yellows_a = rng.binomial(fouls_a, py_a)
    reds_h = (rng.random(n) < np.clip(home["red_pg"], 0.0, 0.30)).astype(np.int64)
    reds_a = (rng.random(n) < np.clip(away["red_pg"], 0.0, 0.30)).astype(np.int64)
    cards_t = yellows_h + yellows_a + reds_h + reds_a

    # matrice risultati esatti
    hm = np.minimum(goals_h, MAX_SCORE)
    am = np.minimum(goals_a, MAX_SCORE)
    matrix = np.zeros((MAX_SCORE + 1, MAX_SCORE + 1), dtype=np.int64)
    np.add.at(matrix, (hm, am), 1)
    matrix_pct = np.round(100.0 * matrix / n, 2)
    labels = [str(i) for i in range(MAX_SCORE)] + [f"{MAX_SCORE}+"]
    flat = [(f"{labels[i]}-{labels[j]}", float(matrix_pct[i, j]))
            for i in range(MAX_SCORE + 1) for j in range(MAX_SCORE + 1)]
    top_scores = sorted(flat, key=lambda x: -x[1])[:10]

    p1 = 100.0 * float(np.mean(goals_h > goals_a))
    p2 = 100.0 * float(np.mean(goals_a > goals_h))
    px = round(100.0 - p1 - p2, 2)
    goals_t = goals_h + goals_a

    # intervalli di confidenza 80% (10°-90° percentile tra i blocchi, che
    # differiscono per il moltiplicatore di forza pescato)
    blk_1 = (goals_h > goals_a).reshape(n_blocks, per).mean(axis=1) * 100
    blk_2 = (goals_a > goals_h).reshape(n_blocks, per).mean(axis=1) * 100
    blk_x = 100.0 - blk_1 - blk_2

    def _ci(blocks):
        return [round(float(np.percentile(blocks, 10)), 1),
                round(float(np.percentile(blocks, 90)), 1)]

    outcomes_ci = {"1": _ci(blk_1), "X": _ci(blk_x), "2": _ci(blk_2)}
    width = ((outcomes_ci["1"][1] - outcomes_ci["1"][0])
             + (outcomes_ci["2"][1] - outcomes_ci["2"][0])) / 2.0
    reliability = {"livello": ("alta" if width < 9.0 else
                               "media" if width < 18.0 else "bassa"),
                   "larghezza_intervallo": round(width, 1)}

    # marcatori (con impatto panchina 70'-90')
    sc_home = _scorer_table(_scorer_weights(home), goals_h, rng)
    sc_away = _scorer_table(_scorer_weights(away), goals_a, rng)
    for table, prof in ((sc_home, home), (sc_away, away)):
        for r in table:
            r["penalty_taker"] = (r["id"] == prof["penalty_taker_id"])

    return {
        "n_sims": n,
        "xg": {"home": round(float(xg_h), 2), "away": round(float(xg_a), 2)},
        "outcomes": {
            "1": round(p1, 2), "X": px, "2": round(p2, 2),
            "1X": round(p1 + px, 2), "X2": round(px + p2, 2),
            "12": round(p1 + p2, 2),
        },
        "outcomes_ci": outcomes_ci,
        "reliability": reliability,
        "btts": round(100.0 * float(np.mean((goals_h > 0) & (goals_a > 0))), 2),
        "over": {f"{l:.1f}": _over(goals_t, l) for l in (0.5, 1.5, 2.5, 3.5, 4.5)},
        "goals_dist": _dist(goals_t, 12),
        "score_matrix": matrix_pct.tolist(),
        "top_scores": top_scores,
        "corners": {
            "mean_home": round(float(np.mean(corners_h)), 2),
            "mean_away": round(float(np.mean(corners_a)), 2),
            "mean_total": round(float(np.mean(corners_t)), 2),
            "dist_total": _dist(corners_t, 26),
            "lines": {f"{l:.1f}": _over(corners_t, l)
                      for l in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
        },
        "shots": {
            "mean_home": round(float(np.mean(shots_h)), 2),
            "mean_away": round(float(np.mean(shots_a)), 2),
            "sot_home": round(float(np.mean(sot_h)), 2),
            "sot_away": round(float(np.mean(sot_a)), 2),
            "sot_dist_home": _dist(sot_h, 15),
            "sot_dist_away": _dist(sot_a, 15),
        },
        "saves": {
            "mean_home": round(float(np.mean(saves_h)), 2),
            "mean_away": round(float(np.mean(saves_a)), 2),
            "dist_home": _dist(saves_h, 14),
            "dist_away": _dist(saves_a, 14),
        },
        "fouls": {
            "mean_home": round(float(np.mean(fouls_h)), 2),
            "mean_away": round(float(np.mean(fouls_a)), 2),
        },
        "cards": {
            "yellows_home": round(float(np.mean(yellows_h)), 2),
            "yellows_away": round(float(np.mean(yellows_a)), 2),
            "red_prob_home": round(100.0 * float(np.mean(reds_h)), 2),
            "red_prob_away": round(100.0 * float(np.mean(reds_a)), 2),
            "mean_total": round(float(np.mean(cards_t)), 2),
            "dist_total": _dist(cards_t, 14),
            "lines": {f"{l:.1f}": _over(cards_t, l)
                      for l in (2.5, 3.5, 4.5, 5.5, 6.5)},
        },
        "scorers": {"home": sc_home, "away": sc_away},
    }


def value_bets(sim: dict, odds_markets: dict, min_edge: float = 2.0) -> list[dict]:
    """Confronta le probabilità del modello con le quote dei bookmaker.
    Value bet = probabilità modello − probabilità implicita (1/quota) > soglia."""
    model_probs = {
        "1": sim["outcomes"]["1"], "X": sim["outcomes"]["X"],
        "2": sim["outcomes"]["2"],
        "Over 2.5": sim["over"]["2.5"],
        "Under 2.5": round(100.0 - sim["over"]["2.5"], 2),
        "BTTS Sì": sim["btts"], "BTTS No": round(100.0 - sim["btts"], 2),
    }
    out = []
    for market, odd in odds_markets.items():
        p_model = model_probs.get(market)
        if p_model is None or not odd or odd <= 1.01:
            continue
        implied = 100.0 / odd
        edge = p_model - implied
        out.append({
            "mercato": market, "quota": odd,
            "prob_modello": round(p_model, 2),
            "prob_implicita": round(implied, 2),
            "edge": round(edge, 2),
            "value": edge >= min_edge,
        })
    out.sort(key=lambda r: -r["edge"])
    return out
