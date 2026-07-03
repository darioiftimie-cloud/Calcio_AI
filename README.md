# ⚽ Calcio AI — Analytics Board

Web app analitica e predittiva sul calcio in stile "Sisal Analytics Board":
**10.000 simulazioni Monte Carlo per partita** su **dati reali gratuiti**,
backend **FastAPI**, pronta per il deploy gratuito su **Vercel**.

## Sorgenti dati (100% gratuite)

| Cosa | Sorgente |
|------|----------|
| Serie A, Premier League, LaLiga, Bundesliga, Ligue 1, Champions, **Mondiali 2026**, **Europei** | [football-data.org](https://www.football-data.org) (piano gratuito) |
| **Europa League**, **Nations League** | [API-Football](https://dashboard.api-football.com) (piano gratuito) |
| Micro-eventi: tiri, tiri in porta, xG, ammonizioni, statistiche giocatori | [FBref](https://fbref.com) / [Understat](https://understat.com) via `soccerdata` |
| Meteo dello stadio | [Open-Meteo](https://open-meteo.com) (senza chiave) |

I dati vengono scaricati **offline** da `updater.py` e salvati nel database JSON
`data/`. Gli endpoint leggono solo da lì: a runtime **nessuna chiamata API né
scraping** (tranne il meteo) → veloce, senza rate limit e compatibile con Vercel.

## Architettura

```
├── updater.py              Scarica dati reali → popola data/*.json (offline)
├── data/                   Database JSON (incluso nel deploy Vercel)
│   ├── index.json          Elenco competizioni + stato dati
│   └── <lega>.json         Classifica/gironi, calendario, marcatori, micro-eventi
├── api/
│   ├── index.py            ★ Backend FastAPI (unica app ASGI, tutti gli endpoint)
│   │                         GET /api/leagues · /api/standings · /api/bracket
│   │                         GET /api/fixtures · /api/simulate · /api/report (PDF)
│   └── _lib/               Moduli condivisi
│       ├── db.py           Lettura/scrittura database JSON
│       ├── footballdata.py Client football-data.org (usato dall'updater)
│       ├── apifootball.py  Client API-Football per EL/Nations League (updater)
│       ├── fbref.py        Scraper micro-eventi FBref/Understat (updater)
│       ├── engine.py       Motore NumPy vettorizzato (10k sim ≈ 15 ms)
│       ├── stats.py        Profili squadra/giocatori dal DB
│       ├── analysis.py     Orchestratore + cache 60 min
│       ├── weather.py      Impatto meteo (Open-Meteo)
│       ├── pdfgen.py       Generatore PDF (fpdf2)
│       └── cache.py        Cache TTL in-process
├── public/                 Frontend statico (dark UI + Plotly.js)
├── dev_server.py           Locale: uvicorn (FastAPI) + statici su :8700
├── vercel.json             Deploy: /api/* → api/index.py (ASGI), data/ inclusa
├── requirements.txt        Runtime: fastapi · uvicorn · numpy · requests · fpdf2
└── requirements-updater.txt  Offline: soccerdata (+ truststore su Windows)
```

## Competizioni supportate (10)

Serie A · Premier League · LaLiga · Bundesliga · Ligue 1 · Champions League ·
**Europa League** · **Nations League** · **Europei** · **Mondiali 2026** (in corso).

- I micro-eventi (tiri, xG, save rate, giocatori) coprono le 5 grandi leghe; le
  squadre di Champions/Europa League ereditano il profilo dal campionato.
- Per le nazionali (Mondiali, Europei, Nations League) il pool marcatori nasce
  dai **capocannonieri reali del torneo**; per il resto si usano le medie del
  torneo ricavate dai risultati veri.
- Le classifiche dei gironi di Mondiali/Europei sono **ricostruite dai
  risultati**; i tabelloni a eliminazione diretta si aggiornano da soli a ogni
  run dell'updater.
- Piano gratuito API-Football = stagioni fino al 2024-25: Europa League e
  Nations League mostrano l'ultima edizione accessibile (banner in app).

## Il modello

Catena stocastica per iterazione: tempo di gara (Gamma) → tiri in porta
(Poisson) → gol (Binomiale sul save rate del portiere avversario) → parate =
SoT−gol → corner accoppiati alla dominanza → falli → cartellini → marcatori
(quote per giocatore, split minuti 1-70/70-90 con boost per i super-sub).
Meteo estremo → −5% precisione tiri, +10% falli. Cache 60 minuti su ogni analisi.

## Setup locale

```bash
pip install -r requirements.txt              # runtime (fastapi, numpy, ...)
pip install -r requirements-updater.txt      # scraper offline
copy .env.example .env                       # inserisci le TUE chiavi (vedi sotto)
python updater.py                            # popola data/ con dati reali
python dev_server.py                         # → http://127.0.0.1:8700
```

Nel `.env` servono due chiavi gratuite:
- `FOOTBALL_DATA_KEY` — https://www.football-data.org/client/register
- `API_FOOTBALL_KEY` — https://dashboard.api-football.com (solo per
  Europa League e Nations League; senza chiave le altre 8 competizioni
  funzionano comunque)

Aggiornare i dati (es. dopo una giornata o un turno dei Mondiali):
```bash
python updater.py                     # tutto
python updater.py --leagues mondiali  # una sola competizione
python updater.py --micro-only        # solo micro-eventi, senza chiamate API
```

## Deploy su Vercel

```bash
npm install -g vercel        # se non presente
vercel login                 # login interattivo (browser)
vercel link --yes            # crea/collega il progetto
vercel --prod                # URL pubblico a fine comando
```

Il database `data/` viene incluso nel deploy (`vercel.json` → `includeFiles`),
quindi il sito funziona subito e **senza chiavi API in produzione** (le chiavi
servono solo all'updater offline). Per aggiornare i dati: rilancia
`python updater.py` in locale e poi `vercel --prod`.

> Nota sicurezza: le chiavi API stanno solo in `.env` (gitignored). Se sono
> state condivise, rigenerale dai rispettivi account.
