#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dev server locale che emula il routing di Vercel:
  /api/<nome>  → handler serverless in api/<nome>.py
  /*           → file statici da public/

Uso:  python dev_server.py [--port 8700]
(in produzione non serve: Vercel gestisce tutto nativamente)
"""

import argparse
import importlib.util
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BASE = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE, "api")
PUBLIC = os.path.join(BASE, "public")

sys.path.insert(0, API_DIR)  # per `from _lib import ...` negli endpoint

_handlers: dict = {}
for fname in os.listdir(API_DIR):
    if fname.endswith(".py") and not fname.startswith("_"):
        name = fname[:-3]
        spec = importlib.util.spec_from_file_location(
            f"api_{name}", os.path.join(API_DIR, fname))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _handlers[name] = mod.handler


class DevHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.path.split('?')[0]} → {args[1] if len(args) > 1 else ''}\n")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            name = path[5:].strip("/")
            cls = _handlers.get(name)
            if cls is None:
                self.send_error(404, "endpoint sconosciuto")
                return
            cls.do_GET(self)  # delega all'handler serverless (stessa interfaccia)
            return
        # statici
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        file_path = os.path.normpath(os.path.join(PUBLIC, rel))
        if not file_path.startswith(PUBLIC) or not os.path.isfile(file_path):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8700)
    args = ap.parse_args()
    print(f"Dev server (emulazione Vercel) su http://127.0.0.1:{args.port}/")
    print(f"Endpoint API caricati: {', '.join(sorted(_handlers))}")
    ThreadingHTTPServer(("127.0.0.1", args.port), DevHandler).serve_forever()
