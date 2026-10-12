"""Bounded GIS processing, deterministic disposal, and per-task project context."""

import json
import math
import operator
import os
import re
import uuid
from collections import Counter
from contextvars import ContextVar
from pathlib import Path

from .formats import (
    safe_name,
    classify_finnish_xy,
    unique_path,
    dfsu_matches as _dfsu_matches,
    dfsu_wkb as _dfsu_wkb,
)

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


_operation_project = ContextVar("muuntaja_operation_project", default=None)


def _project():
    return _operation_project.get() or QgsProject.instance()


class OperationCanceled(Exception):
    pass


def gdb_safe_name(name):
    name = safe_name(name).replace("-", "_")
    if name[0].isdigit() or name.casefold() in {
        "select",
        "table",
        "where",
        "from",
        "order",
    }:
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
        return {
            parts[1]
            for item in probe.dataProvider().subLayers()
            if len(parts := item.split("!!::!!")) > 1
        }
    finally:
        _dispose(probe)


def inferred_crs(layer, path=None):
    try:
        extent = layer.extent()
        code = classify_finnish_xy(extent.center().x(), extent.center().y())
        if code:
            return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    except Exception:
        pass
    if path and Path(path).suffix.lower() in {".dwg", ".dxf", ".dgn"}:
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
        return (
            math.isfinite(point.x())
            and math.isfinite(point.y())
            and 18 <= point.x() <= 33
            and 59 <= point.y() <= 72
        )
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
        if (
            current.authid() in {"EPSG:4326", "EPSG:3857"}
            and guessed
            and guessed.isValid()
            and current != guessed
            and _center_in_finland(layer, guessed)
            and not _center_in_finland(layer, current)
        ):
            raise RuntimeError(
                f"Tason koordinaatisto on {current.authid()}, mutta koordinaatit näyttävät "
                f"järjestelmältä {guessed.authid()}. Aseta oikea lähtö-CRS "
                "lisäasetusten Lähtö-CRS (pakota) -kentässä."
            )
        return
    if guessed:
        layer.setCrs(guessed)
        return
    raise RuntimeError(
        "Lähtökoordinaatistoa ei tunnistettu. Aseta lähtö-CRS lisäasetuksissa."
    )


def _ensure_project_crs(project, layer):
    """Turn on coordinate transformations in projects saved without a CRS."""
    if not layer.crs().isValid():
        raise RuntimeError(f"Tason koordinaatistoa ei tunnistettu: {layer.name()}")
    if not project.crs().isValid():
        project.setCrs(layer.crs())


def _add_project_layer(project, layer, add_to_legend=True):
    _ensure_project_crs(project, layer)
    project.addMapLayer(layer, add_to_legend)


def _shapefile_converter(layer):
    """Preserve columns with unique DBF names and explicit text truncation."""
    from qgis.core import QgsMessageLog
    from .qgisutil import field_type

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
            name = base[: 10 - len(suffix)] + suffix
            number += 1
        used.add(name.casefold())
        field.setName(name)
        widths.append(
            min(field.length() or 254, 254)
            if field.type() == field_type("string")
            else 32
        )
    if len(fields) > 255:
        raise ValueError("Shapefile tukee enintään 255 kenttää; käytä GeoPackagea.")
    original = list(widths)
    for limit in (80, 50, 1):
        if 1 + sum(widths) <= 3900:
            break
        widths = [
            min(width, limit) if field.type() == field_type("string") else width
            for field, width in zip(fields, widths)
        ]
    if 1 + sum(widths) > 3900:
        raise ValueError(
            "Shapefilen riviraja ylittyy; käytä GeoPackagea sarakkeiden säilyttämiseen."
        )
    for field, width in zip(fields, widths):
        if field.type() == field_type("string"):
            field.setLength(width)
    if widths != original:
        QgsMessageLog.logMessage(
            "Shapefile: tekstikenttiä lyhennetään rivirajan vuoksi. "
            "Käytä GeoPackagea pitkien arvojen säilyttämiseen.",
            "Muuntaja",
        )

    class Converter(QgsVectorFileWriter.FieldValueConverter):
        def fieldDefinition(self, field):
            return fields[layer.fields().indexFromName(field.name())]

        def convert(self, index, value):
            if fields[index].type() == field_type("string") and isinstance(value, str):
                # GDAL laskee UTF-8-tekstin leveyden tavuina.
                return value.encode("utf-8")[: widths[index]].decode(
                    "utf-8", errors="ignore"
                )
            return value

        def clone(self):
            return Converter()

    return Converter()


def _write_vector(
    layer,
    path,
    driver,
    layer_name=None,
    target_crs=None,
    append=False,
    feature_filter=None,
    progress=None,
):
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
    writer = QgsVectorFileWriter.create(
        str(path),
        fields,
        layer.wkbType(),
        output_crs,
        _project().transformContext(),
        options,
    )
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
            feature.setAttributes(
                [
                    converter.convert(i, value) if converter else value
                    for i, value in enumerate(source.attributes())
                ]
            )
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


def _validate_vector_file(path):
    extension = path.suffix.lower()
    if extension == ".shp":
        with os.scandir(path.parent) as entries:
            names = {entry.name.casefold() for entry in entries if entry.is_file()}
        missing = [
            ext
            for ext in (".dbf", ".shx")
            if path.with_suffix(ext).name.casefold() not in names
        ]
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
            if archive.testzip() is not None or not any(
                name.lower().endswith(".kml") for name in archive.namelist()
            ):
                raise ValueError(
                    "KMZ-arkisto on virheellinen tai KML-dokumentti puuttuu"
                )


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
    cad = path.suffix.lower() in {".dwg", ".dxf", ".dgn"}
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


class _DfsuWriter:
    """Write bounded feature batches in OGR transactions, including FileGDB."""

    def __init__(self, path, name, fields, crs, geometry_type):
        from osgeo import ogr, osr

        self.ogr = ogr
        driver = ogr.GetDriverByName(
            "OpenFileGDB" if path.suffix.lower() == ".gdb" else "GPKG"
        )
        self.dataset = (
            driver.Open(str(path), 1)
            if path.exists()
            else driver.CreateDataSource(str(path))
        )
        if self.dataset is None:
            raise RuntimeError(f"DFSU-tallennuspaikkaa ei voitu avata: {path}")
        sr = osr.SpatialReference()
        sr.ImportFromWkt(crs.toWkt())
        options = (
            ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
            if path.suffix.lower() == ".gdb"
            else []
        )
        self.layer = self.dataset.CreateLayer(name, sr, geometry_type, options=options)
        if self.layer is None:
            self.close()
            raise RuntimeError("DFSU-tasoa ei voitu luoda")
        self.name = self.layer.GetName()
        for index, field in enumerate(fields):
            definition = ogr.FieldDefn(
                field.name(), ogr.OFTInteger64 if index == 0 else ogr.OFTReal
            )
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
                        feature.SetField(
                            index, int(value) if index == 0 else float(value)
                        )
                feature.SetGeometry(
                    self.ogr.CreateGeometryFromWkb(bytes(source.geometry().asWkb()))
                )
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


def _import_dfsu(
    path,
    destination,
    workspace,
    source_crs,
    target_crs,
    filter_column,
    filter_operator,
    filter_value,
    existing_names=None,
    progress=None,
):
    try:
        import mikeio
    except ImportError as exc:
        raise RuntimeError(
            "DFSU-tuonti vaatii mikeio-kirjaston QGISin Python-ympäristöön"
        ) from exc
    dataset = mikeio.read(str(path), time=0)
    geometry = dataset.geometry
    element_table = getattr(geometry, "element_table", None)
    node_coordinates = getattr(geometry, "node_coordinates", None)
    # Computing every element centroid allocates large temporary arrays in
    # mikeio. Mesh polygons use node coordinates and never need these centers.
    element_coordinates = (
        getattr(geometry, "element_coordinates", None)
        if element_table is None
        else None
    )
    if element_table is None and element_coordinates is None:
        raise RuntimeError("DFSU-elementtien geometriaa ei löytynyt")
    total = (
        len(element_table) if element_table is not None else len(element_coordinates)
    )
    item_names = [item.name for item in dataset.items]
    if filter_column and filter_column.casefold() not in {
        name.casefold() for name in item_names
    }:
        raise ValueError(f"DFSU-suodatinsaraketta ei löytynyt: {filter_column}")
    values = {}
    for name in item_names:
        array = dataset[name].to_numpy()
        if getattr(array, "ndim", 0) >= 2:
            array = array[0]
        values[name] = array.reshape(-1) if hasattr(array, "reshape") else array
    from .qgisutil import field_type

    fields = QgsFields()
    fields.append(QgsField("element_id", field_type("int")))
    field_names = []
    for name in item_names:
        field_name = safe_name(name)[:30]
        base, number = field_name, 2
        while field_name.casefold() in {field.casefold() for field in field_names}:
            field_name = f"{base[:26]}_{number}"
            number += 1
        field_names.append(field_name)
        fields.append(QgsField(field_name, field_type("double")))
    sr = source_crs
    if sr is None:
        projection = str(getattr(geometry, "projection_string", "") or "")
        sr = QgsCoordinateReferenceSystem(projection)
        if not sr.isValid():
            sr = QgsCoordinateReferenceSystem.fromWkt(projection)
    if sr is None or not sr.isValid():
        raise RuntimeError("DFSU:n koordinaatistoa ei tunnistettu; anna lähtö-CRS")
    output_crs = target_crs if target_crs and target_crs.isValid() else sr
    transform = (
        QgsCoordinateTransform(sr, output_crs, _project()) if output_crs != sr else None
    )
    name = (
        gdb_safe_name(path.stem)
        if destination.suffix.lower() == ".gdb"
        else safe_name(path.stem)
    )
    if workspace:
        output_path = destination
        existing = (
            existing_names
            if existing_names is not None
            else _workspace_names(destination)
        )
        base, number = name, 2
        while name in existing:
            name = f"{base[:65]}_{number}"
            number += 1
    else:
        output_path = unique_path(destination / f"{name}.gpkg")
    from osgeo import ogr

    sizes = (
        {len(nodes) for nodes in element_table} if element_table is not None else {1}
    )
    types = {1 if size == 1 else 2 if size == 2 else 3 for size in sizes if size}
    if len(types) != 1:
        raise ValueError(
            "DFSU sisältää eri geometriatyyppejä; taso on jaettava ennen tuontia."
        )
    geometry_type = {1: ogr.wkbPoint, 2: ogr.wkbLineString, 3: ogr.wkbPolygon}[
        types.pop()
    ]
    written = 0
    matched = next(
        (name for name in item_names if name.casefold() == filter_column.casefold()),
        None,
    )
    indices = range(total)
    if matched:
        import numpy as np

        comparisons = {
            "=": operator.eq,
            "≠": operator.ne,
            ">": operator.gt,
            ">=": operator.ge,
            "<": operator.lt,
            "<=": operator.le,
        }
        if filter_operator in comparisons:
            expected = float(str(filter_value).replace(",", "."))
            column = np.asarray(values[matched], dtype=float)
            indices = np.flatnonzero(
                np.isfinite(column) & comparisons[filter_operator](column, expected)
            )
        else:
            indices = np.flatnonzero(
                [
                    _dfsu_matches(value, filter_operator, filter_value)
                    for value in values[matched]
                ]
            )
    writer = _DfsuWriter(output_path, name, fields, output_crs, geometry_type)
    name = writer.name
    batch = []
    try:
        for index in indices:
            index = int(index)
            if progress and written % 1000 == 0:
                progress(written + 1, max(len(indices), 1), path.name)
            if element_table is not None and node_coordinates is not None:
                points = [
                    (
                        float(node_coordinates[int(node)][0]),
                        float(node_coordinates[int(node)][1]),
                    )
                    for node in element_table[index]
                ]
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


def _add_raster_group(
    project, group_name, paths, destination, source_crs, failures=None, progress=None
):
    """Validate one tile at a time and publish a new VRT before replacing layers."""
    from osgeo import gdal

    failures = failures if failures is not None else []
    group = project.layerTreeRoot().findGroup(
        group_name
    ) or project.layerTreeRoot().addGroup(group_name)
    prior = [
        node.layer()
        for node in group.findLayers()
        if node.layer() is not None
        and (
            node.layer().customProperty("muuntaja/managed", False)
            or node.layer().customProperty("muuntaja/source_paths", [])
        )
    ]
    existing = []
    for layer in prior:
        existing.extend(
            layer.customProperty("muuntaja/source_paths", []) or [layer.source()]
        )
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
                raise RuntimeError(
                    "Rasteri on virheellinen tai siitä puuttuu georeferointi"
                )
            dataset = None
            raster = QgsRasterLayer(str(path), Path(path).stem)
            if not raster.isValid():
                raise RuntimeError("Rasteria ei voitu avata")
            assign_source_crs(raster, path, source_crs)
            if crs is None:
                crs = raster.crs()
            elif raster.crs() != crs:
                raise RuntimeError(
                    "Rasteriryhmän koordinaatistot eroavat; projisoi rasterit samaan CRS:ään"
                )
            valid.append(str(path))
        except Exception as exc:
            failures.append((str(path), str(exc)))
        finally:
            dataset = None
            _dispose(raster)
    if not valid:
        return []
    root = (
        destination.parent
        if destination.suffix.lower() in {".gpkg", ".gdb"}
        else destination
    )
    root.mkdir(parents=True, exist_ok=True)
    # Uniikki nimi välttää myös muissa ryhmissä/projekteissa avoimen VRT:n korvaamisen.
    output = (
        root
        / f"muuntaja_{safe_name(destination.stem)}_{safe_name(group_name)}_{uuid.uuid4().hex[:12]}.vrt"
    )
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
        layer.setCustomProperty("muuntaja/managed", True)
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
