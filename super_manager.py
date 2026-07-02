#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 SUPER MANAGER — Gestore dinamico di competizioni (Calcio AI)
================================================================================
Server locale (solo standard library) che gestisce:

  • CAMPIONATI (Serie A, Premier League, La Liga): calendario completo
    andata/ritorno, classifica aggiornata in tempo reale, simulazione di
    singole partite, giornate intere o dell'intera stagione.

  • TORNEI A ELIMINAZIONE (Mondiali, Europei, Champions, Europa League,
    Nations League): tabellone dinamico — chi vince avanza automaticamente
    al turno successivo; pareggi risolti con supplementari e rigori.

  • RISULTATI REALI: ogni partita può essere inserita a mano; il tabellone
    e la classifica si riallineano da soli (i turni successivi dipendenti
    da un risultato modificato vengono rigenerati).

  • ANALISI MONTE CARLO: per qualunque partita, il motore super_simulator
    esegue 10.000 simulazioni complete (risultati esatti, corner, tiri in
    porta e parate binomiali sul save rate, cartellini, marcatori).

  • PERSISTENZA: lo stato è salvato in stato_competizioni.json dopo ogni
    azione — riapri il programma e ritrovi tutto come lo avevi lasciato.

Avvio:
    python super_manager.py                 # avvia e apre il browser
    python super_manager.py --port 8650     # porta personalizzata
    python super_manager.py --no-browser    # non aprire il browser
    python super_manager.py --reset         # riparte da zero (nuovi calendari)
================================================================================
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from super_simulator import (DEFAULT_CONFIG, SuperSimulator, sample_binomial,
                             sample_poisson, sample_tempo)
from football_db import COMPETITIONS, TEAMS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "stato_competizioni.json")
APP_PATH = os.path.join(BASE_DIR, "app.html")

RNG = random.Random()
LOCK = threading.Lock()

AVG_GOALS = 1.40
HOME_BOOST, AWAY_MALUS = 1.18, 0.88          # campionati
NEUTRAL_HOME, NEUTRAL_AWAY = 1.03, 0.97      # gare su campo neutro
TEMPO_SHAPE = 10.0
ROUND_NAMES = {16: "Ottavi di finale", 8: "Quarti di finale",
               4: "Semifinali", 2: "Finale"}


# ==============================================================================
# MODELLO RAPIDO (una estrazione stocastica per gara — fa avanzare il torneo)
# ==============================================================================
def _goal_lambdas(home: str, away: str, neutral: bool) -> tuple[float, float]:
    th, ta = TEAMS[home], TEAMS[away]
    bh, ba = (NEUTRAL_HOME, NEUTRAL_AWAY) if neutral else (HOME_BOOST, AWAY_MALUS)
    return (AVG_GOALS * th["att"] * ta["dif"] * bh,
            AVG_GOALS * ta["att"] * th["dif"] * ba)


def quick_sim(home: str, away: str, neutral: bool, knockout: bool) -> dict:
    """Una singola realizzazione della catena stocastica (stessa struttura del
    motore Monte Carlo: tempo → tiri in porta → gol via thinning binomiale)."""
    tempo = sample_tempo(TEMPO_SHAPE, RNG)
    lam_h, lam_a = _goal_lambdas(home, away, neutral)
    sr_h, sr_a = TEAMS[home]["sr"], TEAMS[away]["sr"]

    sot_h = sample_poisson(lam_h / (1 - sr_a) * tempo, RNG)
    sot_a = sample_poisson(lam_a / (1 - sr_h) * tempo, RNG)
    gh = sample_binomial(sot_h, 1 - sr_a, RNG)
    ga = sample_binomial(sot_a, 1 - sr_h, RNG)

    note = ""
    winner = None
    if knockout and gh == ga:
        eh = sample_poisson(lam_h * 0.33, RNG)   # tempi supplementari
        ea = sample_poisson(lam_a * 0.33, RNG)
        gh, ga = gh + eh, ga + ea
        if gh != ga:
            note = "dts"
        else:
            note = "dcr"                          # rigori: peso sulle forze
            winner = home if RNG.random() < lam_h / (lam_h + lam_a) else away
    if winner is None:
        winner = home if gh > ga else away if ga > gh else None
    return {"gh": gh, "ga": ga, "note": note, "vinc": winner}


# ==============================================================================
# CONFIG COMPLETA PER L'ANALISI MONTE CARLO (10.000 sim con super_simulator)
# ==============================================================================
def _build_lineup(team: dict) -> list[dict]:
    """Formazione 10 titolari di movimento: slot generici rimpiazzati dai
    giocatori chiave del database (per il mercato marcatori)."""
    slots = (
        [{"name": f"Difensore {i}", "role": "DIF", "xg": 0.85, "aggr": team["aggr"]} for i in range(1, 5)]
        + [{"name": f"Centrocampista {i}", "role": "CEN", "xg": 1.00, "aggr": team["aggr"]} for i in range(1, 5)]
        + [{"name": f"Attaccante {i}", "role": "ATT", "xg": 1.30, "aggr": 0.95} for i in range(1, 3)]
    )
    for star in team["stars"]:
        entry = {"name": star["name"], "role": star["role"], "xg": star["xg"],
                 "aggr": team["aggr"], "pen": star["pen"]}
        target = next((i for i, s in enumerate(slots)
                       if s["role"] == star["role"] and s["name"].split()[0] in
                       ("Difensore", "Centrocampista", "Attaccante")), None)
        if target is None:  # nessuno slot libero del ruolo: sacrifica un centrocampista
            target = next((i for i, s in enumerate(slots)
                           if s["name"].startswith("Centrocampista")), None)
        if target is not None:
            slots[target] = entry
    return slots


def _team_cfg(name: str) -> dict:
    t = TEAMS[name]
    return {
        "name": name,
        "attack": t["att"], "defense": t["dif"],
        "flank_left": round(0.85 + 0.25 * t["att"], 3),
        "flank_right": round(0.80 + 0.25 * t["att"], 3),
        "keeper": {"name": t["gk"], "save_rate": t["sr"]},
        "lineup": _build_lineup(t),
    }


def analyze_match(home: str, away: str, neutral: bool, n_sims: int = 10000,
                  label: str = "") -> dict:
    league = copy.deepcopy(DEFAULT_CONFIG["league"])
    if neutral:
        league["home_boost"], league["away_malus"] = NEUTRAL_HOME, NEUTRAL_AWAY
    cfg = {
        "match": {"competition": label or "Analisi match", "n_sims": n_sims},
        "league": league,
        "teams": {"home": _team_cfg(home), "away": _team_cfg(away)},
    }
    sim = SuperSimulator(cfg, n_sims=n_sims)
    sim.run()
    return sim.aggregate()


# ==============================================================================
# CALENDARI E TABELLONI
# ==============================================================================
def berger_rounds(teams: list[str]) -> list[list[tuple[str, str]]]:
    """Girone all'italiana (andata+ritorno) con l'algoritmo del cerchio."""
    ts = list(teams)
    if len(ts) % 2:
        ts.append(None)
    n = len(ts)
    andata = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ts[i], ts[n - 1 - i]
            if a and b:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
        andata.append(pairs)
        ts = [ts[0], ts[-1]] + ts[1:-1]
    ritorno = [[(b, a) for a, b in rd] for rd in andata]
    return andata + ritorno


def init_league(key: str) -> dict:
    teams = list(COMPETITIONS[key]["teams"])
    RNG.shuffle(teams)
    fixtures = [{"g": g + 1, "h": h, "a": a, "gh": None, "ga": None}
                for g, rd in enumerate(berger_rounds(teams)) for h, a in rd]
    return {"tipo": "league", "fixtures": fixtures}


def init_knockout(key: str) -> dict:
    teams = COMPETITIONS[key]["teams"]
    first = [{"h": teams[i], "a": teams[i + 1], "gh": None, "ga": None,
              "note": "", "vinc": None} for i in range(0, len(teams), 2)]
    return {"tipo": "knockout", "rounds": [first], "campione": None}


def standings(fixtures: list[dict]) -> list[dict]:
    table: dict[str, dict] = {}

    def row(t):
        return table.setdefault(t, {"squadra": t, "pt": 0, "g": 0, "v": 0,
                                    "n": 0, "p": 0, "gf": 0, "gs": 0})
    for f in fixtures:
        row(f["h"]); row(f["a"])
        if f["gh"] is None:
            continue
        rh, ra = row(f["h"]), row(f["a"])
        rh["g"] += 1; ra["g"] += 1
        rh["gf"] += f["gh"]; rh["gs"] += f["ga"]
        ra["gf"] += f["ga"]; ra["gs"] += f["gh"]
        if f["gh"] > f["ga"]:
            rh["v"] += 1; ra["p"] += 1; rh["pt"] += 3
        elif f["gh"] < f["ga"]:
            ra["v"] += 1; rh["p"] += 1; ra["pt"] += 3
        else:
            rh["n"] += 1; ra["n"] += 1; rh["pt"] += 1; ra["pt"] += 1
    rows = list(table.values())
    for r in rows:
        r["dr"] = r["gf"] - r["gs"]
    rows.sort(key=lambda r: (-r["pt"], -r["dr"], -r["gf"], r["squadra"]))
    return rows


def ko_advance(st: dict) -> None:
    """Se un turno è completo, genera il successivo accoppiando i vincitori.
    Finale completata ⇒ proclama il campione."""
    while True:
        last = st["rounds"][-1]
        if any(t["vinc"] is None for t in last):
            return
        if len(last) == 1:
            st["campione"] = last[0]["vinc"]
            return
        winners = [t["vinc"] for t in last]
        st["rounds"].append([{"h": winners[i], "a": winners[i + 1], "gh": None,
                              "ga": None, "note": "", "vinc": None}
                             for i in range(0, len(winners), 2)])


# ==============================================================================
# GESTORE DI STATO
# ==============================================================================
class Manager:
    def __init__(self, reset: bool = False):
        self.state: dict = {}
        if not reset and os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, encoding="utf-8") as f:
                    self.state = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.state = {}
        changed = False
        for key, comp in COMPETITIONS.items():
            if key not in self.state or self.state[key].get("tipo") != comp["tipo"]:
                self.state[key] = (init_league(key) if comp["tipo"] == "league"
                                   else init_knockout(key))
                changed = True
        if changed:
            self.save()

    def save(self) -> None:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)

    # -------------------------------------------------------------- snapshot
    def full_state(self) -> dict:
        out = {}
        for key, comp in COMPETITIONS.items():
            st = self.state[key]
            entry = {"nome": comp["nome"], "icona": comp["icona"], "tipo": comp["tipo"]}
            if comp["tipo"] == "league":
                fx = st["fixtures"]
                entry["giornate"] = max(f["g"] for f in fx)
                entry["giornata_corrente"] = next(
                    (g for g in range(1, entry["giornate"] + 1)
                     if any(f["g"] == g and f["gh"] is None for f in fx)),
                    entry["giornate"])
                entry["fixtures"] = fx
                entry["classifica"] = standings(fx)
            else:
                entry["rounds"] = st["rounds"]
                entry["round_names"] = [ROUND_NAMES.get(len(r) * 2, "Turno")
                                        for r in st["rounds"]]
                entry["campione"] = st["campione"]
                entry["neutral"] = comp.get("neutral", False)
            out[key] = entry
        return out

    # ---------------------------------------------------------------- azioni
    def simulate(self, comp: str, scope: str, giornata=None, round_idx=None, idx=None) -> None:
        meta, st = COMPETITIONS[comp], self.state[comp]
        if meta["tipo"] == "league":
            fx = st["fixtures"]
            if scope == "match":
                targets = [fx[idx]] if fx[idx]["gh"] is None else []
            elif scope == "round":
                targets = [f for f in fx if f["g"] == giornata and f["gh"] is None]
            else:
                targets = [f for f in fx if f["gh"] is None]
            for f in targets:
                r = quick_sim(f["h"], f["a"], neutral=False, knockout=False)
                f["gh"], f["ga"] = r["gh"], r["ga"]
        else:
            neutral = meta.get("neutral", False)
            while True:
                rounds = st["rounds"]
                if scope == "match":
                    targets = [(round_idx, idx)] if rounds[round_idx][idx]["vinc"] is None else []
                else:
                    ri = len(rounds) - 1
                    targets = [(ri, i) for i, t in enumerate(rounds[ri]) if t["vinc"] is None]
                for ri, i in targets:
                    tie = rounds[ri][i]
                    r = quick_sim(tie["h"], tie["a"], neutral=neutral, knockout=True)
                    tie.update(gh=r["gh"], ga=r["ga"], note=r["note"], vinc=r["vinc"])
                ko_advance(st)
                if scope != "all" or st["campione"]:
                    break
        self.save()

    def set_result(self, comp: str, gh: int, ga: int, giornata=None,
                   round_idx=None, idx=None, vincitore=None) -> None:
        meta, st = COMPETITIONS[comp], self.state[comp]
        if meta["tipo"] == "league":
            st["fixtures"][idx].update(gh=gh, ga=ga)
        else:
            # un risultato modificato invalida i turni successivi
            st["rounds"] = st["rounds"][:round_idx + 1]
            st["campione"] = None
            tie = st["rounds"][round_idx][idx]
            if gh == ga:
                if vincitore not in (tie["h"], tie["a"]):
                    raise ValueError("con un pareggio serve il vincitore ai rigori")
                tie.update(gh=gh, ga=ga, note="dcr", vinc=vincitore)
            else:
                tie.update(gh=gh, ga=ga, note="",
                           vinc=tie["h"] if gh > ga else tie["a"])
            ko_advance(st)
        self.save()

    def reset(self, comp: str) -> None:
        self.state[comp] = (init_league(comp) if COMPETITIONS[comp]["tipo"] == "league"
                            else init_knockout(comp))
        self.save()


# ==============================================================================
# SERVER HTTP (stdlib)
# ==============================================================================
MANAGER: Manager | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silenzia il log per richiesta
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html", "/app.html"):
            with open(APP_PATH, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            with LOCK:
                self._json(MANAGER.full_state())
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"errore": "JSON non valido"}, 400)
        try:
            if self.path == "/api/sim":
                with LOCK:
                    MANAGER.simulate(body["comp"], body.get("scope", "match"),
                                     giornata=body.get("giornata"),
                                     round_idx=body.get("round"), idx=body.get("idx"))
                    self._json(MANAGER.full_state())
            elif self.path == "/api/risultato":
                with LOCK:
                    MANAGER.set_result(body["comp"], int(body["gh"]), int(body["ga"]),
                                       giornata=body.get("giornata"),
                                       round_idx=body.get("round"), idx=body.get("idx"),
                                       vincitore=body.get("vincitore"))
                    self._json(MANAGER.full_state())
            elif self.path == "/api/reset":
                with LOCK:
                    MANAGER.reset(body["comp"])
                    self._json(MANAGER.full_state())
            elif self.path == "/api/analyze":
                # il Monte Carlo gira fuori dal lock (10.000 sim ≈ qualche secondo)
                agg = analyze_match(body["home"], body["away"],
                                    neutral=body.get("neutral", False),
                                    n_sims=int(body.get("sims", 10000)),
                                    label=body.get("label", ""))
                self._json(agg)
            else:
                self._json({"errore": "endpoint sconosciuto"}, 404)
        except (KeyError, IndexError, ValueError) as exc:
            self._json({"errore": str(exc)}, 400)


def main() -> None:
    global MANAGER
    ap = argparse.ArgumentParser(description="Super Manager — competizioni dinamiche")
    ap.add_argument("--port", type=int, default=8650)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reset", action="store_true", help="rigenera tutti i calendari")
    args = ap.parse_args()

    MANAGER = Manager(reset=args.reset)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 64)
    print("  SUPER MANAGER attivo")
    print(f"  Interfaccia:  {url}")
    print(f"  Stato salvato in: {STATE_PATH}")
    print("  Ctrl+C per uscire")
    print("=" * 64)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto del server.")


if __name__ == "__main__":
    main()
