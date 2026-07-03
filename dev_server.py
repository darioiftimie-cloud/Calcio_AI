#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dev server locale: backend FastAPI + frontend statico su un'unica porta.

  /api/*  → app FastAPI in api/index.py (la stessa deployata su Vercel)
  /*      → file statici da public/

Uso:  python dev_server.py [--port 8700]
(in produzione non serve: Vercel esegue api/index.py come funzione ASGI e
serve public/ dalla CDN)
"""

import argparse
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "api"))

import uvicorn                                  # noqa: E402
from fastapi.staticfiles import StaticFiles     # noqa: E402

from index import app                           # noqa: E402  (api/index.py)

# il mount statico è registrato DOPO le route /api/*, che restano prioritarie
app.mount("/", StaticFiles(directory=os.path.join(BASE, "public"), html=True),
          name="static")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8700)
    args = ap.parse_args()
    print(f"Dev server (FastAPI + statici) su http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
