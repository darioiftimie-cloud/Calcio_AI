# -*- coding: utf-8 -*-
"""Backend FastAPI — tutti gli endpoint /api/* in un'unica app ASGI.

In locale è servita da dev_server.py (uvicorn, porta 8700) insieme al frontend
statico. Su Vercel gira come singola funzione Python: vercel.json riscrive
/api/(.*) su questo file e la piattaforma rileva automaticamente l'app ASGI.

Gli endpoint leggono solo dal database JSON in data/ (popolato offline da
updater.py): nessuna chiamata API a runtime tranne il meteo (Open-Meteo).
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Query, Request                    # noqa: E402
from fastapi.responses import JSONResponse, Response           # noqa: E402

from _lib import db                                            # noqa: E402
from _lib.analysis import full_analysis                        # noqa: E402
from _lib.pdfgen import build_pdf                              # noqa: E402

app = FastAPI(title="Calcio AI — Analytics Board",
              docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ errori
@app.exception_handler(db.DBError)
async def _db_error(request: Request, exc: db.DBError):
    return JSONResponse({"errore": f"dati non disponibili: {exc}"},
                        status_code=503)


@app.exception_handler(Exception)
async def _generic_error(request: Request, exc: Exception):
    return JSONResponse({"errore": "errore interno",
                         "dettaglio": traceback.format_exc(limit=3)},
                        status_code=500)


def _json(payload: dict, smaxage: int) -> JSONResponse:
    """Risposta JSON con cache edge (CDN Vercel) + niente cache browser."""
    return JSONResponse(payload, headers={
        "Cache-Control": f"public, s-maxage={smaxage}, max-age=0"})


# ---------------------------------------------------------------- endpoint
@app.get("/api/leagues")
def leagues():
    """Competizioni disponibili nel database + stato dati."""
    idx = db.read_index()
    ls = [{"key": l["key"], "nome": l["nome"], "icona": l["icona"],
           "tipo": l["tipo"], "season": l["season"]}
          for l in idx.get("leagues", [])]
    return _json({"leagues": ls, "account": idx.get("account", {}),
                  "generato": idx.get("generato")}, smaxage=1800)


@app.get("/api/standings")
def standings(league: str):
    """Classifica (campionati e gironi/fase campionato delle coppe)."""
    data = db.read_league(league)
    meta = data["meta"]
    return _json({"league": league,
                  "season": meta["season_label"],
                  "stagione_corrente": meta["calendar_label"],
                  "piano_limitato": meta["piano_limitato"],
                  "groups": data["standings"]}, smaxage=900)


# ordine dei turni a eliminazione diretta, dal più lontano alla finale
_KO_ORDER = ["Playoff", "Sedicesimi", "Ottavi", "Quarti", "Semifinali",
             "Finale 3° posto", "Finale"]


@app.get("/api/bracket")
def bracket(league: str):
    """Tabellone a eliminazione diretta ricostruito dalle partite knockout."""
    data = db.read_league(league)
    meta = data["meta"]

    rounds: dict[str, list] = {}
    first_date: dict[str, str] = {}
    for fx in data["fixtures"]:
        if not fx.get("knockout"):
            continue
        rname = fx["round"]
        rounds.setdefault(rname, []).append({
            "fixture_id": fx["fixture_id"], "date": fx["date"],
            "status": fx["status"], "played": fx["finished"],
            "home": fx["home"], "away": fx["away"],
            "gh": fx["gh"], "ga": fx["ga"], "rigori": fx["rigori"],
        })
        d = fx.get("date") or ""
        if rname not in first_date or d < first_date[rname]:
            first_date[rname] = d

    def sort_key(r):
        return (_KO_ORDER.index(r) if r in _KO_ORDER else 99,
                first_date.get(r, ""))

    out = [{"nome": r,
            "partite": sorted(rounds[r], key=lambda m: m["date"] or "")}
           for r in sorted(rounds, key=sort_key)]
    return _json({"league": league,
                  "season": meta["season_label"],
                  "stagione_corrente": meta["calendar_label"],
                  "piano_limitato": meta["piano_limitato"],
                  "rounds": out}, smaxage=300)


@app.get("/api/fixtures")
def fixtures(league: str, mode: str = "next", n: int = Query(20, le=40)):
    """Prossime partite (mode=next) o ultimi risultati (mode=last)."""
    data = db.read_league(league)
    meta = data["meta"]

    if mode == "next":
        sel = [f for f in data["fixtures"] if not f["finished"]]
        sel.sort(key=lambda f: f.get("date") or "")
    else:
        sel = [f for f in data["fixtures"] if f["finished"]]
        sel.sort(key=lambda f: f.get("date") or "", reverse=True)

    return _json({"league": league,
                  "season": meta["season_label"],
                  "stagione_corrente": meta["calendar_label"],
                  "piano_limitato": meta["piano_limitato"],
                  "mode": mode, "fixtures": sel[:n]}, smaxage=300)


@app.get("/api/simulate")
def simulate(fixture: int,
             players: str = Query("season", pattern="^(season|last10)$")):
    """Analisi completa: 10.000 simulazioni Monte Carlo + meteo + giocatori.
    Risultato in cache 60 minuti (in-process + edge)."""
    return _json(full_analysis(fixture, players), smaxage=3600)


@app.get("/api/report")
def report(fixture: int,
           players: str = Query("season", pattern="^(season|last10)$")):
    """Report Analitico PDF (riusa la cache dell'analisi)."""
    analysis = full_analysis(fixture, players)
    home = analysis["meta"]["home"]["name"].replace(" ", "_")
    away = analysis["meta"]["away"]["name"].replace(" ", "_")
    pdf = build_pdf(analysis)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            f'attachment; filename="report_{home}_vs_{away}.pdf"',
        "Cache-Control": "public, s-maxage=3600, max-age=0"})
