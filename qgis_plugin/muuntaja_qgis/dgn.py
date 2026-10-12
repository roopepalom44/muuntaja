"""Self-contained DGN V7/V8 reading and V8 writing with bundled cadkit."""

import importlib.util
import json
import math
import platform
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


def readable_source(path, folder, notes=None):
    """Use the native reader regardless of GDAL DGNv8 availability."""
    kit = _cadkit()
    document = kit.read(str(path))
    data = document.to_dict()
    for model in data["models"]:
        for entity in model["entities"]:
            _shapes(entity)
    for block in data["blocks"]:
        for entity in block["entities"]:
            _shapes(entity)
    if document.warnings:
        detail = "; ".join(dict.fromkeys(w["message"] for w in document.warnings))
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
