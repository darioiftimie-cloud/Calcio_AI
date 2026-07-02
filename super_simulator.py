#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 SUPER SIMULATOR — Motore Monte Carlo di Sports Intelligence (Calcio)
================================================================================
Motore a 10.000 simulazioni/partita basato su una CATENA STOCASTICA
INTERCONNESSA. Nessuna metrica è simulata in isolamento:

  [Tempo di gara]  ~ Gamma(media=1)      → volatilità condivisa dell'intensità
        │
        ├─► [Tiri in porta]  ~ Poisson(λ_SoT × tempo)
        │         │
        │         ├─► [Gol]     = Binomiale(SoT, 1 − SaveRate portiere avv.)
        │         │                (thinning binomiale di un Poisson ⇒ i gol
        │         │                 restano marginalmente Poisson: matrice
        │         │                 dei risultati esatti "Poisson combinata")
        │         ├─► [Parate]  = SoT − Gol  ⇒ Binomiale(SoT, SaveRate reale
        │         │                 del portiere titolare)
        │         └─► [Dominanza] → correzione λ corner nella singola sim
        │
        ├─► [Corner]  ~ Poisson(λ_corner × indice fasce laterali × dominanza)
        │
        └─► [Falli]   ~ Poisson(λ_falli × indice aggressività DIF+CEN titolari)
                  └─► [Gialli] = Binomiale(falli, p_giallo × aggressività)
                  └─► [Rossi]  = Bernoulli(p_rosso × aggressività)

  [Marcatori] per ogni gol simulato: distribuzione categoriale pesata su
  ruolo × propensione realizzativa dei titolari in campo, con ramo dedicato
  per i rigori (assegnati al rigorista designato) e quota autogol.

Uso:
    python super_simulator.py                      # match di default, 10.000 sim
    python super_simulator.py --sims 50000         # override n. simulazioni
    python super_simulator.py --config match.json  # carica un match da JSON
    python super_simulator.py --dump-config        # scrive match_template.json
    python super_simulator.py --no-html            # solo report a terminale
    python super_simulator.py --open               # apre la dashboard nel browser
    python super_simulator.py --seed 42            # run riproducibile
================================================================================
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import webbrowser
from collections import Counter
from datetime import datetime

# ------------------------------------------------------------------------------
# Console Windows: forza UTF-8 per i caratteri di disegno del report
# ------------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==============================================================================
# CONFIGURAZIONE DI DEFAULT
# ------------------------------------------------------------------------------
# Tutti i parametri sono indici moltiplicativi rispetto alla media di lega
# (1.00 = media). I dati sotto sono un esempio realistico (derby di Milano):
# sostituiscili con i tuoi rating/formazioni reali oppure carica un JSON
# con la stessa struttura tramite --config.
#
# Campi giocatore:
#   role : POR / DIF / CEN / ATT
#   xg   : propensione realizzativa individuale (1.00 = media di ruolo)
#   aggr : indice di aggressività disciplinare (1.00 = media; conta per DIF/CEN)
#   pen  : True se rigorista designato
# ==============================================================================
DEFAULT_CONFIG = {
    "match": {
        "competition": "Serie A — Derby della Madonnina",
        "n_sims": 10000,
    },
    "league": {
        "avg_goals_team": 1.40,     # gol medi a squadra per partita
        "home_boost": 1.18,         # fattore campo (casa)
        "away_malus": 0.88,         # fattore trasferta
        "tempo_shape": 10.0,        # shape Gamma del "tempo di gara" (var = 1/shape)
        "base_corners": 5.3,        # corner medi a squadra
        "base_fouls": 11.8,         # falli medi a squadra
        "yellow_per_foul": 0.185,   # prob. che un fallo produca un giallo (media lega)
        "red_prob": 0.055,          # prob. base di un rosso per squadra a partita
        "penalty_goal_share": 0.11, # quota di gol su rigore
        "own_goal_share": 0.025,    # quota autogol
    },
    "teams": {
        "home": {
            "name": "Inter",
            "attack": 1.30,         # forza offensiva (xG prodotti vs media)
            "defense": 0.80,        # xG concessi vs media (più basso = migliore)
            "flank_left": 1.25,     # tendenza offensiva fascia sinistra → corner
            "flank_right": 1.08,    # tendenza offensiva fascia destra  → corner
            "keeper": {"name": "Y. Sommer", "save_rate": 0.735},
            "lineup": [
                {"name": "B. Pavard",       "role": "DIF", "xg": 0.90, "aggr": 1.05},
                {"name": "F. Acerbi",       "role": "DIF", "xg": 0.80, "aggr": 1.30},
                {"name": "A. Bastoni",      "role": "DIF", "xg": 0.95, "aggr": 1.00},
                {"name": "D. Dumfries",     "role": "CEN", "xg": 1.30, "aggr": 1.20},
                {"name": "N. Barella",      "role": "CEN", "xg": 1.10, "aggr": 1.25},
                {"name": "H. Calhanoglu",   "role": "CEN", "xg": 1.35, "aggr": 1.10, "pen": True},
                {"name": "H. Mkhitaryan",   "role": "CEN", "xg": 1.00, "aggr": 0.95},
                {"name": "F. Dimarco",      "role": "CEN", "xg": 1.15, "aggr": 0.90},
                {"name": "L. Martinez",     "role": "ATT", "xg": 1.60, "aggr": 1.05},
                {"name": "M. Thuram",       "role": "ATT", "xg": 1.40, "aggr": 0.85},
            ],
        },
        "away": {
            "name": "Milan",
            "attack": 1.18,
            "defense": 0.98,
            "flank_left": 1.30,
            "flank_right": 1.12,
            "keeper": {"name": "M. Maignan", "save_rate": 0.710},
            "lineup": [
                {"name": "D. Calabria",     "role": "DIF", "xg": 0.75, "aggr": 1.10},
                {"name": "F. Tomori",       "role": "DIF", "xg": 0.80, "aggr": 1.20},
                {"name": "M. Gabbia",       "role": "DIF", "xg": 0.85, "aggr": 1.00},
                {"name": "T. Hernandez",    "role": "DIF", "xg": 1.25, "aggr": 1.30},
                {"name": "Y. Fofana",       "role": "CEN", "xg": 0.90, "aggr": 1.35},
                {"name": "T. Reijnders",    "role": "CEN", "xg": 1.20, "aggr": 0.90},
                {"name": "R. Loftus-Cheek", "role": "CEN", "xg": 1.15, "aggr": 1.05},
                {"name": "C. Pulisic",      "role": "ATT", "xg": 1.45, "aggr": 0.80, "pen": True},
                {"name": "R. Leao",         "role": "ATT", "xg": 1.40, "aggr": 0.90},
                {"name": "A. Morata",       "role": "ATT", "xg": 1.35, "aggr": 1.00},
            ],
        },
    },
}

# Peso base del ruolo nella distribuzione categoriale dei marcatori
ROLE_SCORER_WEIGHT = {"ATT": 1.00, "CEN": 0.42, "DIF": 0.13, "POR": 0.0}


# ==============================================================================
# CAMPIONATORI STOCASTICI (stdlib pura — nessuna dipendenza esterna)
# ==============================================================================
def sample_poisson(lam: float, rng: random.Random) -> int:
    """Campiona da Poisson(λ) — algoritmo di Knuth (λ tipici < 20)."""
    if lam <= 0.0:
        return 0
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def sample_binomial(n: int, p: float, rng: random.Random) -> int:
    """Campiona da Binomiale(n, p) come somma di Bernoulli."""
    if n <= 0 or p <= 0.0:
        return 0
    if p >= 1.0:
        return n
    return sum(1 for _ in range(n) if rng.random() < p)


def sample_tempo(shape: float, rng: random.Random) -> float:
    """'Tempo di gara' ~ Gamma(shape, 1/shape): media 1, var 1/shape.
    È il fattore latente condiviso che accoppia tutte le metriche."""
    return rng.gammavariate(shape, 1.0 / shape)


def sample_categorical(weights: list[float], rng: random.Random) -> int:
    """Estrazione categoriale sull'indice, pesi non normalizzati."""
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return i
    return len(weights) - 1


# ==============================================================================
# MOTORE MONTE CARLO
# ==============================================================================
class SuperSimulator:
    MAX_SCORE = 5  # la matrice risultati esatti raggruppa 5+ nell'ultima riga/col

    def __init__(self, config: dict, n_sims: int | None = None, seed: int | None = None):
        self.cfg = config
        self.n_sims = n_sims or config["match"].get("n_sims", 10000)
        self.rng = random.Random(seed)
        self._derive_parameters()
        self._init_accumulators()

    # ------------------------------------------------------------------ setup
    def _derive_parameters(self) -> None:
        lg = self.cfg["league"]
        home, away = self.cfg["teams"]["home"], self.cfg["teams"]["away"]

        # λ gol attesi (modello moltiplicativo attacco × difesa avversaria × campo)
        self.lam_goal = {
            "home": lg["avg_goals_team"] * home["attack"] * away["defense"] * lg["home_boost"],
            "away": lg["avg_goals_team"] * away["attack"] * home["defense"] * lg["away_malus"],
        }

        # Save rate dei portieri titolari (dalle formazioni)
        self.save_rate = {
            "home": home["keeper"]["save_rate"],   # subisce i tiri della trasferta
            "away": away["keeper"]["save_rate"],
        }

        # λ tiri in porta: i gol sono un thinning binomiale dei SoT, quindi
        # λ_SoT = λ_gol / (1 − save_rate del portiere avversario)
        self.lam_sot = {
            "home": self.lam_goal["home"] / (1.0 - self.save_rate["away"]),
            "away": self.lam_goal["away"] / (1.0 - self.save_rate["home"]),
        }

        # λ corner corretti per la tendenza delle fasce laterali
        def flank_index(team: dict) -> float:
            return (team["flank_left"] + team["flank_right"]) / 2.0

        self.lam_corner = {
            "home": lg["base_corners"] * flank_index(home) * (0.75 + 0.25 * home["attack"]),
            "away": lg["base_corners"] * flank_index(away) * (0.75 + 0.25 * away["attack"]),
        }

        # Indice di aggressività = media aggr dei titolari di difesa e centrocampo
        def aggression_index(team: dict) -> float:
            core = [p for p in team["lineup"] if p["role"] in ("DIF", "CEN")]
            return sum(p.get("aggr", 1.0) for p in core) / len(core)

        self.aggr = {"home": aggression_index(home), "away": aggression_index(away)}
        self.lam_fouls = {s: lg["base_fouls"] * self.aggr[s] for s in ("home", "away")}
        self.p_yellow = {
            s: min(0.5, lg["yellow_per_foul"] * self.aggr[s]) for s in ("home", "away")
        }
        self.p_red = {s: min(0.30, lg["red_prob"] * self.aggr[s]) for s in ("home", "away")}

        # Distribuzione categoriale dei marcatori (pesi = ruolo × xg individuale)
        self.scorer_pool: dict[str, list[dict]] = {}
        self.scorer_weights: dict[str, list[float]] = {}
        self.penalty_taker: dict[str, str] = {}
        for side in ("home", "away"):
            team = self.cfg["teams"][side]
            pool = [p for p in team["lineup"] if ROLE_SCORER_WEIGHT.get(p["role"], 0) > 0]
            self.scorer_pool[side] = pool
            self.scorer_weights[side] = [
                ROLE_SCORER_WEIGHT[p["role"]] * p.get("xg", 1.0) for p in pool
            ]
            takers = [p["name"] for p in team["lineup"] if p.get("pen")]
            self.penalty_taker[side] = takers[0] if takers else pool[0]["name"]

    def _init_accumulators(self) -> None:
        n = self.MAX_SCORE + 1
        self.score_matrix = [[0] * n for _ in range(n)]
        self.results = Counter()            # '1' / 'X' / '2'
        self.goals_total = Counter()        # gol totali per sim
        self.btts = 0
        self.corners = {s: Counter() for s in ("home", "away")}
        self.corners_total = Counter()
        self.corner_most = Counter()        # 'home' / 'away' / 'tie'
        self.sot = {s: Counter() for s in ("home", "away")}
        self.saves = {s: Counter() for s in ("home", "away")}   # parate del portiere di s
        self.fouls_sum = {s: 0 for s in ("home", "away")}
        self.yellows = {s: Counter() for s in ("home", "away")}
        self.reds = {s: 0 for s in ("home", "away")}
        self.cards_total = Counter()
        self.scorer_goals = {s: Counter() for s in ("home", "away")}   # gol totali
        self.scorer_any = {s: Counter() for s in ("home", "away")}     # sim con ≥1 gol
        self.scorer_brace = {s: Counter() for s in ("home", "away")}   # sim con ≥2 gol
        self.own_goals = {s: 0 for s in ("home", "away")}
        self.penalty_goals = {s: 0 for s in ("home", "away")}

    # ------------------------------------------------------------- simulazione
    def _simulate_match(self) -> None:
        lg = self.cfg["league"]
        rng = self.rng
        tempo = sample_tempo(lg["tempo_shape"], rng)

        sim_goals, sim_sot = {}, {}
        for side, opp in (("home", "away"), ("away", "home")):
            # 1) Tiri in porta condizionati al tempo di gara
            sot = sample_poisson(self.lam_sot[side] * tempo, rng)
            # 2) Gol = thinning binomiale sul save rate del portiere avversario;
            #    Parate del portiere avversario = SoT − gol (Binomiale(SoT, save_rate))
            goals = sample_binomial(sot, 1.0 - self.save_rate[opp], rng)
            sim_sot[side], sim_goals[side] = sot, goals
            self.sot[side][sot] += 1
            self.saves[opp][sot - goals] += 1

        # 3) Corner accoppiati alla dominanza offensiva della singola simulazione
        sim_corners = {}
        for side in ("home", "away"):
            expected_sot = max(self.lam_sot[side] * tempo, 0.1)
            dominance = min(1.7, max(0.5, 0.65 + 0.35 * sim_sot[side] / expected_sot))
            lam_c = self.lam_corner[side] * (0.5 + 0.5 * tempo) * dominance
            c = sample_poisson(lam_c, rng)
            sim_corners[side] = c
            self.corners[side][c] += 1
        self.corners_total[sim_corners["home"] + sim_corners["away"]] += 1
        if sim_corners["home"] > sim_corners["away"]:
            self.corner_most["home"] += 1
        elif sim_corners["away"] > sim_corners["home"]:
            self.corner_most["away"] += 1
        else:
            self.corner_most["tie"] += 1

        # 4) Falli e cartellini dall'aggressività dei titolari DIF+CEN
        total_cards = 0
        for side in ("home", "away"):
            fouls = sample_poisson(self.lam_fouls[side] * (0.8 + 0.2 * tempo), rng)
            self.fouls_sum[side] += fouls
            yellows = sample_binomial(fouls, self.p_yellow[side], rng)
            red = 1 if rng.random() < self.p_red[side] else 0
            self.yellows[side][yellows] += 1
            self.reds[side] += red
            total_cards += yellows + red
        self.cards_total[total_cards] += 1

        # 5) Marcatori: categoriale pesata + ramo rigorista + quota autogol
        for side in ("home", "away"):
            scored_in_sim = Counter()
            for _ in range(sim_goals[side]):
                r = rng.random()
                if r < lg["penalty_goal_share"]:
                    scorer = self.penalty_taker[side]
                    self.penalty_goals[side] += 1
                elif r < lg["penalty_goal_share"] + lg["own_goal_share"]:
                    self.own_goals[side] += 1
                    scorer = "__OWN__"
                else:
                    idx = sample_categorical(self.scorer_weights[side], rng)
                    scorer = self.scorer_pool[side][idx]["name"]
                if scorer != "__OWN__":
                    scored_in_sim[scorer] += 1
            for name, k in scored_in_sim.items():
                self.scorer_goals[side][name] += k
                self.scorer_any[side][name] += 1
                if k >= 2:
                    self.scorer_brace[side][name] += 1

        # Aggregati risultato
        gh, ga = sim_goals["home"], sim_goals["away"]
        self.score_matrix[min(gh, self.MAX_SCORE)][min(ga, self.MAX_SCORE)] += 1
        self.results["1" if gh > ga else "2" if ga > gh else "X"] += 1
        self.goals_total[gh + ga] += 1
        if gh > 0 and ga > 0:
            self.btts += 1

    def run(self) -> None:
        for _ in range(self.n_sims):
            self._simulate_match()

    # ------------------------------------------------------------ aggregazione
    def _pct(self, count: int) -> float:
        return 100.0 * count / self.n_sims

    def _dist_pct(self, counter: Counter) -> dict[int, float]:
        return {k: self._pct(v) for k, v in sorted(counter.items())}

    def _mean(self, counter: Counter) -> float:
        return sum(k * v for k, v in counter.items()) / self.n_sims

    def _over_prob(self, counter: Counter, line: float) -> float:
        return self._pct(sum(v for k, v in counter.items() if k > line))

    def aggregate(self) -> dict:
        """Consolida i contatori in un dizionario di probabilità percentuali,
        condiviso da report terminale, JSON e dashboard HTML."""
        home = self.cfg["teams"]["home"]["name"]
        away = self.cfg["teams"]["away"]["name"]
        n = self.MAX_SCORE + 1

        matrix = [[self._pct(self.score_matrix[i][j]) for j in range(n)] for i in range(n)]
        flat = [
            (f"{i if i < self.MAX_SCORE else str(self.MAX_SCORE) + '+'}-"
             f"{j if j < self.MAX_SCORE else str(self.MAX_SCORE) + '+'}", matrix[i][j])
            for i in range(n) for j in range(n)
        ]
        top_scores = sorted(flat, key=lambda x: -x[1])[:10]

        p1, px, p2 = (self._pct(self.results[k]) for k in ("1", "X", "2"))

        def scorer_table(side: str) -> list[dict]:
            rows = []
            for p in self.scorer_pool[side]:
                name = p["name"]
                any_p = self._pct(self.scorer_any[side][name])
                rows.append({
                    "name": name,
                    "role": p["role"],
                    "anytime": any_p,
                    "brace": self._pct(self.scorer_brace[side][name]),
                    "xg_sim": self.scorer_goals[side][name] / self.n_sims,
                    "fair_odds": (100.0 / any_p) if any_p > 0 else None,
                    "penalty_taker": p.get("pen", False),
                })
            return sorted(rows, key=lambda r: -r["anytime"])

        return {
            "meta": {
                "home": home,
                "away": away,
                "competition": self.cfg["match"].get("competition", ""),
                "n_sims": self.n_sims,
                "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "keepers": {
                    "home": self.cfg["teams"]["home"]["keeper"],
                    "away": self.cfg["teams"]["away"]["keeper"],
                },
                "aggression": self.aggr,
            },
            "xg": {"home": self.lam_goal["home"], "away": self.lam_goal["away"]},
            "outcomes": {
                "1": p1, "X": px, "2": p2,
                "1X": p1 + px, "X2": px + p2, "12": p1 + p2,
            },
            "btts": self._pct(self.btts),
            "over": {f"{line:.1f}": self._over_prob(self.goals_total, line)
                     for line in (0.5, 1.5, 2.5, 3.5, 4.5)},
            "goals_dist": self._dist_pct(self.goals_total),
            "score_matrix": matrix,
            "top_scores": top_scores,
            "corners": {
                "mean_home": self._mean(self.corners["home"]),
                "mean_away": self._mean(self.corners["away"]),
                "mean_total": self._mean(self.corners_total),
                "dist_total": self._dist_pct(self.corners_total),
                "lines": {f"{line:.1f}": self._over_prob(self.corners_total, line)
                          for line in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
                "most": {k: self._pct(v) for k, v in self.corner_most.items()},
            },
            "sot": {
                "mean_home": self._mean(self.sot["home"]),
                "mean_away": self._mean(self.sot["away"]),
                "dist_home": self._dist_pct(self.sot["home"]),
                "dist_away": self._dist_pct(self.sot["away"]),
            },
            "saves": {
                "mean_home": self._mean(self.saves["home"]),
                "mean_away": self._mean(self.saves["away"]),
                "dist_home": self._dist_pct(self.saves["home"]),
                "dist_away": self._dist_pct(self.saves["away"]),
            },
            "discipline": {
                "fouls_mean": {s: self.fouls_sum[s] / self.n_sims for s in ("home", "away")},
                "yellows_mean": {s: self._mean(self.yellows[s]) for s in ("home", "away")},
                "red_prob": {s: self._pct(self.reds[s]) for s in ("home", "away")},
                "cards_total_mean": self._mean(self.cards_total),
                "cards_dist": self._dist_pct(self.cards_total),
                "cards_lines": {f"{line:.1f}": self._over_prob(self.cards_total, line)
                                for line in (2.5, 3.5, 4.5, 5.5, 6.5)},
            },
            "scorers": {"home": scorer_table("home"), "away": scorer_table("away")},
            "extras": {
                "penalty_goal_pct": {
                    "home": self.penalty_goals["home"] / self.n_sims,
                    "away": self.penalty_goals["away"] / self.n_sims,
                },
                "own_goals_per_match": {s: self.own_goals[s] / self.n_sims for s in ("home", "away")},
            },
        }


# ==============================================================================
# REPORT A TERMINALE
# ==============================================================================
BAR_FULL = "█"
BAR_HALF = "▌"


def bar(pct: float, scale: float = 1.6, width: int = 42) -> str:
    units = pct * scale
    n = min(int(units), width)
    half = BAR_HALF if (units - n) >= 0.5 and n < width else ""
    return BAR_FULL * n + half


def rule(char: str = "═", width: int = 96) -> str:
    return char * width


def section(title: str) -> None:
    print()
    print(rule())
    print(f"  {title}")
    print(rule())


def print_report(agg: dict) -> None:
    m = agg["meta"]
    home, away = m["home"], m["away"]

    print()
    print(rule("█"))
    print(f"  SUPER SIMULATOR — MOTORE MONTE CARLO  |  {m['n_sims']:,} SIMULAZIONI".replace(",", "."))
    print(f"  {home.upper()}  vs  {away.upper()}   ({m['competition']})")
    print(f"  Generato: {m['generated']}")
    print(rule("█"))

    # ------------------------------------------------------------ parametri
    section("0. PARAMETRI DERIVATI DEL MODELLO (catena stocastica)")
    print(f"  xG attesi              : {home} {agg['xg']['home']:.2f}  —  {away} {agg['xg']['away']:.2f}")
    print(f"  Portieri titolari      : {m['keepers']['home']['name']} (save rate {m['keepers']['home']['save_rate']*100:.1f}%)"
          f"  |  {m['keepers']['away']['name']} (save rate {m['keepers']['away']['save_rate']*100:.1f}%)")
    print(f"  Indice aggressività    : {home} {m['aggression']['home']:.2f}  —  {away} {m['aggression']['away']:.2f}"
          f"   (media DIF+CEN titolari, 1.00 = media lega)")
    print(f"  Rigori attesi convertiti: {home} {agg['extras']['penalty_goal_pct']['home']:.3f}/match — "
          f"{away} {agg['extras']['penalty_goal_pct']['away']:.3f}/match")

    # ------------------------------------------------------------ 1X2
    section("1. ESITI FINALI (1X2, doppia chance, gol)")
    o = agg["outcomes"]
    for key, label in (("1", f"Vittoria {home} (1)"), ("X", "Pareggio (X)"), ("2", f"Vittoria {away} (2)")):
        print(f"  {label:<26} {o[key]:6.2f}%  {bar(o[key])}")
    print()
    print(f"  Doppia chance 1X: {o['1X']:6.2f}%   |   X2: {o['X2']:6.2f}%   |   12: {o['12']:6.2f}%")
    print(f"  BTTS / Gol (entrambe segnano): {agg['btts']:6.2f}%")
    print()
    for line, p in agg["over"].items():
        print(f"  Over {line}: {p:6.2f}%   Under {line}: {100-p:6.2f}%")

    # ------------------------------------------------------------ matrice
    section("2. MATRICE RISULTATI ESATTI — Poisson combinata (probabilità %)")
    labels = [str(i) for i in range(SuperSimulator.MAX_SCORE)] + [f"{SuperSimulator.MAX_SCORE}+"]
    header = f"  {home[:12]:>14} \\ {away[:12]:<12}" + "".join(f"{l:>8}" for l in labels)
    print(header)
    print("  " + "─" * (len(header) + 2))
    for i, row in enumerate(agg["score_matrix"]):
        print(f"  {labels[i]:>29}" + "".join(f"{p:7.2f}%" for p in row))
    print()
    print("  TOP 10 RISULTATI PIÙ PROBABILI:")
    for rank, (score, p) in enumerate(agg["top_scores"], 1):
        print(f"   {rank:>2}. {score:<7} {p:6.2f}%  {bar(p, scale=3.0)}")

    # ------------------------------------------------------------ corner
    section("3. CORNER — Poisson corretta per tendenze di fascia + dominanza")
    c = agg["corners"]
    print(f"  Media corner {home:<14}: {c['mean_home']:5.2f}")
    print(f"  Media corner {away:<14}: {c['mean_away']:5.2f}")
    print(f"  Media corner TOTALI{'':<8}: {c['mean_total']:5.2f}")
    print(f"  Più corner nel match     : {home} {c['most'].get('home', 0):.1f}%  |  "
          f"{away} {c['most'].get('away', 0):.1f}%  |  Parità {c['most'].get('tie', 0):.1f}%")
    print()
    print("  Linee Over corner totali:")
    for line, p in c["lines"].items():
        print(f"    Over {line:>4}: {p:6.2f}%   Under: {100-p:6.2f}%")
    print()
    print("  Distribuzione corner totali:")
    for k, p in c["dist_total"].items():
        if p >= 0.3:
            print(f"    {k:>2} corner: {p:5.2f}%  {bar(p, scale=2.5)}")

    # ------------------------------------------------------------ tiri/parate
    section("4. TIRI IN PORTA & PARATE — Binomiale sul Save Rate del portiere")
    s, sv, kp = agg["sot"], agg["saves"], m["keepers"]
    print(f"  Tiri in porta attesi   : {home} {s['mean_home']:.2f}  —  {away} {s['mean_away']:.2f}")
    print(f"  Parate attese          : {kp['home']['name']} ({home}) {sv['mean_home']:.2f}  —  "
          f"{kp['away']['name']} ({away}) {sv['mean_away']:.2f}")
    for side, team in (("home", home), ("away", away)):
        keeper = kp[side]["name"]
        print()
        print(f"  Distribuzione PARATE ESATTE di {keeper} ({team}, save rate {kp[side]['save_rate']*100:.1f}%):")
        for k, p in sv[f"dist_{side}"].items():
            if p >= 0.3:
                print(f"    {k:>2} parate: {p:5.2f}%  {bar(p, scale=2.0)}")

    # ------------------------------------------------------------ disciplina
    section("5. FALLI & CARTELLINI — aggressività dei titolari DIF+CEN")
    d = agg["discipline"]
    print(f"  Falli attesi           : {home} {d['fouls_mean']['home']:5.2f}  —  {away} {d['fouls_mean']['away']:5.2f}")
    print(f"  Gialli attesi          : {home} {d['yellows_mean']['home']:5.2f}  —  {away} {d['yellows_mean']['away']:5.2f}")
    print(f"  Prob. cartellino rosso : {home} {d['red_prob']['home']:5.2f}%  —  {away} {d['red_prob']['away']:5.2f}%")
    print(f"  Cartellini totali medi : {d['cards_total_mean']:.2f}")
    print()
    print("  Linee Over cartellini totali:")
    for line, p in d["cards_lines"].items():
        print(f"    Over {line:>4}: {p:6.2f}%   Under: {100-p:6.2f}%")
    print()
    print("  Distribuzione cartellini totali:")
    for k, p in d["cards_dist"].items():
        if p >= 0.3:
            print(f"    {k:>2} cartellini: {p:5.2f}%  {bar(p, scale=2.0)}")

    # ------------------------------------------------------------ marcatori
    section("6. MARCATORI — distribuzione categoriale sui titolari in campo")
    for side, team in (("home", home), ("away", away)):
        print()
        print(f"  {team.upper()}  (® = rigorista designato)")
        print(f"  {'Giocatore':<20}{'Ruolo':<7}{'Anytime %':>10}{'Doppietta %':>13}{'xG sim':>8}{'Quota equa':>12}")
        print("  " + "─" * 70)
        for r in agg["scorers"][side]:
            flag = " ®" if r["penalty_taker"] else ""
            odds = f"{r['fair_odds']:.2f}" if r["fair_odds"] else "—"
            print(f"  {r['name'] + flag:<20}{r['role']:<7}{r['anytime']:>9.2f}%{r['brace']:>12.2f}%"
                  f"{r['xg_sim']:>8.3f}{odds:>12}")

    print()
    print(rule("█"))
    print("  FINE REPORT — dati completi esportati in dashboard_data.json / dashboard.html")
    print(rule("█"))
    print()


# ==============================================================================
# FRONT-END: DASHBOARD HTML AUTONOMA (nessuna dipendenza, nessun server)
# ==============================================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Super Simulator — Dashboard</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b27; --panel2:#1b2233; --line:#2a3348;
    --txt:#e6e9f0; --dim:#8b93a7; --acc:#39d98a; --acc2:#4da3ff; --warn:#ffb454;
    --red:#ff5d5d; --yellow:#ffd24d;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);font:14px/1.5 "Segoe UI",system-ui,sans-serif;padding:24px}
  h1{font-size:22px;letter-spacing:.5px}
  h2{font-size:13px;text-transform:uppercase;letter-spacing:1.5px;color:var(--acc);margin-bottom:14px;
     border-bottom:1px solid var(--line);padding-bottom:8px}
  .sub{color:var(--dim);margin-top:4px;font-size:12px}
  .grid{display:grid;gap:16px;margin-top:20px}
  .cols-2{grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
  .kpis{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}
  .kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 20px;min-width:150px}
  .kpi .v{font-size:24px;font-weight:700;color:var(--acc)}
  .kpi .l{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px}
  .row{display:flex;align-items:center;gap:10px;margin:5px 0}
  .row .lbl{width:170px;color:var(--dim);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .row .val{width:62px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
  .track{flex:1;height:12px;background:var(--panel2);border-radius:6px;overflow:hidden}
  .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--acc2),var(--acc))}
  .fill.gold{background:linear-gradient(90deg,#f7b733,#fc4a1a)}
  .fill.card{background:linear-gradient(90deg,var(--yellow),var(--red))}
  table{border-collapse:collapse;width:100%}
  th,td{padding:6px 8px;text-align:center;font-variant-numeric:tabular-nums}
  th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:1px}
  .heat td{border:1px solid var(--bg);border-radius:4px;font-size:12px;min-width:52px}
  .scorers td{text-align:left;border-bottom:1px solid var(--line);font-size:13px}
  .scorers td.num{text-align:right}
  .scorers th{text-align:left}
  .scorers th.num{text-align:right}
  .pen{color:var(--warn);font-weight:700}
  .tag{display:inline-block;font-size:10px;padding:1px 7px;border-radius:8px;background:var(--panel2);
       color:var(--dim);margin-left:6px;text-transform:uppercase;letter-spacing:1px}
  footer{margin-top:26px;color:var(--dim);font-size:11px;text-align:center}
</style>
</head>
<body>
  <h1 id="title"></h1>
  <div class="sub" id="subtitle"></div>
  <div class="kpis" id="kpis"></div>

  <div class="grid cols-2">
    <div class="panel"><h2>Esiti 1X2 &amp; linee gol</h2><div id="outcomes"></div></div>
    <div class="panel"><h2>Top risultati esatti</h2><div id="topscores"></div></div>
    <div class="panel" style="grid-column:1/-1"><h2>Matrice risultati esatti (%)</h2><div id="matrix"></div></div>
    <div class="panel"><h2>Corner — distribuzione totale &amp; linee</h2><div id="corners"></div></div>
    <div class="panel"><h2>Tiri in porta &amp; parate (binomiale save-rate)</h2><div id="saves"></div></div>
    <div class="panel"><h2>Falli &amp; cartellini</h2><div id="cards"></div></div>
    <div class="panel"><h2>Marcatori — probabilità anytime</h2><div id="scorers"></div></div>
  </div>
  <footer id="footer"></footer>

<script>
const DATA = __DATA__;

const $ = id => document.getElementById(id);
const fmt = (x, d=2) => Number(x).toFixed(d);

function barRow(label, pct, cls="", scale=1){
  const w = Math.min(100, pct*scale);
  return `<div class="row"><div class="lbl" title="${label}">${label}</div>
    <div class="track"><div class="fill ${cls}" style="width:${w}%"></div></div>
    <div class="val">${fmt(pct)}%</div></div>`;
}

function init(){
  const m = DATA.meta;
  $("title").textContent = `${m.home}  vs  ${m.away}`;
  $("subtitle").textContent =
    `${m.competition} — ${m.n_sims.toLocaleString("it-IT")} simulazioni Monte Carlo — generato ${m.generated}`;

  // KPI
  const o = DATA.outcomes;
  $("kpis").innerHTML = [
    [`xG ${m.home}`, fmt(DATA.xg.home)], [`xG ${m.away}`, fmt(DATA.xg.away)],
    [`1 (${m.home})`, fmt(o["1"]) + "%"], ["X", fmt(o["X"]) + "%"], [`2 (${m.away})`, fmt(o["2"]) + "%"],
    ["BTTS", fmt(DATA.btts) + "%"], ["Over 2.5", fmt(DATA.over["2.5"]) + "%"],
    ["Corner medi", fmt(DATA.corners.mean_total)], ["Cartellini medi", fmt(DATA.discipline.cards_total_mean)],
  ].map(([l,v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  // Esiti
  let out = barRow(`1 — ${m.home}`, o["1"]) + barRow("X — Pareggio", o["X"]) + barRow(`2 — ${m.away}`, o["2"]);
  out += `<div style="height:10px"></div>`;
  out += barRow("BTTS (GG)", DATA.btts, "gold");
  for (const [line, p] of Object.entries(DATA.over)) out += barRow(`Over ${line}`, p, "gold");
  out += `<div class="sub" style="margin-top:8px">Doppia chance — 1X: <b>${fmt(o["1X"])}%</b> ·
          X2: <b>${fmt(o["X2"])}%</b> · 12: <b>${fmt(o["12"])}%</b></div>`;
  $("outcomes").innerHTML = out;

  // Top risultati
  $("topscores").innerHTML = DATA.top_scores
    .map(([s,p]) => barRow(s, p, "", 4)).join("");

  // Matrice heatmap
  const labels = [...Array(DATA.score_matrix.length - 1).keys()].map(String)
                 .concat([(DATA.score_matrix.length - 1) + "+"]);
  const maxP = Math.max(...DATA.score_matrix.flat());
  let html = `<table class="heat"><tr><th>${m.home} \\ ${m.away}</th>` +
             labels.map(l => `<th>${l}</th>`).join("") + "</tr>";
  DATA.score_matrix.forEach((row, i) => {
    html += `<tr><th>${labels[i]}</th>` + row.map(p => {
      const a = maxP > 0 ? p / maxP : 0;
      const col = a > 0.55 ? "#04240f" : "var(--txt)";
      return `<td style="background:rgba(57,217,138,${(0.06 + 0.94*a).toFixed(3)});color:${col}">${fmt(p)}</td>`;
    }).join("") + "</tr>";
  });
  $("matrix").innerHTML = html + "</table>";

  // Corner
  const c = DATA.corners;
  let ch = `<div class="sub" style="margin-bottom:8px">${m.home}: <b>${fmt(c.mean_home)}</b> ·
            ${m.away}: <b>${fmt(c.mean_away)}</b> · Totali: <b>${fmt(c.mean_total)}</b> ·
            Più corner: ${m.home} <b>${fmt(c.most.home||0,1)}%</b> / ${m.away} <b>${fmt(c.most.away||0,1)}%</b></div>`;
  for (const [k,p] of Object.entries(c.dist_total)) if (p >= 0.4) ch += barRow(`${k} corner`, p, "", 4);
  ch += `<div style="height:10px"></div>`;
  for (const [line,p] of Object.entries(c.lines)) ch += barRow(`Over ${line}`, p, "gold");
  $("corners").innerHTML = ch;

  // Parate
  const kp = m.keepers, sv = DATA.saves, st = DATA.sot;
  let sh = `<div class="sub" style="margin-bottom:8px">SoT attesi — ${m.home}: <b>${fmt(st.mean_home)}</b> ·
            ${m.away}: <b>${fmt(st.mean_away)}</b></div>`;
  for (const side of ["home","away"]){
    const team = side === "home" ? m.home : m.away;
    sh += `<div style="margin:10px 0 4px"><b>${kp[side].name}</b> (${team})
           <span class="tag">save rate ${fmt(kp[side].save_rate*100,1)}%</span>
           <span class="tag">parate medie ${fmt(sv["mean_"+side])}</span></div>`;
    for (const [k,p] of Object.entries(sv["dist_"+side])) if (p >= 0.4) sh += barRow(`${k} parate`, p, "", 3);
  }
  $("saves").innerHTML = sh;

  // Cartellini
  const d = DATA.discipline;
  let dh = `<div class="sub" style="margin-bottom:8px">
      Falli — ${m.home}: <b>${fmt(d.fouls_mean.home)}</b> · ${m.away}: <b>${fmt(d.fouls_mean.away)}</b><br>
      Gialli — ${m.home}: <b>${fmt(d.yellows_mean.home)}</b> · ${m.away}: <b>${fmt(d.yellows_mean.away)}</b> ·
      Rosso — ${m.home}: <b>${fmt(d.red_prob.home)}%</b> · ${m.away}: <b>${fmt(d.red_prob.away)}%</b></div>`;
  for (const [k,p] of Object.entries(d.cards_dist)) if (p >= 0.4) dh += barRow(`${k} cartellini`, p, "card", 3);
  dh += `<div style="height:10px"></div>`;
  for (const [line,p] of Object.entries(d.cards_lines)) dh += barRow(`Over ${line}`, p, "card");
  $("cards").innerHTML = dh;

  // Marcatori
  let sc = "";
  for (const side of ["home","away"]){
    const team = side === "home" ? m.home : m.away;
    sc += `<div style="margin:12px 0 6px;font-weight:700">${team}</div>
      <table class="scorers"><tr><th>Giocatore</th><th>Ruolo</th>
      <th class="num">Anytime</th><th class="num">Doppietta</th><th class="num">xG sim</th><th class="num">Quota equa</th></tr>`;
    for (const r of DATA.scorers[side]){
      const pen = r.penalty_taker ? ` <span class="pen">®</span>` : "";
      sc += `<tr><td>${r.name}${pen}</td><td>${r.role}</td>
        <td class="num"><b>${fmt(r.anytime)}%</b></td><td class="num">${fmt(r.brace)}%</td>
        <td class="num">${fmt(r.xg_sim,3)}</td><td class="num">${r.fair_odds ? fmt(r.fair_odds) : "—"}</td></tr>`;
    }
    sc += "</table>";
  }
  $("scorers").innerHTML = sc;

  $("footer").textContent =
    "Super Simulator — catena stocastica: tempo di gara → tiri in porta → gol (thinning binomiale sul save rate) → corner (fasce+dominanza) → falli/cartellini (aggressività titolari) → marcatori (categoriale + rigorista).";
}
init();
</script>
</body>
</html>
"""


def export_outputs(agg: dict, html: bool = True) -> list[str]:
    written = []
    json_path = os.path.join(BASE_DIR, "dashboard_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    written.append(json_path)
    if html:
        html_path = os.path.join(BASE_DIR, "dashboard.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(HTML_TEMPLATE.replace("__DATA__", json.dumps(agg, ensure_ascii=False)))
        written.append(html_path)
    return written


# ==============================================================================
# ENTRY POINT
# ==============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Super Simulator — motore Monte Carlo calcio")
    ap.add_argument("--sims", type=int, default=None, help="numero di simulazioni (default 10000)")
    ap.add_argument("--config", type=str, default=None, help="file JSON con la configurazione del match")
    ap.add_argument("--seed", type=int, default=None, help="seed per run riproducibili")
    ap.add_argument("--no-html", action="store_true", help="non generare la dashboard HTML")
    ap.add_argument("--open", action="store_true", help="apri la dashboard nel browser a fine run")
    ap.add_argument("--dump-config", action="store_true", help="scrivi match_template.json e termina")
    args = ap.parse_args()

    if args.dump_config:
        path = os.path.join(BASE_DIR, "match_template.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"Template di configurazione scritto in: {path}")
        return

    config = DEFAULT_CONFIG
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)

    sim = SuperSimulator(config, n_sims=args.sims, seed=args.seed)
    sim.run()
    agg = sim.aggregate()

    print_report(agg)
    written = export_outputs(agg, html=not args.no_html)
    for path in written:
        print(f"  → esportato: {path}")

    if args.open and not args.no_html:
        webbrowser.open("file:///" + written[-1].replace("\\", "/"))


if __name__ == "__main__":
    main()
