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
from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
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
        if format_name == 'GeoJSON':
            import json
            payload = json.loads(Path(format_written[0]).read_text(encoding='utf-8'))
            assert payload['type'] == 'FeatureCollection'
            x, y = payload['features'][0]['geometry']['coordinates'][:2]
            assert 19 <= x <= 32.5 and 59 <= y <= 71.5, (x, y)
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
    from unittest.mock import patch
    from muuntaja_qgis import core as muuntaja_core
    fake_converter = Path(folder) / 'ODAFileConverter.exe'
    fake_converter.write_bytes(b'fake')
    def fake_oda(command, **kwargs):
        assert command[0] == str(fake_converter)
        assert command[3:5] == ['ACAD2018', 'DWG']
        assert command[-1] == '*.DXF'
        for source in Path(command[1]).glob('*.dxf'):
            (Path(command[2]) / (source.stem + '.dwg')).write_bytes(b'DWG' * 200)
        return types.SimpleNamespace(returncode=0, stderr='')
    with patch.object(muuntaja_core.subprocess, 'run', side_effect=fake_oda), \
         patch.object(muuntaja_core, 'QgsVectorLayer') as probe:
        probe.return_value.isValid.return_value = True
        dwg_written, dwg_failed = export_data([layer], folder, 'DWG', oda_converter=str(fake_converter))
    assert len(dwg_written) == 1 and not dwg_failed and Path(dwg_written[0]).is_file()
    print('ODA DWG orchestration passed (mock converter)', flush=True)
    cad_imported, cad_import_failed = import_data([cad_written[0]], str(Path(folder) / 'cad_import.gpkg'),
                                                 clean_cad=True)
    assert len(cad_imported) == 1 and not cad_import_failed, cad_import_failed
    print('CAD import passed', flush=True)
    newer_dwg = Path(__file__).parents[1] / 'Tarkekuva_pki.dwg'
    with patch.object(muuntaja_core, 'find_oda_converter', return_value=''):
        try:
            import_data([str(newer_dwg)], str(Path(folder) / 'unsupported_dwg'))
        except RuntimeError as exc:
            assert 'AC1032' in str(exc) and 'ODA File Converter' in str(exc)
        else:
            raise AssertionError('Unsupported DWG needs a useful error')
    def fake_oda_import(command, **kwargs):
        assert command[0] == str(fake_converter)
        assert command[3:5] == ['ACAD2018', 'DXF']
        assert command[-1] == '*.DWG'
        (Path(command[2]) / 'Tarkekuva_pki.dxf').write_bytes(Path(cad_written[0]).read_bytes())
        return types.SimpleNamespace(returncode=0, stderr='', stdout='')
    with patch.object(muuntaja_core.subprocess, 'run', side_effect=fake_oda_import):
        dwg_imported, dwg_import_failed = import_data(
            [str(newer_dwg)], str(Path(folder) / 'dwg_import.gpkg'),
            oda_converter=str(fake_converter))
    assert len(dwg_imported) == 1 and not dwg_import_failed, dwg_import_failed
    imported_dwg = QgsVectorLayer(str(Path(folder) / 'dwg_import.gpkg'), 'dwg', 'ogr')
    assert imported_dwg.isValid() and imported_dwg.crs().authid() == 'EPSG:3067'
    print('newer DWG import fallback passed (mock converter)', flush=True)
    dfsu = Path(folder) / 'mesh.dfsu'
    dfsu.write_bytes(b'fake')
    class Geometry:
        element_table = [[0, 1, 2], [1, 3, 2]]
        node_coordinates = [[385000, 6670000], [385001, 6670000],
                            [385000, 6670001], [385001, 6670001]]
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
    assert dfsu_layer.crs().authid() == 'EPSG:3067' and dfsu_layer.extent().xMinimum() >= 385000
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
    second_path = tiles / 'tile2.tif'
    second = gdal.GetDriverByName('GTiff').Create(str(second_path), 2, 2, 1)
    second.SetGeoTransform([2, 1, 0, 2, 0, -1])
    second.SetProjection(spatial.ExportToWkt())
    second.GetRasterBand(1).Fill(20)
    second = None
    raster_written, raster_failed = import_data([str(tiles)], str(Path(folder) / 'raster_out'))
    assert len(raster_written) == 2 and not raster_failed
    group = QgsProject.instance().layerTreeRoot().findGroup('taustakartta_20k')
    assert group and len(group.findLayers()) == 1
    assert group.findLayers()[0].layer().source().endswith('.vrt')
    import_data([str(tiles)], str(Path(folder) / 'raster_out'))
    assert len(group.findLayers()) == 1
    third_path = tiles / 'tile3.tif'
    third = gdal.GetDriverByName('GTiff').Create(str(third_path), 2, 2, 1)
    third.SetGeoTransform([4, 1, 0, 2, 0, -1])
    third.SetProjection(spatial.ExportToWkt())
    third.GetRasterBand(1).Fill(30)
    third = None
    import_data([str(third_path)], str(Path(folder) / 'raster_out'))
    assert len(group.findLayers()) == 1
    assert len(group.findLayers()[0].layer().customProperty('muuntaja/source_paths')) == 3
    print('raster mosaic passed', flush=True)
    wrong_tiles = Path(folder) / 'wrong_crs_tiles'
    wrong_tiles.mkdir()
    wrong_spatial = osr.SpatialReference()
    wrong_spatial.ImportFromEPSG(3857)
    for index in range(2):
        wrong = gdal.GetDriverByName('GTiff').Create(str(wrong_tiles / f'{index}.tif'), 2, 2, 1)
        wrong.SetGeoTransform([385000 + index * 2, 1, 0, 6670000, 0, -1])
        wrong.SetProjection(wrong_spatial.ExportToWkt())
        wrong.GetRasterBand(1).Fill(index + 1)
        wrong = None
    try:
        import_data([str(wrong_tiles)], str(Path(folder) / 'uncorrected_rasters'))
    except RuntimeError as exc:
        assert 'koordinaatit näyttävät järjestelmältä EPSG:3067' in str(exc)
    else:
        raise AssertionError('Conflicting raster CRS must not be silently accepted')
    imported, failures = import_data([str(wrong_tiles)], str(Path(folder) / 'corrected_rasters'),
                                     source_crs=QgsCoordinateReferenceSystem('EPSG:3067'))
    assert len(imported) == 2 and not failures
    corrected = QgsProject.instance().layerTreeRoot().findGroup('wrong_crs_tiles').findLayers()[0].layer()
    assert corrected.crs().authid() == 'EPSG:3067'
    assert corrected.extent().xMinimum() == 385000
    print('source CRS override passed', flush=True)
    QgsProject.instance().removeAllMapLayers()
dialog = MuuntajaDialog()
dialog._add_input_paths([str(newer_dwg)])
assert dialog.import_oda_converter.isEnabled()
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
