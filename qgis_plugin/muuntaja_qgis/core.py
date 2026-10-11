"""Native QGIS import/export operations. No ArcPy dependency."""

import gc
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import operator
from collections import Counter
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField,
    QgsFields, QgsGeometry, QgsProject, QgsRasterLayer, QgsVectorFileWriter,
    QgsVectorLayer, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

VECTOR_EXTENSIONS = {".gpkg", ".geojson", ".json", ".kml", ".kmz", ".gpx", ".dwg", ".dxf", ".shp"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".jp2", ".img"}
WORLD_FILES = {".pgw", ".pngw", ".jgw", ".jpgw", ".jpegw", ".wld"}
DRIVERS = {"GPKG": ("GPKG", ".gpkg"), "GeoJSON": ("GeoJSON", ".geojson"),
           "Shapefile": ("ESRI Shapefile", ".shp"), "KML": ("LIBKML", ".kml"),
           "KMZ": ("LIBKML", ".kmz"), "DXF": ("DXF", ".dxf")}

_operation_project = ContextVar("muuntaja_operation_project", default=None)


def _project():
    return _operation_project.get() or QgsProject.instance()


class OperationCanceled(Exception):
    pass


def safe_name(name):
    name = re.sub(r"[^\w-]+", "_", str(name), flags=re.UNICODE).strip("_-")
    return name[:80] or "layer"


def gdb_safe_name(name):
    name = safe_name(name).replace("-", "_")
    if name[0].isdigit() or name.casefold() in {"select", "table", "where", "from", "order"}:
        name = "_" + name
    return name[:80]


def _dispose(layer):
    if layer is not None:
        from qgis.PyQt import sip
        if not sip.isdeleted(layer):
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                # OGR iterators return handles to QGIS's connection pool. Invalidate
                # that layer's pool before deletion so Windows releases the file.
                layer.dataProvider().reloadData()
            sip.delete(layer)


def _workspace_names(destination):
    if not destination.exists():
        return set()
    probe = QgsVectorLayer(str(destination), "probe", "ogr")
    try:
        return {parts[1] for item in probe.dataProvider().subLayers()
                if len(parts := item.split("!!::!!")) > 1}
    finally:
        _dispose(probe)


def classify_finnish_xy(x, y):
    if 19 <= x <= 32.5 and 59 <= y <= 71.5:
        return 4326
    if 2000000 <= x <= 3700000 and 8000000 <= y <= 11800000:
        return 3857
    if not 6400000 <= y <= 7900000:
        return None
    if 400000 <= x <= 600000:
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


def inferred_crs(layer, path=None):
    try:
        extent = layer.extent()
        code = classify_finnish_xy(extent.center().x(), extent.center().y())
        if code:
            return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    except Exception:
        pass
    if path and Path(path).suffix.lower() in {".dwg", ".dxf"}:
        observed = Counter()
        for index, feature in enumerate(layer.getFeatures()):
            if index >= 256:
                break
            geometry = feature.geometry()
            if geometry.isNull() or geometry.isEmpty():
                continue
            center = geometry.boundingBox().center()
            # Ohita vain origon selitteet. Muu epäselvä geometria vähentää varmuutta.
            if abs(center.x()) < 1000 and abs(center.y()) < 1000:
                continue
            observed[classify_finnish_xy(center.x(), center.y())] += 1
        if observed:
            code, count = observed.most_common(1)[0]
            if code and count / observed.total() >= 0.8:
                return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    if path and "etrs89" in str(path).casefold():
        return QgsCoordinateReferenceSystem("EPSG:3067")
    return None


def _center_in_finland(layer, crs):
    try:
        point = QgsCoordinateTransform(
            crs, QgsCoordinateReferenceSystem("EPSG:4326"), _project()
        ).transform(layer.extent().center())
        return (math.isfinite(point.x()) and math.isfinite(point.y())
                and 18 <= point.x() <= 33 and 59 <= point.y() <= 72)
    except Exception:
        return False


def assign_source_crs(layer, path, source_crs=None):
    """Assign a known CRS or stop when its location conflicts with Finnish coordinates."""
    if source_crs and source_crs.isValid():
        layer.setCrs(source_crs)
        return
    guessed = inferred_crs(layer, path)
    current = layer.crs()
    if current.isValid():
        if (current.authid() in {"EPSG:4326", "EPSG:3857"}
                and guessed and guessed.isValid() and current != guessed
                and _center_in_finland(layer, guessed)
                and not _center_in_finland(layer, current)):
            raise RuntimeError(
                f"Tason koordinaatisto on {current.authid()}, mutta koordinaatit näyttävät "
                f"järjestelmältä {guessed.authid()}. Aseta oikea lähtö-CRS "
                "lisäasetusten Lähtö-CRS (pakota) -kentässä.")
        return
    if guessed:
        layer.setCrs(guessed)
        return
    raise RuntimeError("Lähtökoordinaatistoa ei tunnistettu. Aseta lähtö-CRS lisäasetuksissa.")


def _ensure_project_crs(project, layer):
    """Turn on coordinate transformations in projects saved without a CRS."""
    if not layer.crs().isValid():
        raise RuntimeError(f"Tason koordinaatistoa ei tunnistettu: {layer.name()}")
    if not project.crs().isValid():
        project.setCrs(layer.crs())


def _add_project_layer(project, layer, add_to_legend=True):
    _ensure_project_crs(project, layer)
    project.addMapLayer(layer, add_to_legend)


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Vapaata tiedostonimeä ei löytynyt: {path}")


def has_georeference(path, names=None):
    path = Path(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return True
    candidates = [path.with_suffix(ext) for ext in WORLD_FILES] + [Path(str(path) + ".aux.xml")]
    if names is not None:
        return any(candidate.name.casefold() in names for candidate in candidates)
    return any(candidate.exists() for candidate in candidates)


def _scan_directory(root):
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as entries:
            entries = sorted(entries, key=lambda item: item.name.casefold())
        names = {entry.name.casefold() for entry in entries}
        files = []
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                if not entry.name.startswith(".") and entry.name not in {"__pycache__", "node_modules"}:
                    stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                files.append(Path(entry.path))
        yield names, files


def scan_inputs(paths, progress=None):
    """Expand folders recursively, ignore Shapefile sidecars and unlocated images."""
    found, seen = [], set()
    for entry in paths:
        root = Path(entry)
        batches = _scan_directory(root) if root.is_dir() else [(None, [root])]
        for names, candidates in batches:
            if progress:
                progress(1, 1, f"Skannataan: {root}")
            for path in candidates:
                if path.suffix.lower() not in VECTOR_EXTENSIONS | RASTER_EXTENSIONS | {".dfsu"}:
                    continue
                if names is None and not path.is_file():
                    continue
                if not has_georeference(path, names):
                    continue
                key = os.path.normcase(os.path.abspath(str(path)))
                if key not in seen:
                    seen.add(key)
                    found.append(path)
    return found


def raster_group(path):
    for part in reversed(path.parts[:-1]):
        if part.lower().startswith("taustakartta_"):
            return part
    return path.parent.name


def _shapefile_converter(layer):
    """Preserve columns with unique DBF names and explicit text truncation."""
    from qgis.core import QgsMessageLog
    fields = [QgsField(field) for field in layer.fields()]
    used, widths = set(), []
    for field in fields:
        name = str(field.name()).translate(str.maketrans("äöåÄÖÅ", "aoaAOA"))
        base = re.sub(r"[^A-Za-z0-9_]", "_", name)[:10] or "field"
        if base[0].isdigit():
            base = "f_" + base[:8]
        name, number = base, 2
        while name.casefold() in used:
            suffix = f"_{number}"
            name = base[:10-len(suffix)] + suffix
            number += 1
        used.add(name.casefold())
        field.setName(name)
        widths.append(min(field.length() or 254, 254) if field.type() == QVariant.String else 32)
    if len(fields) > 255:
        raise ValueError("Shapefile tukee enintään 255 kenttää; käytä GeoPackagea.")
    original = list(widths)
    for limit in (80, 50, 1):
        if 1 + sum(widths) <= 3900:
            break
        widths = [min(width, limit) if field.type() == QVariant.String else width
                  for field, width in zip(fields, widths)]
    if 1 + sum(widths) > 3900:
        raise ValueError("Shapefilen riviraja ylittyy; käytä GeoPackagea sarakkeiden säilyttämiseen.")
    for field, width in zip(fields, widths):
        if field.type() == QVariant.String:
            field.setLength(width)
    if widths != original:
        QgsMessageLog.logMessage("Shapefile: tekstikenttiä lyhennetään rivirajan vuoksi. "
                                "Käytä GeoPackagea pitkien arvojen säilyttämiseen.", "Muuntaja")

    class Converter(QgsVectorFileWriter.FieldValueConverter):
        def fieldDefinition(self, field):
            return fields[layer.fields().indexFromName(field.name())]

        def convert(self, index, value):
            if fields[index].type() == QVariant.String and isinstance(value, str):
                # GDAL laskee UTF-8-tekstin leveyden tavuina.
                return value.encode("utf-8")[:widths[index]].decode("utf-8", errors="ignore")
            return value

        def clone(self):
            return Converter()

    return Converter()


def _write_vector(layer, path, driver, layer_name=None, target_crs=None, append=False, feature_filter=None, progress=None):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    converter = _shapefile_converter(layer) if driver == "ESRI Shapefile" else None
    if converter is not None:
        options.fieldValueConverter = converter
    if driver == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    if layer_name:
        options.layerName = layer_name
    if append:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    if target_crs and target_crs.isValid() and layer.crs() != target_crs:
        from qgis.core import QgsCoordinateTransform
        options.ct = QgsCoordinateTransform(layer.crs(), target_crs, _project())
    fields = QgsFields()
    for field in layer.fields():
        fields.append(converter.fieldDefinition(field) if converter else field)
    # The writer owns no source-layer reference. Explicitly close the iterator;
    # the static exporter in QGIS 3.44 can retain pooled OGR read handles.
    options.fieldValueConverter = None
    output_crs = target_crs if target_crs and target_crs.isValid() else layer.crs()
    writer = QgsVectorFileWriter.create(str(path), fields, layer.wkbType(), output_crs,
                                        _project().transformContext(), options)
    iterator = None
    try:
        if writer.hasError() != QgsVectorFileWriter.NoError:
            raise RuntimeError(writer.errorMessage())
        iterator = layer.getFeatures()
        batch = []
        for index, source in enumerate(iterator):
            if progress and index % 1000 == 0:
                progress(index + 1, max(layer.featureCount(), 1), layer.name())
            if feature_filter is not None and not feature_filter(source):
                continue
            feature = QgsFeature(fields)
            geometry = QgsGeometry(source.geometry())
            if target_crs and target_crs.isValid() and layer.crs() != target_crs:
                if geometry.transform(options.ct) != 0:
                    raise RuntimeError("Geometrian projisointi epäonnistui")
            feature.setGeometry(geometry)
            feature.setAttributes([converter.convert(i, value) if converter else value
                                   for i, value in enumerate(source.attributes())])
            batch.append(feature)
            if len(batch) >= 1000:
                if not writer.addFeatures(batch):
                    raise RuntimeError(writer.errorMessage())
                batch.clear()
        if batch and not writer.addFeatures(batch):
            raise RuntimeError(writer.errorMessage())
    finally:
        if iterator is not None:
            iterator.close()
        del writer
    return path


def _write_combined_dxf(layers, path, target_crs=None, progress=None):
    from osgeo import ogr
    if not layers:
        raise ValueError("Valitse vähintään yksi vektoritaso.")
    target_crs = target_crs or layers[0].crs()
    if not target_crs.isValid() or any(not layer.crs().isValid() for layer in layers):
        raise ValueError("CAD-vienti vaatii tunnetun koordinaatiston kaikille tasoille.")
    driver = ogr.GetDriverByName("DXF")
    datasource = driver.CreateDataSource(str(path))
    if datasource is None:
        raise RuntimeError("DXF-tiedostoa ei voitu luoda")
    target = datasource.CreateLayer("entities", geom_type=ogr.wkbUnknown)
    if target is None:
        raise RuntimeError("DXF-tasoa ei voitu luoda")
    layer_field = target.GetLayerDefn().GetFieldIndex("Layer")
    for index, layer in enumerate(layers, 1):
        if progress:
            progress(index, len(layers), layer.name())
        transform = QgsCoordinateTransform(layer.crs(), target_crs, _project()) if layer.crs() != target_crs else None
        for source in layer.getFeatures():
            geometry = QgsGeometry(source.geometry())
            if geometry.isNull() or geometry.isEmpty():
                continue
            if transform and geometry.transform(transform) != 0:
                raise RuntimeError(f"CAD-geometrian projisointi epäonnistui: {layer.name()}")
            feature = ogr.Feature(target.GetLayerDefn())
            feature.SetGeometry(ogr.CreateGeometryFromWkb(bytes(geometry.asWkb())))
            if layer_field >= 0:
                feature.SetField(layer_field, safe_name(layer.name())[:31])
            if target.CreateFeature(feature) != 0:
                raise RuntimeError(f"DXF-geometrian kirjoitus epäonnistui: {layer.name()}")
    target = None
    datasource = None
    return path


def find_oda_converter():
    candidates = [shutil.which("ODAFileConverter"),
                  Path("C:/Program Files/ODA/ODAFileConverter/ODAFileConverter.exe"),
                  Path("C:/Program Files/ODA/ODAFileConverter/ODAFileConverter_QT5.exe")]
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def find_libredwg_converter(name):
    """Prefer the converter shipped with the Windows plugin package."""
    bundled = Path(__file__).parent / "libredwg" / f"{name}.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name) or ""


def _export_dwg(layers, folder, combined, converter):
    oda = converter or find_oda_converter()
    if not oda:
        raise RuntimeError("DWG-vienti vaatii asennetun ODA File Converterin. Ohjelma tunnistetaan automaattisesti; DXF-vienti toimii ilman sitä.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="muuntaja_dwg_") as temp:
        input_folder = Path(temp) / "dxf"
        output_folder = Path(temp) / "dwg"
        input_folder.mkdir()
        output_folder.mkdir()
        if combined:
            dxfs = [_write_combined_dxf(layers, input_folder / "muuntaja_vienti.dxf")]
        else:
            dxfs = []
            for layer in layers:
                path = unique_path(input_folder / f"{safe_name(layer.name())}.dxf")
                dxfs.append(_write_vector(layer, path, "DXF"))
        command = [str(oda), str(input_folder), str(output_folder),
                   "ACAD2018", "DWG", "0", "1", "*.DXF"]
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ODA File Converter epäonnistui (exit {result.returncode}): {result.stderr[-500:]}")
        written = []
        for dxf in dxfs:
            produced = output_folder / f"{dxf.stem}.dwg"
            if not produced.is_file() or produced.stat().st_size < 512:
                raise RuntimeError(f"ODA ei tuottanut DWG-tiedostoa: {dxf.name}")
            probe = QgsVectorLayer(str(produced), produced.stem, "ogr")
            try:
                if not probe.isValid():
                    raise RuntimeError(f"ODA:n DWG-tiedosto ei avaudu QGISissä: {produced.name}")
            finally:
                _dispose(probe)
            target = unique_path(folder / produced.name)
            shutil.move(str(produced), str(target))
            written.append(str(target))
        return ([written[0] for _ in layers] if combined else written), []


def _validate_vector_file(path):
    extension = path.suffix.lower()
    if extension == ".shp":
        with os.scandir(path.parent) as entries:
            names = {entry.name.casefold() for entry in entries if entry.is_file()}
        missing = [ext for ext in (".dbf", ".shx") if path.with_suffix(ext).name.casefold() not in names]
        if missing:
            raise ValueError("Shapefilen sivutiedosto puuttuu: " + ", ".join(missing))
    elif extension in {".geojson", ".json"}:
        with path.open(encoding="utf-8-sig") as stream:
            json.load(stream)
    elif extension in {".gpx", ".kml"}:
        from xml.etree import ElementTree
        ElementTree.parse(path)
    elif extension == ".kmz":
        from zipfile import ZipFile
        with ZipFile(path) as archive:
            if archive.testzip() is not None or not any(name.lower().endswith(".kml") for name in archive.namelist()):
                raise ValueError("KMZ-arkisto on virheellinen tai KML-dokumentti puuttuu")


def _open_vector_layers(path):
    """QGIS/OGR handles CAD, GPX, KMZ and multi-layer GeoPackages."""
    _validate_vector_file(path)
    probe = QgsVectorLayer(str(path), path.stem, "ogr")
    if not probe.isValid():
        _dispose(probe)
        raise RuntimeError(f"Vektorimuotoa ei voitu avata: {path}")
    sublayers = probe.dataProvider().subLayers()
    if not sublayers:
        return [probe]
    layers = []
    cad = path.suffix.lower() in {".dwg", ".dxf"}
    for item in sublayers:
        parts = item.split("!!::!!")
        if len(parts) < 2:
            continue
        name = parts[1]
        uri = f"{path}|layername={name}"
        if cad and len(parts) > 3 and parts[3]:
            uri += f"|geometrytype={parts[3]}"
            name = f"{name}_{parts[3]}"
        layer = QgsVectorLayer(uri, name, "ogr")
        if layer.isValid():
            layers.append(layer)
        else:
            _dispose(layer)
    if layers:
        from qgis.PyQt import sip
        sip.delete(probe)
        return layers
    return [probe]


def _convert_dwg_to_dxf(path, converter, temporary_folder):
    """Use ODA when this QGIS build cannot read a newer DWG directly."""
    converter = Path(converter)
    if not converter.is_file():
        raise RuntimeError("ODA File Converterin .exe-tiedostoa ei löytynyt")
    source_folder = Path(temporary_folder) / "dwg"
    output_folder = Path(temporary_folder) / "dxf"
    source_folder.mkdir()
    output_folder.mkdir()
    shutil.copy2(path, source_folder / path.name)
    command = [str(converter), str(source_folder), str(output_folder),
               "ACAD2018", "DXF", "0", "1", "*.DWG"]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ODA:n DWG–DXF-muunnos epäonnistui: {result.stderr[-500:] or result.stdout[-500:]}")
    converted = output_folder / f"{path.stem}.dxf"
    if not converted.is_file() or converted.stat().st_size == 0:
        raise RuntimeError(f"ODA ei tuottanut DXF-tiedostoa: {path.name}")
    return converted


def _convert_dwg_with_libredwg(path, converter, temporary_folder):
    converted = Path(temporary_folder) / f"{path.stem}.dxf"
    result = subprocess.run([str(converter), "-o", str(converted), str(path)],
                            capture_output=True, text=True, errors="replace", timeout=600)
    if result.returncode != 0 or not converted.is_file() or converted.stat().st_size == 0:
        raise RuntimeError(f"LibreDWG:n DWG–DXF-muunnos epäonnistui: {result.stderr[-500:]}")
    return converted


def _dwg_version(path):
    with Path(path).open("rb") as source:
        return source.read(6).decode("ascii", errors="replace")


def _dfsu_matches(value, operator, expected):
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


def _dfsu_wkb(points):
    if len(points) == 1:
        return struct.pack("<BIdd", 1, 1, *points[0])
    if len(points) == 2:
        return struct.pack("<BII", 1, 2, 2) + b"".join(struct.pack("<dd", *point) for point in points)
    ring = list(points)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return struct.pack("<BIII", 1, 3, 1, len(ring)) + b"".join(struct.pack("<dd", *point) for point in ring)


class _DfsuWriter:
    """Write bounded feature batches in OGR transactions, including FileGDB."""
    def __init__(self, path, name, fields, crs, geometry_type):
        from osgeo import ogr, osr
        self.ogr = ogr
        driver = ogr.GetDriverByName("OpenFileGDB" if path.suffix.lower() == ".gdb" else "GPKG")
        self.dataset = driver.Open(str(path), 1) if path.exists() else driver.CreateDataSource(str(path))
        if self.dataset is None:
            raise RuntimeError(f"DFSU-tallennuspaikkaa ei voitu avata: {path}")
        sr = osr.SpatialReference()
        sr.ImportFromWkt(crs.toWkt())
        options = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"] if path.suffix.lower() == ".gdb" else []
        self.layer = self.dataset.CreateLayer(name, sr, geometry_type, options=options)
        if self.layer is None:
            self.close()
            raise RuntimeError("DFSU-tasoa ei voitu luoda")
        self.name = self.layer.GetName()
        for index, field in enumerate(fields):
            definition = ogr.FieldDefn(field.name(), ogr.OFTInteger64 if index == 0 else ogr.OFTReal)
            if self.layer.CreateField(definition) != 0:
                self.close()
                raise RuntimeError(f"DFSU-kenttää ei voitu luoda: {field.name()}")

    def addFeatures(self, features):
        if self.dataset.StartTransaction(1) != 0:
            raise RuntimeError("DFSU-kirjoituksen transaktiota ei voitu aloittaa")
        try:
            for source in features:
                feature = self.ogr.Feature(self.layer.GetLayerDefn())
                for index, value in enumerate(source.attributes()):
                    # QgsFeature exposes nulls as QPyNullVariant as well as None.
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        feature.SetField(index, int(value) if index == 0 else float(value))
                feature.SetGeometry(self.ogr.CreateGeometryFromWkb(bytes(source.geometry().asWkb())))
                if self.layer.CreateFeature(feature) != 0:
                    raise RuntimeError("DFSU-kohteen kirjoitus epäonnistui")
                feature = None
            if self.dataset.CommitTransaction() != 0:
                raise RuntimeError("DFSU-transaktion tallennus epäonnistui")
        except Exception:
            self.dataset.RollbackTransaction()
            raise
        return True

    def errorMessage(self):
        return "DFSU-kirjoitus epäonnistui"

    def close(self):
        self.layer = None
        self.dataset = None


def _import_dfsu(path, destination, workspace, source_crs, target_crs, filter_column, filter_operator, filter_value,
                 existing_names=None, progress=None):
    try:
        import mikeio
    except ImportError as exc:
        raise RuntimeError("DFSU-tuonti vaatii mikeio-kirjaston QGISin Python-ympäristöön") from exc
    dataset = mikeio.read(str(path), time=0)
    geometry = dataset.geometry
    element_table = getattr(geometry, "element_table", None)
    node_coordinates = getattr(geometry, "node_coordinates", None)
    # Computing every element centroid allocates large temporary arrays in
    # mikeio. Mesh polygons use node coordinates and never need these centers.
    element_coordinates = getattr(geometry, "element_coordinates", None) if element_table is None else None
    if element_table is None and element_coordinates is None:
        raise RuntimeError("DFSU-elementtien geometriaa ei löytynyt")
    total = len(element_table) if element_table is not None else len(element_coordinates)
    item_names = [item.name for item in dataset.items]
    if filter_column and filter_column.casefold() not in {name.casefold() for name in item_names}:
        raise ValueError(f"DFSU-suodatinsaraketta ei löytynyt: {filter_column}")
    values = {}
    for name in item_names:
        array = dataset[name].to_numpy()
        if getattr(array, "ndim", 0) >= 2:
            array = array[0]
        values[name] = array.reshape(-1) if hasattr(array, "reshape") else array
    fields = QgsFields()
    fields.append(QgsField("element_id", QVariant.Int))
    field_names = []
    for name in item_names:
        field_name = safe_name(name)[:30]
        base, number = field_name, 2
        while field_name in field_names:
            field_name = f"{base[:26]}_{number}"
            number += 1
        field_names.append(field_name)
        fields.append(QgsField(field_name, QVariant.Double))
    sr = source_crs
    if sr is None:
        projection = str(getattr(geometry, "projection_string", "") or "")
        sr = QgsCoordinateReferenceSystem(projection)
        if not sr.isValid():
            sr = QgsCoordinateReferenceSystem.fromWkt(projection)
    if sr is None or not sr.isValid():
        raise RuntimeError("DFSU:n koordinaatistoa ei tunnistettu; anna lähtö-CRS")
    output_crs = target_crs if target_crs and target_crs.isValid() else sr
    transform = QgsCoordinateTransform(sr, output_crs, _project()) if output_crs != sr else None
    name = gdb_safe_name(path.stem) if destination.suffix.lower() == ".gdb" else safe_name(path.stem)
    if workspace:
        output_path = destination
        existing = existing_names if existing_names is not None else _workspace_names(destination)
        base, number = name, 2
        while name in existing:
            name = f"{base[:65]}_{number}"
            number += 1
    else:
        output_path = unique_path(destination / f"{name}.gpkg")
    from osgeo import ogr
    sizes = {len(nodes) for nodes in element_table} if element_table is not None else {1}
    types = {1 if size == 1 else 2 if size == 2 else 3 for size in sizes if size}
    if len(types) != 1:
        raise ValueError("DFSU sisältää eri geometriatyyppejä; taso on jaettava ennen tuontia.")
    geometry_type = {1: ogr.wkbPoint, 2: ogr.wkbLineString, 3: ogr.wkbPolygon}[types.pop()]
    written = 0
    matched = next((name for name in item_names if name.casefold() == filter_column.casefold()), None)
    indices = range(total)
    if matched:
        import numpy as np
        comparisons = {"=": operator.eq, "≠": operator.ne, ">": operator.gt, ">=": operator.ge,
                       "<": operator.lt, "<=": operator.le}
        if filter_operator in comparisons:
            expected = float(str(filter_value).replace(",", "."))
            column = np.asarray(values[matched], dtype=float)
            indices = np.flatnonzero(np.isfinite(column) & comparisons[filter_operator](column, expected))
        else:
            indices = np.flatnonzero([_dfsu_matches(value, filter_operator, filter_value) for value in values[matched]])
    writer = _DfsuWriter(output_path, name, fields, output_crs, geometry_type)
    name = writer.name
    batch = []
    try:
        for index in indices:
            index = int(index)
            if progress and written % 1000 == 0:
                progress(written + 1, max(len(indices), 1), path.name)
            if element_table is not None and node_coordinates is not None:
                points = [(float(node_coordinates[int(node)][0]), float(node_coordinates[int(node)][1]))
                          for node in element_table[index]]
            else:
                coord = element_coordinates[index]
                points = [(float(coord[0]), float(coord[1]))]
            if not points:
                continue
            geom = QgsGeometry()
            geom.fromWkb(_dfsu_wkb(points))
            if transform:
                geom.transform(transform)
            feature = QgsFeature(fields)
            attrs = [index + 1]
            for item_name in item_names:
                try:
                    number = float(values[item_name][index])
                    attrs.append(number if math.isfinite(number) else None)
                except (ValueError, TypeError):
                    attrs.append(None)
            feature.setAttributes(attrs)
            feature.setGeometry(geom)
            batch.append(feature)
            if len(batch) >= 1000:
                if not writer.addFeatures(batch):
                    raise RuntimeError(writer.errorMessage())
                batch.clear()
            written += 1
        if batch and not writer.addFeatures(batch):
            raise RuntimeError(writer.errorMessage())
    finally:
        writer.close()
    if not written:
        raise RuntimeError("DFSU-suodatus ei tuottanut kohteita")
    if workspace and existing_names is not None:
        existing_names.add(name)
    result = QgsVectorLayer(f"{output_path}|layername={name}", name, "ogr")
    if not result.isValid():
        _dispose(result)
        raise RuntimeError("DFSU-tulosta ei voitu avata")
    _add_project_layer(_project(), result)


def _add_raster_group(project, group_name, paths, destination, source_crs, failures=None, progress=None):
    """Validate one tile at a time and publish a new VRT before replacing layers."""
    from osgeo import gdal
    failures = failures if failures is not None else []
    group = project.layerTreeRoot().findGroup(group_name) or project.layerTreeRoot().addGroup(group_name)
    prior = [node.layer() for node in group.findLayers() if node.layer() is not None]
    existing = []
    for layer in prior:
        existing.extend(layer.customProperty("muuntaja/source_paths", []) or [layer.source()])
    combined = list(dict.fromkeys(existing + [str(path) for path in paths]))
    valid, crs = [], None
    for index, path in enumerate(combined, 1):
        if progress:
            progress(index, len(combined), path)
        raster = None
        dataset = None
        try:
            dataset = gdal.Open(str(path))
            if dataset is None or dataset.GetGeoTransform(can_return_null=True) is None:
                raise RuntimeError("Rasteri on virheellinen tai siitä puuttuu georeferointi")
            dataset = None
            raster = QgsRasterLayer(str(path), Path(path).stem)
            if not raster.isValid():
                raise RuntimeError("Rasteria ei voitu avata")
            assign_source_crs(raster, path, source_crs)
            if crs is None:
                crs = raster.crs()
            elif raster.crs() != crs:
                raise RuntimeError("Rasteriryhmän koordinaatistot eroavat; projisoi rasterit samaan CRS:ään")
            valid.append(str(path))
        except Exception as exc:
            failures.append((str(path), str(exc)))
        finally:
            dataset = None
            _dispose(raster)
    if not valid:
        return []
    root = destination.parent if destination.suffix.lower() in {".gpkg", ".gdb"} else destination
    root.mkdir(parents=True, exist_ok=True)
    # Uniikki nimi välttää myös muissa ryhmissä/projekteissa avoimen VRT:n korvaamisen.
    output = root / f"muuntaja_{safe_name(destination.stem)}_{safe_name(group_name)}_{uuid.uuid4().hex[:12]}.vrt"
    temp_output = output.with_suffix(".tmp.vrt")
    layer = None
    try:
        options = gdal.BuildVRTOptions(outputSRS=crs.toWkt())
        vrt = gdal.BuildVRT(str(temp_output), valid, options=options)
        if vrt is None:
            raise RuntimeError(f"Rasterimosaiikin luonti epäonnistui: {group_name}")
        vrt.FlushCache()
        vrt = None
        os.replace(temp_output, output)
        layer = QgsRasterLayer(str(output), group_name)
        if not layer.isValid():
            raise RuntimeError(f"Rasterimosaiikkia ei voitu avata: {output}")
        layer.setCustomProperty("muuntaja/source_paths", valid)
        _add_project_layer(project, layer, False)
        group.addLayer(layer)
        layer = None  # project owns it
        for old in prior:
            project.removeMapLayer(old.id())
    except Exception:
        _dispose(layer)
        output.unlink(missing_ok=True)
        raise
    finally:
        temp_output.unlink(missing_ok=True)
    return [str(path) for path in paths if str(path) in valid]


def import_data(paths, destination, source_crs=None, target_crs=None, clean_cad=False,
                progress=None, dfsu_filter_column="", dfsu_filter_operator="=", dfsu_filter_value="",
                oda_converter=""):
    """Import vectors to a GeoPackage or folder; add located rasters by reference."""
    project = _project()
    items = scan_inputs(paths, progress)
    if not items:
        raise ValueError("Tuettavia tiedostoja ei löytynyt.")
    destination = Path(destination)
    gpkg = destination.suffix.lower() == ".gpkg"
    file_gdb = destination.suffix.lower() == ".gdb"
    workspace = gpkg or file_gdb
    if workspace:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    successes, failures = [], []
    existing_names = _workspace_names(destination) if workspace else set()
    raster_groups = {}
    for index, path in enumerate(items, 1):
        converted_dwg = None
        virtual_dxf = None
        layers = []
        if progress:
            progress(index, len(items), str(path))
        try:
            if path.suffix.lower() in RASTER_EXTENSIONS:
                group_name = raster_group(path)
                raster_groups.setdefault(group_name, []).append(path)
                continue
            if path.suffix.lower() == ".dfsu":
                _import_dfsu(path, destination, workspace, source_crs, target_crs,
                             dfsu_filter_column, dfsu_filter_operator, dfsu_filter_value, existing_names, progress)
                successes.append(str(path))
                continue
            try:
                layers = _open_vector_layers(path)
            except RuntimeError as exc:
                if path.suffix.lower() != ".dwg":
                    raise
                libredwg = find_libredwg_converter("dwg2dxf")
                oda = oda_converter or find_oda_converter()
                if not libredwg and not oda:
                    raise RuntimeError(
                        f"DWG {_dwg_version(path)} ei avaudu QGISin CAD-ajurilla. "
                        "Asenna Muuntajan Windows-paketti, joka sisältää DWG-muuntimen.") from exc
                converted_dwg = tempfile.TemporaryDirectory(prefix="muuntaja_dwg_import_")
                try:
                    if libredwg:
                        dxf = _convert_dwg_with_libredwg(path, libredwg, converted_dwg.name)
                    else:
                        dxf = _convert_dwg_to_dxf(path, oda, converted_dwg.name)
                except RuntimeError:
                    if not libredwg or not oda:
                        raise
                    dxf = _convert_dwg_to_dxf(path, oda, converted_dwg.name)
                from osgeo import gdal
                virtual_dxf = f"/vsimem/muuntaja_{uuid.uuid4().hex}.dxf"
                gdal.FileFromMemBuffer(virtual_dxf, dxf.read_bytes())
                layers = _open_vector_layers(PurePosixPath(virtual_dxf))
            cad_crs = source_crs
            if path.suffix.lower() in {".dwg", ".dxf"} and not cad_crs:
                cad_crs = next((guessed for layer in layers
                                if (guessed := inferred_crs(layer, path)) and guessed.isValid()), None)
            written = 0
            for layer in layers:
                if clean_cad and path.suffix.lower() in {".dwg", ".dxf"} and layer.name().casefold() in {"defpoints", "0"}:
                    continue
                cad_field = next((name for name in layer.fields().names() if name.casefold() == "layer"), None)
                feature_filter = None
                if clean_cad and path.suffix.lower() in {".dwg", ".dxf"} and cad_field:
                    feature_filter = lambda feature, field=cad_field: str(feature[field]).casefold() not in {"defpoints", "0"}
                if layer.featureCount() == 0 or layer.extent().isNull():
                    continue
                assign_source_crs(layer, path, cad_crs if path.suffix.lower() in {".dwg", ".dxf"} else source_crs)
                name = (gdb_safe_name if file_gdb else safe_name)(f"{path.stem}_{layer.name()}")
                if workspace:
                    base, number = name, 2
                    while name.casefold() in {value.casefold() for value in existing_names}:
                        name = f"{base[:65]}_{number}"
                        number += 1
                    _write_vector(layer, destination, "OpenFileGDB" if file_gdb else "GPKG",
                                  name, target_crs, destination.exists(), feature_filter, progress)
                    output = QgsVectorLayer(f"{destination}|layername={name}", name, "ogr")
                else:
                    output_path = unique_path(destination / f"{name}.gpkg")
                    _write_vector(layer, output_path, "GPKG", name, target_crs, feature_filter=feature_filter, progress=progress)
                    output = QgsVectorLayer(str(output_path), name, "ogr")
                if not output.isValid():
                    _dispose(output)
                    raise RuntimeError("Kirjoitettua tasoa ei voitu avata")
                _add_project_layer(project, output)
                existing_names.add(name)
                written += 1
            if not written:
                raise RuntimeError("Tiedostossa ei ollut tuotavia kohteita")
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((str(path), str(exc)))
        finally:
            for layer in layers:
                _dispose(layer)
            layers.clear()
            if virtual_dxf:
                from osgeo import gdal
                gdal.Unlink(virtual_dxf)
            if converted_dwg is not None:
                converted_dwg.cleanup()
    for group_name, paths in raster_groups.items():
        if progress:
            progress(len(items), len(items), group_name)
        try:
            successes.extend(_add_raster_group(project, group_name, paths, destination, source_crs, failures, progress))
        except OperationCanceled:
            raise
        except Exception as exc:
            failed_paths = {path for path, _reason in failures}
            failures.extend((str(path), str(exc)) for path in paths if str(path) not in failed_paths)
    if not successes:
        raise RuntimeError("Yksikään tiedosto ei onnistunut: " + "; ".join(f"{p}: {e}" for p, e in failures))
    return successes, failures


def export_data(layers, folder, format_name, combined=False, progress=None, oda_converter=""):
    if format_name == "DWG":
        if not layers:
            raise ValueError("Valitse vähintään yksi vektoritaso.")
        return _export_dwg(layers, folder, combined, oda_converter)
    if format_name not in DRIVERS:
        raise ValueError(f"Tuntematon vientimuoto: {format_name}")
    if not layers:
        raise ValueError("Valitse vähintään yksi vektoritaso.")
    driver, extension = DRIVERS[format_name]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    combined = combined and format_name in {"GPKG", "DXF"}
    common_path = unique_path(folder / f"muuntaja_vienti{extension}") if combined else None
    if combined and format_name == "DXF":
        _write_combined_dxf(layers, common_path, progress=progress)
        return [str(common_path) for _ in layers], []
    successes, failures = [], []
    used_names = set()
    for index, layer in enumerate(layers, 1):
        if progress:
            progress(index, len(layers), layer.name())
        try:
            if not layer.isValid():
                raise RuntimeError("Taso ei ole kelvollinen")
            path = common_path or unique_path(folder / f"{safe_name(layer.name())}{extension}")
            layer_name = safe_name(layer.name())
            base_name, number = layer_name, 2
            while layer_name in used_names:
                layer_name = f"{base_name[:65]}_{number}"
                number += 1
            used_names.add(layer_name)
            if format_name == "GeoJSON" and not layer.crs().isValid():
                raise RuntimeError("GeoJSON-vienti vaatii tunnetun lähtökoordinaatiston")
            _write_vector(layer, path, driver, layer_name if format_name == "GPKG" else None,
                          target_crs=QgsCoordinateReferenceSystem("EPSG:4326") if format_name == "GeoJSON" else None,
                          append=bool(common_path and path.exists()), progress=progress)
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((layer.name(), str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
