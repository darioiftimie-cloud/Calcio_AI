# -*- coding: utf-8 -*-
"""Micro-eventi reali per squadra dal torneo/campionato in corso (API ESPN).

ESPN espone gratis (senza chiave) il boxscore di ogni partita: falli,
ammonizioni, espulsioni, corner, tiri, tiri in porta, parate. L'updater
accumula queste statistiche per ogni squadra sulle gare GIÀ GIOCATE della
competizione e ne ricava le medie per partita, che il motore Monte Carlo
usa al posto delle baseline di lega uguali per tutti.

La cache degli eventi già processati vive nel JSON della lega ("espn"):
ogni giro dell'updater scarica solo i boxscore delle partite nuove, così
il workflow ogni 15 minuti resta leggero.
"""

import time

import requests

from . import config
from .fbref import norm_team

# slug ESPN per le competizioni supportate
LEAGUE_CODES = {
    "serie_a": "ita.1",
    "premier_league": "eng.1",
    "la_liga": "esp.1",
    "bundesliga": "ger.1",
    "ligue_1": "fra.1",
    "champions_league": "uefa.champions",
    "europa_league": "uefa.europa",
    "nations_league": "uefa.nations",
    "europei": "uefa.euro",
    "mondiali": "fifa.world",
}

_BASE = "http://site.api.espn.com/apis/site/v2/sports/soccer"
_PAUSE = 0.35        # cortesia tra le chiamate summary
_STAT_KEYS = {       # nome ESPN → nome interno
    "foulsCommitted": "fouls",
    "yellowCards": "yellows",
    "redCards": "reds",
    "wonCorners": "corners",
    "totalShots": "shots",
    "shotsOnTarget": "sot",
    "saves": "saves",
}


class EspnError(Exception):
    """Errore di rete/formato dall'API ESPN."""


def _get(url: str, params: dict | None = None) -> dict:
    for attempt in range(2):
        try:
            r = requests.get(url, params=params or {},
                             timeout=config.HTTP_TIMEOUT)
            if r.status_code >= 400:
                raise EspnError(f"HTTP {r.status_code} su {url}")
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == 1:
                raise EspnError(str(exc)) from exc
            time.sleep(1.5)
    raise EspnError("irraggiungibile")


def _windows(start: str, end: str) -> list[tuple[str, str]]:
    """Spezza l'intervallo in finestre ~6 mesi (ESPN rifiuta range > 1 anno)."""
    out = []
    lo = start
    while lo <= end:
        year, month = int(lo[:4]), int(lo[4:6])
        month += 6
        if month > 12:
            year, month = year + 1, month - 12
        nxt = f"{year:04d}{month:02d}{lo[6:]}"
        out.append((lo, min(nxt, end)))
        if nxt > end:
            break
        lo = nxt
    return out


def fetch_events(code: str, start: str, end: str) -> list[dict]:
    """Eventi (partite) conclusi nell'intervallo di date YYYYMMDD."""
    events, seen = [], set()
    for lo, hi in _windows(start, end):
        data = _get(f"{_BASE}/{code}/scoreboard",
                    {"dates": f"{lo}-{hi}", "limit": 500})
        for ev in data.get("events", []):
            if str(ev.get("id")) not in seen:
                seen.add(str(ev.get("id")))
                events.append(ev)
        time.sleep(_PAUSE)
    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        status = (((ev.get("status") or {}).get("type")) or {})
        if not status.get("completed"):
            continue
        teams = {}
        for c in comp.get("competitors", []):
            name = ((c.get("team") or {}).get("displayName")) or "?"
            teams[name] = {"homeAway": c.get("homeAway"),
                           "score": int(c.get("score") or 0)}
        if len(teams) == 2:
            out.append({"id": str(ev.get("id")),
                        "date": (ev.get("date") or "")[:10],
                        "teams": teams})
    return out


def fetch_boxscore(code: str, event_id: str) -> dict[str, dict]:
    """Statistiche per squadra di una partita: {nome: {fouls, yellows, ...}}."""
    data = _get(f"{_BASE}/{code}/summary", {"event": event_id})
    out = {}
    for t in (data.get("boxscore") or {}).get("teams", []):
        name = ((t.get("team") or {}).get("displayName")) or "?"
        stats = {}
        for s in t.get("statistics", []):
            key = _STAT_KEYS.get(s.get("name"))
            if key:
                try:
                    stats[key] = float(s.get("displayValue"))
                except (TypeError, ValueError):
                    pass
        if stats:
            out[name] = stats
    return out


def _date_range(fixtures: list[dict]) -> tuple[str, str] | None:
    played = [fx["date"][:10].replace("-", "") for fx in fixtures
              if fx.get("finished") and fx.get("date")]
    if not played:
        return None
    return min(played), max(played)


def _aggregate(events: dict[str, dict], lo: str, hi: str) -> dict[str, dict]:
    """Somma le statistiche per squadra (nome ESPN) sugli eventi in range."""
    acc: dict[str, dict] = {}
    for ev in events.values():
        d = (ev.get("date") or "").replace("-", "")
        if not (lo <= d <= hi):
            continue
        for name, st in (ev.get("teams") or {}).items():
            a = acc.setdefault(name, {"played": 0, "fouls": 0.0, "yellows": 0.0,
                                      "reds": 0.0, "corners": 0.0, "shots": 0.0,
                                      "sot": 0.0, "saves": 0.0, "conceded": 0.0})
            a["played"] += 1
            for k in ("fouls", "yellows", "reds", "corners",
                      "shots", "sot", "saves", "conceded"):
                a[k] += float(st.get(k) or 0.0)
    return acc


def _micro_from_acc(a: dict) -> dict:
    """Medie per gara dal dict accumulato da _aggregate."""
    n = a["played"]
    sv, gc = a["saves"], a["conceded"]
    return {
        "played": n,
        "shots_pg": round(a["shots"] / n, 2),
        "sot_pg": round(a["sot"] / n, 2),
        "corners_pg": round(a["corners"] / n, 2),
        "fouls_pg": round(a["fouls"] / n, 2),
        "yellow_pg": round(a["yellows"] / n, 2),
        "red_pg": round(a["reds"] / n, 3),
        "save_rate": round(sv / (sv + gc), 3) if (sv + gc) > 0 else None,
        "saves_pg": round(sv / n, 2),
        "source": "espn",
    }


def _team_events(league: dict, team_name: str) -> list[tuple[str, dict, dict]]:
    """Le gare in cache della squadra: [(data, proprie, avversario)], in
    ordine cronologico. Le statistiche dell'avversario servono per xGA e
    volume di tiro concesso."""
    events = (league.get("espn") or {}).get("events") or {}
    target = norm_team(team_name)
    tt = set(target.split())
    rows = []
    for ev in events.values():
        teams = ev.get("teams") or {}
        for name, st in teams.items():
            kn = norm_team(name)
            if kn != target:
                kt = set(kn.split())
                if not (kt and tt and (kt <= tt or tt <= kt)):
                    continue
            opp = next((s for n, s in teams.items() if n != name), {})
            rows.append((ev.get("date") or "", st, opp))
    rows.sort(key=lambda r: r[0])
    return rows


def _xg_proxy(st: dict) -> float:
    """xG shot-based di una singola gara: conversioni medie per tiro in
    porta e tiro fuori/bloccato (proxy; ESPN non pubblica xG)."""
    sot = float(st.get("sot") or 0.0)
    off = max(float(st.get("shots") or 0.0) - sot, 0.0)
    return config.XG_PER_SOT * sot + config.XG_PER_OFF * off


def _micro_from_rows(rows: list[tuple[str, dict, dict]]) -> dict | None:
    """Medie per gara con time-decay esponenziale: l'ultima gara pesa 1,
    la precedente STAT_DECAY, poi STAT_DECAY², … (le più recenti contano
    di più). `played` resta il conteggio reale (per lo shrinkage)."""
    if not rows:
        return None
    k = len(rows)
    keys = ("fouls", "yellows", "reds", "corners", "shots", "sot",
            "saves", "conceded")
    acc = {key: 0.0 for key in keys}
    xg = xga = wsum = 0.0
    for i, (_, st, opp) in enumerate(rows):
        w = config.STAT_DECAY ** (k - 1 - i)
        wsum += w
        for key in keys:
            acc[key] += w * float(st.get(key) or 0.0)
        xg += w * _xg_proxy(st)
        xga += w * _xg_proxy(opp)
    sv, gc = acc["saves"], acc["conceded"]
    return {
        "played": k,
        "shots_pg": round(acc["shots"] / wsum, 2),
        "sot_pg": round(acc["sot"] / wsum, 2),
        "corners_pg": round(acc["corners"] / wsum, 2),
        "fouls_pg": round(acc["fouls"] / wsum, 2),
        "yellow_pg": round(acc["yellows"] / wsum, 2),
        "red_pg": round(acc["reds"] / wsum, 3),
        "save_rate": round(sv / (sv + gc), 3) if (sv + gc) > 0 else None,
        "saves_pg": round(sv / wsum, 2),
        "xg_pg": round(xg / wsum, 2),
        "xga_pg": round(xga / wsum, 2),
        "source": "espn",
    }


def team_micro_before(league: dict, team_name: str,
                      before_date: str | None) -> dict | None:
    """Medie ESPN della squadra usando SOLO le gare precedenti a before_date.

    Serve al backtest (out-of-sample): la media statica in team_micro copre
    l'intero torneo e "conoscerebbe" anche le gare successive a quella
    rigiocata. Con before_date=None equivale alla media completa."""
    cutoff = (before_date or "9999")[:10]
    rows = [r for r in _team_events(league, team_name) if r[0] < cutoff]
    return _micro_from_rows(rows)


def team_micro_last_n(league: dict, team_name: str, n: int = 10,
                      before_date: str | None = None) -> dict | None:
    """Medie ESPN della squadra sulle ultime n gare giocate (modo "forma
    ultime 10"): tiri, falli, cartellini, corner e save rate recenti.
    Con before_date conta solo le gare precedenti (analisi pre-partita)."""
    rows = _team_events(league, team_name)
    if before_date:
        cutoff = before_date[:10]
        rows = [r for r in rows if r[0] < cutoff]
    return _micro_from_rows(rows[-n:])


def attach_tournament_micro(key: str, data: dict, old: dict | None = None,
                            max_new: int = 150) -> None:
    """Popola data["team_micro"] con le medie reali del torneo/stagione.

    - riusa la cache eventi del DB precedente (`old["espn"]`);
    - scarica al massimo `max_new` boxscore nuovi per giro (backfill graduale
      dei campionati alla prima esecuzione);
    - le medie coprono solo le date della stagione corrente nel DB.
    """
    code = LEAGUE_CODES.get(key)
    if not code:
        return
    rng = _date_range(data.get("fixtures") or [])
    if not rng:
        print(f"  [{key}] nessuna partita giocata: salto ESPN")
        return
    lo, hi = rng

    cache = dict(((old or {}).get("espn") or {}).get("events") or {})
    # butta gli eventi fuori stagione (cambio stagione → cache pulita)
    cache = {eid: ev for eid, ev in cache.items()
             if lo <= (ev.get("date") or "").replace("-", "") <= hi}

    events = fetch_events(code, lo, hi)
    todo = [ev for ev in events if ev["id"] not in cache]
    skipped = max(0, len(todo) - max_new)
    fetched = 0
    for ev in todo[:max_new]:
        try:
            box = fetch_boxscore(code, ev["id"])
        except EspnError:
            continue     # non in cache: si riprova al giro successivo
        if not box:
            continue
        # gol subiti = punteggio dell'avversaria (per il save rate reale)
        scores = {n: t["score"] for n, t in ev["teams"].items()}
        teams = {}
        for name, st in box.items():
            other = [s for n, s in scores.items() if n != name]
            st["conceded"] = float(other[0]) if other else 0.0
            teams[name] = st
        cache[ev["id"]] = {"date": ev["date"], "teams": teams}
        fetched += 1
        time.sleep(_PAUSE)

    data["espn"] = {"events": cache}

    # nomi football-data della competizione, per l'aggancio ai nomi ESPN
    fd_names = {}
    for fx in data.get("fixtures") or []:
        for side in ("home", "away"):
            fd_names[fx[side]["name"]] = fx[side].get("short")

    agg = _aggregate(cache, lo, hi)
    by_norm = {norm_team(n): (n, a) for n, a in agg.items()}
    micro: dict[str, dict] = {}
    for full, short in fd_names.items():
        hit = by_norm.get(norm_team(full)) or by_norm.get(norm_team(short or ""))
        if not hit:      # contenimento di token (es. "Cape Verde Islands")
            ft = set(norm_team(full).split())
            for k, cand in by_norm.items():
                kt = set(k.split())
                if kt and ft and (kt <= ft or ft <= kt):
                    hit = cand
                    break
        if not hit:
            continue
        _, a = hit
        if a["played"] < 1:
            continue
        micro[full] = _micro_from_acc(a)
    data["team_micro"] = micro

    tail = f" (restano {skipped}, prossimo giro)" if skipped else ""
    print(f"  [{key}] ESPN: {len(cache)} gare in cache (+{fetched} nuove), "
          f"medie reali per {len(micro)} squadre{tail}")
