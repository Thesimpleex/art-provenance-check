"""PDF output for review records and catalogue overviews, without extra dependencies.

A small PDF writer using the standard PDF fonts (Helvetica, Courier) in WinAnsi
encoding. Line breaks are computed from font metrics: if Pillow and the system fonts
are available their metrics are used, otherwise an approximation.
All texts exist in German (default) and English, see texts.py.

Demo: python3 pdf_record.py ["provenance text"] [--en]   → writes protokoll.pdf
"""
from __future__ import annotations

import zlib
from datetime import datetime
from pathlib import Path

import texts
from texts import t as _t

A4 = (595.28, 841.89)
RAND = 56.0
KAPPA = 0.5523                                    # Bézier approximation of a quarter circle
# House colours: black, white, greys and a signal colour for a high review level
TINTE, LEISE, HAUCH, LINIE = (0.04, 0.04, 0.04), (0.45, 0.45, 0.45), (0.64, 0.64, 0.64), (0.9, 0.9, 0.9)
SIGNAL, BERNSTEIN, BELEGT, FLAECHE = (1.0, 0.31, 0.0), (0.76, 0.49, 0.05), (0.04, 0.04, 0.04), (0.96, 0.96, 0.96)
ROT = SIGNAL
FARBE = {"hoch": SIGNAL, "mittel": BERNSTEIN, "hinweis": LEISE, "gering": TINTE}
SCHRIFTEN = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Helvetica-Bold", "F4": "Courier"}
ERSATZ = {"→": "›", "≈": "~", "✓": "x", "′": "'", "″": '"', " ": " ", " ": " "}


def _messer():
    """Text width per font: real metrics via Pillow, otherwise an approximation."""
    try:
        from PIL import ImageFont
        dateien = {"F1": ("/System/Library/Fonts/Helvetica.ttc", 0), "F2": ("/System/Library/Fonts/Helvetica.ttc", 1),
                   "F3": ("/System/Library/Fonts/Helvetica.ttc", 1)}
        fonts = {k: ImageFont.truetype(p, 1000, index=i) for k, (p, i) in dateien.items()}
    except Exception:
        fonts = {}

    def breite(text: str, schrift: str, groesse: float) -> float:
        if schrift == "F4":
            return 0.6 * groesse * len(text)
        if schrift in fonts:
            return fonts[schrift].getlength(text) * groesse / 1000
        return 0.52 * groesse * len(text) * (1.08 if schrift == "F2" else 1.0)
    return breite


_BREITE = _messer()


def _kodiere(text: str) -> bytes:
    """Encode text as an escaped WinAnsi (cp1252) PDF string; unsupported glyphs are replaced."""
    for alt, neu in ERSATZ.items():
        text = text.replace(alt, neu)
    roh = text.encode("cp1252", errors="replace")
    return roh.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class Dokument:
    """Fills pages top to bottom; y grows downwards (converted to PDF coordinates on output)."""

    def __init__(self, titel: str):
        self.titel = titel
        self.seiten: list = []
        self.neue_seite()

    # ------------------------------------------------------------ Primitives
    def neue_seite(self) -> None:
        self.ops: list = []
        self.seiten.append(self.ops)
        self.y = RAND

    def _y(self, y: float) -> float:
        return A4[1] - y

    def farbe(self, rgb, fuellen=True) -> str:
        return f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} {'rg' if fuellen else 'RG'}"

    def text(self, x, y, inhalt, schrift="F1", groesse=9.5, rgb=TINTE, sperrung=0.0) -> None:
        self.ops.append(f"BT /{schrift} {groesse:.2f} Tf {sperrung:.2f} Tc {self.farbe(rgb)} "
                        f"{x:.2f} {self._y(y):.2f} Td (")
        self.ops.append(_kodiere(inhalt))
        self.ops.append(") Tj ET\n")

    def text_rechts(self, x_rechts, y, inhalt, schrift="F1", groesse=9.5, rgb=TINTE) -> None:
        self.text(x_rechts - _BREITE(inhalt, schrift, groesse), y, inhalt, schrift, groesse, rgb)

    def linie(self, x1, y1, x2, y2, rgb=LINIE, staerke=0.6) -> None:
        self.ops.append(f"{self.farbe(rgb, False)} {staerke:.2f} w {x1:.2f} {self._y(y1):.2f} m "
                        f"{x2:.2f} {self._y(y2):.2f} l S\n")

    def rechteck(self, x, y, b, h, fuellung=None, rand=None, staerke=0.6) -> None:
        teile = []
        if fuellung:
            teile.append(self.farbe(fuellung))
        if rand:
            teile.append(f"{self.farbe(rand, False)} {staerke:.2f} w")
        op = "B" if fuellung and rand else "f" if fuellung else "S"
        self.ops.append(" ".join(teile) + f" {x:.2f} {self._y(y + h):.2f} {b:.2f} {h:.2f} re {op}\n")

    def _pfad_rund(self, x, y, b, h, radius) -> str:
        """Outline of a rounded rectangle (four Bézier quarter circles), clockwise from the top left."""
        r = max(0.0, min(radius, b / 2, h / 2))
        k = r * KAPPA
        if r == 0:
            return f"{x:.2f} {self._y(y + h):.2f} {b:.2f} {h:.2f} re"

        def p(px, py) -> str:
            return f"{px:.2f} {self._y(py):.2f}"
        rechts, unten = x + b, y + h
        return (f"{p(x + r, y)} m {p(rechts - r, y)} l "
                f"{p(rechts - r + k, y)} {p(rechts, y + r - k)} {p(rechts, y + r)} c {p(rechts, unten - r)} l "
                f"{p(rechts, unten - r + k)} {p(rechts - r + k, unten)} {p(rechts - r, unten)} c {p(x + r, unten)} l "
                f"{p(x + r - k, unten)} {p(x, unten - r + k)} {p(x, unten - r)} c {p(x, y + r)} l "
                f"{p(x, y + r - k)} {p(x + r - k, y)} {p(x + r, y)} c h")

    def rund_rechteck(self, x, y, b, h, radius, fuellung=None, rand=None, staerke=0.6) -> None:
        """Like rechteck(), but with rounded corners."""
        teile = []
        if fuellung:
            teile.append(self.farbe(fuellung))
        if rand:
            teile.append(f"{self.farbe(rand, False)} {staerke:.2f} w")
        op = "B" if fuellung and rand else "f" if fuellung else "S"
        self.ops.append(" ".join(teile) + f" {self._pfad_rund(x, y, b, h, radius)} {op}\n")

    def ausschnitt_an(self, x, y, b, h, radius=0.0) -> None:
        """Clip everything up to ausschnitt_aus() to this (rounded) area."""
        self.ops.append(f"q {self._pfad_rund(x, y, b, h, radius)} W n\n")

    def ausschnitt_aus(self) -> None:
        self.ops.append("Q\n")

    def schraffur(self, x, y, b, h, rgb=HAUCH, radius=0.0) -> None:
        """Diagonal hatching inside a (rounded) rectangle."""
        self.ops.append(f"q {self._pfad_rund(x, y, b, h, radius)} W n {self.farbe(rgb, False)} 0.4 w ")
        s = -h
        while s < b:
            self.ops.append(f"{x + s:.2f} {self._y(y + h):.2f} m {x + s + h:.2f} {self._y(y):.2f} l ")
            s += 3.2
        self.ops.append("S Q\n")

    def umbrechen(self, inhalt: str, schrift: str, groesse: float, breite: float) -> list:
        """Wrap text into lines that fit the given width."""
        zeilen = []
        for absatz in inhalt.split("\n"):
            zeile = ""
            for wort in absatz.split(" "):
                probe = (zeile + " " + wort).strip()
                if _BREITE(probe, schrift, groesse) <= breite or not zeile:
                    zeile = probe
                else:
                    zeilen.append(zeile)
                    zeile = wort
            zeilen.append(zeile)
        return zeilen

    def platz(self, hoehe: float) -> None:
        """Start a new page if the next block of this height does not fit."""
        if self.y + hoehe > A4[1] - RAND - 24:
            self.neue_seite()

    # ------------------------------------------------------------ Building blocks
    def absatz(self, inhalt, x=RAND, breite=None, schrift="F1", groesse=9.5, rgb=TINTE, zeilenabstand=1.42) -> None:
        breite = breite or A4[0] - RAND - x
        for zeile in self.umbrechen(inhalt, schrift, groesse, breite):
            self.platz(groesse * zeilenabstand)
            self.text(x, self.y + groesse, zeile, schrift, groesse, rgb)
            self.y += groesse * zeilenabstand

    def abschnitt(self, titel: str) -> None:
        """Numbered section heading with a rule."""
        self.platz(46)
        self.y += 20
        self.nummer = getattr(self, "nummer", 0) + 1
        self.text(RAND, self.y + 7, f"{self.nummer:02d}", "F2", 7.5, SIGNAL)
        self.text(RAND + 22, self.y + 7, titel.upper(), "F2", 7.5, TINTE, sperrung=0.6)
        self.y += 13
        self.linie(RAND, self.y, A4[0] - RAND, self.y, TINTE, 0.8)
        self.y += 10

    def fusszeilen(self, hinweis: str, kennung: str = "", sprache: str = "de") -> None:
        """Add footers (and the header bar from page 2 on) to all pages."""
        for i, ops in enumerate(self.seiten, 1):
            self.ops = ops
            if i > 1:
                _leiste(self, kennung)
            y = A4[1] - RAND + 22
            self.linie(RAND, y - 12, A4[0] - RAND, y - 12, LINIE, 0.5)
            self.text(RAND, y, hinweis, "F1", 7, HAUCH)
            self.text_rechts(A4[0] - RAND, y, _t("pdf_seite", sprache, i=i, n=len(self.seiten)), "F1", 7, HAUCH)

    def als_bytes(self) -> bytes:
        """Serialise the document as PDF 1.4."""
        objekte = []

        def obj(inhalt: bytes) -> int:
            objekte.append(inhalt)
            return len(objekte)
        schrift_ids = {k: obj(f"<< /Type /Font /Subtype /Type1 /BaseFont /{v} /Encoding /WinAnsiEncoding >>".encode())
                       for k, v in SCHRIFTEN.items()}
        ressourcen = "<< /Font << " + " ".join(f"/{k} {v} 0 R" for k, v in schrift_ids.items()) + " >> >>"
        seiten_id = len(objekte) + 1 + 2 * len(self.seiten)
        kinder = []
        for ops in self.seiten:
            roh = b"".join(o if isinstance(o, bytes) else o.encode("latin-1") for o in ops)
            gepackt = zlib.compress(roh)
            inhalt_id = obj(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(gepackt) + gepackt + b"\nendstream")
            kinder.append(obj(f"<< /Type /Page /Parent {seiten_id} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                              f"/Resources {ressourcen} /Contents {inhalt_id} 0 R >>".encode()))
        assert obj(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kinder)}] /Count {len(kinder)} >>".encode()) == seiten_id
        katalog = obj(f"<< /Type /Catalog /Pages {seiten_id} 0 R >>".encode())
        info = obj(b"<< /Title (" + _kodiere(self.titel) + b") /Producer (art-provenance-check) /CreationDate (D:"
                   + datetime.now().strftime("%Y%m%d%H%M%S").encode() + b") >>")
        aus = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        lagen = []
        for i, inhalt in enumerate(objekte, 1):
            lagen.append(len(aus))
            aus += f"{i} 0 obj\n".encode() + inhalt + b"\nendobj\n"
        xref = len(aus)
        aus += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
        aus += b"".join(f"{l:010d} 00000 n \n".encode() for l in lagen)
        aus += (f"trailer\n<< /Size {len(objekte) + 1} /Root {katalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(aus)


# ---------------------------------------------------------------- Review record

CHECKLISTE = [pdf for pdf, _ in texts.CHECKLISTE["de"]]      # German defaults kept for compatibility
STUFE = texts.STUFE["de"]
ZEITLEISTE_RADIUS, KOPF_RADIUS, EINGABE_RADIUS = 2.0, 8.0, 6.0


def _leiste(doc: Dokument, kennung: str) -> None:
    """Black header bar across the full width: wordmark on the left, document ID on the right."""
    doc.rechteck(0, 0, A4[0], 30, fuellung=TINTE)
    doc.rechteck(RAND, 11, 7, 7, fuellung=SIGNAL)
    doc.text(RAND + 13, 18.5, "art-provenance-check", "F2", 9, (1, 1, 1))
    doc.text_rechts(A4[0] - RAND, 18.5, kennung, "F4", 7.5, (0.75, 0.75, 0.75))


def _kopf(doc: Dokument, oberzeile: str, titel: str, meta: str, rechts_etikett: str, rechts_wert: str, farbe,
          kennung: str = "", stufe: int = 0) -> None:
    """Page header: overline, title, meta line and a light box with the key result and a level gauge."""
    _leiste(doc, kennung)
    doc.y = 62
    doc.text(RAND, doc.y + 7, oberzeile.upper(), "F2", 7, LEISE, sperrung=0.6)
    doc.y += 16
    breite_titel = A4[0] - 2 * RAND - 160
    for zeile in doc.umbrechen(titel, "F2", 22, breite_titel)[:2]:
        doc.text(RAND, doc.y + 20, zeile, "F2", 22, TINTE, sperrung=-0.3)
        doc.y += 26
    doc.text(RAND, doc.y + 9, meta, "F1", 8.5, LEISE)
    x, y0 = A4[0] - RAND - 140, 62
    doc.rund_rechteck(x, y0, 140, 62, KOPF_RADIUS, rand=LINIE, staerke=0.8)
    doc.text(x + 14, y0 + 17, rechts_etikett, "F1", 7.5, LEISE)
    doc.text(x + 14, y0 + 39, rechts_wert, "F2", 19, farbe, sperrung=-0.3)
    if stufe:                                    # three-segment level gauge
        breite = (140 - 28 - 2 * 3) / 3
        for i in range(3):
            doc.rund_rechteck(x + 14 + i * (breite + 3), y0 + 48, breite, 3, 1.5,
                              fuellung=farbe if i < stufe else (0.9, 0.9, 0.91))
    doc.y = max(doc.y + 22, y0 + 84)


def protokoll_pdf(bericht, text: str, objekt: str | None, zeiten: list, schluss: str, sprache: str = "de") -> bytes:
    """Review record of a provenance text as PDF (A4).

    zeiten and schluss are supplied by the caller in the matching language:
    provenance._zeit(s, sprache) and provenance.schluss(sprache).
    """
    sp = texts.pruefe_sprache(sprache)
    stufen = texts.STUFE[sp]
    b = bericht
    doc = Dokument(_t("pdf_titel", sp, objekt=objekt or "").strip())
    datum = texts.datum(datetime.now(), sp)
    kennung = "PP-" + b.eingabe_sha256[:8].upper()
    _kopf(doc, _t("pdf_oberzeile", sp), objekt or _t("pdf_ohne_objekt", sp),
          _t("pdf_meta", sp, datum=datum, kennung=kennung), _t("pdf_pruefbedarf", sp), stufen[b.pruefbedarf],
          FARBE[b.pruefbedarf], kennung, {"gering": 1, "mittel": 2, "hoch": 3}[b.pruefbedarf])

    doc.abschnitt(_t("pdf_eingabe", sp))
    zeilen = doc.umbrechen(text.strip(), "F1", 9, A4[0] - 2 * RAND - 24)
    hoehe = len(zeilen) * 13 + 14
    doc.platz(hoehe)
    doc.rund_rechteck(RAND, doc.y, A4[0] - 2 * RAND, hoehe, EINGABE_RADIUS, fuellung=FLAECHE)
    for i, zeile in enumerate(zeilen):
        doc.text(RAND + 12, doc.y + 16 + i * 13, zeile, "F1", 9)
    doc.y += hoehe

    if b.ns_relevant and b.zeitraum:
        doc.abschnitt(_t("pdf_zeitraum", sp))
        jahre = list(b.zeitraum.items())
        breite = (A4[0] - 2 * RAND - (len(jahre) - 1) * 3) / len(jahre)
        doc.platz(52)
        for i, (jahr, status) in enumerate(jahre):
            x = RAND + i * (breite + 3)
            r = ZEITLEISTE_RADIUS
            if status == "belegt":
                doc.rund_rechteck(x, doc.y, breite, 16, r, fuellung=BELEGT)
            elif status == "erschlossen":
                doc.schraffur(x, doc.y, breite, 16, radius=r)
                doc.rund_rechteck(x, doc.y, breite, 16, r, rand=BELEGT, staerke=0.6)
            else:
                doc.ausschnitt_an(x, doc.y, breite, 16, r)           # red bottom bar follows the rounded corners
                doc.rechteck(x, doc.y + 14, breite, 2, fuellung=ROT)
                doc.ausschnitt_aus()
                doc.rund_rechteck(x, doc.y, breite, 16, r, rand=ROT, staerke=0.9)
            doc.text(x + breite / 2 - _BREITE(jahr, "F1", 7) / 2, doc.y + 27, jahr, "F1", 7, LEISE)
        doc.y += 38
        x = RAND
        for art in ("belegt", "erschlossen", "offen"):
            name = texts.ZEITSTATUS[sp][art]
            if art == "belegt":
                doc.rund_rechteck(x, doc.y, 8, 8, ZEITLEISTE_RADIUS, fuellung=BELEGT)
            elif art == "erschlossen":
                doc.schraffur(x, doc.y, 8, 8, radius=ZEITLEISTE_RADIUS)
                doc.rund_rechteck(x, doc.y, 8, 8, ZEITLEISTE_RADIUS, rand=BELEGT, staerke=0.5)
            else:
                doc.rund_rechteck(x, doc.y, 8, 8, ZEITLEISTE_RADIUS, rand=ROT, staerke=0.8)
            doc.text(x + 12, doc.y + 7.5, name, "F1", 8, LEISE)
            x += 24 + _BREITE(name, "F1", 8) + 10
        doc.y += 14

    doc.abschnitt(_t("pdf_stationen", sp))
    stufe_je = {}
    for f in b.befunde:
        if f["station"] and (f["station"] not in stufe_je or f["stufe"] == "hoch"):
            stufe_je[f["station"]] = f["stufe"]
    for s in b.stationen:
        zeilen = doc.umbrechen(s["text"], "F1", 9, A4[0] - 2 * RAND - 150)
        doc.platz(len(zeilen) * 12.5 + 8)
        st = stufe_je.get(s["nr"])
        doc.text(RAND, doc.y + 9, f"{s['nr']:02d}", "F2", 8.5, FARBE.get(st, HAUCH) if st in ("hoch", "mittel") else HAUCH)
        for i, zeile in enumerate(zeilen):
            doc.text(RAND + 28, doc.y + 9 + i * 12.5, zeile, "F1", 9)
        doc.text_rechts(A4[0] - RAND, doc.y + 9, zeiten[s["nr"] - 1], "F1", 8.5, LEISE)
        doc.y += len(zeilen) * 12.5 + 5
        doc.linie(RAND, doc.y, A4[0] - RAND, doc.y, LINIE, 0.4)
        doc.y += 4

    doc.abschnitt(_t("pdf_befunde", sp))
    if not b.befunde:
        doc.absatz(_t("pdf_nichts", sp), rgb=LEISE)
    for stufe in ("hoch", "mittel", "hinweis"):
        for f in [x for x in b.befunde if x["stufe"] == stufe]:
            zeilen = doc.umbrechen(f["text"], "F1", 9, A4[0] - 2 * RAND - 96)
            doc.platz(len(zeilen) * 12.5 + 8)
            doc.rechteck(RAND, doc.y + 3.5, 5.5, 5.5, fuellung=FARBE[stufe] if stufe != "hinweis" else LINIE)
            doc.text(RAND + 10, doc.y + 9, stufen[stufe].upper(), "F2", 7, FARBE[stufe] if stufe != "hinweis" else LEISE,
                     sperrung=0.5)
            doc.text(RAND + 52, doc.y + 9, _t("pdf_station_kurz", sp, nr=f["station"]) if f["station"] else "–", "F2",
                     8, HAUCH)
            for i, zeile in enumerate(zeilen):
                doc.text(RAND + 96, doc.y + 9 + i * 12.5, zeile, "F1", 9)
            doc.y += len(zeilen) * 12.5 + 5
            doc.linie(RAND, doc.y, A4[0] - RAND, doc.y, LINIE, 0.4)
            doc.y += 4

    doc.abschnitt(_t("pdf_offen", sp))
    for punkt, _ in texts.CHECKLISTE[sp]:
        doc.platz(16)
        doc.rechteck(RAND, doc.y + 1, 8, 8, rand=TINTE, staerke=0.6)
        doc.text(RAND + 16, doc.y + 8.5, punkt, "F1", 9)
        doc.y += 16

    doc.abschnitt(_t("pdf_nachweis", sp))
    doc.absatz(_t("pdf_pruefsumme", sp, wert=b.eingabe_sha256), schrift="F4", groesse=7, rgb=LEISE)
    doc.absatz(_t("pdf_liste", sp, wert=b.namensliste or _t("keine", sp)), schrift="F4", groesse=7, rgb=LEISE)
    doc.y += 6
    doc.absatz(schluss + " " + _t("aufbewahrung", sp), groesse=8, rgb=LEISE)
    doc.platz(50)
    doc.y += 34
    doc.linie(RAND, doc.y, RAND + 200, doc.y, TINTE, 0.5)
    doc.linie(RAND + 260, doc.y, RAND + 400, doc.y, TINTE, 0.5)
    doc.text(RAND, doc.y + 11, _t("pdf_geprueft", sp), "F1", 7.5, LEISE)
    doc.text(RAND + 260, doc.y + 11, _t("pdf_datum", sp), "F1", 7.5, LEISE)
    doc.fusszeilen(_t("pdf_fuss", sp), kennung, sp)
    return doc.als_bytes()


# ---------------------------------------------------------------- Catalogue overview

def katalog_pdf(eintraege: list, quelle: str, sprache: str = "de") -> bytes:
    """Overview of a catalogue review: one lot per row, sorted by review level."""
    spr = texts.pruefe_sprache(sprache)
    stufen = texts.STUFE[spr]
    doc = Dokument(_t("pdf_kat_titel", spr))
    zahl = {s: sum(1 for e in eintraege if e["pruefbedarf"] == s) for s in ("hoch", "mittel", "gering")}
    _kopf(doc, _t("pdf_kat_oberzeile", spr), quelle or _t("pdf_kat_quelle", spr),
          _t("pdf_kat_meta", spr, datum=texts.datum(datetime.now(), spr), anzahl=len(eintraege)),
          _t("pdf_kat_hoch", spr), f"{zahl['hoch']} / {len(eintraege)}", SIGNAL if zahl["hoch"] else TINTE,
          "KP-" + datetime.now().strftime("%Y%m%d-%H%M"))
    doc.abschnitt(_t("pdf_kat_zusammenfassung", spr))
    doc.platz(40)
    spalte = (A4[0] - 2 * RAND) / 3
    for i, stufe in enumerate(("hoch", "mittel", "gering")):
        doc.text(RAND + i * spalte, doc.y + 22, str(zahl[stufe]), "F2", 24, FARBE[stufe], sperrung=-0.4)
        doc.text(RAND + i * spalte, doc.y + 33, stufen[stufe].upper(), "F2", 6.8, LEISE, sperrung=0.9)
    doc.y += 44
    doc.abschnitt(_t("pdf_kat_lose", spr))
    sp = [RAND, RAND + 44, RAND + 214, RAND + 252]                       # lot, work, year, finding
    for x, k in zip(sp, _t("pdf_kat_spalten", spr).split("|")):
        doc.text(x, doc.y + 7, k, "F2", 6.5, LEISE, sperrung=0.7)
    doc.y += 14
    for e in eintraege:
        werk = doc.umbrechen(e.get("titel") or "–", "F1", 8.5, 160)
        befund = doc.umbrechen(e.get("befund") or _t("pdf_nichts", spr), "F1", 8.5, A4[0] - RAND - sp[3])
        h = max(len(werk), len(befund) + 1) * 11.5 + 6
        doc.platz(h + 4)
        doc.linie(RAND, doc.y, A4[0] - RAND, doc.y, LINIE, 0.4)
        y = doc.y + 11
        doc.text(sp[0], y, str(e.get("los") or "–"), "F4", 8.5, TINTE)
        for i, z in enumerate(werk):
            doc.text(sp[1], y + i * 11.5, z, "F1", 8.5)
        doc.text(sp[2], y, str(e.get("entstehung") or "–"), "F1", 8.5, LEISE)
        doc.text(sp[3], y, stufen[e["pruefbedarf"]].upper() + _t("pdf_kat_zahlen", spr, hoch=e["hoch"],
                                                                    mittel=e["mittel"]),
                 "F2", 7, FARBE[e["pruefbedarf"]], sperrung=0.5)
        for i, z in enumerate(befund):
            doc.text(sp[3], y + 11.5 + i * 11.5, z, "F1", 8.5, TINTE)
        doc.y += h
    doc.fusszeilen(_t("pdf_kat_fuss", spr), sprache=spr)
    return doc.als_bytes()


if __name__ == "__main__":
    import sys
    import provenance as pv
    sprache = "en" if "--en" in sys.argv else "de"
    argumente = [x for x in sys.argv[1:] if x != "--en"]
    text = argumente[0] if argumente else "Sammlung A Beispiel, Wien (bis 1938); Kunsthandel, Zürich"
    liste, name = pv.lade_standardlisten(sprache)
    b = pv.pruefe(text, liste, None, name, sprache)
    Path("protokoll.pdf").write_bytes(protokoll_pdf(b, text, "Beispiel", [pv._zeit(s, sprache) for s in b.stationen],
                                                    pv.schluss(sprache), sprache))
    print("protokoll.pdf")
