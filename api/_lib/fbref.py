# -*- coding: utf-8 -*-
"""Scraper micro-eventi (usato solo dall'updater offline, mai a runtime).

Fornisce i profili micro-evento per squadra — tiri, tiri in porta, corner,
falli, cartellini, save rate portiere e statistiche giocatori — a partire da
sorgenti gratuite, con fallback a cascata:

  1. FBref (via soccerdata)  → sorgente più completa (tiri, SoT, corner, falli,
     parate). Richiede una rete non protetta da Cloudflare/CAPTCHA.
  2. Understat (via soccerdata) → tiri e xG per giocatore/squadra, gol/assist/
     ammonizioni reali. Corner/falli/save rate non disponibili → baseline.
  3. Nessuna sorgente → l'updater usa i marcatori di football-data.org + medie
     di lega (config.BASELINE).

I profili sono indicizzati per nome-squadra normalizzato (accenti/sigle rimossi)
così da poter essere agganciati ai nomi di football-data.org.
"""

import re
import unicodedata

from . import config

# tiri in porta come frazione dei tiri totali (media di lega, per stimare i SoT
# quando la sorgente non li fornisce esplicitamente)
SOT_RATIO = 0.34

# sigle/parole societarie da rimuovere per normalizzare i nomi squadra.
# NB: niente parole distintive come "united"/"city"/"albion" per non collassare
# squadre diverse (es. Manchester City vs Manchester United).
_DROP = {"fc", "cf", "ac", "as", "ss", "ssc", "us", "cd", "rc", "sc", "ud",
         "sd", "afc", "cp", "bc", "rcd", "club", "calcio", "de", "the",
         "and", "futbol", "football", "kv", "sk", "fk", "sfp", "pae",
         "sad", "clube", "stade", "rb", "rasenballsport"}

# alias per token equivalenti tra sorgenti diverse (es. München ↔ Munich)
_ALIASES = {"munchen": "munich", "koln": "cologne", "monchengladbach": "gladbach",
            "internazionale": "inter", "milano": "milan",
            "wolverhampton": "wolves", "rennais": "rennes"}


def norm_team(name: str) -> str:
    """Nome squadra normalizzato per il match tra sorgenti diverse."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z ]", " ", s).lower()
    tokens = []
    for t in s.split():
        t = _ALIASES.get(t, t)
        if t and t not in _DROP:
            tokens.append(t)
    return " ".join(tokens)


def match_profile(index: dict, full: str, short: str) -> dict | None:
    """Trova il profilo micro-evento per una squadra provando: match esatto sul
    nome breve/completo, poi contenimento di token (es. 'brighton' ⊆ 'brighton
    hove albion')."""
    for cand in (short, full):
        prof = index.get(norm_team(cand or ""))
        if prof:
            return prof
    best = None
    for cand in (short, full):
        ct = set(norm_team(cand or "").split())
        if not ct:
            continue
        for k, prof in index.items():
            kt = set(k.split())
            if kt and (kt <= ct or ct <= kt):
                overlap = len(kt & ct)
                if best is None or overlap > best[0]:
                    best = (overlap, prof)
    return best[1] if best else None


def _pos_letter(position: str) -> str:
    p = (position or "").strip().upper()
    if p.startswith("GK") or p == "G":
        return "G"
    first = p[:1]
    if first in ("D", "M", "F"):
        return first
    return "F"  # 'S'/'Sub'/sconosciuto → trattato come attaccante


def _player_row(pid, name, position, matches, minutes, goals, assists, shots,
                yellows, np_goals, xg=0.0) -> dict:
    matches = int(matches or 0)
    minutes = int(minutes or 0)
    shots = int(shots or 0)
    goals = int(goals or 0)
    np_goals = int(np_goals if np_goals is not None else goals)
    penalties = max(0, goals - np_goals)
    mpm = minutes / matches if matches else 0
    starter = mpm >= 55
    is_sub_role = ("SUB" in (position or "").upper()) or (0 < mpm < 30)
    lineups = matches if starter else round(matches * 0.3)
    sub_in = max(0, matches - lineups)
    pos = _pos_letter(position)
    return {
        "id": int(pid) if str(pid).lstrip("-").isdigit() else abs(hash(name)) % 10**8,
        "name": name or "?", "photo": None, "position": pos,
        "minutes": minutes, "appearances": matches,
        "lineups": lineups, "sub_in": (1 if is_sub_role else 0) if sub_in == 0 and is_sub_role else sub_in,
        "goals": goals, "assists": int(assists or 0),
        "conceded": 0, "saves": 0,
        "shots": shots, "shots_on": round(shots * SOT_RATIO),
        "penalties": penalties,
        "rating": round(6.0 + min(2.5, float(xg or 0.0) * 0.5), 2),
    }


def _assemble_team(name: str, players: list[dict], games: int,
                   shots_total: int, yellows_total: int, reds_total: int,
                   xg_for: float | None, source: str) -> dict:
    games = max(1, games)
    shots_pg = shots_total / games if shots_total else config.BASELINE["shots"]
    keepers = [p for p in players if p["position"] == "G"]
    keeper = max(keepers, key=lambda p: p["minutes"], default=None)
    return {
        "source": source,
        "shots_pg": round(shots_pg, 2),
        "sot_pg": round(shots_pg * SOT_RATIO, 2),
        "corners_pg": config.BASELINE["corners"],   # non su Understat → baseline
        "fouls_pg": config.BASELINE["fouls"],        # non su Understat → baseline
        "yellow_pg": round(yellows_total / games, 3) if yellows_total else config.BASELINE["yellows"],
        "red_pg": round(reds_total / games, 3) if reds_total else config.BASELINE["reds"],
        "save_rate": config.BASELINE["save_rate"],
        "keeper": {
            "name": keeper["name"] if keeper else "Portiere",
            "save_rate": config.BASELINE["save_rate"],
            "saves_pg": None,
            "conceded": None,
            "appearances": keeper["appearances"] if keeper else None,
        },
        "xg_for": round(xg_for, 2) if xg_for is not None else None,
        "games": games,
        "players": sorted(players, key=lambda p: (-p["goals"], -p["shots"], -p["minutes"])),
    }


# ------------------------------------------------------------- Understat
def fetch_understat_profiles(fbref_leagues: list[str], season: str) -> dict:
    """Profili micro-evento da Understat. Ritorna {nome_normalizzato: profilo}."""
    import soccerdata as sd

    out: dict[str, dict] = {}
    for league in fbref_leagues:
        try:
            us = sd.Understat(leagues=league, seasons=season)
            players = us.read_player_season_stats().reset_index()
        except Exception as exc:  # lega non coperta o errore rete
            print(f"    · Understat {league}: {type(exc).__name__} — salto")
            continue

        # xG di squadra dalle partite (media per gara)
        team_xg: dict[str, float] = {}
        try:
            tm = us.read_team_match_stats().reset_index()
            acc: dict[str, list] = {}
            for _, r in tm.iterrows():
                acc.setdefault(r["home_team"], []).append(float(r["home_xg"]))
                acc.setdefault(r["away_team"], []).append(float(r["away_xg"]))
            team_xg = {t: sum(v) / len(v) for t, v in acc.items() if v}
        except Exception:
            pass

        by_team: dict[str, list] = {}
        for _, r in players.iterrows():
            by_team.setdefault(r["team"], []).append(r)

        for team, rows in by_team.items():
            plist, shots_t, yel_t, red_t, games = [], 0, 0, 0, 0
            for r in rows:
                pr = _player_row(
                    r.get("player_id"), r.get("player"), r.get("position"),
                    r.get("matches"), r.get("minutes"), r.get("goals"),
                    r.get("assists"), r.get("shots"), r.get("yellow_cards"),
                    r.get("np_goals"), r.get("xg", 0.0))
                plist.append(pr)
                shots_t += pr["shots"]
                yel_t += int(r.get("yellow_cards") or 0)
                red_t += int(r.get("red_cards") or 0)
                games = max(games, pr["appearances"])
            out[norm_team(team)] = _assemble_team(
                team, plist, games, shots_t, yel_t, red_t,
                team_xg.get(team), "understat")
    return out


# ---------------------------------------------------------------- FBref
def fetch_fbref_profiles(fbref_leagues: list[str], season: str) -> dict:
    """Profili micro-evento completi da FBref (tiri, SoT, corner, falli, parate).

    Funziona solo su reti non bloccate da Cloudflare/CAPTCHA. In caso di blocco
    solleva l'eccezione, gestita dall'updater che ripiega su Understat."""
    import soccerdata as sd

    fb = sd.FBref(leagues=fbref_leagues, seasons=season)
    standard = fb.read_team_season_stats(stat_type="standard").reset_index()
    shooting = fb.read_team_season_stats(stat_type="shooting").reset_index()
    misc = fb.read_team_season_stats(stat_type="misc").reset_index()
    keeper = fb.read_team_season_stats(stat_type="keeper").reset_index()
    passing_types = fb.read_team_season_stats(stat_type="passing_types").reset_index()
    players = fb.read_player_season_stats(stat_type="standard").reset_index()
    shooting_p = fb.read_player_season_stats(stat_type="shooting").reset_index()

    def col(df, *path):
        for c in df.columns:
            key = c if isinstance(c, str) else " ".join(str(x) for x in c if x)
            if key.strip().lower() == " ".join(path).strip().lower():
                return c
        return None

    # indici per giocatore (tiri/SoT dalla tabella shooting)
    shp = {}
    for _, r in shooting_p.iterrows():
        shp[(r.get("team"), r.get("player"))] = r

    out: dict[str, dict] = {}
    teams = {r.get("team") for _, r in standard.iterrows()}
    prow = {r.get("team"): r for _, r in players.groupby("team").head(0).iterrows()}  # placeholder

    # raggruppa giocatori per squadra
    pl_by_team: dict[str, list] = {}
    for _, r in players.iterrows():
        pl_by_team.setdefault(r.get("team"), []).append(r)

    def gv(row, df, *path):
        c = col(df, *path)
        try:
            return float(row[c]) if c is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    sht = {r.get("team"): r for _, r in shooting.iterrows()}
    msc = {r.get("team"): r for _, r in misc.iterrows()}
    kpr = {r.get("team"): r for _, r in keeper.iterrows()}
    std = {r.get("team"): r for _, r in standard.iterrows()}

    for team in teams:
        s_row, m_row, k_row, st_row = sht.get(team), msc.get(team), kpr.get(team), std.get(team)
        games = gv(st_row, standard, "Playing Time", "MP") or 1
        shots_pg = gv(s_row, shooting, "Standard", "Sh") / games if s_row is not None else config.BASELINE["shots"]
        sot_pg = gv(s_row, shooting, "Standard", "SoT") / games if s_row is not None else config.BASELINE["sot"]
        corners = gv(m_row, passing_types, "Pass Types", "CK") if m_row is not None else 0.0
        ck_row = {r.get("team"): r for _, r in passing_types.iterrows()}.get(team)
        corners_pg = (gv(ck_row, passing_types, "Pass Types", "CK") / games) if ck_row is not None else config.BASELINE["corners"]
        fouls_pg = gv(m_row, misc, "Performance", "Fls") / games if m_row is not None else config.BASELINE["fouls"]
        yellow_pg = gv(m_row, misc, "Performance", "CrdY") / games if m_row is not None else config.BASELINE["yellows"]
        red_pg = gv(m_row, misc, "Performance", "CrdR") / games if m_row is not None else config.BASELINE["reds"]
        # save rate portiere = 1 - (gol subiti / tiri in porta concessi)
        sota = gv(k_row, keeper, "Performance", "SoTA")
        ga = gv(k_row, keeper, "Performance", "GA")
        save_rate = max(0.55, min(0.85, 1 - ga / sota)) if sota else config.BASELINE["save_rate"]
        saves = gv(k_row, keeper, "Performance", "Saves")

        plist = []
        for r in pl_by_team.get(team, []):
            name = r.get("player")
            g = int(gv(r, players, "Performance", "Gls"))
            a = int(gv(r, players, "Performance", "Ast"))
            mins = int(gv(r, players, "Playing Time", "Min"))
            mp = int(gv(r, players, "Playing Time", "MP"))
            starts = int(gv(r, players, "Playing Time", "Starts"))
            pos = str(r.get("pos") or r.get("Pos") or "")
            spr = shp.get((team, name))
            shots = int(float(spr[col(shooting_p, "Standard", "Sh")]) if spr is not None and col(shooting_p, "Standard", "Sh") else 0)
            sot = int(float(spr[col(shooting_p, "Standard", "SoT")]) if spr is not None and col(shooting_p, "Standard", "SoT") else round(shots * SOT_RATIO))
            pk = int(float(spr[col(shooting_p, "Standard", "PK")]) if spr is not None and col(shooting_p, "Standard", "PK") else 0)
            is_gk = pos.startswith("GK")
            plist.append({
                "id": abs(hash(name)) % 10**8, "name": name, "photo": None,
                "position": "G" if is_gk else _pos_letter(pos[:1]),
                "minutes": mins, "appearances": mp,
                "lineups": starts, "sub_in": max(0, mp - starts),
                "goals": g, "assists": a,
                "conceded": int(ga) if is_gk else 0,
                "saves": int(saves) if is_gk else 0,
                "shots": shots, "shots_on": sot, "penalties": pk,
                "rating": 6.5,
            })

        keepers = [p for p in plist if p["position"] == "G"]
        kp = max(keepers, key=lambda p: p["minutes"], default=None)
        out[norm_team(team)] = {
            "source": "fbref",
            "shots_pg": round(shots_pg, 2), "sot_pg": round(sot_pg, 2),
            "corners_pg": round(corners_pg, 2), "fouls_pg": round(fouls_pg, 2),
            "yellow_pg": round(yellow_pg, 3), "red_pg": round(red_pg, 3),
            "save_rate": round(save_rate, 3),
            "keeper": {
                "name": kp["name"] if kp else "Portiere",
                "save_rate": round(save_rate, 3),
                "saves_pg": round(saves / games, 2) if saves else None,
                "conceded": int(ga) if ga else None,
                "appearances": kp["appearances"] if kp else None,
            },
            "xg_for": round(gv(st_row, standard, "Expected", "xG") / games, 2) if st_row is not None else None,
            "games": int(games),
            "players": sorted(plist, key=lambda p: (-p["goals"], -p["shots"], -p["minutes"])),
        }
    return out


def fetch_micro_profiles(fbref_leagues: list[str], season: str,
                         prefer: str = "fbref") -> tuple[dict, str]:
    """Ritorna (profili, sorgente_usata) provando FBref → Understat."""
    if prefer == "fbref":
        try:
            print("  → provo FBref (micro-eventi completi)…")
            prof = fetch_fbref_profiles(fbref_leagues, season)
            if prof:
                return prof, "fbref"
        except Exception as exc:
            print(f"  ! FBref non disponibile ({type(exc).__name__}): "
                  f"ripiego su Understat")
    try:
        print("  → uso Understat (tiri/xG/giocatori)…")
        prof = fetch_understat_profiles(fbref_leagues, season)
        return prof, ("understat" if prof else "nessuna")
    except Exception as exc:
        print(f"  ! Understat non disponibile ({type(exc).__name__})")
        return {}, "nessuna"
