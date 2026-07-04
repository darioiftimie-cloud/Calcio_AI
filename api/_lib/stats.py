# -*- coding: utf-8 -*-
"""Costruzione dei profili statistici per la simulazione, a partire dal DB.

- Gol fatti/subiti e forma: dalla classifica reale (football-data.org).
- Micro-eventi (tiri, tiri in porta, corner, falli, save rate portiere) e pool
  giocatori: dai profili FBref/Understat agganciati dall'updater; in assenza si
  usano le medie di lega (config.BASELINE).
"""

from . import config


def _team_row(league: dict, team_name: str) -> dict | None:
    for g in league.get("standings", []):
        for r in g["rows"]:
            if r["team"] == team_name or r.get("short") == team_name:
                return r
    return None


def _select_roster(players: list[dict]) -> dict:
    """Portiere titolare, rigorista e super-sub dal pool giocatori."""
    players = [p for p in players if p.get("appearances", 0) > 0 or p.get("minutes", 0) > 0]

    keepers = [p for p in players if p["position"] == "G"]
    keeper = max(keepers, key=lambda p: p["minutes"], default=None)

    outfield = [p for p in players if p["position"] != "G"]
    outfield.sort(key=lambda p: (p["goals"], p["shots_on"], p["minutes"]), reverse=True)

    pen_taker = max(outfield, key=lambda p: p["penalties"], default=None)
    pen_taker_id = (pen_taker["id"] if pen_taker and pen_taker["penalties"] > 0
                    else (outfield[0]["id"] if outfield else None))

    subs = sorted((p for p in outfield if p["sub_in"] >= 2 and p["sub_in"] > p["lineups"]),
                  key=lambda p: p["sub_in"], reverse=True)[:3]
    super_subs = [p["id"] for p in subs
                  if (p["goals"] + p["assists"]) / max(p["appearances"], 1) >= 0.25]

    return {"keeper": keeper, "outfield": outfield[:22],
            "penalty_taker_id": pen_taker_id, "super_sub_ids": super_subs}


def _aggregate(fixtures: list[dict], team_name: str) -> dict | None:
    """Media gol fatti/subiti + stringa forma da una lista di partite giocate."""
    if not fixtures:
        return None
    gf = ga = 0
    form = ""
    for fx in fixtures:
        home = fx["home"]["name"] == team_name
        mine, theirs = (fx["gh"], fx["ga"]) if home else (fx["ga"], fx["gh"])
        gf += mine
        ga += theirs
        form += "W" if mine > theirs else ("D" if mine == theirs else "L")
    k = len(fixtures)
    return {"gf": gf / k, "ga": ga / k, "form": form, "played": k}


def _team_played(league: dict, team_name: str,
                 before_date: str | None = None) -> list[dict]:
    """Partite già giocate dalla squadra nel DB, ordinate cronologicamente.
    Se `before_date` è dato, esclude le gare a partire da quella data (così
    l'analisi di un match resta 'predittiva': solo ciò che l'ha preceduto)."""
    played = [fx for fx in league.get("fixtures", [])
              if fx.get("finished") and fx.get("gh") is not None
              and team_name in (fx["home"]["name"], fx["away"]["name"])]
    if before_date:
        played = [fx for fx in played if (fx.get("date") or "") < before_date]
    played.sort(key=lambda f: f.get("date") or "")
    return played


def _last_n_stats(league: dict, team_name: str, n: int = 10) -> dict | None:
    """Gol fatti/subiti e forma dalle ultime `n` partite reali nel DB."""
    stat = _aggregate(_team_played(league, team_name)[-n:], team_name)
    if stat:
        stat["form"] = stat["form"][-5:]
    return stat


def _tournament_stats(league: dict, team_name: str,
                      before_date: str | None = None) -> dict | None:
    """Gol fatti/subiti e forma da TUTTE le partite del torneo giocate dalla
    squadra dall'inizio (fino a prima di `before_date`). Serve alle coppe:
    più la squadra avanza, più gare entrano nel campione (quarti→semi→finale)."""
    stat = _aggregate(_team_played(league, team_name, before_date), team_name)
    if stat:
        stat["form"] = stat["form"][-6:]
    return stat


def team_profile(league: dict, team_name: str, team_ref: dict | None = None,
                 mode: str = "season", is_cup: bool = False,
                 before_date: str | None = None) -> dict:
    """Profilo completo di una squadra per il motore Monte Carlo.

    Coppe/tornei (is_cup) → gol e forma da TUTTE le gare del torneo giocate
      dall'inizio fino a prima di `before_date` (analisi cumulativa);
    mode="season" → gol e forma dall'intera stagione (classifica reale);
    mode="last10" → ricalcolati sulle ultime 10 partite giocate nel DB."""
    row = _team_row(league, team_name)
    played = int(row.get("played") or 0) if row else 0
    gf = (row["gf"] / played) if (row and played) else config.BASELINE["goals"]
    ga = (row["ga"] / played) if (row and played) else config.BASELINE["goals"]
    form = (row.get("form") if row else "") or ""
    tournament_games = 0

    if is_cup:
        tstat = _tournament_stats(league, team_name, before_date)
        if tstat:
            gf, ga, form, played = (tstat["gf"], tstat["ga"],
                                    tstat["form"], tstat["played"])
            tournament_games = tstat["played"]
    elif mode == "last10":
        recent = _last_n_stats(league, team_name)
        if recent:
            gf, ga, form, played = (recent["gf"], recent["ga"],
                                    recent["form"], recent["played"])

    micro = (league.get("teams") or {}).get(team_name) or {}
    players = micro.get("players", [])
    roster = _select_roster(players)
    keeper = roster["keeper"]

    B = config.BASELINE

    # Medie REALI della squadra nel torneo/stagione in corso (boxscore ESPN,
    # accumulate dall'updater). Entrano con shrinkage n/(n+K): con 3 gare il
    # dato osservato pesa metà, a 10+ gare domina. Il prior è il profilo
    # FBref/Understat se c'è, altrimenti la baseline di lega.
    treal = (league.get("team_micro") or {}).get(team_name)
    if treal and treal.get("played"):
        n = treal["played"]
        w = n / (n + 3.0)

        def _obs(key: str, prior: float, digits: int = 2) -> float:
            v = treal.get(key)
            return round(prior + w * (v - prior), digits) if v is not None else prior

        micro = {**micro,
                 "shots_pg": _obs("shots_pg", micro.get("shots_pg", B["shots"])),
                 "sot_pg": _obs("sot_pg", micro.get("sot_pg", B["sot"])),
                 "corners_pg": _obs("corners_pg", micro.get("corners_pg", B["corners"])),
                 "fouls_pg": _obs("fouls_pg", micro.get("fouls_pg", B["fouls"])),
                 "yellow_pg": _obs("yellow_pg", micro.get("yellow_pg", B["yellows"])),
                 "red_pg": _obs("red_pg", micro.get("red_pg", B["reds"]), 3),
                 "save_rate": _obs("save_rate",
                                   micro.get("save_rate")
                                   or (micro.get("keeper") or {}).get("save_rate")
                                   or B["save_rate"], 3),
                 "micro_real_games": n}

    # Senza profilo micro-evento reale (nazionali, club fuori dalle Big 5) i
    # tiri/corner di base vengono scalati sulla forza d'attacco osservata,
    # con shrinkage sul campione: chi segna il doppio della media tira di
    # più, chi non segna tira meno. Prima tutte le squadre senza profilo
    # condividevano le stesse identiche medie di lega.
    if "shots_pg" not in micro:
        w = played / (played + 5.0) if played else 0.0
        att = 1.0 + w * (gf / B["goals"] - 1.0)
        att = min(max(att, 0.60), 1.70)
        micro = {**micro,
                 "shots_pg": round(B["shots"] * att, 2),
                 "sot_pg": round(B["sot"] * att, 2),
                 "corners_pg": round(B["corners"] * att ** 0.7, 2)}

    save_rate = (micro.get("save_rate") or (micro.get("keeper") or {}).get("save_rate")
                 or B["save_rate"])
    keeper_out = micro.get("keeper") or {
        "name": keeper["name"] if keeper else "Portiere",
        "save_rate": round(save_rate, 3), "saves_pg": None,
        "conceded": None, "appearances": keeper["appearances"] if keeper else None,
    }

    if is_cup and tournament_games:
        players_mode = f"torneo · {tournament_games} gare dall'inizio"
    elif mode == "last10":
        players_mode = f"{micro.get('source', 'baseline')} · forma ultime {played}"
    else:
        players_mode = micro.get("source", "baseline")
    if micro.get("micro_real_games"):
        players_mode += f" · micro reali ({micro['micro_real_games']} gare)"

    return {
        "team_id": (team_ref or {}).get("id") or (row or {}).get("team_id"),
        "name": team_name,
        "played": played or micro.get("games") or 0,
        "gf": gf, "ga": ga, "form": form,
        "shots_pg": micro.get("shots_pg", B["shots"]),
        "sot_pg": micro.get("sot_pg", B["sot"]),
        "corners_pg": micro.get("corners_pg", B["corners"]),
        "fouls_pg": micro.get("fouls_pg", B["fouls"]),
        "yellow_pg": micro.get("yellow_pg", B["yellows"]),
        "red_pg": micro.get("red_pg", B["reds"]),
        "save_rate": round(save_rate, 3),
        "keeper": keeper_out,
        "players": roster["outfield"],
        "players_mode": players_mode,
        "tournament_games": tournament_games,
        "recent_sample": len(players),
        "penalty_taker_id": roster["penalty_taker_id"],
        "super_sub_ids": roster["super_sub_ids"],
    }
