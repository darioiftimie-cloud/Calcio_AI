# -*- coding: utf-8 -*-
"""GET /api/leagues — competizioni disponibili nel database + stato dati."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from _lib import db                                 # noqa: E402
from _lib.webutil import send_json, run_safe        # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        def go():
            idx = db.read_index()
            leagues = [{"key": l["key"], "nome": l["nome"], "icona": l["icona"],
                        "tipo": l["tipo"], "season": l["season"]}
                       for l in idx.get("leagues", [])]
            send_json(self, {"leagues": leagues,
                             "account": idx.get("account", {}),
                             "generato": idx.get("generato")}, smaxage=1800)
        run_safe(self, go)
