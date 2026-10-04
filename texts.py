"""User-facing texts in German (default) and English.

Only the output is translated. Internal keys such as stufe ("hoch", "mittel", "hinweis"),
pruefbedarf, klasse or sicherheit stay German so that the web UI and the JSON output remain stable.
The English wording describes review notes; it is neither an assessment of persons nor an approval.
"""
from __future__ import annotations

SPRACHEN = ("de", "en")


def pruefe_sprache(sprache: str) -> str:
    """Validate a language code and return it."""
    if sprache not in SPRACHEN:
        raise ValueError(f"Unknown language '{sprache}' - allowed: {', '.join(SPRACHEN)}")
    return sprache


def t(schluessel: str, sprache: str = "de", **werte) -> str:
    """Template in the requested language, filled with the given values."""
    vorlage = TEXTE[schluessel][sprache]
    return vorlage.format(**werte) if werte else vorlage


# Finding and review levels: display names for the internal keys
STUFE = {
    "de": {"hoch": "Hoch", "mittel": "Mittel", "hinweis": "Hinweis", "gering": "Gering"},
    "en": {"hoch": "High", "mittel": "Medium", "hinweis": "Note", "gering": "Low"},
}

# Confidence levels of the print check
SICHERHEIT = {
    "de": {"hoch": "hoch", "mittel": "mittel", "niedrig": "niedrig"},
    "en": {"hoch": "high", "mittel": "medium", "niedrig": "low"},
}

# Reference-list categories (German in the CSV); unknown categories are shown verbatim
KATEGORIE_EN = {
    "in ALIU-Berichten genannt (1944–1946)": "named in ALIU reports (1944–1946)",
    "dokumentierte NS-Verfolgung (§ 44 KGSG)": "documented Nazi persecution (§ 44 KGSG)",
    "Bezug zu Entziehungs- oder Restitutionsfall": "linked to a seizure or restitution case",
    "NSDAP-Mitgliedschaft dokumentiert": "documented NSDAP membership",
}


def kategorie(text: str, sprache: str = "de") -> str:
    """Join "a | b" from the reference list into readable text; translated for English."""
    if sprache != "en":
        return text.replace(" | ", t("und", sprache))
    return t("und", sprache).join(KATEGORIE_EN.get(k.strip(), k.strip()) for k in text.split(" | ") if k.strip())


# Features of a provenance entry
MERKMALE = {
    "de": {"haendler": "Handel", "auktion": "Versteigerung", "erbgang": "Erbgang", "entzug": "Entzug",
           "restitution": "Restitution", "institution": "Institution", "kuenstler": "Künstler"},
    "en": {"haendler": "trade", "auktion": "auction", "erbgang": "inheritance", "entzug": "seizure",
           "restitution": "restitution", "institution": "institution", "kuenstler": "artist"},
}

# Timeline 1933–1945
ZEITSTATUS = {
    "de": {"belegt": "belegt", "erschlossen": "erschlossen", "offen": "offen"},
    "en": {"belegt": "documented", "erschlossen": "inferred", "offen": "open"},
}

# Checklist under § 42(1) KGSG: (PDF text, Markdown text)
CHECKLISTE = {
    "de": [
        ("Nr. 1  Name und Anschrift von Einlieferer bzw. Veräußerer festgestellt",
         "Nr. 1 Name und Anschrift von Einlieferer bzw. Veräußerer festgestellt"),
        ("Nr. 2  Beschreibung und Abbildung angefertigt", "Nr. 2 Beschreibung und Abbildung angefertigt"),
        ("Nr. 3  Befunde dieses Protokolls geklärt oder Recherche veranlasst",
         "Nr. 3 Befunde oben geklärt bzw. Recherche veranlasst"),
        ("Nr. 4  Ein- und Ausfuhrdokumente geprüft", "Nr. 4 Ein- und Ausfuhrdokumente geprüft"),
        ("Nr. 5  Verbote und Beschränkungen geprüft", "Nr. 5 Verbote und Beschränkungen geprüft"),
        ("Nr. 6  Datenbanken abgeglichen: Lost Art, Interpol ID-Art, Art Loss Register",
         "Nr. 6 Datenbanken abgeglichen: Lost Art ☐  Interpol ID-Art ☐  Art Loss Register ☐  Ergebnis: ______"),
        ("Nr. 7  Erklärung des Einlieferers zur Verfügungsberechtigung liegt vor",
         "Nr. 7 Erklärung des Einlieferers zur Verfügungsberechtigung liegt vor"),
    ],
    "en": [
        ("No. 1  Name and address of consignor or seller established",
         "No. 1 Name and address of consignor or seller established"),
        ("No. 2  Description and image prepared", "No. 2 Description and image prepared"),
        ("No. 3  Findings of this record resolved or further research commissioned",
         "No. 3 Findings above resolved or further research commissioned"),
        ("No. 4  Import and export documents reviewed", "No. 4 Import and export documents reviewed"),
        ("No. 5  Prohibitions and restrictions reviewed", "No. 5 Prohibitions and restrictions reviewed"),
        ("No. 6  Databases searched: Lost Art, Interpol ID-Art, Art Loss Register",
         "No. 6 Databases searched: Lost Art ☐  Interpol ID-Art ☐  Art Loss Register ☐  Result: ______"),
        ("No. 7  Consignor's declaration of entitlement to dispose of the work on file",
         "No. 7 Consignor's declaration of entitlement to dispose of the work on file"),
    ],
}

MONATE_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")


def datum(zeit, sprache: str = "de") -> str:
    """Date and time for page headers, independent of the system locale."""
    if sprache == "en":
        return f"{zeit.day} {MONATE_EN[zeit.month - 1]} {zeit.year}, {zeit:%H:%M}"
    return zeit.strftime("%d.%m.%Y, %H:%M Uhr")


TEXTE = {
    # ------------------------------------------------------------ general
    "und": {"de": " sowie ", "en": " and "},
    "zitat": {"de": "„{wort}“", "en": "“{wort}”"},
    "keine": {"de": "keine", "en": "none"},
    "liste_personen": {"de": "{anzahl} Personen aus {dateien}", "en": "{anzahl} persons from {dateien}"},

    # ------------------------------------------------------------ findings (provenance.pruefe)
    "keine_jahre": {"de": "Keine Jahresangaben – der Zeitraum 1933–1945 lässt sich nicht prüfen",
                    "en": "No dates given – the period 1933–1945 cannot be reviewed"},
    "luecke": {"de": "Lücke im Zeitraum nach § 44 KGSG: {bereiche} ohne benannten Besitzer ({anzahl} von {gesamt} Jahren)",
               "en": "Gap in the period under § 44 KGSG: {bereiche} without a named owner ({anzahl} of {gesamt} years)"},
    "erschlossen": {"de": "{bereiche} nur erschlossen, nicht ausdrücklich belegt {grund}",
                    "en": "{bereiche} only inferred, not explicitly documented {grund}"},
    "erschlossen_ruhig": {"de": "(Künstler, Erbgang oder Institution)", "en": "(artist, inheritance or institution)"},
    "erschlossen_abgeleitet": {"de": "(Besitzdauer aus Nachbarstationen abgeleitet)",
                               "en": "(period of ownership inferred from adjacent entries)"},
    "spaeter_beginn": {"de": "Provenienz setzt erst {jahr} ein – Verbleib vor 1945 offen",
                       "en": "Provenance begins only in {jahr} – whereabouts before 1945 not documented"},
    "wechsel_handel": {"de": "Besitzwechsel {wann} (Station {a} → {b}) an Handel, Versteigerung oder Unbekannt",
                       "en": "Change of ownership {wann} (entry {a} → {b}) to the trade, an auction or an unnamed party"},
    "wechsel_weitere": {"de": "Weitere Besitzwechsel im Zeitraum nach § 44 KGSG: {liste}",
                        "en": "Further changes of ownership in the period under § 44 KGSG: {liste}"},
    "versteigerung": {"de": "Versteigerung {jahr} im Zeitraum nach § 44 KGSG – Einlieferer und Umstände klären",
                      "en": "Auction in {jahr} within the period under § 44 KGSG – establish consignor and circumstances"},
    "tod": {"de": "Besitzer starb {jahr} – Verbleib nach dem Tod und Erben klären",
            "en": "Owner died in {jahr} – establish whereabouts after death and heirs"},
    "nicht_einschlaegig": {"de": "Entstanden {jahr} – Zeitraum 1933–1945 nicht einschlägig",
                           "en": "Created in {jahr} – period 1933–1945 not applicable"},
    "restitution": {"de": "Restitution oder Collecting Point erwähnt – Akten und abschließende Regelung prüfen "
                          "(§ 44 Satz 2 KGSG)",
                    "en": "Restitution or Collecting Point mentioned – review files and final settlement "
                          "(§ 44 sentence 2 KGSG)"},
    "anonym": {"de": "Anonyme Station – Namen beim Einlieferer erfragen",
               "en": "Anonymous entry – request names from the consignor"},
    "unsicher": {"de": "Unsichere Angabe ({wort})", "en": "Uncertain statement ({wort})"},
    "ohne_datum_befund": {"de": "Station ohne Datum", "en": "Undated entry"},
    "entzug": {"de": "Hinweis auf Entzug oder Verfolgung{auch}: {woerter}",
               "en": "Indication of seizure or persecution{auch}: {woerter}"},
    "nachname": {"de": "Nachname {nachname}{haeufig}{auch} in Referenzliste ({info}) – ohne Vornamen, Identität klären",
                 "en": "Surname {nachname}{haeufig}{auch} in reference list ({info}) – no first name given, "
                       "identity requires further research"},
    "haeufig": {"de": " (häufiger Name)", "en": " (common name)"},
    "name": {"de": "Name in Referenzliste: {info}{auch} – Abschnitt vertieft prüfen",
             "en": "Name in reference list: {info}{auch} – requires further research"},
    "reihenfolge": {"de": "Jahre fallen überwiegend – Reihenfolge eventuell umgekehrt (neueste zuerst)",
                    "en": "Dates mostly descend – order may be reversed (most recent first)"},
    "entstehung_unbekannt": {"de": "Entstehungsjahr unbekannt – Zeitraum 1933–1945 vorsorglich geprüft",
                             "en": "Year of creation unknown – period 1933–1945 reviewed as a precaution"},
    "auch_eine": {"de": " (auch Station {liste})", "en": " (also entry {liste})"},
    "auch_mehrere": {"de": " (auch Station {liste})", "en": " (also entries {liste})"},

    # timing of a change of ownership
    "wann_um": {"de": "um {jahr}", "en": "around {jahr}"},
    "wann_zwischen": {"de": "zwischen {von} und {bis}", "en": "between {von} and {bis}"},
    "wann_fruehestens": {"de": "frühestens {jahr}", "en": "no earlier than {jahr}"},
    "wann_spaetestens": {"de": "spätestens {jahr}", "en": "no later than {jahr}"},

    # date of a provenance entry
    "zeit_ca": {"de": "ca. ", "en": "c. "},
    "zeit_bis": {"de": "{ca}bis {jahr}", "en": "{ca}until {jahr}"},
    "zeit_seit": {"de": "{ca}seit {jahr}", "en": "{ca}since {jahr}"},
    "zeit_ohne": {"de": "ohne Datum", "en": "undated"},
    "anonym_merkmal": {"de": "anonym", "en": "anonymous"},
    "lebensdaten": {"de": "Lebensdaten {von}–{bis}", "en": "life dates {von}–{bis}"},

    "schluss": {"de": "Kein Befund heißt nicht unbedenklich: geprüft wurde nur der Provenienztext. "
                      "Datenbankabgleich und Dokumentenprüfung (§ 42 Abs. 1 Nr. 4–7 KGSG) bleiben Pflicht.",
                "en": "An absence of findings does not mean the provenance is unproblematic: only the provenance "
                      "text was reviewed. Database searches and document review (§ 42 para. 1 nos. 4–7 KGSG) "
                      "remain mandatory."},
    "aufbewahrung": {"de": "Aufbewahrung der Aufzeichnungen: 30 Jahre (§ 45 KGSG).",
                     "en": "Records must be retained for 30 years (§ 45 KGSG)."},

    # ------------------------------------------------------------ plain-text output
    "werkzeug": {"de": "Provenienz-Prüfer", "en": "Provenance checker"},
    "txt_pruefbedarf": {"de": "Prüfbedarf: {stufe}", "en": "Review level: {stufe}"},
    "txt_stationen": {"de": "Stationen:", "en": "Provenance entries:"},
    "txt_zeit": {"de": "Zeit", "en": "Date"},
    "txt_befunde": {"de": "Befunde:", "en": "Findings:"},
    "station_vor": {"de": "Station {nr}: ", "en": "Entry {nr}: "},

    # ------------------------------------------------------------ Markdown record
    "md_titel": {"de": "# Provenienz-Prüfprotokoll", "en": "# Provenance review record"},
    "md_datum": {"de": "Datum", "en": "Date"},
    "md_objekt": {"de": "Objekt", "en": "Object"},
    "md_werkzeug": {"de": "Werkzeug", "en": "Tool"},
    "md_liste": {"de": "Referenzliste", "en": "Reference list"},
    "md_pruefsumme": {"de": "Prüfsumme der Eingabe (SHA-256)", "en": "Checksum of input (SHA-256)"},
    "md_eingabe": {"de": "## Eingabe (wörtlich)", "en": "## Input (verbatim)"},
    "md_ergebnis": {"de": "## Ergebnis: Prüfbedarf {stufe}", "en": "## Result: review level {stufe}"},
    "md_befunde": {"de": "### Befunde", "en": "### Findings"},
    "md_stationen": {"de": "### Stationen", "en": "### Provenance entries"},
    "md_zeitraum": {"de": "### Zeitraum 30.01.1933–08.05.1945", "en": "### Period 30 January 1933 – 8 May 1945"},
    "md_offen": {"de": "## Noch zu erledigen (§ 42 Abs. 1 KGSG)", "en": "## Still to be completed (§ 42 para. 1 KGSG)"},
    "md_geprueft": {"de": "Geprüft von: ____________________   Datum: ____________",
                    "en": "Reviewed by: ____________________   Date: ____________"},

    # ------------------------------------------------------------ catalogue
    "kat_keine_spalte": {"de": "Keine Spalte „Provenienz“ gefunden. Erwartet: los;titel;entstehung;provenienz",
                         "en": "No “provenance” column found. Expected: lot;title;year;provenance "
                               "(or los;titel;entstehung;provenienz)"},
    "kat_zeile": {"de": "{hoch:2} hoch {mittel:2} mittel", "en": "{hoch:2} high {mittel:2} medium"},
    "kat_fertig": {"de": "{anzahl} Lose geprüft → {ordner}/uebersicht.pdf, uebersicht.csv, protokolle/",
                   "en": "{anzahl} lots reviewed → {ordner}/overview.pdf, overview.csv, records/"},
    "kat_dateiname": {"de": "Los_{los}", "en": "Lot_{los}"},
    "kat_objekt": {"de": "Los {los}", "en": "Lot {los}"},
    "cli_fehlt": {"de": "Provenienztext oder --katalog fehlt", "en": "Provenance text, --file or --catalogue missing"},

    # ------------------------------------------------------------ PDF
    "pdf_titel": {"de": "Prüfprotokoll {objekt}", "en": "Provenance review record {objekt}"},
    "pdf_oberzeile": {"de": "Prüfprotokoll Provenienz · §§ 42–45 KGSG", "en": "Provenance review record · §§ 42–45 KGSG"},
    "pdf_ohne_objekt": {"de": "Prüfbericht Provenienz", "en": "Provenance review report"},
    "pdf_meta": {"de": "{datum} · Bericht {kennung}", "en": "{datum} · Report {kennung}"},
    "pdf_pruefbedarf": {"de": "Prüfbedarf", "en": "Review level"},
    "pdf_eingabe": {"de": "Eingabe, wörtlich", "en": "Input, verbatim"},
    "pdf_zeitraum": {"de": "Zeitraum nach § 44 KGSG · 30.01.1933 bis 08.05.1945",
                     "en": "Period under § 44 KGSG · 30 Jan 1933 to 8 May 1945"},
    "pdf_stationen": {"de": "Stationen", "en": "Provenance entries"},
    "pdf_befunde": {"de": "Befunde", "en": "Findings"},
    "pdf_nichts": {"de": "Im Text nichts gefunden.", "en": "Nothing found in the text."},
    "pdf_station_kurz": {"de": "S{nr:02d}", "en": "E{nr:02d}"},
    "pdf_offen": {"de": "Noch zu erledigen · § 42 Abs. 1 KGSG", "en": "Still to be completed · § 42 para. 1 KGSG"},
    "pdf_nachweis": {"de": "Nachweis", "en": "Record"},
    "pdf_pruefsumme": {"de": "Prüfsumme der Eingabe (SHA-256): {wert}", "en": "Checksum of input (SHA-256): {wert}"},
    "pdf_liste": {"de": "Referenzliste: {wert}", "en": "Reference list: {wert}"},
    "pdf_geprueft": {"de": "Geprüft von", "en": "Reviewed by"},
    "pdf_datum": {"de": "Datum", "en": "Date"},
    "pdf_fuss": {"de": "Prüfhinweise, keine Rechtsberatung und keine Freigabe.",
                 "en": "Review notes only – not legal advice and not an approval."},
    "pdf_seite": {"de": "Seite {i} von {n}", "en": "Page {i} of {n}"},
    "pdf_kat_titel": {"de": "Katalogprüfung", "en": "Catalogue review"},
    "pdf_kat_oberzeile": {"de": "Katalogprüfung · Provenienz", "en": "Catalogue review · Provenance"},
    "pdf_kat_quelle": {"de": "Katalog", "en": "Catalogue"},
    "pdf_kat_meta": {"de": "{datum} · {anzahl} Lose", "en": "{datum} · {anzahl} lots"},
    "pdf_kat_hoch": {"de": "Prüfbedarf hoch", "en": "Review level high"},
    "pdf_kat_zusammenfassung": {"de": "Zusammenfassung", "en": "Summary"},
    "pdf_kat_lose": {"de": "Lose", "en": "Lots"},
    "pdf_kat_spalten": {"de": "LOS|WERK|ENTST.|PRÜFBEDARF UND WICHTIGSTER BEFUND",
                        "en": "LOT|WORK|DATE|REVIEW LEVEL AND MAIN FINDING"},
    "pdf_kat_zahlen": {"de": "   {hoch} hoch · {mittel} mittel", "en": "   {hoch} high · {mittel} medium"},
    "pdf_kat_fuss": {"de": "Prüfhinweise, keine Rechtsberatung und keine Freigabe. Einzelprotokolle je Los liegen bei.",
                     "en": "Review notes only – not legal advice and not an approval. Individual records for each "
                           "lot are attached."},

    # ------------------------------------------------------------ print check
    "dc_zu_klein": {"de": "Bild zu klein – mindestens 256 Pixel Kantenlänge.",
                    "en": "Image too small – at least 256 pixels on the shorter side."},
    "dc_rosette": {"de": "{anzahl} Rasterwinkel gefunden (Farb-Rosette): {winkel}",
                   "en": "{anzahl} screen angles found (colour rosette): {winkel}"},
    "dc_ein_gitter": {"de": "Ein Punktgitter bei {winkel:.0f}° gefunden (einfarbiges Raster)",
                      "en": "One dot grid found at {winkel:.0f}° (single-colour screen)"},
    "dc_anteil": {"de": "{anteil:.0f} % der Feinstruktur stecken in den Rasterspitzen; Periode {periode:.1f} px, "
                        "in {kacheln} von {gesamt} Bildkacheln",
                  "en": "{anteil:.0f} % of the fine structure lies in the screen peaks; period {periode:.1f} px, "
                        "in {kacheln} of {gesamt} image tiles"},
    "dc_rasterweite": {"de": "; Rasterweite ≈ {lcm:.0f} Linien/cm ({lpi:.0f} lpi)",
                       "en": "; screen ruling ≈ {lcm:.0f} lines/cm ({lpi:.0f} lpi)"},
    "dc_flach": {"de": "Feinstruktur-Kontrast nur {wert:.3f} (Schwelle {schwelle})",
                 "en": "Fine-structure contrast only {wert:.3f} (threshold {schwelle})"},
    "dc_massstab_passt_nicht": {"de": "Maßstab {massstab:g} µm/px passt nicht zu den Prüfbändern – bitte anderen "
                                      "Abstand wählen",
                                "en": "Scale {massstab:g} µm/px does not match the analysis bands – please choose a "
                                      "different distance"},
    "dc_fein_grob": {"de": "Keine Rasterspitzen; Verhältnis feine zu grobe Struktur {wert:.2f} (Schwelle {schwelle}: "
                           "darüber fein verteilte Punkte, darunter klumpige Körnung)",
                     "en": "No screen peaks; ratio of fine to coarse structure {wert:.2f} (threshold {schwelle}: "
                           "above it finely distributed dots, below it clumpy grain)"},
    "dc_adressraster": {"de": "Zusätzlich ein schwaches Gitter mit {periode:.1f} px Periode (nur {anteil:.1f} % der "
                              "Energie) – passt zum Adressraster eines Druckers",
                        "en": "Additionally a weak grid with a period of {periode:.1f} px (only {anteil:.1f} % of the "
                              "energy) – consistent with a printer's addressing grid"},
    "dc_massstab_angenommen": {"de": "Maßstab angenommen: {wert:g} µm/px (mit --um-pro-px genauer)",
                               "en": "Scale assumed: {wert:g} µm/px (use --um-per-px for a more precise result)"},
    "dc_grob": {"de": "Achtung: {wert:g} µm/px ist grob – Inkjet-Punkte (20–50 µm) sind so kaum aufzulösen",
                "en": "Note: {wert:g} µm/px is coarse – inkjet dots (20–50 µm) can hardly be resolved at this scale"},
    "dc_bildzeile": {"de": "Links: schärfster Ausschnitt.  Rechts: Fourier-Spektrum, Mitte = grobe, Rand = feine "
                           "Strukturen.",
                     "en": "Left: sharpest detail.  Right: Fourier spectrum, centre = coarse, edge = fine structures."},
    "dc_kopf": {"de": "Druckgrafik-Check: {name}", "en": "Print check: {name}"},
    "dc_ergebnis": {"de": "Ergebnis:   {wert}", "en": "Result:     {wert}"},
    "dc_sicherheit": {"de": "Sicherheit: {wert}", "en": "Confidence: {wert}"},
    "dc_einordnung": {"de": "Einordnung: {wert}", "en": "Context:    {wert}"},
}

# Print check: result title per class
DRUCK_TITEL = {
    "de": {
        "offset": "Rasterdruck (AM) – fotomechanische Reproduktion, z. B. Offset",
        "inkjet": "Inkjet / Giclée (fein verteiltes, unregelmäßiges Punktmuster)",
        "litho": "Kein Druckraster – klumpige Körnung (passt zu Lithografie vom Stein oder von der Platte)",
        "flach": "Keine Mikrostruktur erkennbar",
    },
    "en": {
        "offset": "Halftone screen (AM) – photomechanical reproduction, e.g. offset",
        "inkjet": "Inkjet / giclée (finely distributed, irregular dot pattern)",
        "litho": "No halftone screen – clumpy grain (consistent with lithography from stone or plate)",
        "flach": "No microstructure detectable",
    },
}

# Print check: context note per class
DRUCK_HINWEIS = {
    "de": {
        "offset": "Ein regelmäßiges Punktraster entsteht bei fotomechanischer Reproduktion. Wird das Blatt als "
                  "„Original-Lithografie“ oder Handabzug angeboten, ist es sehr wahrscheinlich eine Reproduktion. "
                  "Ausnahme: Künstler, die selbst mit Fotoraster gearbeitet haben (z. B. Warhols Siebdrucke).",
        "inkjet": "Ein Inkjet-Druck ist legitim, wenn er als Giclée bzw. Pigmentdruck verkauft wird. Als Lithografie, "
                  "Radierung oder Siebdruck angeboten, ist die Bezeichnung falsch.",
        "litho": "Passt zu einem Handabzug ohne Fotoraster. Das ist kein Echtheitsbeweis: Signatur, Papier, "
                 "Wasserzeichen, Auflage und Werkverzeichnis bleiben zu prüfen.",
        "flach": "Entweder deckende Farbfläche (z. B. Siebdruck) – oder das Foto ist zu unscharf bzw. zu wenig "
                 "vergrößert. Mit mindestens 10-fach-Makro an einer Stelle mit Halbtönen (Verlauf, Schatten) "
                 "wiederholen.",
    },
    "en": {
        "offset": "A regular halftone dot screen results from photomechanical reproduction. If the sheet is offered "
                  "as an “original lithograph” or hand-pulled print, it is very likely a reproduction. Exception: "
                  "artists who themselves worked with a photographic screen (e.g. Warhol's screenprints).",
        "inkjet": "An inkjet print is legitimate when sold as a giclée or pigment print. If it is offered as a "
                  "lithograph, etching or screenprint, the description is incorrect.",
        "litho": "Consistent with a hand-pulled print without a photographic screen. This is not proof of "
                 "authenticity: signature, paper, watermark, edition and catalogue raisonné still need to be "
                 "checked.",
        "flach": "Either an opaque area of colour (e.g. screenprint) – or the photo is too blurred or not magnified "
                 "enough. Repeat with at least 10× macro on an area with halftones (gradient, shadow).",
    },
}
