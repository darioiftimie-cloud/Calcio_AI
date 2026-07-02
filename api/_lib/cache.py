# -*- coding: utf-8 -*-
"""Cache TTL in-process.

Su Vercel ogni lambda "calda" mantiene questo dizionario tra le invocazioni:
le simulazioni e le risposte API restano in cache 60 minuti, riducendo il
consumo di crediti API-Football. In aggiunta gli endpoint impostano
Cache-Control s-maxage per sfruttare anche la cache edge di Vercel.
"""

import time
import threading

_store: dict = {}
_lock = threading.Lock()
_MAX_ENTRIES = 512


def cache_get(key: str):
    with _lock:
        hit = _store.get(key)
        if hit is None:
            return None
        expiry, value = hit
        if time.time() > expiry:
            del _store[key]
            return None
        return value


def cache_set(key: str, value, ttl: int) -> None:
    with _lock:
        if len(_store) >= _MAX_ENTRIES:  # eviction grossolana ma sufficiente
            now = time.time()
            for k in [k for k, (exp, _) in _store.items() if exp < now]:
                del _store[k]
            while len(_store) >= _MAX_ENTRIES:
                del _store[next(iter(_store))]
        _store[key] = (time.time() + ttl, value)
