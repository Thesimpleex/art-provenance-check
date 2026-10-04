#!/usr/bin/env python3
"""Provenance checker: splits a provenance text into entries and flags what needs review.

Supports the duty to examine provenance under § 42(1) no. 3 of the German Act on the
Protection of Cultural Property (KGSG). Runs locally, rule-based and traceable: every
finding states its reason.

What is checked:
  - entries and dates (until, since, around, before, after, ranges, life dates)
  - the period under § 44 KGSG (30 Jan 1933 - 8 May 1945): years without a documented
    owner, changes of ownership and auctions within this period
  - indications of seizure, persecution or restitution
  - anonymous entries ("private collection, Switzerland") and uncertain statements ("probably")
  - names from a provenance-research reference list, matched fuzzily: spelling variants,
    initials, name particles, birth names; a different first name rules out a match

The tool never reports a provenance as "unproblematic". No findings only means that nothing
was found in the text. Database searches and document review remain mandatory.

Usage:
  python3 provenance.py "Collection A, Berlin (until 1938); art market, Zurich; ..."
  python3 provenance.py --file provenance.txt --year 1912 --record record.md --pdf record.pdf
  python3 provenance.py --file provenance.txt --reference-list my_list.csv --json
  python3 provenance.py --catalogue examples/catalogue_example.csv --out catalogue_review/   # one PDF per lot
  python3 provenance.py --lang de "Sammlung A, Berlin (bis 1938); Kunsthandel, Zürich"     # German output
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import texts
from texts import t as _t

VERSION = "0.2.0"
NS_VON, NS_BIS = 1933, 1945                      # § 44 KGSG: 30 Jan 1933 to 8 May 1945
DATEN = Path(__file__).parent / "data"
# Default reference lists. The first entry is the bundled Wikidata list (CC0); any further
# list files in data/ are merged if present (local use).
STANDARD_LISTEN = [DATEN / "reference_list_wikidata.csv",
                   DATEN / "reference_list_openartdata_2025-01.csv"]

JAHR = r"(1[4-9]\d\d|20\d\d)"

MUSTER = {
    "entzug": r"beschlagnahm\w*|konfiszi\w*|confiscat\w*|seized|seizure|zwangsverk\w*|zwangsversteiger\w*|"
              r"forced sale|judenauktion\w*|arisier\w*|aryani[sz]\w*|reichsfluchtsteuer|sichergestellt|"
              r"sicherstellung|einsatzstab|\berr\b|m-aktion|möbel-aktion|entzogen|enteign\w*|expropriat\w*|"
              r"verfolgungsbedingt|looted|geraubt|raubkunst|deportiert|deported|ermordet|murdered|"
              r"emigr\w*|geflohen|\bflucht\b|fled\b",
    "restitution": r"restitu\w*|rückgabe|zurückgegeben|returned to|rückerstatt\w*|wiedergutmachung|"
                   r"collecting point|\bccp\b",
    "auktion": r"auktion\w*|versteiger\w*|\bverst\.|auction\w*|\bsale\b|\blot\b|\blos\b",
    "kuenstler": r"\bthe artist\b|from the artist|\bvom künstler|künstler/-in|\(künstler\)|^künstler|nachlass des künstlers|"
                 r"estate of the artist|\batelier\b",
    "institution": r"museum|kunsthalle|kunstinstitut|kunstverein|stiftung|foundation|städtische|kunstgesellschaft|"
                   r"gallery of art|national gallery|staatliche|sammlungen|art institute",
    "haendler": r"galerie|gallery|kunsthandlung|kunsthändler\w*|kunsthandel|kunstsalon|dealer|händler|antiquitäten|"
                r"art market|art trade",
    "erbgang": r"erbschaft|erbgang|\berben\b|nachlass|by descent|by inheritance|\bheirs?\b|vererbt|in der familie",
    "unsicher": r"\bwohl\b|vermutlich|möglicherweise|angeblich|\blaut\b|nach angabe|überlieferung|mündlich|"
                r"probably|possibly|presumably|reportedly|according to|said to|perhaps|unklar|fraglich|\?",
}

GENERISCH = {
    "privatsammlung", "privatbesitz", "private", "collection", "collector", "privately", "owned", "kunsthandel",
    "kunstmarkt", "art", "market", "trade", "handel", "sammlung", "eine", "ein", "einer", "a", "an", "the", "die",
    "der", "anonym", "anonyme", "anonymer", "anonymous", "unbekannt", "unbekannter", "unknown", "europäische",
    "europäischer", "deutsche", "schweizer", "amerikanische", "american", "european", "swiss", "german",
}

ABKUERZUNGEN = {"dr", "prof", "slg", "kat", "nr", "ca", "geb", "gest", "st", "bzw", "vgl", "inv", "abb", "bd",
                "jh", "fig", "no", "mr", "mrs", "jr", "co", "coll", "mme", "mlle", "dipl", "ing", "hrsg", "verst",
                "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "okt", "nov", "dec", "dez",
                "calif", "mass", "conn", "penn", "wash", "mich", "ill", "ave", "bros", "inc", "ltd", "mind", "ff"}


@dataclass
class Station:
    nr: int
    text: str
    von: int | None = None
    bis: int | None = None
    ungefaehr: bool = False
    punkt: bool = False                               # single year only: documented then, not start/end
    lebensdaten: list | None = None
    arten: list = field(default_factory=list)       # entry types: haendler, auktion, erbgang, entzug, ...
    anonym: bool = False
    eigentuemer: bool = True                          # a named owner (not just an event)
    unsicher: list = field(default_factory=list)
    namen: list = field(default_factory=list)         # matches in the reference list


@dataclass
class Befund:
    stufe: str            # hoch | mittel | hinweis (high | medium | note)
    text: str
    station: int | None = None


@dataclass
class Bericht:
    pruefbedarf: str
    befunde: list
    stationen: list
    zeitraum: dict        # year → belegt | erschlossen | offen (documented | inferred | open)
    ns_relevant: bool
    namensliste: str
    eingabe_sha256: str


# ---------------------------------------------------------------- Parsing

def _saetze(t: str) -> list:
    """Split at sentence ends, but not after abbreviations, initials or day numbers ("12. März")."""
    teile, start = [], 0
    for m in re.finditer(r"\.\s+(?=[A-ZÄÖÜ0-9])", t):
        wort = re.search(r"(\w+)$", t[start:m.start()])
        w = wort.group(1) if wort else ""
        if w.lower() in ABKUERZUNGEN or len(w) == 1 or (w.isdigit() and len(w) <= 2):
            continue
        teile.append(t[start:m.start()])
        start = m.end()
    teile.append(t[start:])
    return teile


def zerlege(text: str) -> list:
    """Split a provenance text into entries (at semicolons, line breaks and sentence ends)."""
    t = re.sub(r"^\s*(provenienz|provenance|herkunft)\s*:\s*", "", text.strip(), flags=re.I)
    t = t.replace("–", "-").replace("—", "-").replace("‒", "-")
    t = re.sub(r"\[[^\]]*\]", lambda m: m.group(0).replace(";", ","), t)   # keep source references in [ ] together
    teile = [p for p in re.split(r";|\n+|\.\s+-\s+", t) if p.strip()]
    teile = [satz for p in teile for satz in _saetze(p)]
    return [p.strip(" .,\t") for p in teile if p.strip(" .,\t")]


def _jahre(text: str) -> dict:
    """Read the dates of an entry. Life dates in parentheses do not count as ownership periods."""
    t = re.sub(r"\[[^\]]*\]", lambda m: " " * len(m.group(0)), text)     # years in source references are not ownership
    info = {"von": None, "bis": None, "ungefaehr": False, "lebensdaten": None, "punkt": False}
    erstes_komma = t.find(",") if "," in t else len(t)
    for m in re.finditer(r"\(([^)]*)\)", t):
        inhalt = m.group(1)
        ys = [int(y) for y in re.findall(JAHR, inhalt)]
        if len(ys) != 2:
            continue
        markiert = re.search(r"[*†+]|\bb\.|\bd\.|geb\.|gest\.|born|died", inhalt)
        nur_jahre = re.fullmatch(r"\s*\*?\s*\d{4}\s*-\s*†?\s*\d{4}\s*", inhalt)
        spanne = ys[1] - ys[0]
        vorher = t[:m.start()].rstrip()
        ort_davor = "," in vorher and re.fullmatch(r"[A-ZÄÖÜ][\w.-]*", vorher.rsplit(",", 1)[1].strip() or "-")
        lang = 40 <= spanne <= 105 and not ort_davor          # "Hamburg (1910-1958)" is an ownership period
        if markiert or (nur_jahre and (lang or (m.start() < erstes_komma and 20 <= spanne <= 105))):
            info["lebensdaten"] = ys
            t = t[:m.start()] + " " * len(m.group(0)) + t[m.end():]
    tl = re.sub(r"(\$|£|€|\b(?:rm|m|fl|frf|chf|usd|dm|fr|lot|los|nr|no|nos|kat|inv|stock no|lager-nr)\.?)\s*[\d][\d.,']*",
                lambda m: " " * len(m.group(0)), t.lower())
    tl = re.sub(r"\b\d+[.,']\d{3}\b", lambda m: " " * len(m.group(0)), tl)     # 3,200 or 22'500

    def nimm(muster: str) -> list:
        nonlocal tl
        treffer = []
        for m in re.finditer(muster, tl):
            treffer.append(m)
        for m in reversed(treffer):
            tl = tl[:m.start()] + " " * (m.end() - m.start()) + tl[m.end():]
        return treffer

    for m in nimm(JAHR + r"\s*(?:-|bis|to|until)\s*" + JAHR):
        info["von"], info["bis"] = int(m.group(1)), int(m.group(2))
    for m in nimm(JAHR + r"(?:er|s)\b"):                              # 1930er, 1930s
        info["von"], info["bis"], info["ungefaehr"] = int(m.group(1)), int(m.group(1)) + 9, True
    for m in nimm(r"\b(?:bis|until|till)\s+(?:\d{1,2}\.\s*(?:\d{1,2}\.)?\s*)?" + JAHR):
        info["bis"] = int(m.group(1))
    for m in nimm(r"\b(?:seit|ab|from|since)\s+(?:\d{1,2}\.\s*(?:\d{1,2}\.)?\s*)?" + JAHR):
        info["von"] = int(m.group(1))
    for m in nimm(r"\b(?:vor|before)\s+" + JAHR):
        info["bis"], info["ungefaehr"] = int(m.group(1)), True
    for m in nimm(r"\b(?:nach|after)\s+" + JAHR):
        info["von"], info["ungefaehr"] = int(m.group(1)), True
    for m in nimm(r"(?:\bum|\bca\.?|\bcirca|\bc\.)\s*" + JAHR):
        y = int(m.group(1))
        info["punkt"] = info["von"] is None and info["bis"] is None
        info["von"] = info["von"] or y
        info["bis"] = info["bis"] or y
        info["ungefaehr"] = True
    punkte = [int(y) for y in re.findall(JAHR, tl)]                   # remaining single years ("acquired 1937")
    if punkte:
        if info["von"] is None and info["bis"] is None:
            info["von"], info["bis"] = min(punkte), max(punkte)
            info["punkt"] = len(set(punkte)) == 1
        elif info["von"] is None:
            info["von"] = min(punkte + [info["bis"]])
        elif info["bis"] is None and max(punkte) > info["von"]:
            info["bis"] = max(punkte)
    return info


def _anonym(text: str) -> bool:
    """True if the entry names no owner, only generic words ("private collection, Switzerland")."""
    erster = re.split(r"[,(]", text, maxsplit=1)[0]
    woerter = re.findall(r"[a-zäöüß]+", erster.lower())
    return bool(woerter) and all(w in GENERISCH for w in woerter)


# ---------------------------------------------------------------- Reference list

PARTIKEL = {"von", "van", "de", "der", "den", "du", "la", "le", "zu", "ten", "ter", "del", "della", "di", "da", "dos"}
TITEL = {"dr", "prof", "sir", "graf", "graefin", "baron", "baronin", "freiherr", "freifrau", "fuerst", "herr", "frau",
         "mme", "mr", "mrs", "ms", "madame", "monsieur", "dipl", "ing", "konsul", "kommerzienrat", "geheimrat"}
KEIN_NAME = {_w.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue") for _w in GENERISCH} | {
    "galerie", "gallery", "galleries", "kunsthandlung", "kunstsalon", "kunsthaus", "auktion", "auktionshaus",
    "versteigerung", "auction", "haus", "familie", "family", "erben", "heirs", "estate", "nachlass", "firma", "museum",
    "slg", "coll", "durch", "bei", "aus", "of", "und", "and", "des", "dem", "im", "in", "fuer", "for", "by", "from",
    "to", "verlag", "antiquariat", "kunstverein", "stiftung", "foundation", "acquired", "erworben", "gekauft",
    "purchased", "bought", "sold", "verkauft", "bis", "seit", "ab", "until", "since", "um", "ca", "circa", "c", "vor",
    "nach", "before", "after", "thence", "descent", "sohn", "son", "tochter", "daughter", "witwe", "widow", "wife",
    "ehefrau", "dealer", "haendler", "kunsthaendler", "sammler", "sammlerin", "zuerich", "berlin", "paris", "wien",
    "muenchen", "london", "new", "york", "amsterdam", "basel", "luzern", "koeln", "hamburg", "dresden"}


# Most common German surnames: without a first name they only yield a note (too many false positives otherwise)
HAEUFIGE_NACHNAMEN = {
    "mueller", "schmidt", "schneider", "fischer", "weber", "meyer", "wagner", "becker", "schulz", "hoffmann",
    "schaefer", "koch", "bauer", "richter", "klein", "wolf", "schroeder", "neumann", "schwarz", "zimmermann",
    "braun", "krueger", "hofmann", "hartmann", "lange", "schmitt", "werner", "schmitz", "krause", "meier",
    "lehmann", "schmid", "schulze", "maier", "koehler", "herrmann", "koenig", "walter", "mayer", "huber",
    "kaiser", "fuchs", "peters", "lang", "scholz", "moeller", "weiss", "jung", "hahn", "schubert", "vogel",
    "friedrich", "keller", "guenther", "frank", "berger", "winkler", "roth", "beck", "lorenz", "baumann",
    "franke", "albrecht", "schuster", "simon", "ludwig", "boehm", "winter", "kraus", "martin",
}


def _norm(s: str) -> list:
    """Lower case without accents; German umlauts as ae/oe/ue so that "Mühlmann" = "Muehlmann"."""
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("ø", "o").replace("ł", "l").replace("æ", "ae").replace("œ", "oe")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


def _passt(a: str, b: str) -> bool:
    """Same word or a minor spelling variant ("Haberstok" = "Haberstock"), for longer words only."""
    return a == b or (len(a) >= 6 and len(b) >= 6 and a[0] == b[0] and SequenceMatcher(None, a, b).ratio() >= 0.88)


MONATE = {"januar", "jaenner", "februar", "maerz", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "dezember", "january", "february", "march", "may", "june", "july", "october", "december"}


def _vorname_passt(k: str, v: str) -> bool:
    """First name, initial or short form ("Piet" - "Pieter")."""
    if len(k) == 1 or len(v) == 1:
        return k[0] == v[0]
    return _passt(k, v) or (min(len(k), len(v)) >= 4 and (k.startswith(v) or v.startswith(k)))


def _namenswort(t: str) -> bool:
    return t.isalpha() and t not in KEIN_NAME and t not in PARTIKEL and t not in TITEL


def _person(name: str) -> list:
    """"First [particle] Last" → entries for matching; a birth name becomes an additional entry."""
    geburtsnamen = []
    m = re.search(r"[,(]?\s*\b(?:born|n[ée]e|ne[ée]|geb\.?|geborene)\s+([^),]+)\)?", name, flags=re.I)
    if m:
        geburtsnamen.append(m.group(1).strip())
        name = (name[:m.start()] + name[m.end():]).strip(" ,")
    teile = name.split()
    if len(teile) == 1:                               # firm or family name, e.g. "Bernheim-Jeune"
        return [{"nachname": _norm(name), "vornamen": [], "phrase": True}]
    i = len(teile) - 2
    while i >= 1 and teile[i].lower() in PARTIKEL:
        i -= 1
    vornamen = [t for t in _norm(" ".join(teile[:i + 1])) if t not in TITEL]
    return [{"nachname": _norm(n), "vornamen": vornamen, "phrase": False} for n in [teile[-1]] + geburtsnamen]


def _alias_formen(alias: str) -> list:
    """Name variant from Wikidata. "Galerie Flechtheim" counts as a fixed name; single words are skipped."""
    alias = alias.split(",")[0].strip()
    tokens = _norm(alias)
    if len(tokens) < 2 or len(alias.split()) < 2:
        return []
    if any(t in KEIN_NAME for t in tokens):
        return [{"nachname": tokens, "vornamen": [], "phrase": True}]
    return _person(alias)


def _zeilen(pfad: Path) -> tuple:
    """Read a semicolon-separated list, skipping blank and comment lines. Returns (rows, column names)."""
    with open(pfad, encoding="utf-8") as f:
        zeilen = [z for z in f if z.strip() and not z.lstrip().startswith("#")]
    leser = csv.DictReader(zeilen, delimiter=";")
    return list(leser), leser.fieldnames or []


def lade_namensliste(*pfade: Path) -> list:
    """Load one or more reference lists and merge them by Wikidata ID.

    Formats (lines starting with # are comments):
      wikidata;name;aliases;born;died;description;source_status;category - data/build_reference_list.py
      wikidata;name;beschreibung;status_quelle;kategorie                            - older format
      name;note (or name;hinweis) - custom list, "Surname, First name" or a fixed name
    """
    personen, eigene = {}, []
    for pfad in pfade:
        zeilen, spalten = _zeilen(pfad)
        for z in zeilen:
            name = (z.get("name") or "").strip()
            if not name:
                continue
            if "wikidata" not in spalten:
                info = {"name": name, "kategorie": ((z.get("note") or z.get("hinweis")) or "").strip(), "beschreibung": "",
                        "wikidata": "", "geboren": "", "gestorben": ""}
                if "," in name:
                    nach, vor = (t.strip() for t in name.split(",", 1))
                    formen = [{"nachname": _norm(nach), "vornamen": _norm(vor), "phrase": False}]
                else:
                    formen = [{"nachname": _norm(name), "vornamen": [], "phrase": True}]
                eigene += [{**info, **f} for f in formen if f["nachname"]]
                continue
            qid = (z.get("wikidata") or "").strip() or name
            p = personen.setdefault(qid, {"name": name, "kategorien": [], "aliasse": set(), "beschreibung": "",
                                          "geboren": "", "gestorben": ""})
            for k in ((z.get("category") or z.get("kategorie")) or "").split(" | "):
                if k.strip() and k.strip() not in p["kategorien"]:
                    p["kategorien"].append(k.strip())
            p["aliasse"] |= {x.strip() for x in ((z.get("aliases") or z.get("aliasse")) or "").split(" | ") if x.strip()}
            beschreibung = ((z.get("description") or z.get("beschreibung")) or "").strip()
            m = re.search(r"\((\d{4})\s*-\s*(\d{4})?\)", beschreibung)
            p["geboren"] = p["geboren"] or ((z.get("born") or z.get("geboren")) or "").strip() or (m.group(1) if m else "")
            p["gestorben"] = p["gestorben"] or ((z.get("died") or z.get("gestorben")) or "").strip() or ((m.group(2) or "") if m else "")
            p["beschreibung"] = p["beschreibung"] or beschreibung
    eintraege = []
    for qid, p in personen.items():
        info = {"name": p["name"], "kategorie": " | ".join(p["kategorien"]), "beschreibung": p["beschreibung"],
                "wikidata": qid if re.fullmatch(r"Q\d+", qid) else "", "geboren": p["geboren"],
                "gestorben": p["gestorben"]}
        formen = _person(p["name"])
        for alias in sorted(p["aliasse"]):
            formen += _alias_formen(alias)
        gesehen = set()
        for f in formen:
            schluessel = (tuple(f["nachname"]), tuple(f["vornamen"]), f["phrase"])
            if f["nachname"] and schluessel not in gesehen:
                gesehen.add(schluessel)
                eintraege.append({**info, **f})
    return eintraege + eigene


def lade_standardlisten(sprache: str = "de") -> tuple:
    """Load all available default lists. Returns (entries, description for the record)."""
    vorhanden = [p for p in STANDARD_LISTEN if p.exists()]
    if not vorhanden:
        return [], ""
    liste = lade_namensliste(*vorhanden)
    personen = len({e["wikidata"] or e["name"] for e in liste})
    teile = [f"{p.name} (SHA-256 {hashlib.sha256(p.read_bytes()).hexdigest()})" for p in vorhanden]
    return liste, _t("liste_personen", sprache, anzahl=personen, dateien="; ".join(teile))


def namen_treffer(text: str, liste: list) -> list:
    """Match against the reference list, per segment between commas and parentheses.

    stark (strong) - surname and first name (or its initial) match
    schwach (weak) - surname matches, no first name given ("Galerie Fischer")
    no match       - preceded by a different first name, or the word is itself a first name ("Martin Schulz")
    """
    treffer = {}
    for abschnitt in re.split(r"[,;()\[\]/:]|\s-\s", text):
        tokens = _norm(abschnitt)
        for e in liste:
            n = e["nachname"]
            stelle = next((i for i in range(len(tokens) - len(n) + 1)
                           if all(_passt(tokens[i + k], n[k]) for k in range(len(n)))), None)
            if stelle is None:
                continue
            genau = tokens[stelle:stelle + len(n)] == n
            if e["phrase"]:
                staerke = "stark"
            else:
                ende = stelle + len(n)
                # followed by another name word or particle ("Rudolf von Gutmann"): it was a first name
                if ende < len(tokens) and (_namenswort(tokens[ende]) or tokens[ende] in PARTIKEL):
                    continue
                if len(n) == 1 and n[0] in MONATE:
                    continue
                kandidaten, j = [], stelle - 1
                while j >= 0 and len(kandidaten) < 3:
                    t = tokens[j]
                    j -= 1
                    if t in PARTIKEL or t in TITEL:
                        continue
                    if not _namenswort(t):
                        break
                    kandidaten.append(t)
                if not kandidaten:
                    if not genau:             # spelling variants only with a matching first name
                        continue
                    staerke = "schwach"
                elif e["vornamen"] and any(_vorname_passt(k, e["vornamen"][0]) for k in kandidaten):
                    staerke = "stark"
                else:
                    continue
            schluessel = e["wikidata"] or e["name"]
            if staerke == "stark" or schluessel not in treffer:
                nachname = next((w for w in re.split(r"[\s(),]+", e["name"]) if w and _norm(w) == n),
                                " ".join(n).title())
                treffer[schluessel] = {"name": e["name"], "kategorie": e["kategorie"], "wikidata": e["wikidata"],
                                       "beschreibung": e["beschreibung"], "geboren": e.get("geboren", ""),
                                       "gestorben": e.get("gestorben", ""), "staerke": staerke, "nachname": nachname}
    return list(treffer.values())


# ---------------------------------------------------------------- Review

def _bereiche(jahre: list) -> str:
    """[1933, 1934, 1935, 1940] → '1933–1935, 1940'"""
    if not jahre:
        return ""
    teile, a = [], jahre[0]
    for x, y in zip(jahre, jahre[1:] + [None]):
        if y != x + 1:
            teile.append(f"{a}" if a == x else f"{a}–{x}")
            a = y
    return ", ".join(teile)


def _wechselzeit(a: Station, b: Station, untergrenze: int = -10 ** 4, obergrenze: int = 10 ** 4,
                 sprache: str = "de") -> tuple | None:
    """When did the work pass from a to b? Returns (description, earliest, latest) or None.

    The lower and upper bounds come from the years of the preceding and following entries."""
    ende_a = a.bis if a.bis is not None else (a.von if a.punkt else None)
    anfang_b = b.von if b.von is not None else (b.bis if b.punkt else None)
    if ende_a is None and anfang_b is None:
        return None
    if ende_a is not None and anfang_b is not None:
        lo, hi = sorted((ende_a, anfang_b))
        return (_t("wann_um", sprache, jahr=lo) if lo == hi
                else _t("wann_zwischen", sprache, von=lo, bis=hi)), lo, hi
    if ende_a is not None:                         # b undated: change after the last record of a
        if not a.punkt:
            return _t("wann_um", sprache, jahr=ende_a), ende_a, ende_a
        hi = b.bis if b.bis is not None else obergrenze
        return (_t("wann_zwischen", sprache, von=ende_a, bis=hi) if hi < 10 ** 4
                else _t("wann_fruehestens", sprache, jahr=ende_a)), ende_a, hi
    if not b.punkt:                                # a has no end: change at the start of b
        return _t("wann_um", sprache, jahr=anfang_b), anfang_b, anfang_b
    if a.von is not None:                          # a has at least a start
        return _t("wann_zwischen", sprache, von=a.von, bis=anfang_b), a.von, anfang_b
    if untergrenze > -10 ** 4:
        return _t("wann_zwischen", sprache, von=untergrenze, bis=anfang_b), untergrenze, anfang_b
    return _t("wann_spaetestens", sprache, jahr=anfang_b), -10 ** 4, anfang_b


def _kurzinfo(t: dict, sprache: str = "de") -> str:
    """Short description, e.g. "Maria Almas-Dietrich (1892–1971), <category>, Wikidata Q1308305"."""
    jahre = f" ({t['geboren']}–{t['gestorben']})" if t.get("geboren") else ""
    kategorie = texts.kategorie(t["kategorie"], sprache)
    return f"{t['name']}{jahre}, {kategorie}" + (f", Wikidata {t['wikidata']}" if t["wikidata"] else "")


def _auch(nummern: list, sprache: str) -> str:
    """" (also entries 3, 5)" for further entries with the same finding, otherwise empty."""
    if not nummern:
        return ""
    return _t("auch_eine" if len(nummern) == 1 else "auch_mehrere", sprache, liste=", ".join(map(str, nummern)))


def _nahe_ns_zeit(s: Station) -> bool:
    """Undated or between 1925 and 1955: then a bare surname match is relevant as well."""
    if s.von is None and s.bis is None:
        return True
    a = s.von if s.von is not None else s.bis
    b = s.bis if s.bis is not None else s.von
    return a <= 1955 and b >= 1925


def pruefe(text: str, liste: list | None = None, entstehung: int | None = None,
           listenname: str = "", sprache: str = "de") -> Bericht:
    """Review a provenance text. sprache only selects the language of the findings ("de" or "en")."""
    sp = texts.pruefe_sprache(sprache)
    liste = liste if liste is not None else []
    stationen = []
    for i, teil in enumerate(zerlege(text), 1):
        j = _jahre(teil)
        tl = teil.lower()
        arten = [k for k in ("haendler", "auktion", "erbgang", "entzug", "restitution", "institution", "kuenstler")
                 if re.search(MUSTER[k], tl)]
        s = Station(nr=i, text=teil, von=j["von"], bis=j["bis"], ungefaehr=j["ungefaehr"], punkt=j["punkt"],
                    lebensdaten=j["lebensdaten"], arten=arten, anonym=_anonym(teil),
                    unsicher=[m.group(0) for m in re.finditer(MUSTER["unsicher"], tl)],
                    namen=namen_treffer(teil, liste))
        # an auction or a bare event without a name is not an owner
        s.eigentuemer = not s.anonym and not ("auktion" in arten and "haendler" not in arten
                                              and not re.search(r"sammlung|collection", tl))
        if "erbgang" in arten and stationen:                          # inheritance continues the previous ownership
            s.anonym = stationen[-1].anonym
            s.eigentuemer = stationen[-1].eigentuemer
        stationen.append(s)

    befunde = []
    alle_jahre = [y for s in stationen for y in (s.von, s.bis) if y is not None]
    ns_relevant = entstehung is None or entstehung <= NS_BIS

    # Period 1933–1945: belegt (explicit years), erschlossen (inferred from adjacent entries), offen (open)
    beginn = max(NS_VON, entstehung) if entstehung and entstehung <= NS_BIS else NS_VON   # nothing to check before creation
    zeitraum = {y: "offen" for y in range(beginn, NS_BIS + 1)}
    unauffaellig = {}
    for k, s in enumerate(stationen):
        if not s.eigentuemer:
            continue
        if s.von is not None or s.bis is not None:
            a = s.von if s.von is not None else s.bis
            b = s.bis if s.bis is not None else s.von
            for y in range(max(a, beginn), min(b, NS_BIS) + 1):
                zeitraum[y] = "belegt"
        vorher = [y for t in stationen[:k] for y in (t.von, t.bis) if y is not None]
        nachher = [y for t in stationen[k + 1:] for y in (t.von, t.bis) if y is not None]
        offener_anfang, offenes_ende = s.von is None or s.punkt, s.bis is None or s.punkt
        anfang = (max(vorher) if vorher else -10 ** 4) if offener_anfang else s.von
        ende = (min(nachher) if nachher else 10 ** 4) if offenes_ende else s.bis
        for y in range(max(anfang, beginn), min(ende, NS_BIS) + 1):
            if zeitraum[y] == "offen":
                zeitraum[y] = "erschlossen"
                unauffaellig[y] = bool({"erbgang", "institution", "kuenstler"} & set(s.arten))

    if ns_relevant:
        if not alle_jahre:
            befunde.append(Befund("hoch", _t("keine_jahre", sp)))
        else:
            offen = [y for y, v in zeitraum.items() if v == "offen"]
            erschlossen = [y for y, v in zeitraum.items() if v == "erschlossen"]
            if offen:
                stufe = "hoch" if len(offen) >= 3 else "mittel"
                befunde.append(Befund(stufe, _t("luecke", sp, bereiche=_bereiche(offen), anzahl=len(offen),
                                                gesamt=len(zeitraum))))
            if erschlossen:
                ruhig = all(unauffaellig.get(y) for y in erschlossen)
                befunde.append(Befund("hinweis" if ruhig else "mittel",
                                      _t("erschlossen", sp, bereiche=_bereiche(erschlossen),
                                         grund=_t("erschlossen_ruhig" if ruhig else "erschlossen_abgeleitet", sp))))
            if min(alle_jahre) > NS_BIS:
                befunde.append(Befund("hoch", _t("spaeter_beginn", sp, jahr=min(alle_jahre))))
        # changes of ownership and auctions within the period
        weitere = []
        for k, (a, b) in enumerate(zip(stationen, stationen[1:])):
            vorher = [y for t in stationen[:k + 1] for y in (t.von, t.bis) if y is not None]
            nachher = [y for t in stationen[k + 1:] for y in (t.von, t.bis) if y is not None]
            wann = _wechselzeit(a, b, max(vorher, default=-10 ** 4), min(nachher, default=10 ** 4), sp)
            if wann is None or wann[2] < NS_VON or wann[1] > NS_BIS:
                continue
            if b.anonym or {"haendler", "auktion"} & set(b.arten):
                befunde.append(Befund("hoch", _t("wechsel_handel", sp, wann=wann[0], a=a.nr, b=b.nr), b.nr))
            else:
                weitere.append(f"{a.nr} → {b.nr} {wann[0]}")
        if weitere:
            befunde.append(Befund("mittel", _t("wechsel_weitere", sp, liste="; ".join(weitere))))
        for s in stationen:
            if "auktion" in s.arten and s.von is not None and NS_VON <= s.von <= NS_BIS:
                befunde.append(Befund("mittel", _t("versteigerung", sp, jahr=s.von), s.nr))
            if s.lebensdaten and NS_VON <= s.lebensdaten[1] <= NS_BIS:
                befunde.append(Befund("hinweis", _t("tod", sp, jahr=s.lebensdaten[1]), s.nr))
    else:
        befunde.append(Befund("hinweis", _t("nicht_einschlaegig", sp, jahr=entstehung)))

    volle, nur_nachname, entzug = {}, {}, []
    for s in stationen:
        if "entzug" in s.arten:
            entzug.append((s.nr, re.search(MUSTER["entzug"], s.text.lower()).group(0)))
        if "restitution" in s.arten:
            befunde.append(Befund("hinweis", _t("restitution", sp), s.nr))
        for t in s.namen:
            if t["staerke"] == "stark":
                volle.setdefault(t["wikidata"] or t["name"], (t, []))[1].append(s.nr)
            elif _nahe_ns_zeit(s):
                eintrag = nur_nachname.setdefault(t["nachname"], ({}, []))
                eintrag[0][t["wikidata"] or t["name"]] = t
                if s.nr not in eintrag[1]:
                    eintrag[1].append(s.nr)
        if s.anonym:
            befunde.append(Befund("hinweis", _t("anonym", sp), s.nr))
        if s.unsicher:
            befunde.append(Befund("hinweis", _t("unsicher", sp, wort=_t("zitat", sp, wort=s.unsicher[0])), s.nr))
        if s.von is None and s.bis is None and "erbgang" not in s.arten:
            befunde.append(Befund("hinweis", _t("ohne_datum_befund", sp), s.nr))
    if entzug:
        woerter = ", ".join(_t("zitat", sp, wort=w) for w in dict.fromkeys(w for _, w in entzug))
        auch = _auch([n for n, _ in entzug[1:]], sp)
        befunde.append(Befund("hoch", _t("entzug", sp, auch=auch, woerter=woerter), entzug[0][0]))
    for nachname, (personen, nummern) in nur_nachname.items():
        offen_p = [t for k, t in personen.items() if k not in volle]
        if not offen_p:                       # the same person is fully matched elsewhere
            for k, t in personen.items():
                volle[k][1].extend(n for n in nummern if n not in volle[k][1])
            continue
        haeufig = " ".join(_norm(nachname)) in HAEUFIGE_NACHNAMEN
        befunde.append(Befund("hinweis" if haeufig else "mittel",
                              _t("nachname", sp, nachname=_t("zitat", sp, wort=nachname),
                                 haeufig=_t("haeufig", sp) if haeufig else "", auch=_auch(nummern[1:], sp),
                                 info="; ".join(_kurzinfo(t, sp) for t in offen_p)),
                              nummern[0]))
    for t, nummern in volle.values():
        nummern.sort()
        befunde.append(Befund("hoch", _t("name", sp, info=_kurzinfo(t, sp), auch=_auch(nummern[1:], sp)),
                              nummern[0]))
    erste = [s.von if s.von is not None else s.bis for s in stationen if s.von is not None or s.bis is not None]
    if len(erste) >= 3 and sum(b < a for a, b in zip(erste, erste[1:])) > len(erste) // 2:
        befunde.append(Befund("hinweis", _t("reihenfolge", sp)))
    if entstehung is None:
        befunde.append(Befund("hinweis", _t("entstehung_unbekannt", sp)))

    rang = {"hoch": 0, "mittel": 1, "hinweis": 2}
    befunde.sort(key=lambda b: (rang[b.stufe], b.station or 0))
    stufen = {b.stufe for b in befunde}
    pruefbedarf = "hoch" if "hoch" in stufen else "mittel" if "mittel" in stufen else "gering"
    return Bericht(pruefbedarf, [asdict(b) for b in befunde], [asdict(s) for s in stationen],
                   {str(k): v for k, v in zeitraum.items()}, ns_relevant, listenname,
                   hashlib.sha256(text.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------- Output

def _zeit(s: dict, sprache: str = "de") -> str:
    """Date of an entry for display, e.g. "1910–1958", "until 1938" or "undated"."""
    u = _t("zeit_ca", sprache) if s["ungefaehr"] else ""
    if s["von"] is not None and s["bis"] is not None:
        return u + (f"{s['von']}" if s["von"] == s["bis"] else f"{s['von']}–{s['bis']}")
    if s["bis"] is not None:
        return _t("zeit_bis", sprache, ca=u, jahr=s["bis"])
    if s["von"] is not None:
        return _t("zeit_seit", sprache, ca=u, jahr=s["von"])
    return _t("zeit_ohne", sprache)


def _merkmale(s: dict, sprache: str = "de") -> str:
    """Features of an entry for display (trade, auction, anonymous, life dates, ...)."""
    m = [texts.MERKMALE[sprache][a] for a in s["arten"]]
    if s["anonym"]:
        m.append(_t("anonym_merkmal", sprache))
    if s["lebensdaten"]:
        m.append(_t("lebensdaten", sprache, von=s["lebensdaten"][0], bis=s["lebensdaten"][1]))
    return ", ".join(m)


SCHLUSS = _t("schluss", "de")                    # kept for compatibility; use schluss(sprache)


def schluss(sprache: str = "de") -> str:
    """Closing statement for records in the requested language."""
    return _t("schluss", sprache)


def _station_vor(f: dict, sprache: str) -> str:
    return _t("station_vor", sprache, nr=f["station"]) if f["station"] else ""


def als_text(b: Bericht, sprache: str = "de") -> str:
    """Plain-text report for the command line."""
    sp = texts.pruefe_sprache(sprache)
    stufe = b.pruefbedarf if sp == "de" else texts.STUFE[sp][b.pruefbedarf]
    z = [f"{_t('werkzeug', sp)} {VERSION}", _t("txt_pruefbedarf", sp, stufe=stufe.upper()), "",
         _t("txt_stationen", sp)]
    for s in b.stationen:
        extra = _merkmale(s, sp)
        z.append(f"  {s['nr']}. {s['text']}")
        z.append(f"     {_t('txt_zeit', sp)}: {_zeit(s, sp)}" + (f" · {extra}" if extra else ""))
    z += ["", _t("txt_befunde", sp)]
    z += [f"  [{f['stufe'] if sp == 'de' else texts.STUFE[sp][f['stufe']].lower()}] " + _station_vor(f, sp) + f["text"]
          for f in b.befunde]
    z += ["", schluss(sp)]
    return "\n".join(z)


def als_protokoll(b: Bericht, text: str, objekt: str | None, sprache: str = "de") -> str:
    """Markdown record for the record-keeping duty under § 45 KGSG."""
    sp = texts.pruefe_sprache(sprache)

    def stufe(s: str) -> str:                    # German output shows the internal key as is
        return s if sp == "de" else texts.STUFE[sp][s].lower()
    zeit = datetime.now().strftime("%Y-%m-%d %H:%M")
    z = [_t("md_titel", sp), "",
         f"- {_t('md_datum', sp)}: {zeit}",
         f"- {_t('md_objekt', sp)}: {objekt or '—'}",
         f"- {_t('md_werkzeug', sp)}: provenance.py {VERSION}",
         f"- {_t('md_liste', sp)}: {b.namensliste or _t('keine', sp)}",
         f"- {_t('md_pruefsumme', sp)}: `{b.eingabe_sha256}`", "",
         _t("md_eingabe", sp), ""]
    z += [f"> {zeile}" for zeile in text.strip().splitlines()]
    z += ["", _t("md_ergebnis", sp, stufe=stufe(b.pruefbedarf)), "", _t("md_befunde", sp), ""]
    z += [f"- **{stufe(f['stufe'])}** – " + _station_vor(f, sp) + f["text"]
          for f in b.befunde] or [f"- {_t('keine', sp)}"]
    z += ["", _t("md_stationen", sp), ""]
    for s in b.stationen:
        extra = _merkmale(s, sp)
        z.append(f"{s['nr']}. {s['text']} — {_zeit(s, sp)}" + (f" ({extra})" if extra else ""))
    if b.ns_relevant:
        z += ["", _t("md_zeitraum", sp), ""]
        for status in ("belegt", "erschlossen", "offen"):
            jahre = [int(y) for y, v in b.zeitraum.items() if v == status]
            if jahre:
                z.append(f"- {texts.ZEITSTATUS[sp][status]}: {_bereiche(jahre)}")
    z += ["", _t("md_offen", sp), ""]
    z += [f"- [ ] {punkt}" for _, punkt in texts.CHECKLISTE[sp]]
    z += ["", f"_{schluss(sp)} {_t('aufbewahrung', sp)}_", "", _t("md_geprueft", sp), ""]
    return "\n".join(z)


# ---------------------------------------------------------------- Catalogue

SPALTEN_KATALOG = {
    "los": ("los", "lot", "nr", "nummer", "lot no", "losnummer", "inventar", "inv"),
    "provenienz": ("provenienz", "provenance", "herkunft"),
    "entstehung": ("entstehung", "jahr", "year", "datierung", "date", "entstanden"),
    "titel": ("titel", "title", "werk", "objekt", "object", "künstler", "artist"),
}
RANG = {"hoch": 0, "mittel": 1, "gering": 2}


def lies_katalog(inhalt: str, sprache: str = "de") -> list:
    """Read a catalogue CSV with a header row; delimiter ; , or tab. A provenance column is required."""
    zeilen = [z for z in inhalt.splitlines() if z.strip()]
    if not zeilen:
        return []
    kopf = zeilen[0]
    trenner = max((";", ",", "\t"), key=kopf.count)
    leser = csv.DictReader(io.StringIO("\n".join(zeilen)), delimiter=trenner)
    zuordnung = {}
    for feld in leser.fieldnames or []:
        name = feld.strip().lower().lstrip("\ufeff")
        for ziel, namen in SPALTEN_KATALOG.items():
            if ziel not in zuordnung and any(name == n or name.startswith(n) for n in namen):
                zuordnung[ziel] = feld
    if "provenienz" not in zuordnung:
        raise ValueError(_t("kat_keine_spalte", sprache))
    eintraege = []
    for i, z in enumerate(leser, 1):
        text = (z.get(zuordnung["provenienz"]) or "").strip()
        if not text:
            continue
        jahr = re.search(JAHR, z.get(zuordnung.get("entstehung", ""), "") or "")
        eintraege.append({"los": (z.get(zuordnung.get("los", ""), "") or str(i)).strip(),
                          "titel": (z.get(zuordnung.get("titel", ""), "") or "").strip(),
                          "entstehung": int(jahr.group(1)) if jahr else None, "text": text})
    return eintraege


def pruefe_katalog(eintraege: list, liste: list, listenname: str = "", sprache: str = "de") -> list:
    """Review every lot; sorted by review level, then by lot number."""
    ergebnisse = []
    for e in eintraege:
        b = pruefe(e["text"], liste, e["entstehung"], listenname, sprache)
        hoch = [f for f in b.befunde if f["stufe"] == "hoch"]
        mittel = [f for f in b.befunde if f["stufe"] == "mittel"]
        wichtig = (hoch or mittel or [{"text": ""}])[0]["text"]
        ergebnisse.append({**e, "bericht": b, "pruefbedarf": b.pruefbedarf, "hoch": len(hoch), "mittel": len(mittel),
                           "befund": wichtig})

    def losnummer(e):
        zahl = re.match(r"\d+", str(e["los"]))
        return (int(zahl.group(0)) if zahl else 10 ** 9, str(e["los"]))
    return sorted(ergebnisse, key=lambda e: (RANG[e["pruefbedarf"]], losnummer(e)))


def schreibe_katalog(ergebnisse: list, ziel: Path, quelle: str = "", sprache: str = "de") -> None:
    """Write the overview as CSV and PDF, plus one PDF record per lot.

    File names, CSV columns and review levels follow the chosen language.
    """
    import pdf_record
    en = sprache == "en"
    uebersicht, protokolle = ("overview", "records") if en else ("uebersicht", "protokolle")
    stufen = {"hoch": "high", "mittel": "medium", "gering": "low"} if en else {}
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / protokolle).mkdir(exist_ok=True)
    with open(ziel / f"{uebersicht}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["lot", "title", "year", "review_level", "high", "medium", "key_finding"] if en else
                   ["los", "titel", "entstehung", "pruefbedarf", "hoch", "mittel", "wichtigster_befund"])
        for e in ergebnisse:
            w.writerow([e["los"], e["titel"], e["entstehung"] or "", stufen.get(e["pruefbedarf"], e["pruefbedarf"]),
                        e["hoch"], e["mittel"], e["befund"]])
    (ziel / f"{uebersicht}.pdf").write_bytes(pdf_record.katalog_pdf(ergebnisse, quelle, sprache))
    for e in ergebnisse:
        b = e["bericht"]
        datei = re.sub(r"[^\w.-]+", "_", _t("kat_dateiname", sprache, los=e["los"])) + ".pdf"
        objekt = _t("kat_objekt", sprache, los=e["los"]) + (f" · {e['titel']}" if e["titel"] else "")
        (ziel / protokolle / datei).write_bytes(
            pdf_record.protokoll_pdf(b, e["text"], objekt, [_zeit(s, sprache) for s in b.stationen],
                                       schluss(sprache), sprache))


class _Help(argparse.HelpFormatter):
    """Show only the primary (English) option name in --help; aliases keep working."""

    def _format_action_invocation(self, action):
        if not action.option_strings:
            return super()._format_action_invocation(action)
        name = action.option_strings[0]
        if action.nargs == 0:
            return name
        return f"{name} {self._format_args(action, self._get_default_metavar_for_optional(action))}"


def main() -> None:
    """Command-line entry point. German option names (--datei, --katalog, ...) are kept as aliases."""
    ap = argparse.ArgumentParser(formatter_class=_Help, 
        description="Review a provenance text for the period 1933–1945, ownership changes, seizure keywords "
                    "and reference-list names (German KGSG due diligence).")
    ap.add_argument("text", nargs="?", help="provenance text (or use --file)")
    ap.add_argument("--file", "--datei", dest="datei", type=Path, metavar="PATH",
                    help="read the provenance text from a file")
    ap.add_argument("--year", "--entstehung", dest="entstehung", type=int, metavar="YEAR",
                    help="year the work was created")
    ap.add_argument("--reference-list", "--referenzliste", dest="referenzliste", type=Path, metavar="CSV",
                    help="custom reference list instead of the default lists in data/")
    ap.add_argument("--object", "--objekt", dest="objekt", metavar="NAME",
                    help="object title or inventory number for the record")
    ap.add_argument("--record", "--protokoll", dest="protokoll", type=Path, metavar="PATH",
                    help="write a review record (Markdown) to this path")
    ap.add_argument("--pdf", type=Path, metavar="PATH", help="write a review record (PDF) to this path")
    ap.add_argument("--catalogue", "--katalog", dest="katalog", type=Path, metavar="CSV",
                    help="review a whole catalogue: CSV with columns lot;title;year;provenance")
    ap.add_argument("--out", "--ausgabe", dest="ausgabe", type=Path, default=Path("catalogue_review"), metavar="DIR",
                    help="output folder for a catalogue review (default: catalogue_review)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--lang", "--sprache", dest="sprache", choices=texts.SPRACHEN, default="en",
                    help="output language (default: en)")
    a = ap.parse_args()
    sp = a.sprache

    text = a.datei.read_text(encoding="utf-8") if a.datei else a.text
    if not text and not a.katalog:
        ap.error(_t("cli_fehlt", sp))
    if a.referenzliste:
        liste = lade_namensliste(a.referenzliste)
        listenname = f"{a.referenzliste.name} (SHA-256 {hashlib.sha256(a.referenzliste.read_bytes()).hexdigest()})"
    else:
        liste, listenname = lade_standardlisten(sp)
    if a.katalog:
        ergebnisse = pruefe_katalog(lies_katalog(a.katalog.read_text(encoding="utf-8-sig"), sp), liste, listenname, sp)
        schreibe_katalog(ergebnisse, a.ausgabe, a.katalog.name, sp)
        for e in ergebnisse:
            stufe = e["pruefbedarf"] if sp == "de" else texts.STUFE[sp][e["pruefbedarf"]]
            print(f"{str(e['los']):>6}  {stufe.upper():7} {_t('kat_zeile', sp, hoch=e['hoch'], mittel=e['mittel'])}  "
                  f"{(e['titel'] or e['text'])[:60]}")
        print("\n" + _t("kat_fertig", sp, anzahl=len(ergebnisse), ordner=a.ausgabe))
        return
    bericht = pruefe(text, liste, a.entstehung, listenname, sp)
    if a.pdf:
        import pdf_record
        a.pdf.write_bytes(pdf_record.protokoll_pdf(bericht, text, a.objekt,
                                                     [_zeit(s, sp) for s in bericht.stationen], schluss(sp), sp))
    if a.protokoll:
        a.protokoll.write_text(als_protokoll(bericht, text, a.objekt, sp), encoding="utf-8")
    print(json.dumps(asdict(bericht), ensure_ascii=False, indent=2) if a.json else als_text(bericht, sp))


if __name__ == "__main__":
    main()
