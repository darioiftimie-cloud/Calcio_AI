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

from _lib import apifootball as af                          # noqa: E402
from _lib import config                                     # noqa: E402
from _lib import db                                         # noqa: E402
from _lib import footballdata as fd                         # noqa: E402
from _lib.fbref import fetch_micro_profiles, match_profile, norm_team  # noqa: E402

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
    home["winner"] = (winner == "HOME_TEAM") if winner else None
    away["winner"] = (winner == "AWAY_TEAM") if winner else None
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
    if tipo == "cup":
        if n <= 6:  # gironi da 4 (Mondiali, Europei, Nations League): prime 2
            return "next round" if pos <= 2 else None
        # fase campionato Champions/Europa League: 1-8 diretti, 9-24 playoff
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


def _pretty_group(g: str | None) -> str:
    return (g or "").replace("GROUP_", "Girone ").replace("Group ", "Girone ")


def standings_from_fixtures(fixtures: list[dict], tipo: str) -> list[dict]:
    """Ricostruisce le classifiche dei gironi dai risultati del calendario.

    Serve per i tornei dove football-data.org non fornisce tabelle per girone:
    ai Mondiali risponde con un'unica tabella da 48 squadre, agli Europei
    l'endpoint standings non esiste proprio."""
    acc: dict[tuple, dict] = {}
    for fx in sorted(fixtures, key=lambda f: f.get("date") or ""):
        g = fx.get("group")
        gh, ga = fx.get("gh"), fx.get("ga")
        if fx.get("knockout") or not fx.get("finished") or not g \
                or gh is None or ga is None:
            continue
        for team, gf, gs in ((fx["home"], gh, ga), (fx["away"], ga, gh)):
            row = acc.setdefault((g, team["name"]), {
                "team_id": team.get("id"), "team": team["name"],
                "short": team.get("short"), "logo": team.get("logo"),
                "points": 0, "played": 0, "win": 0, "draw": 0, "lose": 0,
                "gf": 0, "ga": 0, "form": ""})
            row["played"] += 1
            row["gf"] += gf
            row["ga"] += gs
            esito = "W" if gf > gs else ("D" if gf == gs else "L")
            row["win"] += esito == "W"
            row["draw"] += esito == "D"
            row["lose"] += esito == "L"
            row["points"] += {"W": 3, "D": 1, "L": 0}[esito]
            row["form"] = (row["form"] + esito)[-5:]

    by_group: dict[str, list] = {}
    for (g, _), row in acc.items():
        by_group.setdefault(g, []).append(row)
    out = []
    for g in sorted(by_group):
        rows = sorted(by_group[g], key=lambda r: (-r["points"], r["ga"] - r["gf"],
                                                  -r["gf"], r["team"]))
        n = len(rows)
        for i, r in enumerate(rows, 1):
            r["rank"] = i
            r["diff"] = r["gf"] - r["ga"]
            r["descrizione"] = _row_descr(tipo, i, n)
        out.append({"nome": _pretty_group(g), "rows": rows})
    return out


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


# ----------------------------------------------- normalizzazione API-Football
# (usata per Europa League e Nations League, assenti da football-data.org)
_APIF_FINISHED = {"FT", "AET", "PEN", "AWD", "WO"}
_APIF_LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
_APIF_ROUND_IT = {
    "knockout round play-offs": "Playoff", "round of 32": "Sedicesimi",
    "round of 16": "Ottavi", "quarter-finals": "Quarti",
    "semi-finals": "Semifinali", "final": "Finale",
    "3rd place final": "Finale 3° posto", "third place final": "Finale 3° posto",
}
_APIF_KO_WORDS = ("play-off", "playoff", "round of", "quarter", "semi", "final")


def _apif_round(raw: str) -> tuple[str, bool]:
    """(nome turno in italiano, è_knockout) dal round API-Football."""
    low = (raw or "").strip().lower()
    if low in _APIF_ROUND_IT:
        return _APIF_ROUND_IT[low], True
    if low.startswith(("league stage", "league phase")):
        num = low.rsplit("-", 1)[-1].strip()
        return (f"Giornata {num}" if num.isdigit() else raw), False
    if "group" in low or "league" in low:
        return raw, False
    ko = any(w in low for w in _APIF_KO_WORDS)
    return raw, ko


def _apif_team(t: dict) -> dict:
    return {"id": t.get("id"), "name": t.get("name") or "?",
            "short": t.get("name") or "?", "logo": t.get("logo"),
            "winner": t.get("winner")}


def norm_match_apif(m: dict, season: int) -> dict:
    fx, lg = m.get("fixture") or {}, m.get("league") or {}
    teams, goals = m.get("teams") or {}, m.get("goals") or {}
    score = m.get("score") or {}
    st = (fx.get("status") or {}).get("short")
    finished = st in _APIF_FINISHED
    status = ("FINISHED" if finished
              else "IN_PLAY" if st in _APIF_LIVE else "TIMED")
    rnd, ko = _apif_round(lg.get("round") or "")
    venue = fx.get("venue") or {}
    pens = score.get("penalty") or {}
    return {
        "fixture_id": fx.get("id"),
        "date": fx.get("date"),
        "status": status,
        "finished": finished,
        "knockout": ko,
        "round": rnd, "stage": lg.get("round"), "group": None,
        "matchday": None, "season": season,
        "venue": venue.get("name"), "city": venue.get("city"),
        "home": _apif_team(teams.get("home") or {}),
        "away": _apif_team(teams.get("away") or {}),
        "gh": goals.get("home"), "ga": goals.get("away"),
        "rigori": ({"home": pens.get("home"), "away": pens.get("away")}
                   if pens.get("home") is not None else None),
    }


def norm_standings_apif(tables: list[list[dict]], tipo: str, nome: str) -> list[dict]:
    groups = []
    for table in tables:
        n = len(table)
        rows = []
        for r in table:
            t = r.get("team") or {}
            tot = r.get("all") or {}
            g = tot.get("goals") or {}
            pos = r.get("rank")
            rows.append({
                "rank": pos, "team_id": t.get("id"), "team": t.get("name"),
                "short": t.get("name"), "logo": t.get("logo"),
                "points": r.get("points"), "played": tot.get("played"),
                "win": tot.get("win"), "draw": tot.get("draw"), "lose": tot.get("lose"),
                "gf": g.get("for"), "ga": g.get("against"),
                "diff": r.get("goalsDiff"),
                "form": (r.get("form") or "")[-5:],
                "descrizione": r.get("description") or (_row_descr(tipo, pos, n) if pos else None),
            })
        if rows:
            # il nome del girone sta nella singola riga API-Football
            gname = (table[0].get("group") or "").strip() if table else ""
            groups.append({"nome": gname or nome, "rows": rows})
    return groups


def norm_scorers_apif(resp: list[dict]) -> list[dict]:
    out = []
    for item in resp:
        p = item.get("player") or {}
        stats = (item.get("statistics") or [{}])[0]
        team = (stats.get("team") or {}).get("name")
        goals = (stats.get("goals") or {})
        games = (stats.get("games") or {})
        pen = (stats.get("penalty") or {})
        out.append({
            "name": p.get("name"), "team": team,
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "penalties": (pen.get("scored") or 0),
            "played": games.get("appearences") or 0,
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
    # Mondiali/Europei: la classifica per gironi va ricostruita dai risultati
    if len(standings) <= 1:
        rebuilt = standings_from_fixtures(fixtures, tipo)
        if len(rebuilt) > 1:
            standings = rebuilt
            print(f"  classifica ricostruita dai risultati: {len(rebuilt)} gironi")
    # per i tornei per nazioni il pool giocatori nasce dai capocannonieri:
    # chiedi una lista lunga (con fallback al default se il piano la rifiuta)
    scorers = norm_scorers(fd.competition_scorers(code, rs, limit=100)
                           or fd.competition_scorers(code, rs))
    print(f"  partite={len(fixtures)}  classifica_gironi={len(standings)}  marcatori={len(scorers)}")

    single = bool(meta.get("single_year"))  # Mondiali/Europei: edizione secca
    label = (str(rs) if single else season_label(rs))
    return {
        "meta": {
            "key": key, "nome": nome, "icona": meta["icona"], "tipo": tipo,
            "fd_code": code, "season": rs, "calendar_season": cs,
            "season_label": label,
            "calendar_label": str(cs) if single else season_label(cs),
            "preferita": config.SEASON,
            "piano_limitato": rs != config.SEASON and not single,
            "generato": now_iso(),
        },
        "standings": standings,
        "fixtures": fixtures,
        "scorers": scorers,
        "teams": {},   # riempito dallo step micro-eventi
    }


def build_league_apif(key: str, meta: dict) -> dict:
    """Competizioni via API-Football (Europa League, Nations League).

    Il piano gratuito arriva fino alla stagione 2024 (= 2024-25): l'updater
    ripiega automaticamente sull'ultima edizione accessibile."""
    lid, tipo, nome = meta["apif_id"], meta["tipo"], meta["nome"]
    print(f"\n[{key}] {nome} (API-Football id {lid})")
    season, raw = af.resolve_season(
        lid, [config.SEASON, config.SEASON - 1, 2024, 2023])
    print(f"  stagione accessibile: {season_label(season)}")

    fixtures = [norm_match_apif(m, season) for m in raw]
    standings = norm_standings_apif(af.league_standings(lid, season), tipo, nome)
    scorers = norm_scorers_apif(af.league_topscorers(lid, season))
    print(f"  partite={len(fixtures)}  classifica_gironi={len(standings)}  marcatori={len(scorers)}")

    return {
        "meta": {
            "key": key, "nome": nome, "icona": meta["icona"], "tipo": tipo,
            "apif_id": lid, "season": season, "calendar_season": season,
            "season_label": season_label(season),
            "calendar_label": season_label(season),
            "preferita": config.SEASON,
            "piano_limitato": season != config.SEASON,
            "generato": now_iso(),
        },
        "standings": standings,
        "fixtures": fixtures,
        "scorers": scorers,
        "teams": {},
    }


def _scorer_player(s: dict) -> dict:
    """Pseudo-giocatore dal tabellone marcatori (per squadre senza profilo
    FBref/Understat: nazionali e club fuori dalle Big 5)."""
    goals, assists = int(s.get("goals") or 0), int(s.get("assists") or 0)
    played = int(s.get("played") or 0) or max(1, goals)
    shots = goals * 8 + assists * 2          # stima dalla conversione media
    return {
        "id": abs(hash(s.get("name"))) % 10**8, "name": s.get("name") or "?",
        "photo": None, "position": "F",
        "minutes": played * 80, "appearances": played,
        "lineups": played, "sub_in": 0,
        "goals": goals, "assists": assists, "conceded": 0, "saves": 0,
        "shots": shots, "shots_on": round(shots * 0.4),
        "penalties": int(s.get("penalties") or 0),
        "rating": 6.5,
    }


def synth_from_scorers(leagues: dict) -> None:
    """Per le squadre rimaste senza profilo micro-evento crea un pool
    giocatori minimo dai capocannonieri reali della competizione."""
    for key, data in leagues.items():
        by_team: dict[str, list] = {}
        for s in data.get("scorers", []):
            if s.get("team"):
                by_team.setdefault(norm_team(s["team"]), []).append(s)
        if not by_team:
            continue
        added = 0
        names = {}
        for fx in data["fixtures"]:
            for side in ("home", "away"):
                names[fx[side]["name"]] = fx[side].get("short")
        for full, short in names.items():
            if data["teams"].get(full):
                continue
            rows = by_team.get(norm_team(full)) or by_team.get(norm_team(short or ""))
            if not rows:
                continue
            players = sorted((_scorer_player(s) for s in rows),
                             key=lambda p: -p["goals"])
            data["teams"][full] = {"source": "marcatori", "players": players,
                                   "games": max(p["appearances"] for p in players)}
            added += 1
        if added:
            print(f"  [{key}] pool marcatori sintetico per {added} squadre")


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
            try:
                leagues[key] = (build_league_apif(key, meta)
                                if meta.get("source") == "apif"
                                else build_league(key, meta))
            except (fd.FootballDataError, af.ApiFootballError) as exc:
                print(f"  ! {key}: {exc} — salto la competizione")

    # --- micro-eventi (FBref → Understat) sulle Big 5 --------------------
    # stagione presa dalle competizioni per club (i tornei secchi come i
    # Mondiali 2026 non hanno una stagione FBref/Understat corrispondente)
    micro_source = "nessuna"
    club_seasons = [d["meta"]["season"] for k, d in leagues.items()
                    if not config.LEAGUES.get(k, {}).get("single_year")]
    if not args.no_micro and club_seasons:
        results_season = max(club_seasons)
        fbref_season = f"{str(results_season)[2:]}{str(results_season + 1)[2:]}"
        print(f"\nMicro-eventi (stagione FBref/Understat {fbref_season})…")
        profiles, micro_source = fetch_micro_profiles(
            config.FBREF_BIG5, fbref_season, prefer=args.micro_source)
        print(f"  profili raccolti: {len(profiles)} (sorgente: {micro_source})")
        if profiles:
            attach_micro(leagues, profiles, micro_source)

    # pool giocatori minimo dai capocannonieri per le squadre senza profilo
    # (nazionali di Mondiali/Europei/Nations League, club fuori dalle Big 5)
    synth_from_scorers(leagues)

    # --- scrittura DB (merge con l'indice esistente: i run parziali con
    # --leagues non devono cancellare le altre competizioni) ---------------
    db.ensure_dir()
    old = db.read_json("index.json") or {}
    entries = {e["key"]: e for e in old.get("leagues", [])}
    for key, data in leagues.items():
        db.write_league(key, data)
        m = data["meta"]
        entries[key] = {
            "key": key, "nome": m["nome"], "icona": m["icona"], "tipo": m["tipo"],
            "season": m["season_label"], "piano_limitato": m["piano_limitato"]}
    micro_final = micro_source if micro_source != "nessuna" else old.get("micro_source", "nessuna")
    index = {"generato": now_iso(), "preferita": season_label(args.season),
             "micro_source": micro_final,
             "account": {"piano": "football-data.org + API-Football · free",
                         "micro": micro_final, "aggiornato": now_iso()[:10]},
             # ordine del menu = ordine di config.LEAGUES
             "leagues": [entries[k] for k in config.LEAGUES if k in entries]}
    db.write_index(index)
    print(f"\n✔ DB aggiornato in {db.DATA_DIR}")
    print(f"  competizioni: {len(leagues)}  ·  micro-eventi: {micro_source}")


if __name__ == "__main__":
    main()
