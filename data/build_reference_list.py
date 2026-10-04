#!/usr/bin/env python3
"""Builds the reference list for the provenance checker from Wikidata (CC0, free to reuse).

  - ALIU:         people with "investigated by" (P1840) = Art Looting Investigation Unit (Q30335959)
  - Restitution:  people on the focus list "WikiProject Provenance" (P5008 = Q98801351) with a significant
                  event (P793/P1344) of restitution claim, restitution, Nazi plunder or "Aryanization"
  - Persecution:  people on the same focus list with an event of persecution of Jews or the Holocaust
Plus name variants (aliases in German and English) and life dates.

  python3 data/build_reference_list.py      # -> data/reference_list_wikidata.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

HIER = Path(__file__).parent
SPALTEN = ["wikidata", "name", "aliases", "born", "died", "description", "source_status", "category"]
KATEGORIE = {
    "aliu": "in ALIU-Berichten genannt (1944–1946)",
    "verfolgung": "dokumentierte NS-Verfolgung (§ 44 KGSG)",
    "restitution": "Bezug zu Entziehungs- oder Restitutionsfall",
}
KOPF = ("# Each entry is a research hint for provenance research, not a judgement about a person.\n")

ABFRAGEN = {
    "aliu": "SELECT DISTINCT ?p WHERE { ?p wdt:P1840 wd:Q30335959 ; wdt:P31 wd:Q5 }",
    "restitution": "SELECT DISTINCT ?p WHERE { ?p wdt:P5008 wd:Q98801351 ; wdt:P31 wd:Q5 . "
                   "{ ?p wdt:P793 ?e } UNION { ?p wdt:P1344 ?e } "
                   "VALUES ?e { wd:Q107614552 wd:Q2146005 wd:Q328376 wd:Q664017 } }",
    "verfolgung": "SELECT DISTINCT ?p WHERE { ?p wdt:P5008 wd:Q98801351 ; wdt:P31 wd:Q5 . "
                  "{ ?p wdt:P793 ?e } UNION { ?p wdt:P1344 ?e } "
                  "VALUES ?e { wd:Q112029888 wd:Q48136 wd:Q105070530 wd:Q2763 } }",
}
KENNUNG = {"User-Agent": "art-provenance-check/0.2 (+https://github.com/Thesimpleex/art-provenance-check)"}


def _hole(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=KENNUNG), timeout=120) as r:
        return json.load(r)


def aus_wikidata() -> list:
    arten = {}
    for art, abfrage in ABFRAGEN.items():
        daten = _hole("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": abfrage, "format": "json"}))
        for z in daten["results"]["bindings"]:
            arten.setdefault(z["p"]["value"].rsplit("/", 1)[-1], set()).add(art)
    ids = sorted(arten)
    zeilen = []
    for i in range(0, len(ids), 50):                       # details in batches of 50
        daten = _hole("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "format": "json",
            "props": "labels|aliases|descriptions|claims", "languages": "de|en"}))
        for qid, e in daten["entities"].items():
            labels = e.get("labels", {})
            name = (labels.get("de") or labels.get("en") or {}).get("value")
            if not name:
                continue
            aliasse = {a["value"] for sprache in ("de", "en") for a in e.get("aliases", {}).get(sprache, [])}
            aliasse |= {l["value"] for l in labels.values()}
            aliasse.discard(name)

            def jahr(prop: str) -> str:
                for c in e.get("claims", {}).get(prop, []):
                    zeit = c["mainsnak"].get("datavalue", {}).get("value", {}).get("time", "")
                    if re.match(r"\+\d{4}", zeit):
                        return zeit[1:5]
                return ""
            beschreibung = (e.get("descriptions", {}).get("en") or e.get("descriptions", {}).get("de") or {}).get("value", "")
            reihe = [a for a in ("aliu", "verfolgung", "restitution") if a in arten[qid]]
            zeilen.append([qid, name, " | ".join(sorted(aliasse)), jahr("P569"), jahr("P570"), beschreibung,
                           " | ".join(reihe), " | ".join(KATEGORIE[a] for a in reihe)])
    return sorted(zeilen, key=lambda z: z[1])


def schreibe(ziel: Path, zeilen: list, herkunft: str) -> None:
    with open(ziel, "w", encoding="utf-8", newline="") as f:
        f.write(f"# Reference list for art-provenance-check: {len(zeilen)} people, built {date.today().isoformat()}\n"
                f"# {herkunft}\n" + KOPF)
        w = csv.writer(f, delimiter=";")
        w.writerow(SPALTEN)
        w.writerows(zeilen)
    print(f"{ziel.name}: {len(zeilen)} people")


def main() -> None:
    argparse.ArgumentParser(description="Build the reference list for art-provenance-check from Wikidata").parse_args()
    schreibe(HIER / "reference_list_wikidata.csv", aus_wikidata(),
             "Source: Wikidata (CC0), query in data/build_reference_list.py")


if __name__ == "__main__":
    main()
