# -*- coding: utf-8 -*-
"""GET /api/report?fixture=<id>&players=season|last10 — Report Analitico PDF
delle 10.000 simulazioni (riusa la cache dell'analisi: zero crediti extra)."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from _lib.analysis import full_analysis        # noqa: E402
from _lib.pdfgen import build_pdf              # noqa: E402
from _lib.webutil import query, send_pdf, run_safe  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        def go():
            q = query(self)
            fixture_id = int(q["fixture"])
            players_mode = q.get("players", "season")
            if players_mode not in ("season", "last10"):
                players_mode = "season"
            analysis = full_analysis(fixture_id, players_mode)
            home = analysis["meta"]["home"]["name"].replace(" ", "_")
            away = analysis["meta"]["away"]["name"].replace(" ", "_")
            pdf = build_pdf(analysis)
            send_pdf(self, pdf, f"report_{home}_vs_{away}.pdf")
        run_safe(self, go)
