#!/usr/bin/env python3
"""Print check: identifies from a macro photo how a sheet was printed.

Under magnification every printing process leaves its own microstructure, which
shows up in the Fourier spectrum of the photo:

  Halftone (offset)     Dots on a regular, rotated grid.
                        Spectrum: sharp peaks, one perpendicular pair per ink;
                        several angles at once = colour rosette.
                        Almost all of the energy lies in these peaks.
  Inkjet / giclée       Tiny dots (20–50 µm), random but evenly distributed.
                        Spectrum: no significant peaks, but much energy in fine
                        structures (25–125 µm) relative to coarse ones
                        (250–640 µm).
  Lithograph (stone)    Crayon on grained stone: irregular, clumpy grain.
                        No peaks; the energy lies mostly in coarse structures.
  Flat colour           Opaque ink without fine structure (e.g. screenprint),
                        or the photo is too blurred or not magnified enough.

The thresholds are tuned on synthetic images (test_synth.py) and still need to
be calibrated against real macro photos of known prints.

Usage:
  python3 printcheck.py examples/offset.jpg
  python3 printcheck.py photo.jpg --um-per-px 8       # known scale → screen ruling in lines/cm
  python3 printcheck.py photo.jpg --diagnose spectrum.png
  python3 printcheck.py photo.jpg --json
  python3 printcheck.py photo.jpg --lang de           # German output
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scipy import ndimage

import texts
from texts import t as _t

R_MIN, R_MAX = 1 / 64, 0.42      # frequency range for screen peaks (cycles per pixel)
SPITZE_MIN = np.log(40.0)        # peak: 40× above the median of its frequency ring ...
SPEICHE_MIN = np.log(8.0)        # ... and 8× above its neighbours on the same spoke
SPITZENANTEIL_MIN = 0.25         # offset: at least a quarter of the fine structure lies in peaks
STRUKTUR_MIN = 0.06              # minimum fine-structure contrast (std. dev. of reflectance)
FEIN_GROB_MIN = 0.10             # inkjet: minimum power ratio of fine to coarse structure
FEIN_UM, GROB_UM = (25, 125), (250, 640)   # structure sizes (period in µm) of the two bands
STANDARD_UM_PRO_PX = 10.0        # assumed scale when none is given
MAX_KACHELN = 6

# Texts per language live in texts.py; German defaults kept here for compatibility
TITEL = texts.DRUCK_TITEL["de"]
HINWEIS = texts.DRUCK_HINWEIS["de"]


@dataclass
class Raster:
    periode_px: float
    winkel: float                 # 0–90 degrees in image coordinates
    staerke: float                # factor above background
    kacheln: int                  # number of image tiles it was found in
    kanaele: list = field(default_factory=list)
    linien_pro_cm: float | None = None


@dataclass
class Befund:
    klasse: str
    titel: str
    sicherheit: str
    begruendung: list
    hinweis: str
    raster: list
    kennzahlen: dict


# ---------------------------------------------------------------- Spectrum

@lru_cache(maxsize=4)
def _gitter(n: int) -> dict:
    """Precomputed frequency grids and masks for an n×n tile."""
    f = (np.arange(n) - n // 2) / n
    fx, fy = np.meshgrid(f, f)
    r = np.hypot(fx, fy)
    ring = np.rint(r * n).astype(int)
    jpeg = np.zeros((n, n), bool)          # 8×8 JPEG blocks create peaks at multiples of 1/8
    for k in range(-4, 5):
        for l in range(-4, 5):
            if k or l:
                cy, cx = n // 2 + k * n // 8, n // 2 + l * n // 8
                jpeg[max(cy - 2, 0):cy + 3, max(cx - 2, 0):cx + 3] = True
    return {
        "fx": fx, "fy": fy, "r": r, "ring": ring,
        "winkel": np.degrees(np.arctan2(fy, fx)) % 180.0,
        "ordnung": np.argsort(ring.ravel(), kind="stable"),
        "grenzen": np.concatenate([[0], np.cumsum(np.bincount(ring.ravel()))]),
        "anzahl": np.bincount(ring.ravel()),
        "halb": (fy > 0) | ((fy == 0) & (fx > 0)),   # the spectrum is point-symmetric
        "jpeg": jpeg,
        "band": (r >= R_MIN) & (r <= R_MAX),
        "fenster": np.outer(np.hanning(n), np.hanning(n)),
    }


def leistungsspektrum(x: np.ndarray) -> np.ndarray:
    """Centred power spectral density. Mean over all frequencies ≈ variance of the tile."""
    g = _gitter(x.shape[0])
    w = g["fenster"]
    F = np.fft.fftshift(np.fft.fft2((x - x.mean()) * w))
    return np.abs(F) ** 2 / (w ** 2).sum()


def _ring_median(werte: np.ndarray, g: dict) -> np.ndarray:
    """Median value per frequency ring."""
    v = werte.ravel()[g["ordnung"]]
    gr = g["grenzen"]
    return np.array([np.median(v[gr[i]:gr[i + 1]]) if gr[i + 1] > gr[i] else 0.0
                     for i in range(len(gr) - 1)])


def radialprofil(P: np.ndarray) -> np.ndarray:
    """Mean power spectral density per frequency ring (index = radius in frequency bins)."""
    g = _gitter(P.shape[0])
    return np.bincount(g["ring"].ravel(), weights=P.ravel()) / np.maximum(g["anzahl"], 1)


def finde_spitzen(P: np.ndarray) -> list:
    """Point-like peaks: far above their frequency ring and above their neighbours on the spoke.

    Returns (frequency, angle, log excess, row, column) for each peak in the upper half-plane.
    """
    n = P.shape[0]
    g = _gitter(n)
    logP = np.log(P + 1e-30)
    ueber = logP - _ring_median(logP, g)[g["ring"]]
    lokal = ueber >= ndimage.maximum_filter(ueber, size=5)
    kandidaten = lokal & g["band"] & g["halb"] & ~g["jpeg"] & (ueber > SPITZE_MIN)
    spitzen = []
    for iy, ix in zip(*np.nonzero(kandidaten)):
        r = g["r"][iy, ix]
        d = max(0.15 * r, 4 / n)
        nachbar = -np.inf
        for rr in (r - d, r + d):            # edges in the image create lines, not points
            jy = int(round(n // 2 + g["fy"][iy, ix] * rr / r * n))
            jx = int(round(n // 2 + g["fx"][iy, ix] * rr / r * n))
            if 1 <= jy < n - 1 and 1 <= jx < n - 1:
                nachbar = max(nachbar, ueber[jy - 1:jy + 2, jx - 1:jx + 2].max())
        if ueber[iy, ix] - nachbar > SPEICHE_MIN:
            spitzen.append((float(r), float(g["winkel"][iy, ix]), float(ueber[iy, ix]), int(iy), int(ix)))
    return spitzen


def _winkelabstand(a: float, b: float, periode: float) -> float:
    """Angular distance between a and b for the given period (e.g. 90 or 180 degrees)."""
    d = abs(a - b) % periode
    return min(d, periode - d)


def raster_paare(spitzen: list) -> list:
    """Pairs of peaks with the same frequency at right angles = one dot grid."""
    paare = []
    for i in range(len(spitzen)):
        for j in range(i + 1, len(spitzen)):
            (ra, wa, sa), (rb, wb, sb) = spitzen[i][:3], spitzen[j][:3]
            if abs(ra - rb) > 0.05 * max(ra, rb) or abs(_winkelabstand(wa, wb, 180) - 90) > 5:
                continue
            z = np.exp(4j * np.radians(wa % 90)) + np.exp(4j * np.radians(wb % 90))
            paare.append(((ra + rb) / 2, float(np.degrees(np.angle(z)) / 4 % 90), min(sa, sb)))
    return paare


def _grundraster(eintraege: list, kacheln: int) -> list:
    """Merge grids across tiles and channels and keep only the fundamental screens.

    Random pairs appear in a single tile only. Harmonics and intermodulation products of the
    rosette lie at other frequencies than the fundamental screens, and the inks normally share
    one screen ruling. Hence only grids close to the frequency of the strongest one are kept.
    """
    gruppen = []
    for r, w, s, t, name in sorted(eintraege, key=lambda e: -e[2]):
        for gr in gruppen:
            if abs(r - gr["r"]) <= 0.05 * gr["r"] and _winkelabstand(w, gr["w"], 90) <= 4:
                gr["kacheln"].add(t)
                gr["kanaele"].add(name)
                break
        else:
            gruppen.append({"r": r, "w": w, "s": s, "kacheln": {t}, "kanaele": {name}})
    gruppen = [gr for gr in gruppen if len(gr["kacheln"]) >= min(2, kacheln)]
    if not gruppen:
        return []
    staerkste = max(gruppen, key=lambda e: e["s"])
    return sorted((gr for gr in gruppen if abs(gr["r"] / staerkste["r"] - 1) <= 0.08),
                  key=lambda e: -e["s"])


# ---------------------------------------------------------------- Analysis

def _kanaele(rgb: np.ndarray) -> dict:
    """Luminance and approximate ink channels (keys are part of the JSON output)."""
    return {
        "Helligkeit": 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2],
        "Cyan": 1 - rgb[..., 0],
        "Magenta": 1 - rgb[..., 1],
        "Gelb": 1 - rgb[..., 2],
    }


def _kacheln(L: np.ndarray, n: int, anzahl: int) -> list:
    """The sharpest non-overlapping tiles (macro photos are often blurred towards the edges)."""
    H, W = L.shape
    schaerfe = ndimage.laplace(ndimage.gaussian_filter(L, 0.7)) ** 2
    ny, nx = H // n, W // n
    oy, ox = (H - ny * n) // 2, (W - nx * n) // 2
    liste = [(schaerfe[oy + i * n:oy + (i + 1) * n, ox + j * n:ox + (j + 1) * n].mean(), oy + i * n, ox + j * n)
             for i in range(ny) for j in range(nx)]
    liste.sort(reverse=True)
    return [(y, x) for _, y, x in liste[:anzahl]]


def _als_rgb(bild: np.ndarray) -> np.ndarray:
    """Image as float RGB in the range 0–1."""
    rgb = np.asarray(bild, dtype=float)
    if rgb.ndim == 2:
        rgb = np.stack([rgb] * 3, -1)
    rgb = rgb[..., :3]
    return rgb / 255.0 if rgb.max() > 1.5 else rgb


def analysiere(bild: np.ndarray, um_pro_px: float | None = None, sprache: str = "de") -> Befund:
    """Determine the printing process. sprache only selects the language of title, reasons and note."""
    sp = texts.pruefe_sprache(sprache)
    rgb = _als_rgb(bild)
    kurz = min(rgb.shape[:2])
    if kurz < 256:
        raise ValueError(_t("dc_zu_klein", sp))
    n = 512 if kurz >= 1024 else 256 if kurz >= 512 else 128
    g = _gitter(n)
    massstab = um_pro_px or STANDARD_UM_PRO_PX
    kanaele = _kanaele(rgb)
    kacheln = _kacheln(kanaele["Helligkeit"], n, MAX_KACHELN)

    eintraege = []                                   # (frequency, angle, strength, tile, channel)
    profile = {k: [] for k in kanaele}
    feinenergie = {k: [] for k in kanaele}
    spitzenanteil = {k: [] for k in kanaele}
    # fine structure = structures of 25–125 µm, converted with the scale
    hoch = (g["r"] >= max(massstab / FEIN_UM[1], R_MIN)) & (g["r"] <= min(massstab / FEIN_UM[0], R_MAX))
    if not hoch.any():
        hoch = g["band"] & (g["r"] >= 0.06)
    for t, (y, x) in enumerate(kacheln):
        for name, kanal in kanaele.items():
            P = leistungsspektrum(kanal[y:y + n, x:x + n])
            profile[name].append(radialprofil(P))
            feinenergie[name].append(P[hoch].sum() / n ** 2)
            spitzen = finde_spitzen(P)
            # share of the fine structure in point-like peaks (×2 for the mirrored half)
            in_spitzen = sum(2 * P[max(iy - 2, 0):iy + 3, max(ix - 2, 0):ix + 3].sum() for *_, iy, ix in spitzen)
            spitzenanteil[name].append(min(in_spitzen / (P[g["band"]].sum() + 1e-30), 1.0))
            eintraege += [(r, w, s, t, name) for r, w, s in raster_paare(spitzen)]

    grund = _grundraster(eintraege, len(kacheln))
    raster = [Raster(periode_px=round(1 / gr["r"], 2), winkel=round(gr["w"], 1),
                     staerke=round(float(np.exp(gr["s"]))), kacheln=len(gr["kacheln"]),
                     kanaele=sorted(gr["kanaele"]),
                     linien_pro_cm=round(gr["r"] / (um_pro_px * 1e-4), 1) if um_pro_px else None)
              for gr in grund]

    # structure channel: the channel with the most fine structure
    struktur = {k: float(np.sqrt(np.median(v))) for k, v in feinenergie.items()}
    haupt = max(struktur, key=struktur.get)
    anteil = float(np.median(spitzenanteil[haupt]))
    S = np.mean(profile[haupt], axis=0)
    f = np.arange(S.size) / n
    fein = (f >= max(massstab / FEIN_UM[1], R_MIN)) & (f <= min(massstab / FEIN_UM[0], R_MAX))
    grob = (f >= max(massstab / GROB_UM[1], 3 / n)) & (f <= massstab / GROB_UM[0])
    fein_grob = float(S[fein].mean() / S[grob].mean()) if fein.any() and grob.any() else float("nan")

    kennzahlen = {
        "kachelgroesse_px": n,
        "kacheln": len(kacheln),
        "strukturkanal": haupt,
        "feinstruktur_kontrast": round(struktur[haupt], 4),
        "spitzenanteil": round(anteil, 3),
        "fein_grob": round(fein_grob, 3),
        "um_pro_px": massstab,
        "massstab_angenommen": um_pro_px is None,
    }

    begruendung = []
    if raster and anteil >= SPITZENANTEIL_MIN:
        klasse = "offset"
        winkel = sorted(r.winkel for r in raster)
        if len(raster) >= 2:
            begruendung.append(_t("dc_rosette", sp, anzahl=len(raster), winkel=", ".join(f"{w:.0f}°" for w in winkel)))
            sicherheit = "hoch"
        else:
            begruendung.append(_t("dc_ein_gitter", sp, winkel=winkel[0]))
            sicherheit = "hoch" if raster[0].kacheln >= 3 else "mittel"
        p = raster[0]
        text = _t("dc_anteil", sp, anteil=100 * anteil, periode=p.periode_px, kacheln=p.kacheln, gesamt=len(kacheln))
        if p.linien_pro_cm:
            text += _t("dc_rasterweite", sp, lcm=p.linien_pro_cm, lpi=p.linien_pro_cm * 2.54)
        begruendung.append(text)
    elif struktur[haupt] < STRUKTUR_MIN:
        klasse, sicherheit = "flach", "mittel"
        begruendung.append(_t("dc_flach", sp, wert=struktur[haupt], schwelle=STRUKTUR_MIN))
    elif np.isnan(fein_grob):
        klasse, sicherheit = "flach", "niedrig"
        begruendung.append(_t("dc_massstab_passt_nicht", sp, massstab=massstab))
    else:
        klasse = "inkjet" if fein_grob >= FEIN_GROB_MIN else "litho"
        deutlich = fein_grob >= 2 * FEIN_GROB_MIN if klasse == "inkjet" else fein_grob <= FEIN_GROB_MIN / 2
        sicherheit = "mittel" if deutlich else "niedrig"
        begruendung.append(_t("dc_fein_grob", sp, wert=fein_grob, schwelle=FEIN_GROB_MIN))
        if raster and klasse == "inkjet":
            begruendung.append(_t("dc_adressraster", sp, periode=raster[0].periode_px, anteil=100 * anteil))
    if um_pro_px is None:
        begruendung.append(_t("dc_massstab_angenommen", sp, wert=STANDARD_UM_PRO_PX))
    elif um_pro_px > 15 and klasse in ("litho", "flach"):
        begruendung.append(_t("dc_grob", sp, wert=um_pro_px))
    # sicherheit stays the internal key (hoch/mittel/niedrig); display text via texts.SICHERHEIT
    return Befund(klasse, texts.DRUCK_TITEL[sp][klasse], sicherheit, begruendung, texts.DRUCK_HINWEIS[sp][klasse],
                  [asdict(r) for r in raster] if klasse == "offset" else [], kennzahlen)


# ---------------------------------------------------------------- Input and output

def lade(pfad: Path) -> np.ndarray:
    """Load an image as an RGB array, honouring EXIF orientation; HEIC is converted on macOS."""
    try:
        img = Image.open(pfad)
    except Exception:
        if pfad.suffix.lower() not in (".heic", ".heif") or sys.platform != "darwin":
            raise
        ziel = Path(tempfile.mkdtemp()) / (pfad.stem + ".jpg")   # convert iPhone HEIC via macOS sips
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100",
                        str(pfad), "--out", str(ziel)], check=True, capture_output=True)
        img = Image.open(ziel)
    return np.asarray(ImageOps.exif_transpose(img).convert("RGB"))


def _schrift(groesse: int):
    """A system font in the given size, falling back to Pillow's default font."""
    for kandidat in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(kandidat, groesse)
        except OSError:
            continue
    return ImageFont.load_default()


def diagnose_teile(bild: np.ndarray, befund: Befund, groesse: int = 640, markieren: bool = True) -> tuple:
    """Sharpest detail and its Fourier spectrum as images; screen peaks are marked in the spectrum."""
    rgb = _als_rgb(bild)
    n = befund.kennzahlen["kachelgroesse_px"]
    kanal = _kanaele(rgb)[befund.kennzahlen["strukturkanal"]]
    y, x = _kacheln(kanal, n, 1)[0]
    logP = np.log(leistungsspektrum(kanal[y:y + n, x:x + n]) + 1e-30)
    lo, hi = np.percentile(logP, [3, 99.95])
    spek = np.clip((logP - lo) / (hi - lo), 0, 1) ** 1.15
    ausschnitt = Image.fromarray((np.clip(rgb[y:y + n, x:x + n], 0, 1) * 255).astype(np.uint8))
    ausschnitt = ausschnitt.resize((groesse, groesse), Image.NEAREST)
    spektrum = Image.fromarray((spek * 255).astype(np.uint8)).convert("RGB").resize((groesse, groesse), Image.BICUBIC)
    d = ImageDraw.Draw(spektrum)
    s, m, rad = groesse / n, groesse / 2, groesse / 48
    for r in befund.raster if markieren else []:
        f = 1 / r["periode_px"]
        for w in (r["winkel"], r["winkel"] + 90, r["winkel"] + 180, r["winkel"] + 270):
            cx = m + f * n * np.cos(np.radians(w)) * s
            cy = m + f * n * np.sin(np.radians(w)) * s
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(214, 64, 52), width=2)
    return ausschnitt, spektrum


def diagnosebild(bild: np.ndarray, befund: Befund, ziel, sprache: str = "de") -> None:
    """Write detail and spectrum side by side, with a short caption, as PNG."""
    ausschnitt, spektrum = diagnose_teile(bild, befund, 640)
    blatt = Image.new("RGB", (1300, 740), "white")
    blatt.paste(ausschnitt, (0, 0))
    blatt.paste(spektrum, (660, 0))
    t = ImageDraw.Draw(blatt)
    t.text((0, 656), befund.titel, fill=(22, 24, 29), font=_schrift(22))
    t.text((0, 692), _t("dc_bildzeile", texts.pruefe_sprache(sprache)), fill=(107, 111, 118), font=_schrift(16))
    blatt.save(ziel, format="PNG")


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
    """Command-line entry point. German option names (--um-pro-px, --sprache) are kept as aliases."""
    ap = argparse.ArgumentParser(formatter_class=_Help, 
        description="Identify the printing process of a sheet (halftone/offset, inkjet, lithograph) "
                    "from a macro photo via its Fourier spectrum.")
    ap.add_argument("foto", type=Path, metavar="photo", help="macro photo of the print (JPEG, PNG, ...; HEIC on macOS)")
    ap.add_argument("--um-per-px", "--um-pro-px", dest="um_pro_px", type=float, metavar="UM",
                    help="scale in micrometres per pixel, e.g. measured from a ruler in the photo")
    ap.add_argument("--diagnose", type=Path, metavar="PATH", help="write a diagnostic image (PNG) to this path")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--lang", "--sprache", dest="sprache", choices=texts.SPRACHEN, default="en",
                    help="output language (default: en)")
    a = ap.parse_args()
    sp = a.sprache

    bild = lade(a.foto)
    befund = analysiere(bild, a.um_pro_px, sp)
    if a.diagnose:
        diagnosebild(bild, befund, a.diagnose, sp)
    if a.json:
        print(json.dumps(asdict(befund), ensure_ascii=False, indent=2))
        return
    print(_t("dc_kopf", sp, name=a.foto.name))
    print(_t("dc_ergebnis", sp, wert=befund.titel))
    print(_t("dc_sicherheit", sp, wert=texts.SICHERHEIT[sp][befund.sicherheit]))
    for zeile in befund.begruendung:
        print(f"  – {zeile}")
    print(_t("dc_einordnung", sp, wert=befund.hinweis))


if __name__ == "__main__":
    main()
