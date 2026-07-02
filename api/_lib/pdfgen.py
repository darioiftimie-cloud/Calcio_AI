# -*- coding: utf-8 -*-
"""Report Analitico PDF (fpdf2): riassume le 10.000 simulazioni del match
con tabelle e grafici a barre disegnati nativamente (leggero, serverless-safe).
"""

from fpdf import FPDF

ACCENT = (34, 197, 94)      # verde
ACCENT2 = (59, 130, 246)    # blu
DARK = (17, 24, 39)
GRAY = (107, 114, 128)
LIGHT = (243, 244, 246)


def _tx(s) -> str:
    """fpdf2 con font core supporta solo latin-1: sanitizza i nomi."""
    return str(s).encode("latin-1", "replace").decode("latin-1")


class Report(FPDF):
    def header(self):
        self.set_fill_color(*DARK)
        self.rect(0, 0, 210, 18, "F")
        self.set_font("helvetica", "B", 12)
        self.set_text_color(255, 255, 255)
        self.set_xy(10, 5)
        self.cell(0, 8, "CALCIO AI - Analytics Board | Report Monte Carlo 10.000 simulazioni")
        self.set_y(24)

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"Pagina {self.page_no()} - generato da Calcio AI", align="C")

    # ------------------------------------------------------------ componenti
    def section(self, title: str):
        self.ln(3)
        self.set_font("helvetica", "B", 11)
        self.set_text_color(*DARK)
        self.cell(0, 7, _tx(title.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.6)
        self.line(10, self.get_y(), 70, self.get_y())
        self.ln(2.5)

    def bar_row(self, label: str, pct: float, color=ACCENT, width=90.0):
        self.set_font("helvetica", "", 9)
        self.set_text_color(*DARK)
        self.cell(52, 5.4, _tx(label))
        x, y = self.get_x(), self.get_y()
        self.set_fill_color(*LIGHT)
        self.rect(x, y + 0.8, width, 3.8, "F")
        self.set_fill_color(*color)
        self.rect(x, y + 0.8, max(width * min(pct, 100) / 100.0, 0.6), 3.8, "F")
        self.set_xy(x + width + 2, y)
        self.cell(18, 5.4, f"{pct:.2f}%", new_x="LMARGIN", new_y="NEXT")

    def kv_row(self, label: str, value: str):
        self.set_font("helvetica", "", 9)
        self.set_text_color(*GRAY)
        self.cell(70, 5.2, _tx(label))
        self.set_text_color(*DARK)
        self.set_font("helvetica", "B", 9)
        self.cell(0, 5.2, _tx(value), new_x="LMARGIN", new_y="NEXT")


def build_pdf(analysis: dict) -> bytes:
    meta, sim = analysis["meta"], analysis["sim"]
    meteo, prof = analysis["meteo"], analysis["profili"]
    home, away = meta["home"]["name"], meta["away"]["name"]

    pdf = Report()
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()

    # intestazione match
    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 9, _tx(f"{home}  vs  {away}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, _tx(f"{meta['league']} - {meta['round']} - {str(meta['date'])[:16]} "
                       f"- {meta.get('venue') or ''} ({meta.get('city') or '?'})"),
             new_x="LMARGIN", new_y="NEXT")

    # meteo
    if meteo.get("disponibile"):
        cond = meteo["condizione"]
        extra = (" -> modello corretto: -5% precisione tiri, +10% falli"
                 if meteo["estremo"] else "")
        pdf.cell(0, 5, _tx(f"Meteo: {cond}, {meteo['temperatura']}°C, "
                           f"pioggia {meteo['pioggia_mm']} mm/h, vento "
                           f"{meteo['vento_kmh']} km/h{extra}"),
                 new_x="LMARGIN", new_y="NEXT")

    # esiti principali
    pdf.section("Esiti 1X2 e linee gol")
    o = sim["outcomes"]
    pdf.bar_row(f"1 - {home}", o["1"])
    pdf.bar_row("X - Pareggio", o["X"])
    pdf.bar_row(f"2 - {away}", o["2"], ACCENT2)
    pdf.bar_row("BTTS (Gol/Gol)", sim["btts"], ACCENT2)
    for line, p in sim["over"].items():
        pdf.bar_row(f"Over {line}", p, ACCENT2)

    # top risultati esatti
    pdf.section("Risultati esatti piu probabili")
    for score, p in sim["top_scores"][:8]:
        pdf.bar_row(score, p * 4, width=90)  # scala x4 per leggibilità
        pdf.set_xy(pdf.get_x(), pdf.get_y() - 5.4)
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*GRAY)
        pdf.set_x(160)
        pdf.cell(0, 5.4, f"({p:.2f}%)", new_x="LMARGIN", new_y="NEXT")

    # micro-eventi
    pdf.section("Micro-eventi attesi (medie su 10.000 sim)")
    pdf.kv_row("xG modello", f"{home} {sim['xg']['home']}  -  {away} {sim['xg']['away']}")
    pdf.kv_row("Tiri totali", f"{sim['shots']['mean_home']}  -  {sim['shots']['mean_away']}")
    pdf.kv_row("Tiri in porta", f"{sim['shots']['sot_home']}  -  {sim['shots']['sot_away']}")
    pdf.kv_row("Parate portieri",
               f"{prof['home']['keeper']['name']} {sim['saves']['mean_home']}  -  "
               f"{prof['away']['keeper']['name']} {sim['saves']['mean_away']}")
    pdf.kv_row("Corner", f"{sim['corners']['mean_home']}  -  {sim['corners']['mean_away']}"
               f"  (totali {sim['corners']['mean_total']})")
    pdf.kv_row("Falli", f"{sim['fouls']['mean_home']}  -  {sim['fouls']['mean_away']}")
    pdf.kv_row("Ammonizioni", f"{sim['cards']['yellows_home']}  -  {sim['cards']['yellows_away']}"
               f"  (cartellini totali {sim['cards']['mean_total']})")
    pdf.kv_row("Prob. espulsione", f"{sim['cards']['red_prob_home']}%  -  {sim['cards']['red_prob_away']}%")

    # linee corner / cartellini
    pdf.section("Linee Corner e Cartellini")
    for line, p in list(sim["corners"]["lines"].items())[:4]:
        pdf.bar_row(f"Corner Over {line}", p)
    for line, p in list(sim["cards"]["lines"].items())[:4]:
        pdf.bar_row(f"Cartellini Over {line}", p, ACCENT2)

    # marcatori
    pdf.add_page()
    pdf.section(f"Marcatori - {home}")
    for r in sim["scorers"]["home"][:8]:
        tag = " (R)" if r["penalty_taker"] else (" (sub)" if r["super_sub"] else "")
        pdf.bar_row(f"{r['name']}{tag}", r["anytime"])
    pdf.section(f"Marcatori - {away}")
    for r in sim["scorers"]["away"][:8]:
        tag = " (R)" if r["penalty_taker"] else (" (sub)" if r["super_sub"] else "")
        pdf.bar_row(f"{r['name']}{tag}", r["anytime"], ACCENT2)

    # value bets
    if analysis.get("value_bets"):
        pdf.section(f"Value Bets vs bookmaker ({analysis['odds'].get('bookmaker') or '-'})")
        pdf.set_font("helvetica", "B", 8.5)
        pdf.set_text_color(*DARK)
        for col, w in (("Mercato", 40), ("Quota", 25), ("Prob. modello", 35),
                       ("Prob. implicita", 35), ("Edge", 25), ("Value", 20)):
            pdf.cell(w, 6, col, border="B")
        pdf.ln()
        pdf.set_font("helvetica", "", 8.5)
        for b in analysis["value_bets"]:
            pdf.cell(40, 5.6, _tx(b["mercato"]))
            pdf.cell(25, 5.6, f"{b['quota']:.2f}")
            pdf.cell(35, 5.6, f"{b['prob_modello']:.1f}%")
            pdf.cell(35, 5.6, f"{b['prob_implicita']:.1f}%")
            pdf.cell(25, 5.6, f"{b['edge']:+.1f}%")
            pdf.set_text_color(*(ACCENT if b["value"] else GRAY))
            pdf.cell(20, 5.6, "SI" if b["value"] else "no",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*DARK)

    pdf.set_y(-24)
    pdf.set_font("helvetica", "I", 7.5)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(0, 3.6, _tx(
        "Modello: catena stocastica Monte Carlo (tempo di gara -> tiri in porta -> "
        "gol via thinning binomiale sul save rate del portiere -> corner/falli/cartellini "
        "accoppiati). Statistiche cumulative del torneo in corso + forma recente. "
        "Documento a scopo analitico: nessuna garanzia di risultato."))

    return bytes(pdf.output())
