import sys
print('start', flush=True)
from qgis.core import QgsApplication, Qgis
print('imported', flush=True)
QgsApplication.setPrefixPath('C:/Program Files/QGIS 3.44.14/apps/qgis-ltr', True)
app = QgsApplication([], False)
print('app', flush=True)
app.initQgis()
print(Qgis.QGIS_VERSION, flush=True)
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import types
import numpy as np
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
from muuntaja_qgis.core import classify_finnish_xy, export_data, import_data
from muuntaja_qgis.plugin import MuuntajaDialog
from muuntaja_qgis import classFactory
layer = QgsVectorLayer('Point?crs=EPSG:3067', 'test_points', 'memory')
assert classify_finnish_xy(385000, 6670000) == 3067
feature = QgsFeature(layer.fields())
feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(385000, 6670000)))
assert layer.dataProvider().addFeatures([feature])[0]
QgsProject.instance().addMapLayer(layer)
with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    written, failed = export_data([layer], folder, 'GPKG')
    assert len(written) == 1 and not failed
    for format_name in ('GeoJSON', 'Shapefile', 'KML', 'KMZ', 'DXF'):
        format_written, format_failed = export_data([layer], folder, format_name)
        assert len(format_written) == 1 and not format_failed, (format_name, format_failed)
        assert QgsVectorLayer(format_written[0], format_name, 'ogr').isValid(), format_name
    print('export formats passed', flush=True)
    loaded, failed = import_data(written, str(Path(folder) / 'imported.gpkg'))
    assert len(loaded) == 1 and not failed
    print('export/import smoke passed', flush=True)
    combined_written, combined_failed = export_data([layer, layer], folder, 'GPKG', combined=True)
    assert len(combined_written) == 2 and not combined_failed
    combined_probe = QgsVectorLayer(combined_written[0], 'combined', 'ogr')
    assert len(combined_probe.dataProvider().subLayers()) == 2
    print('combined GPKG passed', flush=True)
    gdb_loaded, gdb_failed = import_data(written, str(Path(folder) / 'imported.gdb'))
    assert len(gdb_loaded) == 1 and not gdb_failed, gdb_failed
    print('FileGDB import passed', flush=True)
    cad_written, cad_failed = export_data([layer, layer], folder, 'DXF', combined=True)
    assert len(cad_written) == 2 and not cad_failed, cad_failed
    cad_layer = QgsVectorLayer(cad_written[0], 'cad_check', 'ogr')
    assert cad_layer.isValid() and cad_layer.featureCount() == 2
    print('combined DXF passed', flush=True)
    cad_imported, cad_import_failed = import_data([cad_written[0]], str(Path(folder) / 'cad_import.gpkg'),
                                                 clean_cad=True)
    assert len(cad_imported) == 1 and not cad_import_failed, cad_import_failed
    print('CAD import passed', flush=True)
    dfsu = Path(folder) / 'mesh.dfsu'
    dfsu.write_bytes(b'fake')
    class Geometry:
        element_table = [[0, 1, 2], [1, 3, 2]]
        node_coordinates = [[0, 0], [1, 0], [0, 1], [1, 1]]
        projection_string = 'EPSG:3067'
    class Value:
        def to_numpy(self):
            return np.array([[1.0, 2.0]])
    class Dataset:
        geometry = Geometry()
        items = [types.SimpleNamespace(name='value')]
        def __getitem__(self, name):
            return Value()
    sys.modules['mikeio'] = types.SimpleNamespace(read=lambda *a, **k: Dataset())
    dfsu_written, dfsu_failed = import_data([str(dfsu)], str(Path(folder) / 'mesh.gpkg'),
                                           dfsu_filter_column='value', dfsu_filter_operator='>',
                                           dfsu_filter_value='1')
    assert len(dfsu_written) == 1 and not dfsu_failed, dfsu_failed
    dfsu_layer = QgsVectorLayer(str(Path(folder) / 'mesh.gpkg'), 'mesh_check', 'ogr')
    assert dfsu_layer.isValid() and dfsu_layer.featureCount() == 1
    print('DFSU filter/import passed', flush=True)
    from osgeo import gdal, osr
    tiles = Path(folder) / 'taustakartta_20k'
    tiles.mkdir()
    raster_path = tiles / 'tile.tif'
    dataset = gdal.GetDriverByName('GTiff').Create(str(raster_path), 2, 2, 1)
    dataset.SetGeoTransform([0, 1, 0, 2, 0, -1])
    spatial = osr.SpatialReference()
    spatial.ImportFromEPSG(3067)
    dataset.SetProjection(spatial.ExportToWkt())
    dataset.GetRasterBand(1).Fill(10)
    dataset = None
    raster_written, raster_failed = import_data([str(tiles)], str(Path(folder) / 'raster_out'))
    assert len(raster_written) == 1 and not raster_failed
    assert QgsProject.instance().layerTreeRoot().findGroup('taustakartta_20k')
    print('raster group passed', flush=True)
    QgsProject.instance().removeAllMapLayers()
dialog = MuuntajaDialog()
print('dialog constructed', flush=True)
dialog.close()
class Interface:
    def mainWindow(self): return None
    def addPluginToMenu(self, *args): pass
    def addToolBarIcon(self, *args): pass
    def removePluginMenu(self, *args): pass
    def removeToolBarIcon(self, *args): pass
plugin = classFactory(Interface())
plugin.initGui()
plugin.unload()
print('plugin lifecycle passed', flush=True)
