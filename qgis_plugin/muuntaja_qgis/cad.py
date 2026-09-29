"""DWG/DXF import and export that behave like native QGIS layers.

Tuonti lukee CAD-kohteet GDAL:n DXF-ajurilla (DWG muunnetaan ensin DXF:ksi
LibreDWG:llä, joka tulee Windowsissa lisäosan mukana) ja kirjoittaa ne neljäksi tasoksi:
tekstit, pisteet, viivat ja alueet. Tasot saavat CAD-värit, CAD-tasot
näkyvät sisällysluettelossa päälle/pois kytkettävinä sääntöinä ja tekstit
nimiöinä. Vienti käyttää QGISin omaa DXF-vientiä, joten tasojen symbologia,
nimiöt ja CAD-tasonimet säilyvät; DWG tehdään DXF:stä LibreDWG:llä (kokeellinen).
"""

import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDxfExport, QgsExpression,
    QgsFeature, QgsField, QgsFields, QgsFillSymbol, QgsGeometry, QgsLineSymbol, QgsMapSettings,
    QgsMarkerSymbol, QgsNullSymbolRenderer, QgsPalLayerSettings, QgsProject, QgsProperty, QgsRectangle,
    QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsSymbolLayer, QgsTextFormat,
    QgsVectorFileWriter, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QFile
from qgis.PyQt.QtGui import QColor

from . import formats
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


# --- DWG <-> DXF conversion ---------------------------------------------------

def converter_status():
    """Describe the DWG converter that would be used (for the user interface)."""
    tool = formats.find_libredwg_tool("dwg2dxf")
    if not tool:
        return ""
    bundled = Path(tool).parent == formats.BUNDLED_LIBREDWG
    return "LibreDWG (lisäosan mukana)" if bundled else f"LibreDWG: {Path(tool).parent}"


def missing_converter_message(action, version=""):
    detail = f" ({formats.dwg_version_label(version)})" if version else ""
    return (f"DWG{detail} {action} vaatii LibreDWG:n. Windowsissa se tulee lisäosan mukana; "
            "muilla alustoilla asenna LibreDWG (komennot dwg2dxf ja dxf2dwg) tai tallenna piirustus DXF-muotoon.")


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


def dxf_to_dwg(dxf_paths, output_folder):
    """Convert DXF files to DWG files in ``output_folder``; returns {dxf: dwg}."""
    output_folder = Path(output_folder)
    produced = {}
    tool = formats.find_libredwg_tool("dxf2dwg")
    if not tool:
        raise RuntimeError(missing_converter_message("vienti"))
    for dxf in dxf_paths:
        target = formats.unique_path(output_folder / f"{Path(dxf).stem}.dwg")
        try:
            formats.run_converter([tool, "-y", "-o", target, dxf], "LibreDWG dxf2dwg")
            _check_dwg(target, dxf)
            _verify_libredwg_output(target, dxf)
        except Exception:
            Path(target).unlink(missing_ok=True)
            raise
        produced[str(dxf)] = str(target)
    return produced


def _entity_count(path):
    buckets, _samples = read_cad(path)
    return sum(len(records) for records in buckets.values())


def _verify_libredwg_output(dwg, dxf):
    """LibreDWG:n DWG-kirjoitus on kokeellinen: varmista ettei kohteita katoa."""
    reader = formats.find_libredwg_tool("dwg2dxf")
    if not reader:
        return
    with tempfile.TemporaryDirectory(prefix="muuntaja_verify_") as temp:
        back = Path(temp) / "tarkistus.dxf"
        formats.run_converter([reader, "-y", "-o", back, dwg], "LibreDWG dwg2dxf (tarkistus)")
        expected = _entity_count(dxf)
        try:
            actual = _entity_count(back)
        except RuntimeError:
            actual = 0
    if actual < expected:
        raise RuntimeError(
            f"LibreDWG kirjoitti DWG:hen vain {actual}/{expected} kohdetta. LibreDWG:n "
            "DWG-kirjoitus on vielä kokeellinen: vie DXF-muotoon.")


def _check_dwg(path, source):
    # QGISin CAD-ajuri ei avaa AutoCAD 2004+ -tiedostoja, joten DWG:n kelpoisuus
    # tarkistetaan tiedoston otsakkeesta eikä avaamalla sitä tasona.
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 512 or not formats.dwg_version(path):
        raise RuntimeError(f"DWG-muunnin ei tuottanut kelvollista DWG-tiedostoa: {Path(source).name}")


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


def read_cad(path, clean_cad=False):
    """Read model-space CAD entities; returns {bucket: [record]} and sample points."""
    from osgeo import gdal
    buckets = {name: [] for name, _flat, _z in BUCKETS}
    samples = []
    with _gdal_config(DXF_MERGE_BLOCK_GEOMETRIES="FALSE", DXF_INLINE_BLOCKS="TRUE"):
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
                    cad_layer = str(_field(feature, "Layer", "layer") or source_layer.GetName())
                    if clean_cad and cad_layer.casefold() in SKIPPED_CAD_LAYERS:
                        continue
                    style = formats.parse_ogr_style(feature.GetStyleString())
                    color = style["color"] or formats.parse_ogr_style(
                        f"PEN(c:{_field(feature, 'color') or ''})")["color"]
                    if color == "#ffffff":
                        # ACI 7 on "valkoinen/musta": musta näkyy vaalealla kartalla.
                        color = DEFAULT_COLOR
                    subclasses = str(_field(feature, "SubClasses", "cadgeom_type") or "")
                    entity = subclasses.split(":")[-1] if subclasses else ""
                    text = style["text"] or str(_field(feature, "Text", "text") or "")
                    for part in _flatten(feature.GetGeometryRef()):
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
    code = formats.vote_finnish_epsg(samples[::max(1, len(samples) // 2000)])
    if code:
        return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    if "etrs89" in str(path).casefold():
        return QgsCoordinateReferenceSystem("EPSG:3067")
    raise CrsNotDetected("CAD-tiedoston koordinaatistoa ei tunnistettu (DWG/DXF ei sisällä sitä). "
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
                                        QgsProject.instance().transformContext(), options)
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
    if path.suffix.lower() == ".dxf":
        return path
    version = formats.dwg_version(path)
    if formats.find_libredwg_tool("dwg2dxf"):
        return dwg_to_dxf(path, work_folder)
    if version in formats.OGR_CAD_READABLE_DWG:
        return path
    raise RuntimeError(missing_converter_message("tuonti", version))


def import_cad(path, destination, source_crs=None, target_crs=None, clean_cad=False,
               project=None, add_to_project=True):
    """Import one DWG/DXF; returns the created QGIS layers."""
    project = project or QgsProject.instance()
    path = Path(path)
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix="muuntaja_cad_") as work_folder:
        source = _open_source(path, work_folder)
        buckets, samples = read_cad(source, clean_cad)
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


def write_dxf(layers, path, crs=None, symbology_scale=None, project=None, mtext=True):
    """Export layers with QGIS' own DXF writer (symbology, labels, CAD layer names)."""
    project = project or QgsProject.instance()
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
    if not mtext:
        export.setFlags(QgsDxfExport.Flags(QgsDxfExport.FlagNoMText))
    result = export.writeToFile(QFile(str(path)), "UTF-8")
    if result != QgsDxfExport.ExportResult.Success:
        messages = {
            QgsDxfExport.ExportResult.DeviceNotWritableError: "DXF-tiedostoa ei voitu kirjoittaa",
            QgsDxfExport.ExportResult.EmptyExtentError: "Vietävien kohteiden laajuus on tyhjä",
            QgsDxfExport.ExportResult.InvalidDeviceError: "DXF-tiedostoa ei voitu luoda",
        }
        raise RuntimeError(f"{messages.get(result, 'DXF-vienti epäonnistui')}: {path}")
    return Path(path)


def export_cad(layers, folder, format_name, combined=False, progress=None,
               symbology_scale=None, project=None):
    """Export vector layers to DXF or DWG. Returns (written paths per layer, failures)."""
    project = project or QgsProject.instance()
    if format_name == "DWG" and not formats.find_libredwg_tool("dxf2dwg"):
        raise RuntimeError(missing_converter_message("vienti"))
    invalid = [layer.name() for layer in layers if not layer.isValid()]
    if invalid:
        raise RuntimeError("Tasot eivät ole kelvollisia (tietolähde puuttuu): " + ", ".join(invalid))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    crs = _destination_crs(layers, project)
    # LibreDWG:n dxf2dwg hylkää QGISin MTEXT-kohteet ("Invalid DXF code 50");
    # DWG:tä varten tekstit kirjoitetaan yksirivisinä TEXT-kohteina.
    mtext = format_name == "DXF"
    groups = [(list(layers), "muuntaja_vienti")] if combined else \
        [([layer], formats.safe_name(layer.name())) for layer in layers]
    successes, failures = [], []
    with tempfile.TemporaryDirectory(prefix="muuntaja_dxf_") as temp:
        for index, (group, name) in enumerate(groups, 1):
            if progress:
                progress(index, len(groups), name)
            try:
                if format_name == "DXF":
                    target = write_dxf(group, formats.unique_path(folder / f"{name}.dxf"), crs,
                                       symbology_scale, project)
                else:
                    dxf = write_dxf(group, formats.unique_path(Path(temp) / f"{name}.dxf"), crs,
                                    symbology_scale, project, mtext)
                    target = dxf_to_dwg([dxf], folder)[str(dxf)]
                successes.extend(str(target) for _layer in group)
            except Exception as exc:
                if combined:
                    raise
                failures.append((group[0].name(), str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
