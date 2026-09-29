"""Native QGIS import/export operations. No ArcPy dependency."""

import os
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField, QgsFields,
    QgsGeometry, QgsProject, QgsRasterLayer, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
)

from . import cad
from .formats import (  # noqa: F401  (julkinen rajapinta lisäosalle ja testeille)
    CAD_EXTENSIONS, RASTER_EXTENSIONS, VECTOR_EXTENSIONS, classify_finnish_xy, dfsu_matches,
    dfsu_wkb, find_oda_converter, has_georeference, raster_group, safe_name, scan_inputs,
    unique_name, unique_path,
)
from .qgisutil import (  # noqa: F401
    add_project_layer, assign_source_crs, ensure_project_crs, field_type, inferred_crs, write_vector,
)

DRIVERS = {"GPKG": ("GPKG", ".gpkg"), "GeoJSON": ("GeoJSON", ".geojson"),
           "Shapefile": ("ESRI Shapefile", ".shp"), "KML": ("LIBKML", ".kml"),
           "KMZ": ("LIBKML", ".kmz")}
CAD_FORMATS = ("DXF", "DWG")
EXPORT_FORMATS = list(DRIVERS) + list(CAD_FORMATS)
MANAGED_PROPERTY = "muuntaja/managed"
SOURCE_PATHS_PROPERTY = "muuntaja/source_paths"


class OperationCanceled(Exception):
    pass


def _open_vector_layers(path):
    """QGIS/OGR handles GPX, KMZ and multi-layer GeoPackages."""
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
        layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
        if layer.isValid():
            layers.append(layer)
    return layers or [probe]


def _import_dfsu(path, destination, workspace, source_crs, target_crs, filter_column, filter_operator,
                 filter_value, project):
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
    matched_filter = None
    if filter_column:
        matched_filter = next((item for item in item_names if item.casefold() == filter_column.casefold()), None)
        if matched_filter is None:
            raise ValueError(f"DFSU-suodatinsaraketta ei löytynyt: {filter_column}")
    values = {}
    for item in item_names:
        array = dataset[item].to_numpy()
        if getattr(array, "ndim", 0) >= 2:
            array = array[0]
        values[item] = array.reshape(-1) if hasattr(array, "reshape") else array
    fields = QgsFields()
    fields.append(QgsField("element_id", field_type("int")))
    field_names = []
    for item in item_names:
        field_name = unique_name(safe_name(item)[:30], field_names, 30)
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
    transform = QgsCoordinateTransform(sr, output_crs, project) if output_crs != sr else None
    layer_name = safe_name(path.stem)
    if workspace:
        output_path = destination
        layer_name = unique_name(layer_name, cad.existing_layer_names(destination), 80)
    else:
        output_path = unique_path(destination / f"{layer_name}.gpkg")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "OpenFileGDB" if output_path.suffix.lower() == ".gdb" else "GPKG"
    if options.driverName == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    options.layerName = layer_name
    if output_path.exists():
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(str(output_path), fields, QgsWkbTypes.Unknown,
                                        output_crs, project.transformContext(), options)
    if writer.hasError() != QgsVectorFileWriter.NoError:
        error = writer.errorMessage()
        del writer
        raise RuntimeError(error)
    written = 0
    try:
        for index in range(total):
            if matched_filter and not dfsu_matches(values[matched_filter][index], filter_operator, filter_value):
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
            geom.fromWkb(dfsu_wkb(points))
            if transform:
                geom.transform(transform)
            feature = QgsFeature(fields)
            attributes = [index + 1]
            # Oma silmukkamuuttuja: aiemmin ``name`` ylikirjoitti tason nimen,
            # jolloin valmis taso avattiin väärällä nimellä.
            for item in item_names:
                try:
                    number = float(values[item][index])
                    attributes.append(number if number == number else None)
                except (ValueError, TypeError):
                    attributes.append(None)
            feature.setAttributes(attributes)
            feature.setGeometry(geom)
            if not writer.addFeature(feature):
                raise RuntimeError(writer.errorMessage())
            written += 1
    finally:
        del writer
    if not written:
        raise RuntimeError("DFSU-suodatus ei tuottanut kohteita")
    result = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
    if not result.isValid():
        raise RuntimeError("DFSU-tulosta ei voitu avata")
    add_project_layer(project, result)


def _managed_layers(group):
    """Layers in a group that Muuntaja itself added (never the user's own)."""
    managed = []
    for node in group.findLayers():
        layer = node.layer()
        if layer is not None and (layer.customProperty(MANAGED_PROPERTY, False)
                                  or layer.customProperty(SOURCE_PATHS_PROPERTY, [])):
            managed.append(layer)
    return managed


def _add_raster_group(project, group_name, paths, destination, source_crs):
    """Represent a raster group by one VRT when multiple tiles are present."""
    from osgeo import gdal
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.addGroup(group_name)
    managed = _managed_layers(group)
    existing = []
    for layer in managed:
        existing.extend(str(path) for path in (layer.customProperty(SOURCE_PATHS_PROPERTY, []) or [layer.source()]))
    combined = list(dict.fromkeys(existing + [str(path) for path in paths]))
    rasters = []
    for path in combined:
        raster = QgsRasterLayer(path, Path(path).stem)
        if not raster.isValid():
            raise RuntimeError(f"Rasteria ei voitu avata: {path}")
        assign_source_crs(raster, path, source_crs)
        rasters.append(raster)
    if len(rasters) == 1:
        if not managed:
            rasters[0].setCustomProperty(MANAGED_PROPERTY, True)
            add_project_layer(project, rasters[0], False)
            group.addLayer(rasters[0])
        else:
            ensure_project_crs(project, rasters[0])
        return
    folder = destination.parent if destination.suffix.lower() in {".gpkg", ".gdb"} else destination
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"muuntaja_{safe_name(destination.stem)}_{safe_name(group_name)}.vrt"
    temp_output = output.with_name(output.stem + "_uusi.vrt")
    options = None
    if rasters[0].crs().isValid():
        options = gdal.BuildVRTOptions(outputSRS=rasters[0].crs().authid())
    vrt = gdal.BuildVRT(str(temp_output), combined, options=options)
    if vrt is None:
        raise RuntimeError(f"Rasterimosaiikin luonti epäonnistui: {group_name}")
    vrt = None
    for layer in managed:
        project.removeMapLayer(layer.id())
    os.replace(temp_output, output)
    layer = QgsRasterLayer(str(output), group_name)
    if not layer.isValid():
        raise RuntimeError(f"Rasterimosaiikkia ei voitu avata: {output}")
    layer.setCustomProperty(SOURCE_PATHS_PROPERTY, combined)
    layer.setCustomProperty(MANAGED_PROPERTY, True)
    add_project_layer(project, layer, False)
    group.addLayer(layer)


def _import_vector(path, destination, workspace, file_gdb, source_crs, target_crs, project, taken_names):
    written = 0
    for layer in _open_vector_layers(path):
        if layer.featureCount() == 0:
            continue
        assign_source_crs(layer, path, source_crs)
        name = safe_name(f"{path.stem}_{layer.name()}")
        if workspace:
            name = unique_name(name, taken_names, 80)
            write_vector(layer, destination, "OpenFileGDB" if file_gdb else "GPKG",
                         name, target_crs, destination.exists())
            taken_names.add(name)
            output = QgsVectorLayer(f"{destination}|layername={name}", name, "ogr")
        else:
            output_path = unique_path(destination / f"{name}.gpkg")
            write_vector(layer, output_path, "GPKG", name, target_crs)
            output = QgsVectorLayer(str(output_path), name, "ogr")
        if not output.isValid():
            raise RuntimeError("Kirjoitettua tasoa ei voitu avata")
        add_project_layer(project, output)
        written += 1
    if not written:
        raise RuntimeError("Tiedostossa ei ollut tuotavia kohteita")


def import_data(paths, destination, source_crs=None, target_crs=None, clean_cad=False,
                progress=None, dfsu_filter_column="", dfsu_filter_operator="=", dfsu_filter_value="",
                oda_converter=""):
    """Import vectors to a GeoPackage/FileGDB or folder; add located rasters by reference."""
    project = QgsProject.instance()
    items = scan_inputs(paths)
    if not items:
        raise ValueError("Tuettavia tiedostoja ei löytynyt.")
    destination = Path(destination)
    file_gdb = destination.suffix.lower() == ".gdb"
    workspace = file_gdb or destination.suffix.lower() == ".gpkg"
    if workspace:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    taken_names = cad.existing_layer_names(destination) if workspace else set()
    successes, failures = [], []
    raster_groups = {}
    for index, path in enumerate(items, 1):
        if progress:
            progress(index, len(items), str(path))
        suffix = path.suffix.lower()
        try:
            if suffix in RASTER_EXTENSIONS:
                raster_groups.setdefault(raster_group(path), []).append(path)
                continue
            if suffix == ".dfsu":
                _import_dfsu(path, destination, workspace, source_crs, target_crs,
                             dfsu_filter_column, dfsu_filter_operator, dfsu_filter_value, project)
            elif suffix in CAD_EXTENSIONS:
                layers = cad.import_cad(path, destination, source_crs, target_crs, clean_cad,
                                        oda_converter, project)
                taken_names.update(layer.name() for layer in layers)
            else:
                _import_vector(path, destination, workspace, file_gdb, source_crs, target_crs,
                               project, taken_names)
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((str(path), str(exc)))
    group_names = list(raster_groups)
    for number, group_name in enumerate(group_names, 1):
        group_paths = raster_groups[group_name]
        if progress:
            progress(len(items), len(items), f"Rasteriryhmä {number}/{len(group_names)}: {group_name}")
        try:
            _add_raster_group(project, group_name, group_paths, destination, source_crs)
            successes.extend(str(path) for path in group_paths)
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.extend((str(path), str(exc)) for path in group_paths)
    if not successes:
        raise RuntimeError("Yksikään tiedosto ei onnistunut: " + "; ".join(f"{p}: {e}" for p, e in failures))
    return successes, failures


def export_data(layers, folder, format_name, combined=False, progress=None, oda_converter="",
                symbology_scale=None):
    if format_name not in EXPORT_FORMATS:
        raise ValueError(f"Tuntematon vientimuoto: {format_name}")
    layers = [layer for layer in layers or [] if layer is not None]
    if not layers:
        raise ValueError("Valitse vähintään yksi vektoritaso.")
    if format_name in CAD_FORMATS:
        return cad.export_cad(layers, folder, format_name, combined, progress, oda_converter,
                              symbology_scale)
    driver, extension = DRIVERS[format_name]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    combined = combined and format_name == "GPKG"
    common_path = unique_path(folder / f"muuntaja_vienti{extension}") if combined else None
    successes, failures = [], []
    used_names = set()
    for index, layer in enumerate(layers, 1):
        name = layer.name()
        if progress:
            progress(index, len(layers), name)
        try:
            if not layer.isValid():
                raise RuntimeError("Taso ei ole kelvollinen")
            path = common_path or unique_path(folder / f"{safe_name(name)}{extension}")
            layer_name = unique_name(safe_name(name), used_names, 80)
            used_names.add(layer_name)
            if format_name == "GeoJSON" and not layer.crs().isValid():
                raise RuntimeError("GeoJSON-vienti vaatii tunnetun lähtökoordinaatiston")
            write_vector(layer, path, driver, layer_name if format_name == "GPKG" else None,
                         target_crs=QgsCoordinateReferenceSystem("EPSG:4326") if format_name == "GeoJSON" else None,
                         append=bool(common_path and path.exists()))
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((name, str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
