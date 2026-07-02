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


def team_profile(league: dict, team_name: str, team_ref: dict | None = None) -> dict:
    """Profilo completo di una squadra per il motore Monte Carlo."""
    row = _team_row(league, team_name)
    played = int(row.get("played") or 0) if row else 0
    gf = (row["gf"] / played) if (row and played) else config.BASELINE["goals"]
    ga = (row["ga"] / played) if (row and played) else config.BASELINE["goals"]
    form = (row.get("form") if row else "") or ""

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
        "players_mode": micro.get("source", "baseline"),
        "recent_sample": len(players),
        "penalty_taker_id": roster["penalty_taker_id"],
        "super_sub_ids": roster["super_sub_ids"],
    }
