"""Native QGIS import/export operations. No ArcPy dependency."""

import os
import re
import struct
from pathlib import Path

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


class OperationCanceled(Exception):
    pass


def safe_name(name):
    name = re.sub(r"[^\w-]+", "_", str(name), flags=re.UNICODE).strip("_-")
    return name[:80] or "layer"


def classify_finnish_xy(x, y):
    if 19 <= x <= 32.5 and 59 <= y <= 71.5:
        return 4326
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


def inferred_crs(layer, path=None):
    try:
        extent = layer.extent()
        code = classify_finnish_xy(extent.center().x(), extent.center().y())
        if code:
            return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    except Exception:
        pass
    if path and "etrs89" in str(path).casefold():
        return QgsCoordinateReferenceSystem("EPSG:3067")
    return None


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Vapaata tiedostonimeä ei löytynyt: {path}")


def has_georeference(path):
    path = Path(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return True
    return any(path.with_suffix(ext).exists() for ext in WORLD_FILES) or Path(str(path) + ".aux.xml").exists()


def scan_inputs(paths):
    """Expand folders recursively, ignore Shapefile sidecars and unlocated images."""
    found, seen = [], set()
    for entry in paths:
        root = Path(entry)
        candidates = root.rglob("*") if root.is_dir() else [root]
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in VECTOR_EXTENSIONS | RASTER_EXTENSIONS | {".dfsu"}:
                continue
            if not has_georeference(path):
                continue
            key = os.path.normcase(str(path.resolve()))
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found


def raster_group(path):
    for part in reversed(path.parts[:-1]):
        if part.lower().startswith("taustakartta_"):
            return part
    return path.parent.name


def _write_vector(layer, path, driver, layer_name=None, target_crs=None, append=False):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    if driver == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    if layer_name:
        options.layerName = layer_name
    if append:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    if target_crs and target_crs.isValid() and layer.crs() != target_crs:
        from qgis.core import QgsCoordinateTransform
        options.ct = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), QgsProject.instance().transformContext(), options)
    if result[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(result[3] or f"Kirjoitusvirhe: {result[0]}")
    return path


def _write_combined_dxf(layers, path):
    from osgeo import ogr
    driver = ogr.GetDriverByName("DXF")
    datasource = driver.CreateDataSource(str(path))
    if datasource is None:
        raise RuntimeError("DXF-tiedostoa ei voitu luoda")
    target = datasource.CreateLayer("entities", geom_type=ogr.wkbUnknown)
    if target is None:
        raise RuntimeError("DXF-tasoa ei voitu luoda")
    layer_field = target.GetLayerDefn().GetFieldIndex("Layer")
    for layer in layers:
        for source in layer.getFeatures():
            if source.geometry().isEmpty():
                continue
            feature = ogr.Feature(target.GetLayerDefn())
            feature.SetGeometry(ogr.CreateGeometryFromWkb(bytes(source.geometry().asWkb())))
            if layer_field >= 0:
                feature.SetField(layer_field, safe_name(layer.name())[:31])
            if target.CreateFeature(feature) != 0:
                raise RuntimeError(f"DXF-geometrian kirjoitus epäonnistui: {layer.name()}")
    target = None
    datasource = None
    return path


def _open_vector_layers(path):
    """QGIS/OGR handles CAD, GPX, KMZ and multi-layer GeoPackages."""
    probe = QgsVectorLayer(str(path), path.stem, "ogr")
    if not probe.isValid():
        raise RuntimeError(f"Vektorimuotoa ei voitu avata: {path}")
    sublayers = probe.dataProvider().subLayers()
    if not sublayers:
        return [probe]
    layers = []
    for item in sublayers:
        parts = item.split("!!::!!")
        if len(parts) < 2:
            continue
        name = parts[1]
        uri = f"{path}|layername={name}"
        layer = QgsVectorLayer(uri, name, "ogr")
        if layer.isValid():
            layers.append(layer)
    return layers or [probe]


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


def _import_dfsu(path, destination, workspace, source_crs, target_crs, filter_column, filter_operator, filter_value):
    try:
        import mikeio
    except ImportError as exc:
        raise RuntimeError("DFSU-tuonti vaatii mikeio-kirjaston QGISin Python-ympäristöön") from exc
    dataset = mikeio.read(str(path), time=0)
    geometry = dataset.geometry
    element_table = getattr(geometry, "element_table", None)
    node_coordinates = getattr(geometry, "node_coordinates", None)
    element_coordinates = getattr(geometry, "element_coordinates", None)
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
    transform = QgsCoordinateTransform(sr, output_crs, QgsProject.instance()) if output_crs != sr else None
    name = safe_name(path.stem)
    if workspace:
        output_path = destination
        existing = set()
        if destination.exists():
            probe = QgsVectorLayer(str(destination), "probe", "ogr")
            existing = {part.split("!!::!!")[1] for part in probe.dataProvider().subLayers() if "!!::!!" in part}
        base, number = name, 2
        while name in existing:
            name = f"{base[:65]}_{number}"
            number += 1
    else:
        output_path = unique_path(destination / f"{name}.gpkg")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "OpenFileGDB" if output_path.suffix.lower() == ".gdb" else "GPKG"
    if options.driverName == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    options.layerName = name
    if output_path.exists():
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(str(output_path), fields, QgsWkbTypes.Unknown,
                                        output_crs, QgsProject.instance().transformContext(), options)
    if writer.hasError() != QgsVectorFileWriter.NoError:
        error = writer.errorMessage()
        del writer
        raise RuntimeError(error)
    written = 0
    try:
        for index in range(total):
            if filter_column:
                matched = next(name for name in item_names if name.casefold() == filter_column.casefold())
                if not _dfsu_matches(values[matched][index], filter_operator, filter_value):
                    continue
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
            for name in item_names:
                try:
                    number = float(values[name][index])
                    attrs.append(number if number == number else None)
                except (ValueError, TypeError):
                    attrs.append(None)
            feature.setAttributes(attrs)
            feature.setGeometry(geom)
            if not writer.addFeature(feature):
                raise RuntimeError(writer.errorMessage())
            written += 1
    finally:
        del writer
    if not written:
        raise RuntimeError("DFSU-suodatus ei tuottanut kohteita")
    result = QgsVectorLayer(f"{output_path}|layername={name}", name, "ogr")
    if not result.isValid():
        probe = QgsVectorLayer(str(output_path), name, "ogr")
        sublayers = probe.dataProvider().subLayers() if probe.isValid() else []
        for sublayer in sublayers:
            parts = sublayer.split("!!::!!")
            if len(parts) > 1 and parts[1] == name:
                result = QgsVectorLayer(f"{output_path}|layerid={parts[0]}", name, "ogr")
                break
        if not result.isValid() and len(sublayers) == 1:
            result = probe
        if not result.isValid():
            raise RuntimeError("DFSU-tulosta ei voitu avata")
    QgsProject.instance().addMapLayer(result)


def import_data(paths, destination, source_crs=None, target_crs=None, clean_cad=False,
                progress=None, dfsu_filter_column="", dfsu_filter_operator="=", dfsu_filter_value=""):
    """Import vectors to a GeoPackage or folder; add located rasters by reference."""
    project = QgsProject.instance()
    items = scan_inputs(paths)
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
    groups = {}
    for index, path in enumerate(items, 1):
        if progress:
            progress(index, len(items), str(path))
        try:
            if path.suffix.lower() in RASTER_EXTENSIONS:
                raster = QgsRasterLayer(str(path), path.stem)
                if not raster.isValid():
                    raise RuntimeError("Rasteria ei voitu avata")
                if not raster.crs().isValid() and source_crs and source_crs.isValid():
                    raster.setCrs(source_crs)
                elif not raster.crs().isValid():
                    inferred = inferred_crs(raster, path)
                    if inferred:
                        raster.setCrs(inferred)
                group_name = raster_group(path)
                group = groups.get(group_name)
                if group is None:
                    group = project.layerTreeRoot().findGroup(group_name) or project.layerTreeRoot().addGroup(group_name)
                    groups[group_name] = group
                if any(node.layer() and node.layer().source() == str(path) for node in group.findLayers()):
                    continue
                project.addMapLayer(raster, False)
                group.addLayer(raster)
                successes.append(str(path))
                continue
            if path.suffix.lower() == ".dfsu":
                _import_dfsu(path, destination, workspace, source_crs, target_crs,
                             dfsu_filter_column, dfsu_filter_operator, dfsu_filter_value)
                successes.append(str(path))
                continue
            layers = _open_vector_layers(path)
            written = 0
            for layer in layers:
                if clean_cad and path.suffix.lower() in {".dwg", ".dxf"} and layer.name().casefold() in {"defpoints", "0"}:
                    continue
                if clean_cad and path.suffix.lower() in {".dwg", ".dxf"} and "Layer" in layer.fields().names():
                    if not layer.setSubsetString('"Layer" NOT IN (\'Defpoints\', \'0\')'):
                        raise RuntimeError("CAD-tason siivous ei onnistu tälle tiedostolle")
                if layer.featureCount() == 0:
                    continue
                if not layer.crs().isValid() and source_crs and source_crs.isValid():
                    layer.setCrs(source_crs)
                elif not layer.crs().isValid():
                    inferred = inferred_crs(layer, path)
                    if inferred:
                        layer.setCrs(inferred)
                name = safe_name(f"{path.stem}_{layer.name()}")
                if workspace:
                    existing = set(QgsVectorLayer(str(destination), "probe", "ogr").dataProvider().subLayers()) if destination.exists() else set()
                    existing_names = {part.split("!!::!!")[1] for part in existing if "!!::!!" in part}
                    base, number = name, 2
                    while name in existing_names:
                        name = f"{base[:65]}_{number}"
                        number += 1
                    _write_vector(layer, destination, "OpenFileGDB" if file_gdb else "GPKG",
                                  name, target_crs, destination.exists())
                    output = QgsVectorLayer(f"{destination}|layername={name}", name, "ogr")
                else:
                    output_path = unique_path(destination / f"{name}.gpkg")
                    _write_vector(layer, output_path, "GPKG", name, target_crs)
                    output = QgsVectorLayer(str(output_path), name, "ogr")
                if not output.isValid():
                    raise RuntimeError("Kirjoitettua tasoa ei voitu avata")
                project.addMapLayer(output)
                written += 1
            if not written:
                raise RuntimeError("Tiedostossa ei ollut tuotavia kohteita")
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((str(path), str(exc)))
    if not successes:
        raise RuntimeError("Yksikään tiedosto ei onnistunut: " + "; ".join(f"{p}: {e}" for p, e in failures))
    return successes, failures


def export_data(layers, folder, format_name, combined=False, progress=None):
    if format_name == "DWG":
        raise RuntimeError("DWG-vienti tarvitsee erillisen DWG-kirjoittimen. QGISin GDAL tukee vain DWG-lukua.")
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
        _write_combined_dxf(layers, common_path)
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
            _write_vector(layer, path, driver, layer_name if format_name == "GPKG" else None,
                          append=bool(common_path and path.exists()))
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((layer.name(), str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
