"""DWG/DXF import and DXF/DWG export that behave like native QGIS layers.

Tuonti lukee CAD-kohteet GDAL:n DXF-ajurilla (DWG muunnetaan ensin DXF:ksi
LibreDWG:llä, joka tulee Windowsissa lisäosan mukana) ja kirjoittaa ne neljäksi tasoksi:
tekstit, pisteet, viivat ja alueet. Tasot saavat CAD-värit, CAD-tasot
näkyvät sisällysluettelossa päälle/pois kytkettävinä sääntöinä ja tekstit
nimiöinä. Vienti käyttää QGISin omaa DXF-vientiä, joten tasojen symbologia,
nimiöt ja CAD-tasonimet säilyvät. DWG kirjoitetaan tästä DXF:stä lisäosan
mukana tulevalla ACadSharp-ohjelmalla (qgis_plugin/dwgwriter).
"""

import os
import re
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDxfExport, QgsExpression,
    QgsFeature, QgsField, QgsFields, QgsFillSymbol, QgsGeometry, QgsLineSymbol, QgsMapSettings,
    QgsMarkerSymbol, QgsNullSymbolRenderer, QgsPalLayerSettings, QgsProperty, QgsRectangle,
    QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsSymbolLayer, QgsTextFormat,
    QgsUnitTypes, QgsVectorFileWriter, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QFile
from qgis.PyQt.QtGui import QColor

from . import formats, processing
from .qgisutil import add_layers_as_group, field_type

MAX_LEGEND_RULES = 250
DEFAULT_COLOR = "#000000"
DEFAULT_TEXT_HEIGHT = 2.5
# (tason pääte, geometriatyyppi 2D, tyyppi Z) – järjestys on sisällysluettelon
# järjestys ylhäältä alas.
BUCKETS = (
    ("tekstit", QgsWkbTypes.Point, QgsWkbTypes.PointZ),
    ("pisteet", QgsWkbTypes.Point, QgsWkbTypes.PointZ),
    ("viivat", QgsWkbTypes.MultiLineString, QgsWkbTypes.MultiLineStringZ),
    ("alueet", QgsWkbTypes.MultiPolygon, QgsWkbTypes.MultiPolygonZ),
)
FIELD_SPECS = (
    ("cad_layer", "string"), ("cad_color", "string"), ("entity", "string"), ("handle", "string"),
    ("linetype", "string"), ("text", "string"), ("text_size", "double"), ("text_angle", "double"),
    ("text_anchor", "int"),
)
SKIPPED_CAD_LAYERS = {"defpoints", "0"}


class CrsNotDetected(RuntimeError):
    """DWG/DXF has no CRS and it could not be inferred from the coordinates."""


# --- enum compatibility (QGIS 3.34 … 3.44+) -----------------------------------

def _enum(owner, scoped, name, legacy=None):
    container = getattr(owner, scoped, None)
    if container is not None and hasattr(container, name):
        return getattr(container, name)
    return getattr(owner, legacy or (scoped + name))


def _symbol_property(name):
    return _enum(QgsSymbolLayer, "Property", name)


def _label_property(name):
    return _enum(QgsPalLayerSettings, "Property", name, name)


def _fields():
    fields = QgsFields()
    for name, kind in FIELD_SPECS:
        fields.append(QgsField(name, field_type(kind)))
    return fields


# --- DWG -> DXF conversion ---------------------------------------------------

def missing_converter_message(action, version=""):
    detail = f" ({formats.dwg_version_label(version)})" if version else ""
    return (f"DWG{detail} {action} vaatii LibreDWG:n. Windowsissa se tulee lisäosan mukana; "
            "muilla alustoilla asenna LibreDWG (komento dwg2dxf) tai tallenna piirustus DXF-muotoon.")


def dwg_to_dxf(path, work_folder):
    """Convert one DWG to DXF with LibreDWG."""
    path = Path(path)
    tool = formats.find_libredwg_tool("dwg2dxf")
    if not tool:
        raise RuntimeError(missing_converter_message("tuonti", formats.dwg_version(path)))
    converted = Path(work_folder) / f"{path.stem}.dxf"
    formats.run_converter([tool, "-y", "-o", converted, path], "LibreDWG dwg2dxf")
    if not converted.is_file() or converted.stat().st_size == 0:
        raise RuntimeError(f"DWG-muunnin ei tuottanut DXF-tiedostoa: {path.name}")
    return converted


# --- reading ------------------------------------------------------------------

@contextmanager
def _gdal_config(**options):
    """Set GDAL options and exceptions only for this block (QGIS shares GDAL)."""
    from osgeo import gdal
    previous = {key: gdal.GetConfigOption(key) for key in options}
    exceptions_were_on = bool(gdal.GetUseExceptions())
    gdal.UseExceptions()
    for key, value in options.items():
        gdal.SetConfigOption(key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            gdal.SetConfigOption(key, value)
        if not exceptions_were_on:
            gdal.DontUseExceptions()


def _field(feature, *names):
    for name in names:
        index = feature.GetFieldIndex(name)
        if index >= 0 and feature.IsFieldSet(index):
            return feature.GetField(index)
    return None


def _flatten(geometry):
    """Yield simple OGR geometries (points, lines, polygons) from any geometry."""
    from osgeo import ogr
    if geometry is None or geometry.IsEmpty():
        return
    if geometry.HasCurveGeometry():
        geometry = geometry.GetLinearGeometry()
    flat = ogr.GT_Flatten(geometry.GetGeometryType())
    if flat in (ogr.wkbGeometryCollection, ogr.wkbMultiPoint, ogr.wkbMultiLineString, ogr.wkbMultiPolygon):
        for index in range(geometry.GetGeometryCount()):
            yield from _flatten(geometry.GetGeometryRef(index))
    else:
        yield geometry.Clone()


def _bucket(geometry, has_text):
    from osgeo import ogr
    flat = ogr.GT_Flatten(geometry.GetGeometryType())
    if flat == ogr.wkbPoint:
        return "tekstit" if has_text else "pisteet"
    if flat == ogr.wkbLineString:
        return "viivat"
    if flat == ogr.wkbPolygon:
        return "alueet"
    return None


def read_cad(path, clean_cad=False, notes=None, encoding=None):
    """Read model-space CAD entities; returns {bucket: [record]} and sample points."""
    from osgeo import gdal, ogr
    if Path(path).suffix.lower() == ".dgn":
        from .dgn import readable_source
        with tempfile.TemporaryDirectory(prefix="muuntaja_dgn_") as folder:
            return read_cad(readable_source(path, folder, notes), clean_cad, notes, "UTF-8")
    buckets = {name: [] for name, _flat, _z in BUCKETS}
    samples = []
    with _gdal_config(DXF_MERGE_BLOCK_GEOMETRIES="FALSE", DXF_INLINE_BLOCKS="TRUE",
                      DXF_ENCODING=encoding):
        try:
            dataset = gdal.OpenEx(str(path), gdal.OF_VECTOR)
        except RuntimeError as exc:
            raise RuntimeError(f"CAD-tiedostoa ei voitu avata: {Path(path).name} ({exc})") from exc
        try:
            for layer_index in range(dataset.GetLayerCount()):
                source_layer = dataset.GetLayer(layer_index)
                for feature in source_layer:
                    if _field(feature, "PaperSpace"):
                        continue
                    level = _field(feature, "Layer", "layer", "Level")
                    cad_layer = str(level) if level is not None else source_layer.GetName()
                    if clean_cad and cad_layer.casefold() in SKIPPED_CAD_LAYERS:
                        continue
                    style = formats.parse_ogr_style(feature.GetStyleString())
                    color = style["color"] or formats.parse_ogr_style(
                        f"PEN(c:{_field(feature, 'color') or ''})")["color"]
                    if color == "#ffffff":
                        # ACI 7 on "valkoinen/musta": musta näkyy vaalealla kartalla.
                        color = DEFAULT_COLOR
                    subclasses = str(_field(feature, "SubClasses", "cadgeom_type", "Entity", "Type") or "")
                    entity = subclasses.split(":")[-1] if subclasses else ""
                    text = formats.strip_mtext(style["text"] or str(_field(feature, "Text", "text", "TextString") or ""))
                    for part in _flatten(feature.GetGeometryRef()):
                        # GDAL V7 represents an unlabelled point as a zero-length line.
                        if _field(feature, "Type") == 3 and ogr.GT_Flatten(part.GetGeometryType()) == ogr.wkbLineString and part.GetPointCount() >= 2:
                            if all(part.GetPoint(i) == part.GetPoint(0) for i in range(1, part.GetPointCount())):
                                point = ogr.Geometry(ogr.wkbPoint25D if part.GetCoordinateDimension() == 3 else ogr.wkbPoint)
                                if part.GetCoordinateDimension() == 3:
                                    point.AddPoint(*part.GetPoint(0))
                                else:
                                    point.AddPoint_2D(*part.GetPoint(0)[:2])
                                part = point
                        bucket = _bucket(part, bool(text))
                        if bucket is None:
                            continue
                        envelope = part.GetEnvelope()
                        samples.append(((envelope[0] + envelope[1]) / 2.0, (envelope[2] + envelope[3]) / 2.0))
                        buckets[bucket].append({
                            "wkb": bytes(part.ExportToIsoWkb()),
                            "z": part.GetCoordinateDimension() == 3,
                            "attributes": {
                                "cad_layer": cad_layer,
                                "cad_color": color or None,
                                "entity": entity or None,
                                "handle": _field(feature, "EntityHandle"),
                                "linetype": _field(feature, "Linetype"),
                                "text": text if bucket == "tekstit" else None,
                                "text_size": style["text_size"] if bucket == "tekstit" else None,
                                "text_angle": style["angle"] if bucket == "tekstit" else None,
                                "text_anchor": style["anchor"] if bucket == "tekstit" else None,
                            },
                        })
        except RuntimeError as exc:
            raise RuntimeError(f"CAD-tiedoston luku epäonnistui ({Path(path).name}): {exc}") from exc
        finally:
            dataset = None
    return buckets, samples


def cad_source_crs(samples, path, source_crs=None):
    if source_crs and source_crs.isValid():
        return source_crs
    if Path(path).suffix.lower() == ".dgn":
        from .dgn import metadata
        wkt = metadata(path).get("crs", "")
        if not wkt and Path(path).with_suffix(".prj").is_file():
            wkt = Path(path).with_suffix(".prj").read_text(encoding="utf-8-sig")
        if wkt:
            crs = QgsCoordinateReferenceSystem.fromWkt(wkt)
            if crs.isValid():
                return crs
    code = formats.vote_finnish_epsg(samples[::max(1, len(samples) // 2000)])
    if code:
        return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    if "etrs89" in str(path).casefold():
        return QgsCoordinateReferenceSystem("EPSG:3067")
    raise CrsNotDetected("CAD-tiedoston koordinaatistoa ei tunnistettu. "
                         "Aseta lähtö-CRS lisäasetuksissa.")


# --- writing ------------------------------------------------------------------

def existing_layer_names(path):
    path = Path(path)
    if not path.exists():
        return set()
    from osgeo import gdal
    with _gdal_config():
        try:
            dataset = gdal.OpenEx(str(path), gdal.OF_VECTOR)
        except RuntimeError:
            return set()
        return {dataset.GetLayer(i).GetName() for i in range(dataset.GetLayerCount())}


def _to_output_geometry(record, wkb_type, transform):
    geometry = QgsGeometry()
    geometry.fromWkb(record["wkb"])
    if QgsWkbTypes.isMultiType(wkb_type):
        geometry.convertToMultiType()
    if QgsWkbTypes.hasZ(wkb_type) and not geometry.constGet().is3D():
        geometry.get().addZValue(0)
    if transform is not None:
        geometry.transform(transform)
    return geometry


def write_layer(output_path, layer_name, driver, wkb_type, crs, records, transform=None):
    """Write records to a new layer in a GeoPackage/FileGDB and return it opened."""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    options.layerName = layer_name
    if driver == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    if Path(output_path).exists():
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    fields = _fields()
    writer = QgsVectorFileWriter.create(str(output_path), fields, wkb_type, crs,
                                        processing._project().transformContext(), options)
    if writer.hasError() != QgsVectorFileWriter.NoError:
        message = writer.errorMessage()
        del writer
        raise RuntimeError(message)
    try:
        for record in records:
            feature = QgsFeature(fields)
            feature.setAttributes([record["attributes"].get(name) for name, _kind in FIELD_SPECS])
            feature.setGeometry(_to_output_geometry(record, wkb_type, transform))
            if not writer.addFeature(feature):
                raise RuntimeError(writer.errorMessage())
    finally:
        del writer
    layer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Kirjoitettua tasoa ei voitu avata: {layer_name}")
    return layer


# --- styling ------------------------------------------------------------------

def _color_expression(fallback):
    return QgsProperty.fromExpression(f"coalesce(\"cad_color\", {QgsExpression.quotedString(fallback)})")


def _symbol(bucket, color):
    color = color or DEFAULT_COLOR
    if bucket == "viivat":
        symbol = QgsLineSymbol.createSimple({"color": color, "width": "0.26", "capstyle": "round"})
        symbol.symbolLayer(0).setDataDefinedProperty(_symbol_property("StrokeColor"), _color_expression(color))
    elif bucket == "alueet":
        symbol = QgsFillSymbol.createSimple({"color": color, "outline_color": color, "outline_width": "0.1"})
        symbol.symbolLayer(0).setDataDefinedProperty(_symbol_property("FillColor"), _color_expression(color))
        symbol.symbolLayer(0).setDataDefinedProperty(_symbol_property("StrokeColor"), _color_expression(color))
    else:
        symbol = QgsMarkerSymbol.createSimple({"name": "circle", "size": "1.2", "color": color,
                                               "outline_style": "no"})
        symbol.symbolLayer(0).setDataDefinedProperty(_symbol_property("FillColor"), _color_expression(color))
    return symbol


def _renderer(bucket, records):
    if bucket == "tekstit":
        # Teksti piirretään nimiönä ilman merkkiä. Tyhjä renderöijä pitää myös
        # DXF-viennin puhtaana: vain TEXT-kohteet, ei näkymättömiä symboleita.
        return QgsNullSymbolRenderer()
    colors_by_layer = {}
    for record in records:
        attributes = record["attributes"]
        colors_by_layer.setdefault(attributes["cad_layer"], Counter())[attributes["cad_color"] or DEFAULT_COLOR] += 1
    if not colors_by_layer or len(colors_by_layer) > MAX_LEGEND_RULES:
        return QgsSingleSymbolRenderer(_symbol(bucket, DEFAULT_COLOR))
    root = QgsRuleBasedRenderer.Rule(None)
    for cad_layer in sorted(colors_by_layer, key=lambda name: (name.casefold(), name)):
        color = colors_by_layer[cad_layer].most_common(1)[0][0]
        expression = f"\"cad_layer\" = {QgsExpression.quotedString(cad_layer)}"
        root.appendChild(QgsRuleBasedRenderer.Rule(_symbol(bucket, color), 0, 0, expression, cad_layer))
    return QgsRuleBasedRenderer(root)


def _text_labeling():
    settings = QgsPalLayerSettings()
    settings.fieldName = "text"
    settings.enabled = True
    settings.placement = _enum(Qgis, "LabelPlacement", "OverPoint", "OverPoint") \
        if hasattr(Qgis, "LabelPlacement") else QgsPalLayerSettings.OverPoint
    text_format = QgsTextFormat()
    text_format.setSize(DEFAULT_TEXT_HEIGHT)
    text_format.setSizeUnit(_enum(Qgis, "RenderUnit", "MapUnits", "MapUnits"))
    text_format.setColor(QColor(DEFAULT_COLOR))
    settings.setFormat(text_format)
    properties = settings.dataDefinedProperties()
    properties.setProperty(_label_property("Size"),
                           QgsProperty.fromExpression(f"coalesce(\"text_size\", {DEFAULT_TEXT_HEIGHT})"))
    # CAD-kulma on vastapäivään, QGISin nimiön kierto myötäpäivään.
    properties.setProperty(_label_property("LabelRotation"),
                           QgsProperty.fromExpression("360 - coalesce(\"text_angle\", 0)"))
    properties.setProperty(_label_property("Color"), _color_expression(DEFAULT_COLOR))
    # OGR:n ankkuri 1–12 (vasen/keski/oikea × ala/keski/ylä) → QGISin kvadrantti.
    properties.setProperty(_label_property("OffsetQuad"), QgsProperty.fromExpression(
        "with_variable('a', if(coalesce(\"text_anchor\", 1) > 9, \"text_anchor\" - 9, "
        "coalesce(\"text_anchor\", 1)), floor((@a - 1) / 3) * 3 + (2 - ((@a - 1) % 3)))"))
    settings.setDataDefinedProperties(properties)
    try:
        settings.placementSettings().setOverlapHandling(Qgis.LabelOverlapHandling.AllowOverlapAtNoCost)
    except AttributeError:
        settings.displayAll = True
    try:
        settings.obstacleSettings().setIsObstacle(False)
    except AttributeError:
        pass
    return QgsVectorLayerSimpleLabeling(settings)


def style_layer(layer, bucket, records):
    layer.setRenderer(_renderer(bucket, records))
    if bucket == "tekstit":
        layer.setLabeling(_text_labeling())
        layer.setLabelsEnabled(True)


# --- import -------------------------------------------------------------------

def _open_source(path, work_folder):
    path = Path(path)
    if path.suffix.lower() == ".dgn":
        return path
    if path.suffix.lower() == ".dxf":
        return path
    version = formats.dwg_version(path)
    if formats.find_libredwg_tool("dwg2dxf"):
        return dwg_to_dxf(path, work_folder)
    if version in formats.OGR_CAD_READABLE_DWG:
        return path
    raise RuntimeError(missing_converter_message("tuonti", version))


def import_cad(path, destination, source_crs=None, target_crs=None, clean_cad=False,
               project=None, add_to_project=True, notes=None):
    """Import one DWG/DXF/DGN; returns the created QGIS layers."""
    project = project or processing._project()
    path = Path(path)
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix="muuntaja_cad_") as work_folder:
        source = _open_source(path, work_folder)
        buckets, samples = read_cad(source, clean_cad, notes)
    if not any(buckets.values()):
        raise RuntimeError("CAD-tiedostossa ei ollut tuotavia mallitilan kohteita.")
    crs = cad_source_crs(samples, path, source_crs)
    output_crs = target_crs if target_crs and target_crs.isValid() else crs
    transform = QgsCoordinateTransform(crs, output_crs, project) if output_crs != crs else None

    suffix = destination.suffix.lower()
    if suffix in {".gpkg", ".gdb"}:
        output_path, driver = destination, ("OpenFileGDB" if suffix == ".gdb" else "GPKG")
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
        output_path, driver = formats.unique_path(destination / f"{formats.safe_name(path.stem)}.gpkg"), "GPKG"

    layers = []
    taken = existing_layer_names(output_path)
    base = formats.safe_name(path.stem)
    if driver == "OpenFileGDB":
        from .processing import gdb_safe_name
        base = gdb_safe_name(base)
    for bucket, flat_type, z_type in BUCKETS:
        records = buckets[bucket]
        if not records:
            continue
        wkb_type = z_type if any(record["z"] for record in records) else flat_type
        name = formats.unique_name(f"{base}_{bucket}", taken)
        taken.add(name)
        layer = write_layer(output_path, name, driver, wkb_type, output_crs, records, transform)
        style_layer(layer, bucket, records)
        layer.setCustomProperty("muuntaja/source", str(path))
        layers.append(layer)
    if add_to_project:
        add_layers_as_group(project, layers, path.name)
    return layers


# --- export -------------------------------------------------------------------

def _destination_crs(layers, project):
    if project.crs().isValid():
        return project.crs()
    return next((layer.crs() for layer in layers if layer.crs().isValid()), QgsCoordinateReferenceSystem())


def _combined_extent(layers, crs, project):
    extent = None
    for layer in layers:
        layer.updateExtents()
        if layer.featureCount() == 0:
            continue
        layer_extent = layer.extent()
        if layer.crs() != crs:
            layer_extent = QgsCoordinateTransform(layer.crs(), crs, project).transformBoundingBox(layer_extent)
        if extent is None:
            extent = QgsRectangle(layer_extent)
        else:
            extent.combineExtentWith(layer_extent)
    if extent is None:
        raise RuntimeError("Valituilla tasoilla ei ole vietäviä kohteita.")
    # Yhden pisteen laajuus on tyhjä, jolloin QGIS ei vie mitään: kasvata aina.
    extent.grow(max(1.0, 0.01 * max(extent.width(), extent.height())))
    return extent


def write_dxf(layers, path, crs=None, symbology_scale=None, project=None):
    """Export layers with QGIS' own DXF writer (symbology, labels, CAD layer names)."""
    project = project or processing._project()
    crs = crs if crs and crs.isValid() else _destination_crs(layers, project)
    if not crs.isValid():
        raise RuntimeError("DXF-vienti vaatii tunnetun koordinaatiston.")
    extent = _combined_extent(layers, crs, project)
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(crs)
    settings.setTransformContext(project.transformContext())
    settings.setExtent(extent)
    export = QgsDxfExport()
    export.setMapSettings(settings)
    export.setExtent(extent)
    # Tuodun CAD-aineiston cad_layer-kenttä palauttaa alkuperäiset CAD-tasonimet.
    export.addLayers([QgsDxfExport.DxfLayer(layer, layer.fields().indexOf("cad_layer")) for layer in layers])
    export.setSymbologyScale(float(symbology_scale or 1000))
    export.setSymbologyExport(_enum(Qgis, "FeatureSymbologyExport", "PerFeature", "FeatureSymbology")
                              if hasattr(Qgis, "FeatureSymbologyExport") else QgsDxfExport.FeatureSymbology)
    export.setDestinationCrs(crs)
    export.setLayerTitleAsName(False)
    result = export.writeToFile(QFile(str(path)), "UTF-8")
    if result != QgsDxfExport.ExportResult.Success:
        messages = {
            QgsDxfExport.ExportResult.DeviceNotWritableError: "DXF-tiedostoa ei voitu kirjoittaa",
            QgsDxfExport.ExportResult.EmptyExtentError: "Vietävien kohteiden laajuus on tyhjä",
            QgsDxfExport.ExportResult.InvalidDeviceError: "DXF-tiedostoa ei voitu luoda",
        }
        raise RuntimeError(f"{messages.get(result, 'DXF-vienti epäonnistui')}: {path}")
    meters = crs.mapUnits() == QgsUnitTypes.DistanceMeters
    factor = 1.0 if meters else QgsUnitTypes.fromUnitToUnitFactor(QgsUnitTypes.DistanceMeters, crs.mapUnits())
    _cad_strokes(path, float(symbology_scale or 1000) / 1000 * factor, meters)
    return Path(path)


# AutoCADin vakioviivapaksuudet (1/100 mm, DXF-ryhmä 370).
_LINE_WEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)


def _line_weight(millimetres):
    return min(_LINE_WEIGHTS, key=lambda weight: abs(weight - millimetres * 100))


def _cad_strokes(path, units_per_mm, meters):
    """Turn QGIS' stroke widths into CAD line weights in a DXF; returns the number of lines.

    QGIS kirjoittaa viivan leveyden LWPOLYLINE-leveydeksi karttayksiköissä
    symbologiamittakaavassa, jolloin 1:5 000 000:ssa 1,6 mm tieviiva on CADissa
    8 km leveä kaista. Mallitilan viivat saavat leveydeksi 0 ja paksuus
    tallennetaan viivapaksuudeksi (ryhmä 370). Lohkojen (pistesymbolien) sisältö
    säilyy. Metrisessä koordinaatistossa piirustusyksiköksi ($INSUNITS) tulee metri.
    """
    data = Path(path).read_bytes()
    newline = b"\r\n" if b"\r\n" in data[:4096] else b"\n"
    lines = data.split(newline)
    tail = lines[len(lines) // 2 * 2:]
    pairs = [[lines[index], lines[index + 1]] for index in range(0, len(lines) // 2 * 2, 2)]
    output, section, entity, changed = [], None, None, 0
    has_units = False

    def finish():
        nonlocal changed
        if entity and entity["width"] > 0:
            for pair in entity["widths"]:
                pair[1] = b"0.0"
            weight = str(_line_weight(entity["width"] / units_per_mm)).encode() if units_per_mm > 0 else None
            if weight is not None:
                if entity["weight"] is not None:
                    entity["weight"][1] = weight
                else:
                    output.insert(entity["anchor"], [b"370", weight])
            changed += 1

    for pair in pairs:
        code, value = pair[0].strip(), pair[1].strip()
        if code == b"0":
            finish()
            entity = None
            if value == b"ENDSEC" and section == b"HEADER" and meters and not has_units:
                output += [[b"  9", b"$INSUNITS"], [b" 70", b"     6"]]
            if value == b"ENDSEC":
                section = None
            elif section == b"ENTITIES" and value == b"LWPOLYLINE":
                entity = {"width": 0.0, "widths": [], "weight": None, "anchor": len(output) + 1}
        elif code == b"2" and output and output[-1][0].strip() == b"0" and output[-1][1].strip() == b"SECTION":
            section = value
        elif section == b"HEADER" and code == b"9" and value == b"$INSUNITS":
            has_units = True
        elif section == b"HEADER" and has_units and code == b"70" and meters and output[-1][1].strip() == b"$INSUNITS":
            pair = [pair[0], b"     6"]
        elif entity is not None:
            if code == b"100" and value == b"AcDbEntity":
                entity["anchor"] = len(output) + 1
            elif code == b"370":
                entity["weight"] = pair
            elif code in (b"43", b"40", b"41"):
                try:
                    width = float(value)
                except ValueError:
                    width = 0.0
                if width > 0:
                    entity["width"] = max(entity["width"], width)
                    entity["widths"].append(pair)
        output.append(pair)
    finish()
    Path(path).write_bytes(newline.join([line for pair in output for line in pair] + tail))
    return changed


def missing_dwg_writer_message():
    rid = formats.dwg_writer_platform() or "tämä alusta"
    return (f"DWG-kirjoitin puuttuu lisäosasta ({rid}). Asenna Muuntajan uusin ZIP uudelleen "
            "tai vie DXF-muotoon, jonka AutoCAD ja ArcGIS avaavat sellaisenaan.")


def write_dwg(layers, path, crs, project=None, notes=None, symbology_scale=None, version="2018"):
    """Export layers to DWG: QGIS' own DXF export, then ACadSharp writes the DWG.

    Symbologia, nimiöt, lohkosymbolit ja CAD-tasonimet tulevat QGISin
    DXF-viennistä. Kirjoitin lukee DWG:n takaisin ja vertaa kohdemäärät ennen
    kuin tiedosto hyväksytään. Koordinaatisto tallennetaan viereen .prj-
    tiedostoon, jonka ArcGIS Pro lukee CAD-aineistolle automaattisesti.
    """
    import json
    tool = formats.find_dwg_writer()
    if not tool:
        raise RuntimeError(missing_dwg_writer_message())
    path = Path(path)
    if path.exists():
        raise RuntimeError(f"DWG-tiedosto on jo olemassa: {path}")
    labels = dict(formats.DWG_EXPORT_VERSIONS)
    version = str(version or "2018")
    if version not in labels:
        raise ValueError(f"Tuntematon DWG-versio: {version}")
    crs = crs if crs is not None and crs.isValid() else _destination_crs(layers, project or processing._project())
    with tempfile.TemporaryDirectory(prefix="muuntaja_dwg_") as temp:
        dxf = write_dxf(layers, Path(temp) / "vienti.dxf", crs, symbology_scale, project)
        result = formats.run_converter([tool, dxf, path, "--version", version], "DWG-kirjoitin (ACadSharp)")
    if not path.is_file() or not formats.dwg_version(path):
        path.unlink(missing_ok=True)
        raise RuntimeError(f"DWG-kirjoitin ei tuottanut kelvollista DWG-tiedostoa: {path.name}")
    try:
        report = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        report = {}
    prj = path.with_suffix(".prj")
    if not crs.isValid():
        crs_note = "Koordinaatistoa ei tunnettu, joten .prj-tiedostoa ei kirjoitettu."
    elif prj.exists():
        crs_note = f"Olemassa olevaa tiedostoa {prj.name} ei korvattu; koordinaatisto on {crs.authid()}."
    else:
        esri = getattr(QgsCoordinateReferenceSystem, "WKT1_ESRI", None)
        prj.write_text(crs.toWkt(esri) if esri is not None else crs.toWkt(), encoding="utf-8")
        crs_note = f"Koordinaatisto {crs.authid()} tallennettiin tiedostoon {prj.name}."
    if notes is not None:
        notes.append(f"DWG {labels[version]}: {path.name}, {report.get('entities', '?')} CAD-kohdetta, "
                     f"{report.get('layers', '?')} CAD-tasoa. {crs_note}")
        for warning in report.get("warnings", [])[:5]:
            notes.append(f"DWG-kirjoittimen huomautus: {warning}")
    return path


def combined_export_name(layers, project=None):
    """File name for layers exported into one file.

    Saman ryhmän tasot saavat ryhmän nimen (tuodun tiedoston nimi ilman
    päätettä), muuten tasonimien yhteinen alku, tallennetun projektin nimi tai
    ensimmäisen tason nimi ja muiden tasojen määrä.
    """
    layers = list(layers)
    names = [layer.name() for layer in layers]
    if len(layers) == 1:
        return formats.safe_name(names[0])
    project = project or processing._project()
    root = project.layerTreeRoot()
    groups = set()
    for layer in layers:
        node = root.findLayer(layer.id())
        parent = node.parent() if node is not None else None
        groups.add(parent.name() if parent is not None and parent.parent() is not None else None)
    if len(groups) == 1 and None not in groups:
        group = groups.pop()
        stem = Path(group)
        return formats.safe_name(stem.stem if stem.suffix.lower() in formats.VECTOR_EXTENSIONS else group)
    # Yhteinen alku kokonaisina sanoina: kaivot_2024 + kaivot_2025 -> kaivot.
    words = os.path.commonprefix([re.split(r"([\s_.()-]+)", name) for name in names])
    prefix = "".join(words).strip(" _-.(")
    if len(prefix) >= 3:
        return formats.safe_name(prefix)
    if project.fileName():
        return formats.safe_name(project.baseName())
    return formats.safe_name(f"{formats.safe_name(names[0])[:60]}_ja_{len(names) - 1}_muuta")


def export_cad(layers, folder, combined=False, progress=None, symbology_scale=None, project=None,
                target_crs=None, format_name="DXF", writer=None, notes=None):
    """Export vector layers to DXF. Returns (written paths per layer, failures).

    Ilman ``target_crs``:ää jokainen tasokohtainen DXF säilyttää tason oman
    koordinaatiston. Yhteen DXF:ään mahtuu vain yksi koordinaatisto, joten
    eri koordinaatistoissa olevia tasoja ei yhdistetä ilman kohdekoordinaatistoa.
    """
    project = project or processing._project()
    invalid = [layer.name() for layer in layers if not layer.isValid()]
    if invalid:
        raise RuntimeError("Tasot eivät ole kelvollisia (tietolähde puuttuu): " + ", ".join(invalid))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = target_crs if target_crs is not None and target_crs.isValid() else None
    if combined and target is None:
        systems = {layer.crs().authid() or "tuntematon" for layer in layers}
        if len(systems) > 1:
            raise RuntimeError(
                "Tasot ovat eri koordinaatistoissa (" + ", ".join(sorted(systems)) + "), eikä yhteen "
                f"{format_name}-tiedostoon mahdu kuin yksi koordinaatisto. Valitse kohdekoordinaatisto tai vie tasot "
                "omiin tiedostoihinsa, jolloin jokainen taso säilyttää omansa.")
    groups = ([(list(layers), combined_export_name(layers, project))] if combined
              else [([layer], formats.safe_name(layer.name())) for layer in layers])
    successes, failures = [], []
    for index, (group, name) in enumerate(groups, 1):
        if progress:
            progress(index, len(groups), name)
        try:
            # Tason oma koordinaatisto; tuntemattomalle tasolle projektin koordinaatisto.
            own = group[0].crs()
            crs = target or (own if own.isValid() else _destination_crs(group, project))
            path = formats.unique_path(folder / f"{name}.{format_name.lower()}")
            written = writer(group, path, crs, project, notes) if writer else write_dxf(group, path, crs, symbology_scale, project)
            successes.extend(str(written) for _layer in group)
        except Exception as exc:
            if combined:
                raise
            failures.append((group[0].name(), str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
