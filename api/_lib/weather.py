# -*- coding: utf-8 -*-
"""Impatto meteo: dalla città dello stadio (API-Football) alle condizioni
al calcio d'inizio via Open-Meteo (gratuito, senza chiave).

Condizioni estreme (pioggia, vento forte, gelo, caldo torrido) attivano i
modificatori del modello: -5% precisione tiri in porta, +10% falli/contrasti.
"""

from datetime import datetime, timedelta, timezone

import requests

from . import config
from .cache import cache_get, cache_set

_NEUTRAL = {
    "disponibile": False, "citta": None, "temperatura": None,
    "pioggia_mm": None, "vento_kmh": None, "condizione": "non disponibile",
    "estremo": False, "precisione_tiri": 1.0, "moltiplicatore_falli": 1.0,
}


def weather_for(city: str | None, iso_date: str | None) -> dict:
    """Meteo previsto per città e ora del match. In caso di qualunque
    problema (città mancante, data lontana, rete) torna il profilo neutro."""
    if not city or not iso_date:
        return dict(_NEUTRAL)

    key = f"weather:{city}:{iso_date[:13]}"
    hit = cache_get(key)
    if hit is not None:
        return hit

    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1}, timeout=10).json()
        results = geo.get("results") or []
        if not results:
            return dict(_NEUTRAL)
        lat, lon = results[0]["latitude"], results[0]["longitude"]

        day = iso_date[:10]
        hour = int(iso_date[11:13]) if len(iso_date) >= 13 else 18
        # date passate → archivio storico; future → previsioni
        cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        base = ("https://archive-api.open-meteo.com/v1/archive" if day < cutoff
                else "https://api.open-meteo.com/v1/forecast")
        fc = requests.get(
            base,
            params={
                "latitude": lat, "longitude": lon,
                "hourly": "temperature_2m,precipitation,wind_speed_10m",
                "start_date": day, "end_date": day, "timezone": "auto",
            }, timeout=10).json()
        hourly = fc.get("hourly", {})
        temps = hourly.get("temperature_2m") or []
        rains = hourly.get("precipitation") or []
        winds = hourly.get("wind_speed_10m") or []
        if not temps:
            return dict(_NEUTRAL)
        i = min(hour, len(temps) - 1)
        temp, rain, wind = temps[i], (rains[i] if rains else 0), (winds[i] if winds else 0)

        estremo, condizione = False, "normale"
        if rain is not None and rain >= 0.5:
            estremo, condizione = True, "pioggia"
        if wind is not None and wind >= 40:
            estremo, condizione = True, "vento forte"
        if temp is not None and temp >= 35:
            estremo, condizione = True, "caldo estremo"
        if temp is not None and temp <= 0:
            estremo, condizione = True, "gelo"

        out = {
            "disponibile": True, "citta": city, "temperatura": temp,
            "pioggia_mm": rain, "vento_kmh": wind, "condizione": condizione,
            "estremo": estremo,
            "precisione_tiri": config.WEATHER_SHOT_PRECISION if estremo else 1.0,
            "moltiplicatore_falli": config.WEATHER_FOULS_MULT if estremo else 1.0,
        }
        cache_set(key, out, config.CACHE_TTL)
        return out
    except Exception:
        return dict(_NEUTRAL)
