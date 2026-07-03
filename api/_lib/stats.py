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


def _last_n_stats(league: dict, team_name: str, n: int = 10) -> dict | None:
    """Gol fatti/subiti e forma dalle ultime `n` partite reali nel DB."""
    recent = [fx for fx in league.get("fixtures", [])
              if fx.get("finished") and fx.get("gh") is not None
              and team_name in (fx["home"]["name"], fx["away"]["name"])]
    recent.sort(key=lambda f: f.get("date") or "")
    recent = recent[-n:]
    if not recent:
        return None
    gf = ga = 0
    form = ""
    for fx in recent:
        home = fx["home"]["name"] == team_name
        mine, theirs = (fx["gh"], fx["ga"]) if home else (fx["ga"], fx["gh"])
        gf += mine
        ga += theirs
        form += "W" if mine > theirs else ("D" if mine == theirs else "L")
    k = len(recent)
    return {"gf": gf / k, "ga": ga / k, "form": form[-5:], "played": k}


def team_profile(league: dict, team_name: str, team_ref: dict | None = None,
                 mode: str = "season") -> dict:
    """Profilo completo di una squadra per il motore Monte Carlo.

    mode="season" → gol e forma dall'intera stagione (classifica reale);
    mode="last10" → ricalcolati sulle ultime 10 partite giocate nel DB."""
    row = _team_row(league, team_name)
    played = int(row.get("played") or 0) if row else 0
    gf = (row["gf"] / played) if (row and played) else config.BASELINE["goals"]
    ga = (row["ga"] / played) if (row and played) else config.BASELINE["goals"]
    form = (row.get("form") if row else "") or ""

    if mode == "last10":
        recent = _last_n_stats(league, team_name)
        if recent:
            gf, ga, form, played = (recent["gf"], recent["ga"],
                                    recent["form"], recent["played"])

    micro = (league.get("teams") or {}).get(team_name) or {}
    players = micro.get("players", [])
    roster = _select_roster(players)
    keeper = roster["keeper"]

    B = config.BASELINE
    save_rate = (micro.get("save_rate") or (micro.get("keeper") or {}).get("save_rate")
                 or B["save_rate"])
    keeper_out = micro.get("keeper") or {
        "name": keeper["name"] if keeper else "Portiere",
        "save_rate": round(save_rate, 3), "saves_pg": None,
        "conceded": None, "appearances": keeper["appearances"] if keeper else None,
    }

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
        "players_mode": (f"{micro.get('source', 'baseline')} · forma ultime {played}"
                         if mode == "last10" else micro.get("source", "baseline")),
        "recent_sample": len(players),
        "penalty_taker_id": roster["penalty_taker_id"],
        "super_sub_ids": roster["super_sub_ids"],
    }
