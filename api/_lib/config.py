# -*- coding: utf-8 -*-
"""Configurazione centrale: competizioni supportate, baseline statistiche, chiavi API.

Sorgenti dati (tutte gratuite):
  - football-data.org  → risultati, classifiche, calendari, marcatori (chiave
    FOOTBALL_DATA_KEY). Stagione di riferimento SEASON (default 2026), con
    fallback automatico alla stagione più recente con partite giocate.
  - FBref (via soccerdata) → micro-eventi: tiri, tiri in porta, save rate
    portiere, falli, corner e statistiche giocatori (scraping offline).

Le chiavi NON sono hardcodate: vengono lette da variabile d'ambiente. In locale
dal file .env (gitignored); su Vercel dalle Environment Variables del progetto.
"""

import os

try:
    # Solo sviluppo locale su Windows: usa lo store certificati di sistema
    # (necessario dietro proxy/antivirus che intercettano il TLS).
    # Non è in requirements.txt: su Vercel l'import fallisce e viene ignorato.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def _load_dotenv() -> None:
    """Mini-parser .env per lo sviluppo locale (nessuna dipendenza esterna)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    except OSError:
        pass  # su Vercel il file non esiste: si usano le env del progetto


_load_dotenv()

# --- football-data.org --------------------------------------------------------
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
FD_BASE = "https://api.football-data.org/v4"

# --- API-Football (solo updater: Europa League e Nations League) --------------
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
APIF_BASE = "https://v3.football.api-sports.io"

# Stagione di riferimento (anno d'inizio). Per football-data.org 2026 = 2026-27.
# I preferiti vengono provati in ordine: la prima con partite giocate diventa
# la "stagione dei risultati"; il calendario dell'anno in corso resta comunque
# disponibile per le prossime partite.
SEASON = int(os.environ.get("SEASON", "2026"))
SEASON_FALLBACKS = [SEASON, 2025, 2024]

N_SIMS = 10_000          # iterazioni Monte Carlo per partita
CACHE_TTL = 3600         # 60 minuti: cache simulazioni
HTTP_TIMEOUT = 25

# Rate limit football-data.org piano gratuito: 10 richieste/minuto.
FD_MIN_INTERVAL = 6.5    # secondi tra richieste (usato dall'updater offline)

# Competizioni supportate. Per ognuna:
#   source  : "fd" = football-data.org · "apif" = API-Football (piano gratuito)
#   fd_code : codice competizione football-data.org
#   apif_id : id lega API-Football (per le competizioni non coperte da fd)
#   fbref   : id lega soccerdata/FBref per i micro-eventi (None = usa baseline
#             o, per le coppe, il profilo del campionato nazionale delle squadre)
#   single_year : torneo a edizione secca (Mondiali/Europei): stagione "2026",
#                 non "2026-27"
LEAGUES = {
    "serie_a":          {"source": "fd", "fd_code": "SA",  "fd_id": 2019, "nome": "Serie A",          "icona": "🇮🇹", "tipo": "league", "fbref": "ITA-Serie A"},
    "premier_league":   {"source": "fd", "fd_code": "PL",  "fd_id": 2021, "nome": "Premier League",   "icona": "🏴", "tipo": "league", "fbref": "ENG-Premier League"},
    "la_liga":          {"source": "fd", "fd_code": "PD",  "fd_id": 2014, "nome": "LaLiga",           "icona": "🇪🇸", "tipo": "league", "fbref": "ESP-La Liga"},
    "bundesliga":       {"source": "fd", "fd_code": "BL1", "fd_id": 2002, "nome": "Bundesliga",       "icona": "🇩🇪", "tipo": "league", "fbref": "GER-Bundesliga"},
    "ligue_1":          {"source": "fd", "fd_code": "FL1", "fd_id": 2015, "nome": "Ligue 1",          "icona": "🇫🇷", "tipo": "league", "fbref": "FRA-Ligue 1"},
    "champions_league": {"source": "fd", "fd_code": "CL",  "fd_id": 2001, "nome": "Champions League", "icona": "⭐", "tipo": "cup",    "fbref": None},
    "europa_league":    {"source": "apif", "apif_id": 3,   "nome": "Europa League",    "icona": "🏆", "tipo": "cup",  "fbref": None},
    "nations_league":   {"source": "apif", "apif_id": 5,   "nome": "Nations League",   "icona": "🌍", "tipo": "cup",  "fbref": None},
    "europei":          {"source": "fd", "fd_code": "EC",  "fd_id": 2018, "nome": "Europei",          "icona": "🇪🇺", "tipo": "cup", "fbref": None, "single_year": True},
    "mondiali":         {"source": "fd", "fd_code": "WC",  "fd_id": 2000, "nome": "Mondiali 2026",    "icona": "🌎", "tipo": "cup", "fbref": None, "single_year": True},
}

# Le 5 grandi leghe FBref: sorgente dei profili micro-evento (anche per le
# squadre di Champions, cercate per nome tra queste).
FBREF_BIG5 = ["ITA-Serie A", "ENG-Premier League", "ESP-La Liga",
              "GER-Bundesliga", "FRA-Ligue 1"]

# Medie di lega usate come fallback quando una statistica non è disponibile
BASELINE = {
    "goals": 1.40,       # gol a squadra per partita
    "shots": 12.5,       # tiri totali
    "sot": 4.6,          # tiri in porta
    "corners": 5.2,      # corner
    "fouls": 12.0,       # falli
    "yellows": 2.1,      # ammonizioni
    "reds": 0.055,       # espulsioni
    "save_rate": 0.70,   # save rate portiere
}

# Vantaggi campo (per le fasi KO di coppa il campo è ~neutro)
HOME_BOOST_LEAGUE, AWAY_MALUS_LEAGUE = 1.16, 0.90
HOME_BOOST_CUP, AWAY_MALUS_CUP = 1.06, 0.96

# Modificatori meteo (requisiti: -5% precisione tiri, +10% falli/contrasti)
WEATHER_SHOT_PRECISION = 0.95
WEATHER_FOULS_MULT = 1.10
