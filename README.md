# ⚽ Calcio AI — Analytics Board

Web app analitica e predittiva sul calcio in stile "Sisal Analytics Board":
**10.000 simulazioni Monte Carlo per partita** su **dati reali gratuiti**,
pronta per il deploy gratuito su **Vercel**.

## Sorgenti dati (100% gratuite)

| Cosa | Sorgente |
|------|----------|
| Risultati, classifiche, calendari, marcatori | [football-data.org](https://www.football-data.org) (piano gratuito) |
| Micro-eventi: tiri, tiri in porta, xG, ammonizioni, statistiche giocatori | [FBref](https://fbref.com) / [Understat](https://understat.com) via `soccerdata` |
| Meteo dello stadio | [Open-Meteo](https://open-meteo.com) (senza chiave) |

I dati vengono scaricati **offline** da `updater.py` e salvati nel database JSON
`data/`. Gli endpoint serverless leggono solo da lì: a runtime **nessuna chiamata
API né scraping** → veloce, senza rate limit e compatibile con Vercel.

## Architettura

```
├── updater.py              Scarica dati reali → popola data/*.json (offline)
├── data/                   Database JSON (incluso nel deploy Vercel)
│   ├── index.json          Elenco competizioni + stato dati
│   └── <lega>.json         Classifica, calendario/risultati, marcatori, micro-eventi
├── api/                    Funzioni Python serverless (runtime Vercel)
│   ├── leagues.py          GET /api/leagues     → competizioni disponibili
│   ├── standings.py        GET /api/standings   → classifiche
│   ├── bracket.py          GET /api/bracket     → tabelloni a eliminazione diretta
│   ├── fixtures.py         GET /api/fixtures    → prossime partite / risultati
│   ├── simulate.py         GET /api/simulate    → analisi Monte Carlo completa
│   ├── report.py           GET /api/report      → Report Analitico PDF
│   └── _lib/               Moduli condivisi
│       ├── db.py           Lettura/scrittura database JSON
│       ├── footballdata.py Client football-data.org (usato dall'updater)
│       ├── fbref.py        Scraper micro-eventi FBref/Understat (updater)
│       ├── engine.py       Motore NumPy vettorizzato (10k sim ≈ 15 ms)
│       ├── stats.py        Profili squadra/giocatori dal DB
│       ├── analysis.py     Orchestratore + cache 60 min
│       ├── weather.py      Impatto meteo (Open-Meteo)
│       ├── pdfgen.py       Generatore PDF (fpdf2)
│       └── cache.py        Cache TTL in-process
├── public/                 Frontend statico (dark UI + Plotly.js)
├── vercel.json             Configurazione deploy (include data/ nel bundle)
├── requirements.txt        Runtime: numpy · requests · fpdf2
└── requirements-updater.txt  Offline: soccerdata (+ truststore su Windows)
```

## Competizioni supportate

Serie A · Premier League · LaLiga · Bundesliga · Ligue 1 · Champions League.
Sono le competizioni coperte dal piano gratuito di football-data.org. I
micro-eventi (tiri, xG, marcatori) coprono le 5 grandi leghe; le squadre di
Champions ereditano il profilo dal campionato nazionale (o le medie di lega se
non disponibile).

## Stagione e dati "2026"

`SEASON=2026` (in `.env`) = stagione 2026-27. Finché non è iniziata, l'updater
mostra **il calendario 2026-27 reale** per le prossime partite e ripiega su
**risultati, classifiche e statistiche dell'ultima stagione disputata** (2025-26),
segnalandolo con un banner. Appena il campionato riparte, rilanciando l'updater
tutto passa da solo ai dati 2026-27 in tempo reale.

## Il modello

Catena stocastica per iterazione: tempo di gara (Gamma) → tiri in porta
(Poisson) → gol (Binomiale sul save rate del portiere avversario) → parate =
SoT−gol → corner accoppiati alla dominanza → falli → cartellini → marcatori
(quote per giocatore, split minuti 1-70/70-90 con boost per i super-sub).
Meteo estremo → −5% precisione tiri, +10% falli. Cache 60 minuti su ogni analisi.

## Setup locale

```bash
pip install -r requirements.txt              # runtime
pip install -r requirements-updater.txt      # scraper offline
copy .env.example .env                        # inserisci FOOTBALL_DATA_KEY
python updater.py                             # popola data/ con dati reali
python dev_server.py                          # → http://127.0.0.1:8700
```

Aggiornare i dati (es. dopo una giornata di campionato):
```bash
python updater.py                     # tutto
python updater.py --micro-only        # solo micro-eventi, senza ricontattare football-data
python updater.py --leagues serie_a   # una sola competizione
```

## Deploy su Vercel

```bash
npm install -g vercel        # se non presente
vercel login                 # login interattivo (browser)
vercel link --yes            # crea/collega il progetto
echo "LA_TUA_CHIAVE" | vercel env add FOOTBALL_DATA_KEY production
vercel --prod                # URL pubblico a fine comando
```

Il database `data/` viene incluso nel deploy (`vercel.json` → `includeFiles`),
quindi il sito funziona subito. Per aggiornare i dati: rilancia `updater.py` in
locale e poi `vercel --prod` (oppure una GitHub Action pianificata).

> Nota sicurezza: la chiave football-data.org è in `.env` (gitignored). Se è
> stata condivisa, valuta di rigenerarla dal tuo account.
