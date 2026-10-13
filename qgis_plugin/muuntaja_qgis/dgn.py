"""Self-contained DGN V7/V8 reading and V8 writing with bundled cadkit."""

import importlib.util
import json
import math
import platform
import re
import struct
import sys
from pathlib import Path

VENDOR = Path(__file__).with_name("vendor") / "cadkit"


def _cadkit():
    # Another plugin's installed cadkit must not replace our private ABI.
    name = __package__ + "._cadkit"
    if name in sys.modules:
        return sys.modules[name]
    system = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform)
    machine = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine().lower())
    manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["binaries"].get(f"{system}-{machine}")
    if entry is None or sys.version_info < (3, 9):
        raise RuntimeError("DGN-tuki vaatii 64-bittisen Windows-, Linux- tai macOS-QGISin ja Python 3.9+:n.")
    spec = importlib.util.spec_from_file_location(name, VENDOR / entry["path"])
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise RuntimeError("Lisäosan mukana toimitetun DGN-kirjaston lataaminen epäonnistui. Asenna Muuntajan ZIP uudelleen.") from exc
    sys.modules[name] = module
    return module


def metadata(path):
    sidecar = Path(str(path) + ".muuntaja.json")
    return json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}


def _inside(point, ring):
    x, y = point["x"], point["y"]
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a["y"] > y) != (b["y"] > y) and x < (b["x"] - a["x"]) * (y - a["y"]) / (b["y"] - a["y"]) + a["x"]:
            inside = not inside
    return inside


def _shapes(entity):
    """DGN shapes and hole cells become filled polygons rather than outlines."""
    kind = entity["kind"]
    if kind["type"] == "polyline" and kind["closed"] and not any(v["bulge"] for v in kind["vertices"]):
        if entity["props"].get("dgn.type") == 6:
            ring = [v["position"] for v in kind["vertices"]]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            entity["kind"] = {"type": "polygon", "exterior": ring, "interiors": []}
    elif kind["type"] == "group":
        for child in kind["children"]:
            _shapes(child)
        children = kind["children"]
        if children and all(c["kind"]["type"] == "polygon" for c in children):
            outers = [c for c in children if not c["props"].get("dgn.hole")]
            for hole in (c for c in children if c["props"].get("dgn.hole")):
                ring = hole["kind"]["exterior"]
                parent = next((c for c in outers if ring and _inside(ring[0], c["kind"]["exterior"])), None)
                if parent is None:
                    raise RuntimeError("DGN-alueen reiälle ei löytynyt ulkorajaa.")
                parent["kind"]["interiors"].append(ring)
            if len(outers) == 1:
                entity["kind"] = outers[0]["kind"]
            else:
                kind["children"] = outers


# --- elements cadkit keeps as Unknown ------------------------------------------
#
# cadkit 0.3 decodes the common DGN element families but leaves dimensions (33)
# and cones (23) as Unknown entities without geometry. Their V8 layouts were
# confirmed on a MicroStation V8 drawing (68 dimensions, 66 cones): every
# coordinate matches the element's own range and the surrounding cells.
#
# Cone (23), offsets from the element start, UOR doubles:
#   0x70 quaternion (w, x, y, z), 0x90 centre 1 (xyz), 0xA8 radius 1,
#   0xB0 centre 2 (xyz), 0xC8 radius 2 – the V7 field order of GDAL dgnlib.
# Dimension (33): u32 point count at 0xB4; points as xyz doubles every 0x30
#   bytes from the first one inside the element range; text height at 0x98;
#   the displayed text follows the points as NUL-terminated strings.

_NO_DISPLAY_HEADER = {1, 5, 8, 9, 10, 39, 57, 63, 66, 90, 91, 92, 93, 95, 96, 97, 98, 99}
_TAG = 37
_CONE = 23
_DIMENSION = 33


def _v8_range(raw):
    if len(raw) < 0x68:
        return None
    low = struct.unpack_from("<3q", raw, 0x38)
    extent = struct.unpack_from("<3q", raw, 0x50)
    if not any(low) and not any(extent):
        return None
    return low, extent


class _Units:
    """UOR → document units; the offset is calibrated from decoded elements."""

    def __init__(self, model):
        props = model.get("props") or {}
        self.per_master = float(props.get("dgn.uor_per_master") or 1.0) or 1.0
        self.offset = [0.0, 0.0, 0.0]
        samples = [[], [], []]
        for entity in _walk(model["entities"]):
            kind = entity["kind"]
            points = []
            if kind["type"] == "line":
                points = [kind["start"], kind["end"]]
            elif kind["type"] == "point":
                points = [kind["position"]]
            elif kind["type"] == "polyline":
                points = [vertex["position"] for vertex in kind["vertices"]]
            raw = (entity.get("raw") or {}).get("bytes")
            limits = _v8_range(bytes(raw)) if raw and points else None
            if limits is None:
                continue
            for axis, name in enumerate("xyz"):
                samples[axis].append(min(p[name] for p in points) - limits[0][axis] / self.per_master)
        for axis, values in enumerate(samples):
            if values:
                values.sort()
                self.offset[axis] = values[len(values) // 2]

    def point(self, values):
        values = list(values) + [0.0] * (3 - len(values))
        return {name: values[axis] / self.per_master + self.offset[axis] for axis, name in enumerate("xyz")}

    def length(self, value):
        return value / self.per_master


def _walk(entities):
    for entity in entities:
        yield entity
        if entity["kind"]["type"] == "group":
            yield from _walk(entity["kind"]["children"])


def _within_range(values, limits, tolerance=2.0):
    low, extent = limits
    return all(
        math.isfinite(value) and low[axis] - tolerance <= value <= low[axis] + extent[axis] + tolerance
        for axis, value in enumerate(values)
    )


def _strings(raw, start, end):
    texts = []
    for match in re.finditer(rb"([\x20-\x7e\xa0-\xff]+)\x00", raw[start:end]):
        chunk = match.group(1)
        # Tekstissä on oltava ASCII-kirjain tai -numero; yksittäiset korkeat
        # tavut ovat liukulukujen (esim. -1.0 = ... f0 bf) jäänteitä.
        if not re.search(rb"[0-9A-Za-z]", chunk) or sum(byte >= 0x80 for byte in chunk) * 2 > len(chunk):
            continue
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            text = chunk.decode("cp1252", errors="replace")
        if text.strip() and text not in texts:
            texts.append(text.strip())
    return texts


def _vertex(point):
    return {"position": point, "bulge": 0.0, "start_width": 0.0, "end_width": 0.0}


def _dimension(raw, limits, units, is_3d):
    """Dimension/leader → its line through the definition points and its text."""
    size = 3 if is_3d else 2
    attributes = struct.unpack_from("<I", raw, 8)[0] * 2 or len(raw)
    last = min(attributes, len(raw)) - 8 * size
    hits = [offset for offset in range(0x68, last + 1, 8)
            if _within_range(struct.unpack_from(f"<{size}d", raw, offset), limits)]
    if not hits:
        return None
    count = struct.unpack_from("<I", raw, 0xB4)[0] if len(raw) >= 0xB8 else 0
    start = hits[0]
    offsets = []
    for stride in sorted({later - start for later in hits[1:] if later - start >= 8 * size}):
        candidate = [start + stride * index for index in range(count)] if 1 <= count <= 256 else []
        if candidate and candidate[-1] <= last and all(offset in hits for offset in candidate):
            offsets = candidate
            break
    if not offsets:
        for offset in hits:
            if not offsets or offset >= offsets[-1] + 8 * size:
                offsets.append(offset)
    points = []
    for offset in offsets:
        point = units.point(struct.unpack_from(f"<{size}d", raw, offset))
        if not points or point != points[-1]:
            points.append(point)
    texts = _strings(raw, offsets[-1] + 8 * size, attributes)
    height = units.length(struct.unpack_from("<d", raw, 0x98)[0]) if len(raw) >= 0xA0 else 0.0
    diagonal = units.length(math.hypot(limits[1][0], limits[1][1])) or 1.0
    if not (math.isfinite(height) and 0 < height <= diagonal):
        height = max(diagonal / 20.0, 0.1)
    children = []
    if len(points) >= 2:
        children.append({"type": "polyline", "vertices": [_vertex(point) for point in points],
                         "closed": False, "normal": {"x": 0.0, "y": 0.0, "z": 1.0}})
    elif points:
        children.append({"type": "point", "position": points[0]})
    if texts:
        # Teksti istuu viimeisen janan päällä, kuten MicroStationin nimiöviivassa,
        # ja käännetään luettavaksi (ei ylösalaisin).
        base, tip = (points[-2], points[-1]) if len(points) >= 2 else (points[0], points[0])
        angle = math.atan2(tip["y"] - base["y"], tip["x"] - base["x"])
        if math.cos(angle) < -1e-9:
            base, tip, angle = tip, base, angle + math.pi
        lift = 0.25 * height
        position = {"x": base["x"] - math.sin(angle) * lift, "y": base["y"] + math.cos(angle) * lift,
                    "z": base["z"]}
        children.append({"type": "text", "position": position, "end_point": None, "height": height,
                         "rotation": math.atan2(math.sin(angle), math.cos(angle)), "width_factor": 1.0,
                         "oblique": 0.0, "value": " / ".join(texts), "style": None, "halign": "left",
                         "valign": "baseline", "normal": {"x": 0.0, "y": 0.0, "z": 1.0}})
    return children or None


def _rotate_z_axis(quaternion):
    w, x, y, z = quaternion
    return (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))


def _hull(points):
    unique = {}
    for point in points:
        key = (round(point["x"], 6), round(point["y"], 6))
        if key not in unique or point["z"] > unique[key]["z"]:
            unique[key] = point
    ordered = sorted(unique.values(), key=lambda p: (p["x"], p["y"]))
    if len(ordered) < 3:
        return ordered

    def cross(o, a, b):
        return (a["x"] - o["x"]) * (b["y"] - o["y"]) - (a["y"] - o["y"]) * (b["x"] - o["x"])

    lower, upper = [], []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _cone(raw, limits, units):
    """Cone/cylinder (e.g. a manhole) → its footprint seen from above."""
    if len(raw) < 0xD0:
        return None
    quaternion = struct.unpack_from("<4d", raw, 0x70)
    centres = [struct.unpack_from("<3d", raw, 0x90), struct.unpack_from("<3d", raw, 0xB0)]
    radii = [struct.unpack_from("<d", raw, 0xA8)[0], struct.unpack_from("<d", raw, 0xC8)[0]]
    largest = max(limits[1]) + 2.0
    if not all(_within_range(centre, limits) for centre in centres) or \
            not all(math.isfinite(r) and 0 <= r <= largest for r in radii) or not any(radii):
        return None
    axis = [b - a for a, b in zip(*centres)]
    length = math.sqrt(sum(value * value for value in axis))
    normal = [value / length for value in axis] if length > 1e-9 else list(_rotate_z_axis(quaternion))
    helper = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = [normal[1] * helper[2] - normal[2] * helper[1], normal[2] * helper[0] - normal[0] * helper[2],
         normal[0] * helper[1] - normal[1] * helper[0]]
    u_length = math.sqrt(sum(value * value for value in u))
    u = [value / u_length for value in u]
    v = [normal[1] * u[2] - normal[2] * u[1], normal[2] * u[0] - normal[0] * u[2],
         normal[0] * u[1] - normal[1] * u[0]]
    samples = []
    for centre, radius in zip(centres, radii):
        for step in range(64):
            angle = 2 * math.pi * step / 64
            samples.append(units.point([centre[i] + radius * (math.cos(angle) * u[i] + math.sin(angle) * v[i])
                                        for i in range(3)]))
    ring = _hull(samples)
    if len(ring) < 3:
        return None
    return [{"type": "polygon", "exterior": ring + [ring[0]], "interiors": []}]


def _replace(entity, kinds):
    if len(kinds) == 1:
        entity["kind"] = kinds[0]
        return
    entity["kind"] = {"type": "group", "group_kind": "other", "name": None, "origin": None,
                      "children": [dict(entity, kind=kind, id=None, attributes=[]) for kind in kinds]}


def _reconstruct_unknown(data):
    """Give geometry to elements cadkit leaves as Unknown; returns counts per type."""
    counts = {}
    if data.get("format") not in (None, "dgn_v8"):
        return counts
    for model in data["models"]:
        units = _Units(model)
        for entity in list(_walk(model["entities"])):
            raw = entity.get("raw")
            if entity["kind"]["type"] != "unknown" or not raw:
                continue
            code = raw.get("type_code")
            data_bytes = bytes(raw.get("bytes") or b"")
            limits = _v8_range(data_bytes)
            if code in _NO_DISPLAY_HEADER or code == _TAG or limits is None:
                continue
            kinds = None
            try:
                if code == _CONE:
                    kinds = _cone(data_bytes, limits, units)
                elif code == _DIMENSION:
                    kinds = _dimension(data_bytes, limits, units, bool(model.get("is_3d")))
            except struct.error:
                kinds = None
            how = "decoded"
            if not kinds:
                # Tuntematon graafinen elementti säilyy vähintään sijaintinaan.
                low, extent = limits
                kinds = [{"type": "point", "position": units.point(
                    [low[axis] + extent[axis] / 2.0 for axis in range(3)])}]
                how = "located"
            _replace(entity, kinds)
            counts[(code, how)] = counts.get((code, how), 0) + 1
    return counts


def _strip_raw(entities):
    for entity in entities:
        entity.pop("raw", None)
        if entity["kind"]["type"] == "group":
            _strip_raw(entity["kind"]["children"])


def _reconstruction_note(path, counts):
    labels = {_DIMENSION: "mitoitusta/nimiöviivaa (tyyppi 33) viivoina ja teksteinä",
              _CONE: "kartiota/sylinteriä (tyyppi 23, esim. kaivot) pohja-alueina"}
    decoded = [f"{count} {labels.get(code, f'tyypin {code} elementtiä')}"
               for (code, how), count in sorted(counts.items()) if how == "decoded"]
    located = [f"{count} tyypin {code} elementtiä pisteinä (geometriaa ei voitu purkaa)"
               for (code, how), count in sorted(counts.items()) if how == "located"]
    parts = decoded + located
    return f"DGN ({Path(path).name}): tuotiin {', '.join(parts)}." if parts else ""


def readable_source(path, folder, notes=None):
    """Use the native reader regardless of GDAL DGNv8 availability."""
    kit = _cadkit()
    document = kit.read(str(path), keep_raw=True)
    data = document.to_dict()
    counts = _reconstruct_unknown(data)
    for model in data["models"]:
        _strip_raw(model["entities"])
        for entity in model["entities"]:
            _shapes(entity)
    for block in data["blocks"]:
        _strip_raw(block["entities"])
        for entity in block["entities"]:
            _shapes(entity)
    note = _reconstruction_note(path, counts)
    if note and notes is not None:
        notes.append(note)
    handled = {f"dgn.unknown_element.type_{code}" for code, _how in counts}
    remaining = [w for w in document.warnings if w.get("code") not in handled]
    if remaining:
        detail = "; ".join(dict.fromkeys(w["message"] for w in remaining))
        if notes is not None:
            notes.append(f"DGN-lukijan huomautukset ({Path(path).name}): {detail}")
        else:
            import warnings
            warnings.warn(detail, RuntimeWarning, stacklevel=2)
    output = Path(folder) / "dgn.dxf"
    # cadkit already emits CRLF: write bytes to avoid CRCRLF on Windows.
    output.write_bytes(kit.Document.from_json(json.dumps(data, ensure_ascii=False)).to_dxf().encode("utf-8"))
    return output


def _point(part, index=0):
    x, y, z = part.GetPoint(index)
    if not part.Is3D():
        z = 0.0
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise RuntimeError("DGN-kohteessa on puuttuva tai virheellinen koordinaatti.")
    return {"x": x, "y": y, "z": z}


def _kind(part):
    from osgeo import ogr
    kind = ogr.GT_Flatten(part.GetGeometryType())
    if kind == ogr.wkbPoint:
        return {"type": "point", "position": _point(part)}
    if kind == ogr.wkbLineString:
        return {"type": "polyline", "vertices": [
            {"position": _point(part, i), "bulge": 0.0, "start_width": 0.0, "end_width": 0.0}
            for i in range(part.GetPointCount())], "closed": False, "normal": {"x": 0.0, "y": 0.0, "z": 1.0}}
    if kind == ogr.wkbPolygon:
        rings = [[_point(part.GetGeometryRef(r), i) for i in range(part.GetGeometryRef(r).GetPointCount())]
                 for r in range(part.GetGeometryCount())]
        return {"type": "polygon", "exterior": rings[0], "interiors": rings[1:]}
    raise RuntimeError("DGN-vienti tukee pisteitä, viivoja ja tasomaisia alueita.")


def _value(feature, name, default=None):
    from qgis.core import QgsVariantUtils
    if feature.fields().indexOf(name) >= 0:
        value = feature[name]
        if not QgsVariantUtils.isNull(value):
            return value
    return default


def write_dgn(layers, path, crs, project, notes=None):
    from osgeo import ogr
    from qgis.core import QgsCoordinateTransform, QgsFeatureRequest, QgsUnitTypes
    from . import cad
    path = Path(path)
    if path.exists():
        raise RuntimeError(f"DGN-tiedosto on jo olemassa: {path}")
    if not crs.isValid() or any(not layer.crs().isValid() for layer in layers):
        raise RuntimeError("DGN-vienti vaatii tunnetun lähtö- ja kohdekoordinaatiston.")
    if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
        raise RuntimeError("DGN V8 -vienti tarvitsee metrisen kohdekoordinaatiston. Valitse esimerkiksi EPSG:3067.")
    kit = _cadkit()
    seed = (VENDOR / "seed3d-metric.dgn").read_bytes()
    data = kit.read(seed).to_dict()
    data.update(layers=[], blocks=[], linetypes=[], text_styles=[], props={}, warnings=[])
    model = data["models"][0]
    model.update(entities=[], props={})
    names = set()
    sidecars = (path.with_suffix(".prj"), Path(str(path) + ".muuntaja.json"))
    existing = {candidate for candidate in sidecars if candidate.exists()}
    if existing:
        raise RuntimeError(f"DGN-viennin oheistiedosto on jo olemassa: {next(iter(existing))}")
    try:
        for layer in layers:
            transform = QgsCoordinateTransform(layer.crs(), crs, project) if layer.crs() != crs else None
            request = QgsFeatureRequest().setFilterFids(layer.selectedFeatureIds()) if layer.selectedFeatureCount() else QgsFeatureRequest()
            for feature in layer.getFeatures(request):
                geometry = feature.geometry()
                if geometry.isNull() or geometry.isEmpty():
                    raise RuntimeError("DGN-viennissä on tyhjä geometria.")
                if transform is not None:
                    geometry.transform(transform)
                name = str(_value(feature, "cad_layer", layer.name()))
                if name not in names:
                    names.add(name)
                    data["layers"].append({"name": name, "id": None, "color": {"type": "by_layer"}, "linetype": None,
                                           "lineweight": {"type": "by_layer"}, "visible": True, "frozen": False,
                                           "locked": False, "plottable": True, "description": None, "props": {}})
                for part in cad._flatten(ogr.CreateGeometryFromWkb(bytes(geometry.asWkb()))):
                    kind = _kind(part)
                    text = _value(feature, "text", "")
                    if text and kind["type"] == "point":
                        kind = {"type": "text", "position": kind["position"], "end_point": None,
                                "value": str(text), "height": float(_value(feature, "text_size", 2.5)),
                                "rotation": math.radians(float(_value(feature, "text_angle", 0))),
                                "width_factor": 1.0, "oblique": 0.0, "style": None,
                                "halign": "left", "valign": "baseline", "normal": {"x": 0.0, "y": 0.0, "z": 1.0}}
                    model["entities"].append({"id": None, "layer": name, "color": {"type": "by_layer"},
                                               "linetype": None, "lineweight": {"type": "by_layer"}, "visible": True,
                                               "kind": kind, "attributes": [], "props": {}})
        if not model["entities"]:
            raise RuntimeError("Valituilla tasoilla ei ole vietäviä kohteita.")
        document = kit.Document.from_json(json.dumps(data, ensure_ascii=False, allow_nan=False))
        output = document.to_dgn(seed, json.dumps({
            "clear_seed_model": True, "preserve_seed_rasters": False, "preserve_seed_controls": False,
        }))
        path.write_bytes(output)
        sidecars[0].write_text(crs.toWkt(), encoding="utf-8")
        sidecars[1].write_text(json.dumps({"crs": crs.toWkt(), "version": "V8"}, ensure_ascii=False), encoding="utf-8")
        if notes is not None:
            notes.append(f"DGN V8: {path.name}. Geometriat, korkeudet, CAD-tasonimet ja CAD-tekstikohteet tallennettiin.")
    except Exception:
        for candidate in (path,) + sidecars:
            if candidate not in existing:
                candidate.unlink(missing_ok=True)
        raise
    return path
