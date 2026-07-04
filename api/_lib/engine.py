# -*- coding: utf-8 -*-
"""Motore Monte Carlo vettorizzato (NumPy) — 15.000 simulazioni < 100 ms.

Catena stocastica per ogni iterazione:
  ritmo-gara condiviso (Gamma, media 1, varianza bassa)
    → tiri in porta ~ Binomiale Negativa(μ = λ_SoT × ritmo, α per lega)
      (overdispersion reale dei conteggi: Var = μ + α·μ², α stimato dai
       boxscore della competizione — calib.py)
    → gol = Binomiale(SoT, conversione) dove la conversione ingloba il
      save rate del portiere avversario e la precisione meteo (-5% se estremo)
    → game state DINAMICO all'intervallo: la reazione del 2° tempo scala
      linearmente con i minuti trascorsi dal gol del divario (campionati
      per-sim) e col delta ELO (il favorito che insegue spinge di più,
      lo sfavorito in vantaggio si chiude di più)
    → parate portiere = SoT subiti − gol subiti
    → corner ~ NB accoppiata ai tiri della singola sim
    → falli ~ NB (+10% con meteo estremo) → cartellini binomiali
    → marcatori: quote per giocatore con split minuti 1-70 / 70-90
  Dixon-Coles in coda: reweighting per-sim col fattore τ (ρ per lega) che
  corregge la dipendenza sui punteggi bassi (0-0, 1-0, 0-1, 1-1); tutte le
  metriche sono medie pesate, quindi restano coerenti tra loro.
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


def _wmean(x, w: np.ndarray | None = None) -> float:
    """Media (pesata se w è dato): con Dixon-Coles ogni sim ha un peso τ."""
    return float(np.average(x, weights=w))


def _dist(arr: np.ndarray, cap: int = 30, w: np.ndarray | None = None) -> dict:
    vals = np.clip(arr, 0, cap).astype(np.int64)
    weights = w if w is not None else np.ones(len(arr))
    counts = np.bincount(vals, weights=weights, minlength=cap + 1)
    tot = float(weights.sum())
    return {int(k): round(100.0 * c / tot, 2)
            for k, c in enumerate(counts) if c > 0}


def _over(arr: np.ndarray, line: float, w: np.ndarray | None = None) -> float:
    return round(100.0 * _wmean(arr > line, w), 2)


def _nb(rng: np.random.Generator, mu, alpha: float) -> np.ndarray:
    """Binomiale Negativa NB2: media μ, Var = μ + α·μ².
    Con α→0 degenera nella Poisson (equidispersione)."""
    if alpha <= 1e-9:
        return rng.poisson(mu)
    r = 1.0 / alpha
    p = r / (r + np.maximum(np.asarray(mu, dtype=np.float64), 1e-12))
    return rng.negative_binomial(r, p)


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
                  rng: np.random.Generator,
                  w: np.ndarray | None = None) -> list[dict]:
    """Probabilità marcatori calcolate sull'intera distribuzione simulata
    (medie pesate Dixon-Coles, coerenti col resto delle metriche)."""
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
        anytime = 100.0 * (1.0 - _wmean(p0, w))
        brace = max(0.0, 100.0 * (1.0 - _wmean(p0, w) - _wmean(p1, w)))
        late_only = 100.0 * (1.0 - _wmean(none_l, w))
        xg_sim = _wmean(g_early, w) * se + _wmean(g_late, w) * sl
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
    calib = home.get("calib") or {}
    # Normalizzante del modello moltiplicativo gf·ga/L: è la media gol per
    # squadra DELLA competizione (calib.py). La media globale 1.40 resta il
    # fallback: usarla ovunque gonfiava le leghe da tanti gol (Bundesliga
    # ~1.75) e comprimeva i tornei avari — il grosso del bias sui gol totali.
    L = float(calib.get("league_goals") or config.BASELINE["goals"])
    boost_h, boost_a = ((config.HOME_BOOST_CUP, config.AWAY_MALUS_CUP) if is_cup
                        else (config.HOME_BOOST_LEAGUE, config.AWAY_MALUS_LEAGUE))

    # xG dal modello moltiplicativo attacco × difesa avversaria × campo,
    # con shrinkage sulle medie osservate (campioni piccoli → più prudenza).
    # Le medie gf/ga arrivano già come blend gol reali + xG shot-based con
    # time-decay (stats.py): qui si aggiunge il peso del Ranking ELO.
    gf_h = _shrink(home["gf"], home.get("played") or 0, L)
    ga_h = _shrink(home["ga"], home.get("played") or 0, L)
    gf_a = _shrink(away["gf"], away.get("played") or 0, L)
    ga_a = _shrink(away["ga"], away.get("played") or 0, L)

    # Poisson ponderato ELO: il divario di rating (ricostruito dai risultati,
    # senza vantaggio campo: quello è già in boost_h/a) modula gli xG con
    # esponente ELO_ALPHA. A parità di medie, chi ha battuto avversarie più
    # forti pesa di più. E = prob. attesa di vittoria dal divario ELO.
    elo_f_h = elo_f_a = 1.0
    if home.get("elo") and away.get("elo"):
        exp_h = 1.0 / (1.0 + 10.0 ** (-(home["elo"] - away["elo"]) / 400.0))
        elo_f_h = (max(exp_h, 0.02) / 0.5) ** config.ELO_ALPHA
        elo_f_a = (max(1.0 - exp_h, 0.02) / 0.5) ** config.ELO_ALPHA

    xg_h = np.clip(gf_h * ga_a / L * boost_h * elo_f_h, 0.15, 3.6)
    xg_a = np.clip(gf_a * ga_h / L * boost_a * elo_f_a, 0.15, 3.6)

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
    # con pochi n servono comunque più blocchi, o l'intervallo di confidenza
    # collassa a zero e il badge affidabilità mentirebbe ("alta" con 100 sim)
    n_blocks = 20 if n >= 2000 else max(min(n // 10, 20), 1)
    per = n // n_blocks
    n = per * n_blocks
    k_h = 4.0 + 1.2 * (home.get("played") or 0)
    k_a = 4.0 + 1.2 * (away.get("played") or 0)
    mult_h = np.repeat(rng.gamma(k_h, 1.0 / k_h, n_blocks), per)
    mult_a = np.repeat(rng.gamma(k_a, 1.0 / k_a, n_blocks), per)

    # Motivation Index (fase calda del torneo / volata di campionato):
    # amplifica produzione offensiva e agonismo di entrambe le squadre
    mot_h = float(home.get("motivation") or 1.0)
    mot_a = float(away.get("motivation") or 1.0)
    lam_sot_h *= 1.0 + config.MOTIVATION_SOT * (mot_h - 1.0)
    lam_sot_a *= 1.0 + config.MOTIVATION_SOT * (mot_a - 1.0)

    # Indice di Riposo: ≤3 giorni dall'ultima gara → gambe pesanti nella
    # ripresa (precisione giù, falli su)
    rest_h, rest_a = home.get("rest_days"), away.get("rest_days")
    tired_h = rest_h is not None and rest_h <= config.REST_SHORT_DAYS
    tired_a = rest_a is not None and rest_a <= config.REST_SHORT_DAYS

    # Ritmo-gara condiviso: correla i volumi delle due squadre (partite
    # aperte/bloccate insieme). Varianza bassa (1/TEMPO_K): il grosso della
    # dispersione marginale lo mette la Binomiale Negativa qui sotto.
    tempo = rng.gamma(config.TEMPO_K, 1.0 / config.TEMPO_K, n)

    # Binomiale Negativa al posto della Poisson (overdispersion reale).
    # L'α empirico per competizione (calib.py) misura la dispersione TOTALE
    # marginale: da esso si sottraggono le componenti già simulate — ritmo
    # condiviso (1/TEMPO_K) e moltiplicatore gerarchico dei blocchi (1/k) —
    # per non contare due volte la stessa varianza. Il residuo entra nelle
    # estrazioni; diviso (s1²+s2²) perché la somma di due NB per-tempo
    # disperde meno di una NB unica a pari α.
    s1, s2 = config.H1_SHARE, 1.0 - config.H1_SHARE
    A = {**config.NB_ALPHA_DEFAULT, **(calib.get("dispersion") or {})}
    hs = s1 * s1 + s2 * s2
    a_sot_h = max(A["sot"] - 1.0 / config.TEMPO_K - 1.0 / k_h, 0.0) / hs
    a_sot_a = max(A["sot"] - 1.0 / config.TEMPO_K - 1.0 / k_a, 0.0) / hs
    a_off = max(A["shots"] - 1.0 / config.TEMPO_K, 0.0) / hs
    a_fouls = max(A["fouls"] - 0.02, 0.0) / hs   # 0.02 ≈ contributo di dom^0.45
    # i corner sono estratti condizionatamente ai tiri della sim, quindi ne
    # ereditano già l'intera dispersione: resta solo l'eccesso specifico
    a_corn = max(A["corners"] - A["shots"], 0.0)

    # ---------------- 1° TEMPO (quota H1_SHARE del volume di gioco) -------
    sot_h1 = _nb(rng, lam_sot_h * mult_h * tempo * s1, a_sot_h)
    sot_a1 = _nb(rng, lam_sot_a * mult_a * tempo * s1, a_sot_a)
    goals_h1 = rng.binomial(sot_h1, conv_h)
    goals_a1 = rng.binomial(sot_a1, conv_a)

    # ---------------- GAME STATE DINAMICO all'intervallo ------------------
    # Chi insegue alza i giri, chi conduce si abbassa — ma l'intensità non è
    # più una percentuale fissa: scala linearmente con (a) i minuti trascorsi
    # dal gol che ha creato il divario e (b) il delta ELO. Il minuto del gol
    # è campionato per-sim da una triangolare crescente (i gol arrivano più
    # spesso a fine tempo); l'effetto, valutato a metà ripresa (67.5'), è
    # normalizzato a media 1 per non spostare la calibrazione complessiva.
    diff = goals_h1 - goals_a1
    ahead_h, behind_h = diff > 0, diff < 0        # per l'ospite è speculare
    t_goal = rng.triangular(1.0, 45.0, 45.0, n)
    time_f = np.where(diff != 0, (67.5 - t_goal) / (67.5 - 91.0 / 3.0), 1.0)

    d_elo = 0.0
    if home.get("elo") and away.get("elo"):
        d_elo = (home["elo"] - away["elo"]) / 400.0
    lo_c, hi_c = config.GS_DYN_CLIP
    # il favorito che insegue spinge di più; lo sfavorito che conduce si
    # chiude di più (catenaccio), il dominatore in vantaggio meno
    push_elo_h = min(max(1.0 + config.GS_ELO_SLOPE * d_elo, lo_c), hi_c)
    push_elo_a = min(max(1.0 - config.GS_ELO_SLOPE * d_elo, lo_c), hi_c)
    shut_elo_h, shut_elo_a = push_elo_a, push_elo_h
    dyn_push_h, dyn_push_a = time_f * push_elo_h, time_f * push_elo_a
    dyn_shut_h, dyn_shut_a = time_f * shut_elo_h, time_f * shut_elo_a

    push_h = np.clip(1.0 + config.GS_PUSH_BEHIND * dyn_push_h * behind_h
                     - config.GS_SHUT_AHEAD * dyn_shut_h * ahead_h, 0.5, 1.6)
    push_a = np.clip(1.0 + config.GS_PUSH_BEHIND * dyn_push_a * ahead_h
                     - config.GS_SHUT_AHEAD * dyn_shut_a * behind_h, 0.5, 1.6)
    # anche il malus di conversione di chi insegue segue la stessa dinamica
    conv2_h = conv_h * (1.0 - (1.0 - config.GS_CONV_BEHIND) * dyn_push_h * behind_h) \
        * (config.REST_CONV_MALUS if tired_h else 1.0)
    conv2_a = conv_a * (1.0 - (1.0 - config.GS_CONV_BEHIND) * dyn_push_a * ahead_h) \
        * (config.REST_CONV_MALUS if tired_a else 1.0)

    # ---------------- 2° TEMPO (parametri adattati allo stato) ------------
    sot_h2 = _nb(rng, lam_sot_h * mult_h * tempo * s2 * push_h, a_sot_h)
    sot_a2 = _nb(rng, lam_sot_a * mult_a * tempo * s2 * push_a, a_sot_a)
    goals_h2 = rng.binomial(sot_h2, np.clip(conv2_h, 0.02, 0.65))
    goals_a2 = rng.binomial(sot_a2, np.clip(conv2_a, 0.02, 0.65))

    sot_h, sot_a = sot_h1 + sot_h2, sot_a1 + sot_a2
    goals_h, goals_a = goals_h1 + goals_h2, goals_a1 + goals_a2
    saves_h = sot_a - goals_a       # parate del portiere di casa
    saves_a = sot_h - goals_h

    # tiri totali = tiri in porta + tiri fuori/bloccati (aggiustati per la
    # difesa avversaria; nel 2° tempo seguono la spinta del game state)
    off_target_h = max(home["shots_pg"] - home["sot_pg"], 2.0) * def_a
    off_target_a = max(away["shots_pg"] - away["sot_pg"], 2.0) * def_h
    shots_h = sot_h + _nb(rng, off_target_h * tempo * s1, a_off) \
        + _nb(rng, off_target_h * tempo * s2 * push_h, a_off)
    shots_a = sot_a + _nb(rng, off_target_a * tempo * s1, a_off) \
        + _nb(rng, off_target_a * tempo * s2 * push_a, a_off)

    # dominanza offensiva della singola simulazione (volume di tiro sopra o
    # sotto l'atteso): guida corner propri e falli commessi dall'avversario
    dom_h = np.clip(0.65 + 0.35 * sot_h / np.maximum(lam_sot_h * tempo, 0.5), 0.5, 1.7)
    dom_a = np.clip(0.65 + 0.35 * sot_a / np.maximum(lam_sot_a * tempo, 0.5), 0.5, 1.7)

    # Correlazione corner ↔ tiri: i corner nascono dal tasso REALE corner-per-
    # tiro della squadra applicato ai tiri totali DELLA SINGOLA simulazione.
    # Se in una sim la squadra tira tanto, guadagna proporzionalmente più
    # corner; la media resta ancorata a corners_pg osservato.
    cps_h = home["corners_pg"] / max(home["shots_pg"], 6.0)
    cps_a = away["corners_pg"] / max(away["shots_pg"], 6.0)
    corners_h = _nb(rng, cps_h * shots_h, a_corn)
    corners_a = _nb(rng, cps_a * shots_a, a_corn)
    corners_t = corners_h + corners_a

    # Correlazione falli ↔ baricentro avversario: quando l'avversaria domina
    # (dom alto = baricentro schiacciato nella propria metà campo) si commettono
    # più falli per fermarla; meteo estremo aggiunge il suo +10%. Nel 2° tempo
    # pesano game state (chi insegue/conduce falla di più), stanchezza da
    # riposo corto e motivazione (agonismo della fase calda).
    fbase_h = home["fouls_pg"] * fouls_mult * (0.8 + 0.2 * tempo) * dom_a ** 0.45 * mot_h
    fbase_a = away["fouls_pg"] * fouls_mult * (0.8 + 0.2 * tempo) * dom_h ** 0.45 * mot_a
    state_f_h = 1.0 + config.GS_FOULS_BEHIND * dyn_push_h * behind_h \
        + config.GS_FOULS_AHEAD * dyn_shut_h * ahead_h
    state_f_a = 1.0 + config.GS_FOULS_BEHIND * dyn_push_a * ahead_h \
        + config.GS_FOULS_AHEAD * dyn_shut_a * behind_h
    fouls_h = _nb(rng, fbase_h * s1, a_fouls) + _nb(
        rng, fbase_h * s2 * state_f_h * (config.REST_FOULS_MALUS if tired_h else 1.0), a_fouls)
    fouls_a = _nb(rng, fbase_a * s1, a_fouls) + _nb(
        rng, fbase_a * s2 * state_f_a * (config.REST_FOULS_MALUS if tired_a else 1.0), a_fouls)
    py_h = np.clip(home["yellow_pg"] / max(home["fouls_pg"], 4.0), 0.04, 0.45)
    py_a = np.clip(away["yellow_pg"] / max(away["fouls_pg"], 4.0), 0.04, 0.45)
    yellows_h = rng.binomial(fouls_h, py_h)
    yellows_a = rng.binomial(fouls_a, py_a)
    reds_h = (rng.random(n) < np.clip(home["red_pg"], 0.0, 0.30)).astype(np.int64)
    reds_a = (rng.random(n) < np.clip(away["red_pg"], 0.0, 0.30)).astype(np.int64)
    cards_t = yellows_h + yellows_a + reds_h + reds_a

    # ---------------- CORREZIONE DIXON-COLES ------------------------------
    # La Poisson/NB indipendente sbaglia sistematicamente la dipendenza sui
    # punteggi bassi. Reweighting per-simulazione col fattore τ(x,y; λ, μ, ρ)
    # — ρ stimato per lega in calib.py. Da qui in poi OGNI metrica è una
    # media pesata: 1X2, matrice, over, marcatori restano coerenti tra loro.
    # τ è auto-normalizzato (Σ τ·P = 1); w/mean(w) protegge dal residuo NB.
    rho = float(calib.get("rho", config.DC_RHO_DEFAULT))
    lam_dc, mu_dc = float(xg_h), float(xg_a)
    w = np.ones(n)
    w[(goals_h == 0) & (goals_a == 0)] = max(1.0 - lam_dc * mu_dc * rho, 0.05)
    w[(goals_h == 1) & (goals_a == 0)] = max(1.0 + mu_dc * rho, 0.05)
    w[(goals_h == 0) & (goals_a == 1)] = max(1.0 + lam_dc * rho, 0.05)
    w[(goals_h == 1) & (goals_a == 1)] = max(1.0 - rho, 0.05)
    w /= w.mean()

    # matrice risultati esatti (pesata)
    hm = np.minimum(goals_h, MAX_SCORE)
    am = np.minimum(goals_a, MAX_SCORE)
    matrix = np.zeros((MAX_SCORE + 1, MAX_SCORE + 1))
    np.add.at(matrix, (hm, am), w)
    matrix_pct = np.round(100.0 * matrix / w.sum(), 2)
    labels = [str(i) for i in range(MAX_SCORE)] + [f"{MAX_SCORE}+"]
    flat = [(f"{labels[i]}-{labels[j]}", float(matrix_pct[i, j]))
            for i in range(MAX_SCORE + 1) for j in range(MAX_SCORE + 1)]
    top_scores = sorted(flat, key=lambda x: -x[1])[:10]

    p1 = 100.0 * _wmean(goals_h > goals_a, w)
    p2 = 100.0 * _wmean(goals_a > goals_h, w)
    px = round(100.0 - p1 - p2, 2)
    goals_t = goals_h + goals_a

    # intervalli di confidenza 80% (10°-90° percentile tra i blocchi, che
    # differiscono per il moltiplicatore di forza pescato); medie pesate DC
    wb = np.maximum(w.reshape(n_blocks, per).sum(axis=1), 1e-9)
    blk_1 = ((goals_h > goals_a) * w).reshape(n_blocks, per).sum(axis=1) / wb * 100
    blk_2 = ((goals_a > goals_h) * w).reshape(n_blocks, per).sum(axis=1) / wb * 100
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
    sc_home = _scorer_table(_scorer_weights(home), goals_h, rng, w)
    sc_away = _scorer_table(_scorer_weights(away), goals_a, rng, w)
    for table, prof in ((sc_home, home), (sc_away, away)):
        for r in table:
            r["penalty_taker"] = (r["id"] == prof["penalty_taker_id"])

    return {
        "n_sims": n,
        "xg": {"home": round(float(xg_h), 2), "away": round(float(xg_a), 2)},
        "modello": {
            "elo": {"home": home.get("elo"), "away": away.get("elo")},
            "fattore_elo": {"home": round(elo_f_h, 3), "away": round(elo_f_a, 3)},
            "xg_proxy": {"home": home.get("xg_pg"), "away": away.get("xg_pg")},
            "xga_proxy": {"home": home.get("xga_pg"), "away": away.get("xga_pg")},
            "time_decay": config.STAT_DECAY,
            "riposo_giorni": {"home": rest_h, "away": rest_a},
            "stanchezza": {"home": tired_h, "away": tired_a},
            "motivazione": {"home": mot_h, "away": mot_a},
            "quota_2t_in_svantaggio": {
                "home": round(100.0 * _wmean(behind_h, w), 1),
                "away": round(100.0 * _wmean(ahead_h, w), 1)},
            "dispersione_nb": {k: round(float(v), 3) for k, v in A.items()},
            "dixon_coles_rho": rho,
            "l_lega": round(L, 3),
            "xg_scale": calib.get("xg_scale"),
            "game_state_dinamico": {
                "delta_elo_400": round(d_elo, 3),
                "spinta_elo": {"home": round(push_elo_h, 3),
                               "away": round(push_elo_a, 3)}},
            "componenti": "Binomiale Negativa (α per lega) · Dixon-Coles (ρ"
                          " per lega) · ELO-ponderato · time-decay · blend xG"
                          " shot-based v2 (rigori, tiri murati, cross) ·"
                          " corner∝tiri · falli∝pressione avversaria · game"
                          " state dinamico (minuti dal gol × ΔELO) · riposo"
                          " · motivazione",
        },
        "outcomes": {
            "1": round(p1, 2), "X": px, "2": round(p2, 2),
            "1X": round(p1 + px, 2), "X2": round(px + p2, 2),
            "12": round(p1 + p2, 2),
        },
        "outcomes_ci": outcomes_ci,
        "reliability": reliability,
        "btts": round(100.0 * _wmean((goals_h > 0) & (goals_a > 0), w), 2),
        "over": {f"{l:.1f}": _over(goals_t, l, w) for l in (0.5, 1.5, 2.5, 3.5, 4.5)},
        "goals_dist": _dist(goals_t, 12, w),
        "score_matrix": matrix_pct.tolist(),
        "top_scores": top_scores,
        "corners": {
            "mean_home": round(_wmean(corners_h, w), 2),
            "mean_away": round(_wmean(corners_a, w), 2),
            "mean_total": round(_wmean(corners_t, w), 2),
            "dist_total": _dist(corners_t, 26, w),
            "lines": {f"{l:.1f}": _over(corners_t, l, w)
                      for l in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
        },
        "shots": {
            "mean_home": round(_wmean(shots_h, w), 2),
            "mean_away": round(_wmean(shots_a, w), 2),
            "sot_home": round(_wmean(sot_h, w), 2),
            "sot_away": round(_wmean(sot_a, w), 2),
            "sot_dist_home": _dist(sot_h, 15, w),
            "sot_dist_away": _dist(sot_a, 15, w),
        },
        "saves": {
            "mean_home": round(_wmean(saves_h, w), 2),
            "mean_away": round(_wmean(saves_a, w), 2),
            "dist_home": _dist(saves_h, 14, w),
            "dist_away": _dist(saves_a, 14, w),
        },
        "fouls": {
            "mean_home": round(_wmean(fouls_h, w), 2),
            "mean_away": round(_wmean(fouls_a, w), 2),
        },
        "cards": {
            "yellows_home": round(_wmean(yellows_h, w), 2),
            "yellows_away": round(_wmean(yellows_a, w), 2),
            "red_prob_home": round(100.0 * _wmean(reds_h, w), 2),
            "red_prob_away": round(100.0 * _wmean(reds_a, w), 2),
            "mean_total": round(_wmean(cards_t, w), 2),
            "dist_total": _dist(cards_t, 14, w),
            "lines": {f"{l:.1f}": _over(cards_t, l, w)
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
