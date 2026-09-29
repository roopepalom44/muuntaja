"""Check that each local import format lands in Finland after conversion."""

import gc
import sys
import tempfile
from pathlib import Path

from osgeo import gdal, osr
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer, QgsVectorLayer,
)

QgsApplication.setPrefixPath("C:/Program Files/QGIS 3.44.14/apps/qgis-ltr", True)
app = QgsApplication([], False)
app.initQgis()
sys.path.insert(0, str(Path(__file__).resolve().parent))

from muuntaja_qgis.core import export_data, import_data

project = QgsProject.instance()
wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
source = QgsVectorLayer("Point?crs=EPSG:3067", "helsinki", "memory")
feature = QgsFeature(source.fields())
feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(385000, 6670000)))
assert source.dataProvider().addFeatures([feature])[0]


def verify_import(path, destination, raster=False):
    imported, failures = import_data([str(path)], str(destination))
    assert len(imported) == 1 and not failures, (imported, failures)
    if raster:
        layers = list(project.mapLayers().values())
        assert len(layers) == 1 and isinstance(layers[0], QgsRasterLayer)
        layer = layers[0]
    else:
        files = list(destination.glob("*.gpkg"))
        assert len(files) == 1, files
        layer = QgsVectorLayer(str(files[0]), path.stem, "ogr")
    assert layer.isValid() and layer.crs().isValid(), (path, layer.crs().authid())
    center = QgsCoordinateTransform(layer.crs(), wgs84, project).transform(layer.extent().center())
    assert 18 <= center.x() <= 33 and 59 <= center.y() <= 72, (path, center.x(), center.y())
    print(f"PASS {path.suffix}: {layer.crs().authid()} lon={center.x():.4f} lat={center.y():.4f}", flush=True)
    project.removeAllMapLayers()
    layer = None
    gc.collect()


with tempfile.TemporaryDirectory(prefix="muuntaja_spatial_", ignore_cleanup_errors=True) as folder:
    root = Path(folder)
    source_gpkg = None
    for name in ("GPKG", "GeoJSON", "Shapefile", "KML", "KMZ", "DXF"):
        input_folder = root / f"input_{name}"
        path = Path(export_data([source], str(input_folder), name)[0][0])
        if name == "GPKG":
            source_gpkg = path
        verify_import(path, root / f"output_{name}")

    for suffix in (".gpkg", ".gdb"):
        destination = root / f"workspace{suffix}"
        imported, failures = import_data([str(source_gpkg)], str(destination))
        assert len(imported) == 1 and not failures
        layers = list(project.mapLayers().values())
        assert len(layers) == 1 and layers[0].isValid() and layers[0].crs().authid() == "EPSG:3067"
        center = QgsCoordinateTransform(layers[0].crs(), wgs84, project).transform(layers[0].extent().center())
        assert 18 <= center.x() <= 33 and 59 <= center.y() <= 72
        print(f"PASS workspace {suffix}: lon={center.x():.4f} lat={center.y():.4f}", flush=True)
        project.removeAllMapLayers()
        layers = None
        gc.collect()

    gpx = root / "helsinki.gpx"
    gpx.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Muuntaja test" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="60.1700" lon="24.9400"><name>Helsinki</name></wpt></gpx>''', encoding="utf-8")
    verify_import(gpx, root / "output_GPX")

    for suffix, driver, world in ((".png", "PNG", ".pgw"), (".jpg", "JPEG", ".jgw"),
                                  (".tif", "GTiff", None)):
        input_folder = root / f"raster_{driver}"
        input_folder.mkdir()
        path = input_folder / f"helsinki{suffix}"
        memory = gdal.GetDriverByName("MEM").Create("", 2, 2, 1)
        memory.GetRasterBand(1).Fill(100)
        dataset = gdal.GetDriverByName(driver).CreateCopy(str(path), memory)
        if world:
            path.with_suffix(world).write_text("1\n0\n0\n-1\n385000.5\n6669999.5\n", encoding="ascii")
        else:
            dataset.SetGeoTransform([385000, 1, 0, 6670000, 0, -1])
            spatial = osr.SpatialReference()
            spatial.ImportFromEPSG(3067)
            dataset.SetProjection(spatial.ExportToWkt())
        dataset = None
        memory = None
        verify_import(path, root / f"output_raster_{driver}", raster=True)

    missing_crs = root / "raster_missing_crs" / "old_kapsi.tif"
    missing_crs.parent.mkdir()
    dataset = gdal.GetDriverByName("GTiff").Create(str(missing_crs), 2, 2, 1)
    dataset.SetGeoTransform([385000, 1, 0, 6670000, 0, -1])
    dataset.GetRasterBand(1).Fill(100)
    dataset = None
    verify_import(missing_crs, root / "output_missing_crs", raster=True)

    missing_mercator = root / "raster_missing_mercator" / "helsinki_mercator.tif"
    missing_mercator.parent.mkdir()
    dataset = gdal.GetDriverByName("GTiff").Create(str(missing_mercator), 2, 2, 1)
    dataset.SetGeoTransform([2750000, 1, 0, 8400000, 0, -1])
    dataset.GetRasterBand(1).Fill(100)
    dataset = None
    verify_import(missing_mercator, root / "output_missing_mercator", raster=True)

    for input_path, destination, expected_crs in (
            (source_gpkg, root / "output_project_without_crs", "EPSG:3067"),
            (missing_mercator, root / "output_raster_project_without_crs", "EPSG:3857")):
        project.addMapLayer(QgsVectorLayer("Point?crs=EPSG:3857", "existing basemap", "memory"))
        project.setCrs(QgsCoordinateReferenceSystem())
        assert not project.crs().isValid()
        imported, failures = import_data([str(input_path)], str(destination))
        assert len(imported) == 1 and not failures, failures
        assert project.crs().authid() == expected_crs, project.crs().authid()
        project.removeAllMapLayers()
        gc.collect()
        print(f"PASS project without CRS: {expected_crs}", flush=True)

print("All local formats, TIFFs without CRS, and both workspace modes passed", flush=True)
