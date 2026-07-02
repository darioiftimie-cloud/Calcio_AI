#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 UPDATER — popola il database JSON con dati reali gratuiti
================================================================================
Sorgenti:
  · football-data.org  → risultati, classifiche, calendari, marcatori
  · FBref / Understat   → micro-eventi (tiri, SoT, corner, falli, save rate,
                          statistiche giocatori) via lo scraper api/_lib/fbref.py

Uso:
  python updater.py                      # tutte le competizioni, stagione 2026
  python updater.py --season 2025        # forza la stagione d'inizio
  python updater.py --leagues serie_a,champions_league
  python updater.py --no-micro           # salta lo scraping micro-eventi
  python updater.py --micro-source understat   # forza la sorgente micro-eventi

Scrive in data/*.json. Gli endpoint serverless (api/) leggono solo da qui.
================================================================================
"""

import argparse
import sys
from datetime import datetime, timezone

# stdout UTF-8: i log contengono simboli (✔, —, emoji) fuori dalla codepage
# Windows di default (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, "api")

from _lib import config                                     # noqa: E402
from _lib import db                                         # noqa: E402
from _lib import footballdata as fd                         # noqa: E402
from _lib.fbref import fetch_micro_profiles, match_profile  # noqa: E402

_FINISHED = ("FINISHED", "AWARDED")
_KO_STAGES = {"PLAYOFFS", "PLAYOFF_ROUND", "LAST_32", "LAST_16", "ROUND_OF_16",
              "QUARTER_FINALS", "SEMI_FINALS", "FINAL", "THIRD_PLACE",
              "PRELIMINARY_ROUND", "1ST_QUALIFYING_ROUND", "2ND_QUALIFYING_ROUND",
              "3RD_QUALIFYING_ROUND"}
_STAGE_IT = {
    "PLAYOFFS": "Playoff", "PLAYOFF_ROUND": "Playoff", "LAST_32": "Sedicesimi",
    "LAST_16": "Ottavi", "ROUND_OF_16": "Ottavi", "QUARTER_FINALS": "Quarti",
    "SEMI_FINALS": "Semifinali", "FINAL": "Finale", "THIRD_PLACE": "Finale 3° posto",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def season_label(year: int) -> str:
    return f"{year}-{str(year + 1)[2:]}"


# ------------------------------------------------------- normalizzazione FD
def _team_obj(t: dict) -> dict:
    return {"id": t.get("id"), "name": t.get("name") or t.get("shortName") or "?",
            "short": t.get("shortName") or t.get("name") or "?",
            "logo": t.get("crest")}


def norm_match(m: dict, season: int) -> dict:
    score = m.get("score") or {}
    ft = score.get("fullTime") or {}
    winner = score.get("winner")
    stage = m.get("stage") or ""
    pens = score.get("penalties") or {}
    home, away = _team_obj(m.get("homeTeam") or {}), _team_obj(m.get("awayTeam") or {})
    home["winner"] = winner == "HOME_TEAM" or None if winner else None
    away["winner"] = winner == "AWAY_TEAM" or None if winner else None
    matchday = m.get("matchday")
    if stage in _STAGE_IT:
        rnd = _STAGE_IT[stage]
    elif stage and stage not in ("REGULAR_SEASON", "GROUP_STAGE", "LEAGUE_STAGE"):
        rnd = stage.replace("_", " ").title()
    else:
        rnd = f"Giornata {matchday}" if matchday else (m.get("group") or "")
    return {
        "fixture_id": m.get("id"),
        "date": m.get("utcDate"),
        "status": m.get("status"),
        "finished": m.get("status") in _FINISHED,
        "knockout": stage in _KO_STAGES,
        "round": rnd, "stage": stage, "group": m.get("group"),
        "matchday": matchday, "season": season,
        "venue": m.get("venue"), "city": m.get("venue"),
        "home": home, "away": away,
        "gh": ft.get("home"), "ga": ft.get("away"),
        "rigori": ({"home": pens.get("home"), "away": pens.get("away")}
                   if pens.get("home") is not None else None),
    }


def _row_descr(tipo: str, pos: int, n: int) -> str | None:
    """Descrizione qualificazione (per la colorazione della classifica)."""
    if tipo == "cup":  # fase campionato Champions: 1-8 diretti, 9-24 playoff
        if pos <= 8:
            return "next round"
        if pos <= 24:
            return "knockout play-off"
        return None
    if pos <= 4:
        return "Champions League"
    if pos == 5 or pos == 6:
        return "Europa League"
    if pos >= n - 2:
        return "relegation"
    return None


def norm_standings(raw: dict, tipo: str, nome: str) -> list[dict]:
    groups = []
    for table in raw.get("standings", []):
        if table.get("type") != "TOTAL":
            continue
        rows_raw = table.get("table") or []
        n = len(rows_raw)
        rows = []
        for r in rows_raw:
            t = r.get("team") or {}
            pos = r.get("position")
            rows.append({
                "rank": pos,
                "team_id": t.get("id"),
                "team": t.get("name") or t.get("shortName"),
                "short": t.get("shortName") or t.get("name"),
                "logo": t.get("crest"),
                "points": r.get("points"),
                "played": r.get("playedGames"),
                "win": r.get("won"), "draw": r.get("draw"), "lose": r.get("lost"),
                "gf": r.get("goalsFor"), "ga": r.get("goalsAgainst"),
                "diff": r.get("goalDifference"),
                "form": (r.get("form") or "").replace(",", "")[-5:],
                "descrizione": _row_descr(tipo, pos, n) if pos else None,
            })
        if rows:
            groups.append({"nome": table.get("group") or nome, "rows": rows})
    return groups


def norm_scorers(raw: list[dict]) -> list[dict]:
    out = []
    for s in raw:
        p = s.get("player") or {}
        t = s.get("team") or {}
        out.append({
            "name": p.get("name"), "team": t.get("name") or t.get("shortName"),
            "goals": s.get("goals") or 0, "assists": s.get("assists") or 0,
            "penalties": s.get("penalties") or 0,
            "played": s.get("playedMatches") or 0,
        })
    return out


# --------------------------------------------------------------- pipeline
def build_league(key: str, meta: dict) -> dict:
    code, tipo, nome = meta["fd_code"], meta["tipo"], meta["nome"]
    print(f"\n[{key}] {nome} ({code})")
    res = fd.resolve_result_season(code)
    rs, cs = res["results"], res["calendar"]
    print(f"  stagione risultati={season_label(rs)}  calendario={season_label(cs)}")

    # calendario: risultati della stagione rs + eventuali partite future di cs
    matches = list(res["matches"].get(rs, []))
    if cs != rs:
        future = [m for m in res["matches"].get(cs, [])
                  if m.get("status") not in _FINISHED]
        matches += future
    fixtures, seen = [], set()
    for m in matches:
        mid = m.get("id")
        if mid in seen:
            continue
        seen.add(mid)
        season_of = cs if (m in res["matches"].get(cs, []) and m.get("status") not in _FINISHED) else rs
        fixtures.append(norm_match(m, season_of))

    try:
        standings = norm_standings(fd.competition_standings(code, rs), tipo, nome)
    except fd.FootballDataError as exc:
        print(f"  ! classifica non disponibile: {exc}")
        standings = []
    scorers = norm_scorers(fd.competition_scorers(code, rs))
    print(f"  partite={len(fixtures)}  classifica_gironi={len(standings)}  marcatori={len(scorers)}")

    return {
        "meta": {
            "key": key, "nome": nome, "icona": meta["icona"], "tipo": tipo,
            "fd_code": code, "season": rs, "calendar_season": cs,
            "season_label": season_label(rs),
            "calendar_label": season_label(cs),
            "preferita": config.SEASON,
            "piano_limitato": rs != config.SEASON,
            "generato": now_iso(),
        },
        "standings": standings,
        "fixtures": fixtures,
        "scorers": scorers,
        "teams": {},   # riempito dallo step micro-eventi
    }


def attach_micro(leagues: dict, profiles: dict, source: str) -> None:
    """Aggancia i profili micro-evento (con matcher tollerante) alle squadre."""
    matched = unmatched = 0
    for key, data in leagues.items():
        data["teams"] = {}
        names = set()
        for g in data["standings"]:
            for r in g["rows"]:
                names.add((r["team"], r.get("short")))
        for fx in data["fixtures"]:
            names.add((fx["home"]["name"], fx["home"].get("short")))
            names.add((fx["away"]["name"], fx["away"].get("short")))
        for full, short in names:
            prof = match_profile(profiles, full, short)
            if prof:
                data["teams"][full] = prof
                matched += 1
            else:
                unmatched += 1
    print(f"  squadre agganciate a {source}: {matched}  (senza match: {unmatched})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Popola il DB JSON con dati reali gratuiti")
    ap.add_argument("--season", type=int, default=config.SEASON)
    ap.add_argument("--leagues", default="", help="chiavi separate da virgola")
    ap.add_argument("--no-micro", action="store_true", help="salta i micro-eventi")
    ap.add_argument("--micro-only", action="store_true",
                    help="rigenera solo i micro-eventi dal DB esistente "
                         "(nessuna chiamata a football-data.org)")
    ap.add_argument("--micro-source", choices=["fbref", "understat"], default="fbref")
    args = ap.parse_args()
    config.SEASON = args.season
    config.SEASON_FALLBACKS = list(dict.fromkeys([args.season, 2025, 2024]))

    keys = [k.strip() for k in args.leagues.split(",") if k.strip()] or list(config.LEAGUES)
    print(f"Aggiornamento DB — stagione preferita {season_label(args.season)} — "
          f"competizioni: {', '.join(keys)}")

    leagues: dict[str, dict] = {}
    if args.micro_only:
        print("Modalità --micro-only: riuso i dati football-data.org già nel DB")
        for key in keys:
            try:
                leagues[key] = db.read_league(key)
            except db.DBError:
                print(f"  ! {key} non nel DB, salto (esegui prima un update completo)")
    else:
        for key in keys:
            meta = config.LEAGUES.get(key)
            if not meta:
                print(f"  ! competizione sconosciuta: {key}")
                continue
            leagues[key] = build_league(key, meta)

    # --- micro-eventi (FBref → Understat) sulle Big 5 --------------------
    micro_source = "nessuna"
    if not args.no_micro and leagues:
        results_season = max((d["meta"]["season"] for d in leagues.values()),
                             default=args.season)
        fbref_season = f"{str(results_season)[2:]}{str(results_season + 1)[2:]}"
        print(f"\nMicro-eventi (stagione FBref/Understat {fbref_season})…")
        profiles, micro_source = fetch_micro_profiles(
            config.FBREF_BIG5, fbref_season, prefer=args.micro_source)
        print(f"  profili raccolti: {len(profiles)} (sorgente: {micro_source})")
        if profiles:
            attach_micro(leagues, profiles, micro_source)

    # --- scrittura DB ----------------------------------------------------
    db.ensure_dir()
    index = {"generato": now_iso(), "preferita": season_label(args.season),
             "micro_source": micro_source,
             "account": {"piano": "football-data.org · free",
                         "micro": micro_source, "aggiornato": now_iso()[:10]},
             "leagues": []}
    for key, data in leagues.items():
        db.write_league(key, data)
        m = data["meta"]
        index["leagues"].append({
            "key": key, "nome": m["nome"], "icona": m["icona"], "tipo": m["tipo"],
            "season": m["season_label"], "piano_limitato": m["piano_limitato"]})
    db.write_index(index)
    print(f"\n✔ DB aggiornato in {db.DATA_DIR}")
    print(f"  competizioni: {len(leagues)}  ·  micro-eventi: {micro_source}")


if __name__ == "__main__":
    main()
