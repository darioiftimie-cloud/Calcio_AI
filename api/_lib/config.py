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

N_SIMS = 15_000          # iterazioni Monte Carlo per partita
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

# --- Parametri del modello statistico ------------------------------------
# ELO interno (ricostruito dai risultati del DB, per lega/torneo)
ELO_START = 1500.0       # rating iniziale
ELO_K = 24.0             # K-factor (sensibilità all'ultimo risultato)
ELO_HOME_ADV = 60.0      # vantaggio campo in punti ELO (0 nelle coppe: campo ~neutro)
ELO_ALPHA = 0.35         # esponente del fattore ELO sugli xG: (E/0.5)^alpha

# Time-decay esponenziale sulle statistiche per-partita: l'ultima gara pesa 1,
# quella prima 0.85, poi 0.72… (half-life ≈ 4 partite)
STAT_DECAY = 0.85

# xG shot-based (proxy dai boxscore ESPN): coefficienti medi di conversione
# per tiro in porta e tiro fuori/bloccato (letteratura xG)
XG_PER_SOT = 0.29
XG_PER_OFF = 0.045
XG_BLEND = 0.5           # peso dell'xG proxy nel blend con i gol reali

# xG proxy v2 (campi ESPN estesi; ESPN non pubblica key passes né tocchi in
# area: i segnali reali più vicini sono rigori, tiri murati e cross riusciti).
# Un tiro murato è quasi sempre una conclusione poco pericolosa (spesso da
# fuori area): pesa meno di un tiro fuori pulito. Il cross riuscito è il
# proxy dell'ingresso in area avversaria (deep completion).
XG_PER_PEN = 0.76        # xG di un calcio di rigore
XG_PER_OFF_CLEAN = 0.055 # tiro fuori non murato
XG_PER_BLOCKED = 0.025   # tiro murato
XG_PER_CROSS_ACC = 0.012 # cross riuscito (proxy tocchi in area)

# Binomiale Negativa (overdispersion dei conteggi): Var = μ + α·μ².
# α stimato per competizione dai boxscore (metodo dei momenti); questi sono
# i fallback quando il campione è troppo piccolo (<40 gare-squadra).
NB_ALPHA_DEFAULT = {"sot": 0.10, "shots": 0.08, "fouls": 0.12, "corners": 0.10}
NB_ALPHA_MAX = 0.80      # tetto all'α stimato (protegge dai campioni rumorosi)
TEMPO_K = 25.0           # Gamma del ritmo-gara condiviso (var 1/25): correla
                         # i volumi delle due squadre; il resto della
                         # dispersione lo mette la Binomiale Negativa

# Dixon-Coles: correzione della dipendenza sui punteggi bassi (0-0, 1-0,
# 0-1, 1-1). ρ stimato per lega via massima verosimiglianza sui risultati
# del DB; intervallo ammesso e fallback se il campione è scarso.
DC_RHO_RANGE = (-0.25, 0.10)
DC_RHO_DEFAULT = -0.05
DC_RHO_SHRINK = 30       # shrinkage del rho: n_celle_basse/(n+30)
DC_TAU_CLIP = (0.60, 1.45)   # tetto al fattore per cella (τ(0,0) cresce con λμ)

# Game state dinamico: l'aggiustamento del 2° tempo scala linearmente con i
# minuti trascorsi dal gol del divario e col delta ELO (il favorito che
# insegue spinge di più; lo sfavorito in vantaggio si chiude di più).
GS_ELO_SLOPE = 0.5       # pendenza per 400 punti ELO di divario
GS_DYN_CLIP = (0.6, 1.4) # limiti del fattore ELO sul game state

# --- Fasi a eliminazione diretta: correzioni anti-bias pareggio -----------
# Nei KO i profili cumulativi (poche gare) + shrinkage piatto appiattivano
# le differenze reali → 0-0/1-1 in testa ovunque, anche nei match sbilanciati.
KO_SHRINK_FACTOR = 0.30  # peso della media lega ridotto del 70% nei KO
KO_ELO_ALPHA = 0.50      # esponente ELO potenziato nei KO (base: 0.35)
KO_ASSAULT_SOT = 0.25    # pareggio al 75': +25% tiri del team con ELO più alto
KO_ASSAULT_CONV = 0.15   # ... e +15% conversione (contropiedi) dell'altro
KO_DRAW_RHO = 0.10       # Dixon-Coles positivo: penalizza 0-0/1-1 nei KO
                         # (storicamente i 90' dei KO si sbloccano nel finale)

# --- Variabili situazionali (game state, riposo, motivazione) -------------
H1_SHARE = 0.44          # quota del volume di gioco nel 1° tempo (storico ~44/56)
GS_PUSH_BEHIND = 0.14    # chi insegue all'intervallo: +14% tiri nel 2° tempo
GS_SHUT_AHEAD = 0.16     # chi conduce: -16% tiri nel 2° tempo (si abbassa)
GS_CONV_BEHIND = 0.94    # chi insegue converte peggio (difese chiuse, tiri forzati)
GS_FOULS_BEHIND = 0.12   # chi insegue: +12% falli nel 2° tempo (recupero palla)
GS_FOULS_AHEAD = 0.05    # chi conduce: +5% falli (spezzare il gioco)
REST_SHORT_DAYS = 3      # ≤3 giorni dall'ultima gara = riposo corto
REST_CONV_MALUS = 0.95   # stanchezza: -5% precisione tiri nel 2° tempo
REST_FOULS_MALUS = 1.08  # stanchezza: +8% falli nel 2° tempo
MOTIVATION_SOT = 0.6     # quota dell'indice motivazione che agisce sui tiri

# Modificatori meteo (requisiti: -5% precisione tiri, +10% falli/contrasti)
WEATHER_SHOT_PRECISION = 0.95
WEATHER_FOULS_MULT = 1.10
