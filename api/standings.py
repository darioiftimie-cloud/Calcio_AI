# -*- coding: utf-8 -*-
"""GET /api/standings?league=<key> — classifica (campionati e fase campionato
delle coppe). Legge dal database popolato dall'updater."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from _lib import db                                     # noqa: E402
from _lib.webutil import query, send_json, run_safe     # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        def go():
            q = query(self)
            data = db.read_league(q["league"])
            meta = data["meta"]
            send_json(self, {"league": q["league"],
                             "season": meta["season_label"],
                             "stagione_corrente": meta["calendar_label"],
                             "piano_limitato": meta["piano_limitato"],
                             "groups": data["standings"]}, smaxage=900)
        run_safe(self, go)
