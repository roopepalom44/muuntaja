"""Format helpers without QGIS dependencies (unit-testable with plain Python)."""

import glob
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

VECTOR_EXTENSIONS = {".gpkg", ".geojson", ".json", ".kml", ".kmz", ".gpx", ".dwg", ".dxf", ".shp"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".jp2", ".img"}
CAD_EXTENSIONS = {".dwg", ".dxf"}
WORLD_FILES = {".pgw", ".pngw", ".jgw", ".jpgw", ".jpegw", ".wld"}
CONVERTER_TIMEOUT_SECONDS = 600

# DWG-tiedoston kuusi ensimmäistä tavua kertovat AutoCAD-version.
DWG_VERSIONS = {
    "AC1012": "R13", "AC1014": "R14", "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004", "AC1021": "AutoCAD 2007", "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013", "AC1032": "AutoCAD 2018",
}
# GDAL:n CAD-ajuri (libopencad) lukee DWG:stä vain AutoCAD 2000 -version.
OGR_CAD_READABLE_DWG = {"AC1015"}


def safe_name(name):
    name = re.sub(r"[^\w-]+", "_", str(name), flags=re.UNICODE).strip("_-")
    return name[:80] or "layer"


def unique_name(name, existing, max_length=80):
    """Return ``name`` or ``name_N`` so that it is unique case-insensitively.

    GeoPackage- ja FileGDB-taulujen nimet ovat kirjainkoosta riippumattomia,
    joten ``Tiet`` ja ``tiet`` olisivat sama taso.
    """
    taken = {str(item).casefold() for item in existing}
    candidate, number = name[:max_length], 2
    while candidate.casefold() in taken:
        suffix = f"_{number}"
        candidate = name[:max_length - len(suffix)] + suffix
        number += 1
    return candidate


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Vapaata tiedostonimeä ei löytynyt: {path}")


def classify_finnish_xy(x, y):
    """Return the EPSG code of a Finnish coordinate system matching ``x, y``."""
    if 19 <= x <= 32.5 and 59 <= y <= 71.5:
        return 4326
    if 2000000 <= x <= 3700000 and 8000000 <= y <= 11800000:
        return 3857
    if not 6400000 <= y <= 7900000:
        return None
    if 20000 <= x <= 800000:
        return 3067
    for low, high, code in ((1000000, 1900000, 2391), (2000000, 2900000, 2392),
                            (3000000, 3900000, 2393), (4000000, 4900000, 2394)):
        if low <= x <= high:
            return code
    if 19000000 <= x <= 32000000:
        zone = int(x // 1000000)
        if 19 <= zone <= 31:
            return 3873 + zone - 19
    return None


def vote_finnish_epsg(points, minimum_share=0.6):
    """Majority vote over sample points; ``None`` when the result is uncertain.

    Yksittäinen origossa oleva CAD-apuviiva ei saa kaataa tunnistusta, kuten
    laajuuden keskipisteeseen perustuva arvaus tekisi.
    """
    votes = {}
    for x, y in points or []:
        code = classify_finnish_xy(x, y)
        if code:
            votes[code] = votes.get(code, 0) + 1
    if not votes:
        return None
    best, count = max(votes.items(), key=lambda item: item[1])
    return best if count / float(sum(votes.values())) >= minimum_share else None


def has_georeference(path):
    path = Path(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return True
    return any(path.with_suffix(ext).exists() for ext in WORLD_FILES) or Path(str(path) + ".aux.xml").exists()


def looks_like_geojson(path, sample_bytes=65536):
    """True when the start of a JSON file looks like GeoJSON or Esri JSON."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(sample_bytes).decode("utf-8", errors="ignore")
    except OSError:
        return False
    compact = re.sub(r"\s+", "", head)
    markers = ('"type":"FeatureCollection"', '"type":"Feature"', '"features":[',
               '"geometryType":"esriGeometry', '"coordinates":[')
    return any(marker in compact for marker in markers)


def scan_inputs(paths):
    """Expand folders recursively, ignore Shapefile sidecars and unlocated images.

    Kansiosta otetaan JSON-tiedostoista mukaan vain paikkatietoa sisältävät,
    mutta yksittäin valittu JSON hyväksytään sellaisenaan.
    """
    supported = VECTOR_EXTENSIONS | RASTER_EXTENSIONS | {".dfsu"}
    found, seen = [], set()
    for entry in paths:
        root = Path(entry)
        from_folder = root.is_dir()
        candidates = sorted(root.rglob("*"), key=lambda p: str(p).casefold()) if from_folder else [root]
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in supported:
                continue
            if not has_georeference(path):
                continue
            if from_folder and path.suffix.lower() == ".json" and not looks_like_geojson(path):
                continue
            key = os.path.normcase(str(path.resolve()))
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found


def raster_group(path):
    for part in reversed(Path(path).parts[:-1]):
        if part.lower().startswith("taustakartta_"):
            return part
    return Path(path).parent.name


def dfsu_matches(value, operator, expected):
    if operator in {"contains", "starts with", "ends with"}:
        text = str(value).casefold()
        target = str(expected).casefold()
        return {"contains": target in text, "starts with": text.startswith(target),
                "ends with": text.endswith(target)}[operator]
    try:
        left, right = float(value), float(str(expected).replace(",", "."))
    except (ValueError, TypeError):
        left, right = str(value), str(expected)
    return {"=": left == right, "≠": left != right, ">": left > right,
            ">=": left >= right, "<": left < right, "<=": left <= right}[operator]


def dfsu_wkb(points):
    if len(points) == 1:
        return struct.pack("<BIdd", 1, 1, *points[0])
    if len(points) == 2:
        return struct.pack("<BII", 1, 2, 2) + b"".join(struct.pack("<dd", *point) for point in points)
    ring = list(points)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return struct.pack("<BIII", 1, 3, 1, len(ring)) + b"".join(struct.pack("<dd", *point) for point in ring)


# --- CAD ---------------------------------------------------------------------

def dwg_version(path):
    """Return the DWG version code such as ``AC1032`` or ``""``."""
    try:
        with Path(path).open("rb") as source:
            code = source.read(6).decode("ascii", errors="replace")
    except OSError:
        return ""
    return code if re.fullmatch(r"AC10\d\d", code) else ""


def dwg_version_label(code):
    return DWG_VERSIONS.get(code, code or "tuntematon versio")


_STYLE_TOOL = re.compile(r"(PEN|BRUSH|LABEL|SYMBOL)\((.*?)\)(?:;|$)")


def _style_params(body):
    params, key, value, quoted, i = {}, "", "", False, 0
    reading_value = False
    while i < len(body):
        char = body[i]
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted and not reading_value:
            reading_value = True
        elif char == "," and not quoted:
            params[key.strip()] = value.strip()
            key, value, reading_value = "", "", False
        elif reading_value:
            value += char
        else:
            key += char
        i += 1
    if key.strip():
        params[key.strip()] = value.strip()
    return params


def _style_color(value):
    match = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", value or "")
    return f"#{match.group(1).lower()}" if match else ""


def _style_number(value):
    match = re.match(r"(-?\d+(?:\.\d+)?)", value or "")
    return float(match.group(1)) if match else None


def parse_ogr_style(style):
    """Parse an OGR feature style string written by the DXF driver.

    Palauttaa värin (``#rrggbb``), tekstin, tekstin korkeuden maastoyksiköissä
    ja kiertokulman asteina vastapäivään. Puuttuvat arvot ovat tyhjiä.
    """
    result = {"color": "", "text": "", "text_size": None, "angle": None, "anchor": None}
    for tool, body in _STYLE_TOOL.findall(style or ""):
        params = _style_params(body)
        if tool == "LABEL":
            result["text"] = params.get("t", "").strip('"')
            size = params.get("s", "")
            # Vain maastoyksiköissä (g) annettu korkeus on mittakaavaton CAD-korkeus.
            if re.fullmatch(r"-?\d+(?:\.\d+)?g?", size):
                result["text_size"] = _style_number(size)
            result["angle"] = _style_number(params.get("a"))
            anchor = _style_number(params.get("p"))
            result["anchor"] = int(anchor) if anchor and 1 <= anchor <= 12 else None
            result["color"] = result["color"] or _style_color(params.get("c"))
        elif tool == "BRUSH":
            result["color"] = result["color"] or _style_color(params.get("fc"))
        else:
            result["color"] = result["color"] or _style_color(params.get("c"))
    return result


# --- DWG converters -----------------------------------------------------------

def _windows_program_dirs():
    return [os.environ.get(name, "") for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]


# Windowsissa LibreDWG (GPL) jaetaan lisäosan mukana, joten DWG toimii ilman
# asennuksia. Muilla alustoilla käytetään järjestelmän LibreDWG:tä.
BUNDLED_LIBREDWG = Path(__file__).resolve().parent / "libredwg"


def find_libredwg_tool(name):
    """Locate a LibreDWG command line tool (``dwg2dxf`` or ``dxf2dwg``)."""
    candidates = [BUNDLED_LIBREDWG / f"{name}.exe"] if sys.platform == "win32" else []
    candidates += [shutil.which(name), shutil.which(name + ".exe")]
    for base in filter(None, _windows_program_dirs()):
        candidates += glob.glob(os.path.join(base, "libredwg*", name + ".exe"))
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def run_converter(command, description):
    """Run an external converter without a console window and with a timeout."""
    # Muuntimien tuloste ei aina ole UTF-8:aa (esim. ääkköset polussa):
    # korvaa tunnistamattomat merkit, jottei lukusäie kaadu.
    options = {"capture_output": True, "text": True, "errors": "replace",
               "timeout": CONVERTER_TIMEOUT_SECONDS, "check": False}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        options["env"] = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    try:
        result = subprocess.run([str(part) for part in command], **options)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{description} ei valmistunut {CONVERTER_TIMEOUT_SECONDS // 60} minuutissa.") from exc
    except OSError as exc:
        raise RuntimeError(f"{description} ei käynnistynyt: {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"{description} epäonnistui (exit {result.returncode}): {details}")
    return result


# --- export coordinate systems -------------------------------------------------

# Viennin yleisimmät kohdekoordinaatistot (nimi, EPSG). Sama lista kuin ArcGIS
# Pro -työkalussa; muun koordinaatiston voi valita QGISin omasta valitsimesta.
COMMON_EXPORT_CRS = (
    [("ETRS-TM35FIN", 3067)]
    + [(f"ETRS-GK{zone}", 3873 + zone - 19) for zone in range(19, 32)]
    + [("KKJ kaista 1", 2391), ("KKJ kaista 2", 2392), ("KKJ Yhtenäiskoordinaatisto", 2393),
       ("KKJ kaista 4", 2394), ("WGS 84", 4326), ("WGS 84 / Pseudo-Mercator", 3857)]
)
# KML/KMZ on standardin mukaan aina WGS84.
WGS84_ONLY_EXPORT_FORMATS = {"KML", "KMZ"}
