# -*- coding: utf-8 -*-
"""GET /api/simulate?fixture=<id>&players=season|last10 — analisi completa:
10.000 simulazioni Monte Carlo + meteo + value bets + statistiche giocatori.
Risultato in cache 60 minuti (in-process + edge)."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from _lib.analysis import full_analysis        # noqa: E402
from _lib.webutil import query, send_json, run_safe  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        def go():
            q = query(self)
            fixture_id = int(q["fixture"])
            players_mode = q.get("players", "season")
            if players_mode not in ("season", "last10"):
                players_mode = "season"
            result = full_analysis(fixture_id, players_mode)
            send_json(self, result, smaxage=3600)
        run_safe(self, go)
