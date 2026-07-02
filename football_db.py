# -*- coding: utf-8 -*-
"""
================================================================================
 FOOTBALL DB — Database squadre e competizioni per il Super Manager
================================================================================
Rating illustrativi ma realistici (1.00 = media). Modifica liberamente questo
file per aggiornare forze, portieri e bomber, o per aggiungere campionati:
il Super Manager legge tutto da qui.

Formato squadra (helper T):
    att   : forza offensiva (moltiplicatore xG prodotti)
    dif   : xG concessi (più basso = difesa migliore)
    gk    : nome portiere titolare
    sr    : save rate del portiere (0-1)
    aggr  : indice aggressività disciplinare (falli/cartellini)
    stars : giocatori chiave (nome, ruolo POR/DIF/CEN/ATT, peso xG, rigorista)
================================================================================
"""


def T(att, dif, gk, sr, aggr=1.05, stars=()):
    return {
        "att": att, "dif": dif, "gk": gk, "sr": sr, "aggr": aggr,
        "stars": [{"name": n, "role": r, "xg": x, "pen": bool(p)} for n, r, x, p in stars],
    }


TEAMS = {
    # ---------------------------------------------------------------- Serie A
    "Inter":        T(1.30, 0.80, "Y. Sommer", 0.735, 1.09, [("L. Martínez", "ATT", 1.60, 1), ("M. Thuram", "ATT", 1.40, 0), ("H. Çalhanoğlu", "CEN", 1.35, 0)]),
    "Milan":        T(1.18, 0.98, "M. Maignan", 0.710, 1.13, [("C. Pulisic", "ATT", 1.45, 1), ("R. Leão", "ATT", 1.40, 0)]),
    "Juventus":     T(1.15, 0.85, "M. Di Gregorio", 0.720, 1.05, [("D. Vlahović", "ATT", 1.45, 1), ("K. Yıldız", "ATT", 1.35, 0)]),
    "Napoli":       T(1.24, 0.84, "A. Meret", 0.720, 1.02, [("R. Højlund", "ATT", 1.45, 0), ("K. De Bruyne", "CEN", 1.35, 1)]),
    "Roma":         T(1.10, 0.90, "M. Svilar", 0.740, 1.08, [("P. Dybala", "ATT", 1.40, 1), ("A. Dovbyk", "ATT", 1.35, 0)]),
    "Lazio":        T(1.08, 0.98, "I. Provedel", 0.700, 1.10, [("V. Castellanos", "ATT", 1.35, 1), ("M. Zaccagni", "ATT", 1.25, 0)]),
    "Atalanta":     T(1.22, 0.95, "M. Carnesecchi", 0.710, 1.07, [("A. Lookman", "ATT", 1.45, 0), ("G. Scamacca", "ATT", 1.40, 1)]),
    "Fiorentina":   T(1.05, 1.00, "D. De Gea", 0.730, 1.05, [("M. Kean", "ATT", 1.45, 1), ("A. Guðmundsson", "ATT", 1.25, 0)]),
    "Bologna":      T(1.05, 0.95, "Ł. Skorupski", 0.700, 1.06, [("R. Orsolini", "ATT", 1.35, 1), ("S. Castro", "ATT", 1.25, 0)]),
    "Torino":       T(0.92, 1.02, "V. Milinković-Savić", 0.720, 1.10, [("D. Zapata", "ATT", 1.30, 1)]),
    "Udinese":      T(0.95, 1.05, "M. Okoye", 0.680, 1.08, [("K. Davis", "ATT", 1.25, 1)]),
    "Genoa":        T(0.88, 1.05, "N. Leali", 0.690, 1.08, [("L. Colombo", "ATT", 1.20, 1)]),
    "Como":         T(1.00, 1.05, "J. Butez", 0.680, 1.02, [("Á. Morata", "ATT", 1.35, 1), ("N. Paz", "CEN", 1.25, 0)]),
    "Verona":       T(0.82, 1.12, "L. Montipò", 0.690, 1.12, [("Giovane", "ATT", 1.15, 1)]),
    "Cagliari":     T(0.85, 1.10, "E. Caprile", 0.700, 1.08, [("S. Esposito", "ATT", 1.20, 1)]),
    "Lecce":        T(0.80, 1.10, "W. Falcone", 0.700, 1.10, [("N. Krstović", "ATT", 1.25, 1)]),
    "Parma":        T(0.88, 1.12, "Z. Suzuki", 0.680, 1.07, [("M. Pellegrino", "ATT", 1.20, 1)]),
    "Sassuolo":     T(0.92, 1.15, "S. Turati", 0.670, 1.04, [("D. Berardi", "ATT", 1.35, 1)]),
    "Pisa":         T(0.78, 1.15, "A. Šemper", 0.670, 1.10, [("M. Nzola", "ATT", 1.20, 1)]),
    "Cremonese":    T(0.78, 1.18, "E. Audero", 0.670, 1.08, [("J. Vardy", "ATT", 1.25, 1)]),

    # ---------------------------------------------------------- Premier League
    "Man City":     T(1.35, 0.85, "G. Donnarumma", 0.740, 1.00, [("E. Haaland", "ATT", 1.70, 1), ("P. Foden", "CEN", 1.30, 0)]),
    "Arsenal":      T(1.30, 0.78, "D. Raya", 0.740, 1.05, [("V. Gyökeres", "ATT", 1.50, 1), ("B. Saka", "ATT", 1.40, 0)]),
    "Liverpool":    T(1.35, 0.85, "Alisson", 0.740, 1.02, [("M. Salah", "ATT", 1.55, 1), ("A. Isak", "ATT", 1.45, 0)]),
    "Chelsea":      T(1.22, 0.92, "R. Sánchez", 0.700, 1.06, [("C. Palmer", "ATT", 1.45, 1), ("João Pedro", "ATT", 1.30, 0)]),
    "Man United":   T(1.10, 1.00, "S. Lammens", 0.690, 1.08, [("B. Fernandes", "CEN", 1.30, 1), ("B. Šeško", "ATT", 1.35, 0)]),
    "Tottenham":    T(1.15, 1.02, "G. Vicario", 0.710, 1.04, [("D. Solanke", "ATT", 1.30, 1), ("M. Kudus", "ATT", 1.25, 0)]),
    "Newcastle":    T(1.18, 0.92, "N. Pope", 0.720, 1.10, [("A. Gordon", "ATT", 1.30, 1), ("N. Woltemade", "ATT", 1.30, 0)]),
    "Aston Villa":  T(1.15, 0.95, "E. Martínez", 0.730, 1.06, [("O. Watkins", "ATT", 1.35, 1), ("M. Rogers", "CEN", 1.25, 0)]),
    "Brighton":     T(1.10, 1.02, "B. Verbruggen", 0.700, 1.03, [("D. Welbeck", "ATT", 1.20, 1), ("K. Mitoma", "ATT", 1.20, 0)]),
    "West Ham":     T(0.95, 1.10, "A. Areola", 0.700, 1.08, [("J. Bowen", "ATT", 1.30, 1)]),
    "Crystal Palace": T(1.02, 0.92, "D. Henderson", 0.720, 1.07, [("J.-P. Mateta", "ATT", 1.30, 1), ("I. Sarr", "ATT", 1.20, 0)]),
    "Fulham":       T(1.00, 1.02, "B. Leno", 0.710, 1.05, [("R. Jiménez", "ATT", 1.20, 1)]),
    "Brentford":    T(1.05, 1.05, "C. Kelleher", 0.710, 1.06, [("I. Thiago", "ATT", 1.25, 1)]),
    "Everton":      T(0.95, 1.00, "J. Pickford", 0.730, 1.08, [("I. Ndiaye", "ATT", 1.20, 1), ("J. Grealish", "ATT", 1.15, 0)]),
    "Nottingham Forest": T(1.02, 0.95, "M. Sels", 0.720, 1.08, [("C. Wood", "ATT", 1.30, 1)]),
    "Bournemouth":  T(1.08, 1.00, "Đ. Petrović", 0.710, 1.07, [("A. Semenyo", "ATT", 1.30, 1)]),
    "Wolves":       T(0.90, 1.10, "J. Sá", 0.690, 1.08, [("J. Strand Larsen", "ATT", 1.25, 1)]),
    "Leeds":        T(0.92, 1.08, "L. Perri", 0.690, 1.07, [("J. Piroe", "ATT", 1.20, 1)]),
    "Burnley":      T(0.80, 1.15, "M. Dúbravka", 0.690, 1.06, [("L. Foster", "ATT", 1.15, 1)]),
    "Sunderland":   T(0.85, 1.10, "R. Roefs", 0.690, 1.06, [("W. Isidor", "ATT", 1.15, 1)]),

    # ------------------------------------------------------------------ La Liga
    "Real Madrid":  T(1.40, 0.85, "T. Courtois", 0.750, 1.02, [("K. Mbappé", "ATT", 1.70, 1), ("Vinícius Jr", "ATT", 1.50, 0), ("J. Bellingham", "CEN", 1.35, 0)]),
    "Barcellona":   T(1.40, 0.90, "J. García", 0.730, 1.00, [("R. Lewandowski", "ATT", 1.55, 1), ("L. Yamal", "ATT", 1.50, 0), ("Raphinha", "ATT", 1.40, 0)]),
    "Atletico Madrid": T(1.18, 0.85, "J. Oblak", 0.750, 1.12, [("J. Álvarez", "ATT", 1.45, 1), ("A. Griezmann", "ATT", 1.30, 0)]),
    "Athletic Bilbao": T(1.08, 0.92, "U. Simón", 0.720, 1.08, [("N. Williams", "ATT", 1.35, 1), ("O. Sancet", "CEN", 1.25, 0)]),
    "Real Sociedad": T(1.02, 0.98, "Á. Remiro", 0.710, 1.04, [("M. Oyarzabal", "ATT", 1.30, 1)]),
    "Villarreal":   T(1.12, 0.95, "L. Júnior", 0.700, 1.03, [("A. Pérez", "ATT", 1.30, 1), ("G. Moleiro", "CEN", 1.20, 0)]),
    "Betis":        T(1.05, 1.00, "Á. Valles", 0.700, 1.05, [("Antony", "ATT", 1.25, 1), ("Isco", "CEN", 1.25, 0)]),
    "Siviglia":     T(0.98, 1.05, "Ø. Nyland", 0.680, 1.09, [("I. Romero", "ATT", 1.20, 1)]),
    "Valencia":     T(0.95, 1.05, "J. Agirrezabala", 0.700, 1.06, [("H. Duro", "ATT", 1.20, 1)]),
    "Girona":       T(0.98, 1.08, "P. Gazzaniga", 0.690, 1.05, [("C. Stuani", "ATT", 1.20, 1)]),
    "Osasuna":      T(0.92, 1.05, "S. Herrera", 0.690, 1.10, [("A. Budimir", "ATT", 1.25, 1)]),
    "Celta Vigo":   T(0.98, 1.05, "V. Guaita", 0.690, 1.04, [("I. Aspas", "ATT", 1.25, 1), ("B. Iglesias", "ATT", 1.20, 0)]),
    "Mallorca":     T(0.88, 1.02, "L. Román", 0.700, 1.09, [("V. Muriqi", "ATT", 1.20, 1)]),
    "Getafe":       T(0.85, 1.00, "D. Soria", 0.710, 1.15, [("B. Mayoral", "ATT", 1.20, 1)]),
    "Alaves":       T(0.85, 1.08, "A. Sivera", 0.690, 1.10, [("L. Boyé", "ATT", 1.15, 1)]),
    "Espanyol":     T(0.90, 1.08, "M. Dmitrović", 0.700, 1.07, [("J. Puado", "ATT", 1.20, 1)]),
    "Rayo Vallecano": T(0.95, 1.02, "A. Batalla", 0.700, 1.10, [("S. Camello", "ATT", 1.15, 1), ("I. Palazón", "ATT", 1.15, 0)]),
    "Levante":      T(0.85, 1.12, "M. Ryan", 0.680, 1.06, [("C. Álvarez", "ATT", 1.15, 1)]),
    "Elche":        T(0.82, 1.10, "M. Dituro", 0.680, 1.05, [("Rafa Mir", "ATT", 1.20, 1)]),
    "Oviedo":       T(0.80, 1.12, "A. Escandell", 0.680, 1.07, [("F. Viñas", "ATT", 1.15, 1)]),

    # ------------------------------------------- Altri club europei (coppe)
    "Bayern Monaco": T(1.42, 0.88, "M. Neuer", 0.720, 1.03, [("H. Kane", "ATT", 1.70, 1), ("M. Olise", "ATT", 1.40, 0)]),
    "B. Leverkusen": T(1.15, 0.95, "M. Flekken", 0.700, 1.05, [("P. Schick", "ATT", 1.35, 1)]),
    "B. Dortmund":  T(1.18, 0.95, "G. Kobel", 0.730, 1.06, [("S. Guirassy", "ATT", 1.45, 1)]),
    "PSG":          T(1.38, 0.82, "L. Chevalier", 0.730, 1.04, [("O. Dembélé", "ATT", 1.50, 1), ("D. Doué", "ATT", 1.35, 0), ("Vitinha", "CEN", 1.25, 0)]),
    "Benfica":      T(1.15, 0.92, "A. Trubin", 0.720, 1.07, [("V. Pavlidis", "ATT", 1.35, 1)]),
    "Ajax":         T(1.10, 1.00, "V. Jaroš", 0.690, 1.04, [("W. Weghorst", "ATT", 1.25, 1)]),
    "Porto":        T(1.10, 0.90, "D. Costa", 0.730, 1.08, [("Samu", "ATT", 1.30, 1)]),
    "Sporting CP":  T(1.15, 0.88, "R. Silva", 0.720, 1.05, [("F. Ioannidis", "ATT", 1.30, 1), ("P. Gonçalves", "CEN", 1.25, 0)]),
    "Lipsia":       T(1.12, 0.98, "P. Gulácsi", 0.710, 1.05, [("Rômulo", "ATT", 1.25, 1), ("A. Nusa", "ATT", 1.20, 0)]),
    "Eintracht Francoforte": T(1.12, 1.02, "M. Zetterer", 0.690, 1.06, [("J. Burkardt", "ATT", 1.30, 1)]),
    "Marsiglia":    T(1.12, 1.00, "G. Rulli", 0.710, 1.08, [("P.-E. Aubameyang", "ATT", 1.35, 1), ("M. Greenwood", "ATT", 1.30, 0)]),
    "Lione":        T(1.05, 1.02, "R. Descamps", 0.690, 1.06, [("M. Fofana", "ATT", 1.20, 1)]),
    "Fenerbahçe":   T(1.10, 1.00, "İ. Eğribayat", 0.690, 1.10, [("Y. En-Nesyri", "ATT", 1.30, 1)]),
    "Feyenoord":    T(1.08, 1.02, "T. Wellenreuther", 0.700, 1.06, [("A. Ueda", "ATT", 1.25, 1)]),

    # ------------------------------------------------------------- Nazionali
    "Argentina":    T(1.30, 0.78, "E. Martínez", 0.750, 1.06, [("L. Messi", "ATT", 1.50, 1), ("J. Álvarez", "ATT", 1.40, 0), ("L. Martínez", "ATT", 1.35, 0)]),
    "Francia":      T(1.32, 0.80, "M. Maignan", 0.710, 1.04, [("K. Mbappé", "ATT", 1.70, 1), ("O. Dembélé", "ATT", 1.45, 0)]),
    "Brasile":      T(1.28, 0.85, "Alisson", 0.740, 1.05, [("Vinícius Jr", "ATT", 1.50, 1), ("Raphinha", "ATT", 1.40, 0)]),
    "Inghilterra":  T(1.28, 0.82, "J. Pickford", 0.730, 1.03, [("H. Kane", "ATT", 1.70, 1), ("B. Saka", "ATT", 1.40, 0)]),
    "Spagna":       T(1.35, 0.80, "U. Simón", 0.720, 1.02, [("L. Yamal", "ATT", 1.50, 0), ("M. Oyarzabal", "ATT", 1.30, 1), ("Pedri", "CEN", 1.20, 0)]),
    "Germania":     T(1.25, 0.90, "M. ter Stegen", 0.720, 1.05, [("F. Wirtz", "CEN", 1.40, 1), ("N. Woltemade", "ATT", 1.35, 0)]),
    "Portogallo":   T(1.28, 0.85, "D. Costa", 0.730, 1.05, [("C. Ronaldo", "ATT", 1.50, 1), ("R. Leão", "ATT", 1.35, 0)]),
    "Olanda":       T(1.22, 0.88, "B. Verbruggen", 0.700, 1.05, [("M. Depay", "ATT", 1.35, 1), ("C. Gakpo", "ATT", 1.30, 0)]),
    "Italia":       T(1.15, 0.85, "G. Donnarumma", 0.740, 1.06, [("M. Retegui", "ATT", 1.35, 1), ("G. Raspadori", "ATT", 1.20, 0)]),
    "Belgio":       T(1.18, 0.95, "T. Courtois", 0.750, 1.05, [("R. Lukaku", "ATT", 1.40, 1), ("K. De Bruyne", "CEN", 1.35, 0)]),
    "Croazia":      T(1.10, 0.95, "D. Livaković", 0.710, 1.07, [("L. Modrić", "CEN", 1.20, 1), ("A. Kramarić", "ATT", 1.25, 0)]),
    "Uruguay":      T(1.12, 0.88, "S. Rochet", 0.710, 1.10, [("D. Núñez", "ATT", 1.35, 1)]),
    "Colombia":     T(1.12, 0.92, "C. Vargas", 0.700, 1.08, [("L. Díaz", "ATT", 1.35, 0), ("J. Rodríguez", "CEN", 1.25, 1)]),
    "Marocco":      T(1.10, 0.85, "Y. Bounou", 0.730, 1.08, [("Y. En-Nesyri", "ATT", 1.30, 1), ("A. Hakimi", "DIF", 1.20, 0)]),
    "USA":          T(1.05, 0.98, "M. Turner", 0.700, 1.05, [("C. Pulisic", "ATT", 1.40, 1)]),
    "Giappone":     T(1.08, 0.92, "Z. Suzuki", 0.700, 1.03, [("T. Kubo", "ATT", 1.25, 1), ("K. Mitoma", "ATT", 1.25, 0)]),
    "Svizzera":     T(1.05, 0.95, "G. Kobel", 0.730, 1.06, [("B. Embolo", "ATT", 1.25, 1)]),
    "Danimarca":    T(1.08, 0.95, "K. Schmeichel", 0.700, 1.05, [("R. Højlund", "ATT", 1.35, 1)]),
    "Austria":      T(1.08, 0.98, "P. Pentz", 0.690, 1.10, [("M. Sabitzer", "CEN", 1.20, 1), ("M. Gregoritsch", "ATT", 1.20, 0)]),
    "Turchia":      T(1.10, 1.00, "A. Bayındır", 0.700, 1.09, [("A. Güler", "CEN", 1.30, 1), ("K. Yıldız", "ATT", 1.35, 0)]),
    "Ucraina":      T(1.05, 0.98, "A. Lunin", 0.720, 1.06, [("A. Dovbyk", "ATT", 1.30, 1)]),
    "Polonia":      T(1.02, 1.02, "Ł. Skorupski", 0.700, 1.06, [("R. Lewandowski", "ATT", 1.50, 1)]),
    "Scozia":       T(0.95, 1.05, "A. Gunn", 0.690, 1.10, [("S. McTominay", "CEN", 1.30, 1)]),
}


COMPETITIONS = {
    # ------------------------------------------------------ Campionati (girone)
    "serie_a": {
        "nome": "Serie A", "icona": "🇮🇹", "tipo": "league",
        "teams": ["Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio", "Atalanta",
                  "Fiorentina", "Bologna", "Torino", "Udinese", "Genoa", "Como", "Verona",
                  "Cagliari", "Lecce", "Parma", "Sassuolo", "Pisa", "Cremonese"],
    },
    "premier_league": {
        "nome": "Premier League", "icona": "🏴", "tipo": "league",
        "teams": ["Man City", "Arsenal", "Liverpool", "Chelsea", "Man United", "Tottenham",
                  "Newcastle", "Aston Villa", "Brighton", "West Ham", "Crystal Palace",
                  "Fulham", "Brentford", "Everton", "Nottingham Forest", "Bournemouth",
                  "Wolves", "Leeds", "Burnley", "Sunderland"],
    },
    "la_liga": {
        "nome": "La Liga", "icona": "🇪🇸", "tipo": "league",
        "teams": ["Real Madrid", "Barcellona", "Atletico Madrid", "Athletic Bilbao",
                  "Real Sociedad", "Villarreal", "Betis", "Siviglia", "Valencia", "Girona",
                  "Osasuna", "Celta Vigo", "Mallorca", "Getafe", "Alaves", "Espanyol",
                  "Rayo Vallecano", "Levante", "Elche", "Oviedo"],
    },
    # --------------------------------------------- Tornei a eliminazione diretta
    "champions_league": {
        "nome": "Champions League", "icona": "⭐", "tipo": "knockout", "neutral": True,
        "teams": ["Real Madrid", "Ajax", "Man City", "Benfica", "Bayern Monaco", "Juventus",
                  "PSG", "Chelsea", "Barcellona", "Napoli", "Liverpool", "Atletico Madrid",
                  "Arsenal", "B. Dortmund", "Inter", "B. Leverkusen"],
    },
    "europa_league": {
        "nome": "Europa League", "icona": "🟠", "tipo": "knockout", "neutral": True,
        "teams": ["Roma", "Feyenoord", "Man United", "Porto", "Lazio", "Betis",
                  "Tottenham", "Eintracht Francoforte", "Siviglia", "Bologna", "Lipsia",
                  "Fenerbahçe", "Sporting CP", "Marsiglia", "Villarreal", "Lione"],
    },
    "mondiali": {
        "nome": "Mondiali FIFA", "icona": "🏆", "tipo": "knockout", "neutral": True,
        "teams": ["Argentina", "Giappone", "Francia", "USA", "Brasile", "Marocco",
                  "Inghilterra", "Colombia", "Spagna", "Uruguay", "Germania", "Croazia",
                  "Portogallo", "Belgio", "Olanda", "Italia"],
    },
    "europei": {
        "nome": "Europei UEFA", "icona": "🇪🇺", "tipo": "knockout", "neutral": True,
        "teams": ["Spagna", "Scozia", "Francia", "Polonia", "Inghilterra", "Ucraina",
                  "Germania", "Turchia", "Italia", "Austria", "Portogallo", "Danimarca",
                  "Olanda", "Svizzera", "Belgio", "Croazia"],
    },
    "nations_league": {
        "nome": "Nations League — Final Four", "icona": "🔷", "tipo": "knockout", "neutral": True,
        "teams": ["Spagna", "Francia", "Portogallo", "Germania"],
    },
}
