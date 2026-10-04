#!/usr/bin/env python3
"""Local browser interface for the provenance review and the print-process check.

  python3 app.py            # then open http://localhost:8777

Listens on 127.0.0.1 only; nothing is sent over the network.
"""
from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image, ImageOps

import printcheck
import pdf_record
import provenance

PORT = int(os.environ.get("PORT", 8777))
HIER = Path(__file__).parent
BEISPIELE = HIER / "examples"
LISTE, LISTENNAME = provenance.lade_standardlisten()
SEITE = (HIER / "app.html").read_text(encoding="utf-8")

MELDUNG = {
    "en": {"kein_text": "Please enter a provenance text.",
           "keine_lose": "No lots found. Expected a CSV file with a header row.",
           "fehler": "Could not be processed: {}",
           "liste": "Reference list: {} people ({}).", "keine_liste": "No reference list loaded."},
    "de": {"kein_text": "Bitte einen Provenienztext eingeben.",
           "keine_lose": "Keine Lose gefunden. Erwartet wird eine CSV mit Kopfzeile.",
           "fehler": "Konnte nicht verarbeitet werden: {}",
           "liste": "Referenzliste: {} Personen ({}).", "keine_liste": "Keine Referenzliste geladen."},
}


def _sprache(wert) -> str:
    return wert if wert in ("de", "en") else "en"


def _jahr(daten: dict) -> int | None:
    wert = str(daten.get("entstehung", "")).strip()
    return int(wert) if wert.isdigit() else None


class Handler(BaseHTTPRequestHandler):
    def _antwort(self, code: int, inhalt: bytes, typ: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        self.wfile.write(inhalt)

    def _json(self, daten: dict) -> None:
        self._antwort(200, json.dumps(daten, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        url = urlparse(self.path)
        sp = _sprache(parse_qs(url.query).get("lang", ["en"])[0])
        if url.path == "/beispielkatalog":
            datei = "catalogue_example.csv" if sp == "en" else "catalogue_example_de.csv"
            return self._antwort(200, (BEISPIELE / datei).read_bytes(), "text/csv; charset=utf-8")
        if url.path == "/info":
            quellen = "Wikidata" + (" + openartdata" if sum(p.exists() for p in provenance.STANDARD_LISTEN) > 1 else "")
            personen = len({e["wikidata"] or e["name"] for e in LISTE})
            return self._json({"liste": MELDUNG[sp]["liste"].format(personen, quellen) if LISTE
                               else MELDUNG[sp]["keine_liste"]})
        self._antwort(200, SEITE.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        daten = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        sp = _sprache(daten.get("sprache"))
        try:
            if self.path in ("/provenienz", "/pdf"):
                text = (daten.get("text") or "").strip()
                if not text:
                    return self._json({"fehler": MELDUNG[sp]["kein_text"]})
                objekt = daten.get("objekt") or None
                b = provenance.pruefe(text, LISTE, _jahr(daten), LISTENNAME, sprache=sp)
                zeiten = [provenance._zeit(s, sp) for s in b.stationen]
                if self.path == "/pdf":
                    pdf = pdf_record.protokoll_pdf(b, text, objekt, zeiten, provenance.schluss(sp), sprache=sp)
                    return self._json({"pdf": base64.b64encode(pdf).decode()})
                datum = datetime.now().strftime("%d %b %Y" if sp == "en" else "%d.%m.%Y")
                return self._json({"bericht": asdict(b), "zeiten": zeiten, "datum": datum, "objekt": objekt or "",
                                   "protokoll": provenance.als_protokoll(b, text, objekt, sp),
                                   "schluss": provenance.schluss(sp)})
            if self.path in ("/katalog", "/katalog_zip"):
                eintraege = provenance.lies_katalog(daten.get("csv") or "")
                ergebnisse = provenance.pruefe_katalog(eintraege, LISTE, LISTENNAME, sprache=sp)
                if not ergebnisse:
                    return self._json({"fehler": MELDUNG[sp]["keine_lose"]})
                if self.path == "/katalog":
                    felder = ("los", "titel", "entstehung", "text", "pruefbedarf", "hoch", "mittel", "befund")
                    return self._json({"lose": [{k: e[k] for k in felder} for e in ergebnisse]})
                with tempfile.TemporaryDirectory() as ordner:
                    provenance.schreibe_katalog(ergebnisse, Path(ordner), daten.get("name") or "catalogue", sprache=sp)
                    puffer = io.BytesIO()
                    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
                        for datei in sorted(Path(ordner).rglob("*")):
                            if datei.is_file():
                                z.write(datei, datei.relative_to(ordner))
                return self._json({"zip": base64.b64encode(puffer.getvalue()).decode()})
            if self.path == "/druck":
                beispiel = {"offset": "offset", "inkjet": "inkjet", "litho": "litho", "flach": "flat", "flat": "flat"}
                if daten.get("beispiel") in beispiel:
                    roh = (BEISPIELE / f"{beispiel[daten['beispiel']]}.jpg").read_bytes()
                else:
                    roh = base64.b64decode(daten["bild"].split(",", 1)[1])
                bild = np.asarray(ImageOps.exif_transpose(Image.open(io.BytesIO(roh))).convert("RGB"))
                um = float(str(daten.get("um")).replace(",", ".")) if str(daten.get("um") or "").strip() else None
                befund = printcheck.analysiere(bild, um, sprache=sp)
                bilder = {}
                for name, teil in zip(("ausschnitt", "spektrum"), printcheck.diagnose_teile(bild, befund)):
                    puffer = io.BytesIO()
                    teil.save(puffer, format="PNG")
                    bilder[name] = base64.b64encode(puffer.getvalue()).decode()
                return self._json({"befund": asdict(befund), **bilder})
            self._antwort(404, b"", "text/plain")
        except Exception as fehler:                       # report errors as text instead of crashing
            self._json({"fehler": MELDUNG[sp]["fehler"].format(fehler)})

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    print(f"Interface running: http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
