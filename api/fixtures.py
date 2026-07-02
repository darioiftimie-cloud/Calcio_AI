# -*- coding: utf-8 -*-
"""GET /api/fixtures?league=<key>&mode=next|last — prossime partite o ultimi
risultati. Legge dal database (calendario reale football-data.org)."""

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
            mode = q.get("mode", "next")
            n = min(int(q.get("n", 20)), 40)

            fixtures = data["fixtures"]
            if mode == "next":
                sel = [f for f in fixtures if not f["finished"]]
                sel.sort(key=lambda f: f.get("date") or "")
            else:
                sel = [f for f in fixtures if f["finished"]]
                sel.sort(key=lambda f: f.get("date") or "", reverse=True)
            sel = sel[:n]

            send_json(self, {"league": q["league"],
                             "season": meta["season_label"],
                             "stagione_corrente": meta["calendar_label"],
                             "piano_limitato": meta["piano_limitato"],
                             "mode": mode, "fixtures": sel}, smaxage=300)
        run_safe(self, go)
