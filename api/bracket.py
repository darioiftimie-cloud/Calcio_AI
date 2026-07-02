# -*- coding: utf-8 -*-
"""GET /api/bracket?league=<key> — tabellone a eliminazione diretta ricostruito
dalle partite knockout del database (si aggiorna con l'updater)."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from _lib import db                                     # noqa: E402
from _lib.webutil import query, send_json, run_safe     # noqa: E402

# ordine dei turni dal più lontano alla finale
_ORDER = ["Playoff", "Sedicesimi", "Ottavi", "Quarti", "Semifinali",
          "Finale 3° posto", "Finale"]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        def go():
            q = query(self)
            data = db.read_league(q["league"])
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
                return (_ORDER.index(r) if r in _ORDER else 99,
                        first_date.get(r, ""))
            out = [{"nome": r, "partite": sorted(rounds[r],
                                                 key=lambda m: m["date"] or "")}
                   for r in sorted(rounds, key=sort_key)]
            send_json(self, {"league": q["league"],
                             "season": meta["season_label"],
                             "stagione_corrente": meta["calendar_label"],
                             "piano_limitato": meta["piano_limitato"],
                             "rounds": out}, smaxage=300)
        run_safe(self, go)
