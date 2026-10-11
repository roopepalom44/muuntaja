"""Native ArcGIS tests: run with propy.bat and unittest discover."""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    import arcpy
    HAS_ARCPY = hasattr(arcpy, "GetInstallInfo")
except ImportError:
    HAS_ARCPY = False

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_ARCPY, "Requires licensed ArcGIS Pro Python")
class ArcgisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("audit_native_arcgis", str(ROOT / "Toolboxes/Muuntaja.pyt"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.module = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.module)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="muuntaja_arc_audit_")
        self.root = Path(self.temp.name)
        arcpy.management.CreateFileGDB(str(self.root), "test.gdb")
        arcpy.management.CreateFileGDB(str(self.root), "scratch.gdb")
        self.gdb = str(self.root / "test.gdb")
        self.old_scratch = arcpy.env.scratchWorkspace
        self.old_workspace = arcpy.env.workspace
        arcpy.env.scratchWorkspace = str(self.root / "scratch.gdb")
        arcpy.env.addOutputsToMap = False
        arcpy.env.overwriteOutput = True
        self.tool = self.module.UniversalImportTool()
        self.paths = []
        self.logs = []
        self.tool._add_layers_to_map = lambda paths, *args, **kwargs: self.paths.extend(paths)
        self.tool.log = lambda messages, text, level="INFO": self.logs.append((level, text))
        self.messages = type("Messages", (), {
            "addMessage": lambda self, text: None,
            "addWarningMessage": lambda self, text: None,
            "addErrorMessage": lambda self, text: None,
        })()

    def tearDown(self):
        self.tool._run_deferred_cleanup(self.messages)
        arcpy.env.workspace = self.old_workspace
        arcpy.env.scratchWorkspace = self.old_scratch
        arcpy.management.ClearWorkspaceCache()
        self.temp.cleanup()

    def points(self, code=4326):
        fc = os.path.join(self.gdb, "source")
        arcpy.management.CreateFeatureclass(self.gdb, "source", "POINT", spatial_reference=arcpy.SpatialReference(code))
        with arcpy.da.InsertCursor(fc, ["SHAPE@XY"]) as cursor:
            cursor.insertRow(([(24.94, 60.17) if code == 4326 else (385000, 6670000)][0],))
        return fc

    def assert_target(self):
        self.assertTrue(self.paths)
        for path in self.paths:
            self.assertEqual(arcpy.Describe(path).spatialReference.factoryCode, 3067)

    def test_geojson_reprojection_with_native_crs(self):
        path = self.root / "aineisto.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                        "geometry": {"type": "Point", "coordinates": [24.94, 60.17]}}]}), encoding="utf-8")
        self.tool.process_geojson_flattened(str(path), self.gdb, False, self.messages, target_sr=arcpy.SpatialReference(3067))
        self.assert_target()

    def test_shapefile_forced_source_and_target_crs(self):
        source = self.points()
        path = self.root / "roads.shp"
        arcpy.management.CopyFeatures(source, str(path))
        path.with_suffix(".prj").unlink()
        self.tool.process_generic(str(path), self.gdb, False, self.messages,
                                  input_sr=arcpy.SpatialReference(4326), target_sr=arcpy.SpatialReference(3067))
        self.assert_target()

    def test_gpkg_reprojection(self):
        source = self.points()
        path = self.root / "roads.gpkg"
        self.tool._export_to_geopackage(source, str(path), self.messages)
        self.tool.process_geopackage(str(path), self.gdb, False, self.messages, target_sr=arcpy.SpatialReference(3067))
        self.assert_target()

    def test_plain_kml_is_xml_and_import_reprojects(self):
        source = self.points()
        path = self.root / "roads.kml"
        self.tool._export_to_kml(source, str(path), self.messages)
        self.assertTrue(path.read_bytes().lstrip().startswith(b"<?xml"))
        self.tool.process_kml_flattened(str(path), self.gdb, False, self.messages, target_sr=arcpy.SpatialReference(3067))
        self.assert_target()

    def test_gpx_points_and_tracks_reproject(self):
        path = self.root / "route.gpx"
        path.write_text('<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
                        '<wpt lat="60.17" lon="24.94"/><trk><trkseg><trkpt lat="60.17" lon="24.94"/>'
                        '<trkpt lat="60.18" lon="24.95"/></trkseg></trk></gpx>', encoding="utf-8")
        self.tool.process_gpx_flattened(str(path), self.gdb, False, self.messages, target_sr=arcpy.SpatialReference(3067))
        self.assert_target()

    def test_cad_worker_reads_real_dxf(self):
        source = self.points(3067)
        path = self.root / "drawing.dxf"
        arcpy.conversion.ExportCAD(source, "DXF_R2018", str(path))
        self.tool.process_cad(str(path), self.gdb, False, False, arcpy.SpatialReference(3067), None, self.messages)
        self.assert_target()

    def test_shapefile_wide_table_preserves_all_attribute_columns(self):
        source = self.points(3067)
        for index in range(20):
            arcpy.management.AddField(source, f"attribute_{index}", "TEXT", field_length=254)
        path = self.root / "wide.shp"
        self.tool._export_to_shapefile(source, str(path), self.messages)
        attrs = [field for field in arcpy.ListFields(str(path)) if field.type == "String"]
        self.assertEqual(len(attrs), 20)
        self.assertTrue(all(field.length <= 80 for field in attrs))

    def test_raster_batch_builds_valid_layers_without_root_insertion(self):
        import numpy as np
        paths = []
        for index in range(10):
            path = self.root / f"tile{index}.tif"
            raster = arcpy.NumPyArrayToRaster(np.ones((2, 2), dtype="uint8"), arcpy.Point(385000 + index * 8, 6670000), 4, 4)
            raster.save(str(path))
            del raster
            arcpy.management.DefineProjection(str(path), arcpy.SpatialReference(3067))
            paths.append(str(path))
        calls = []
        class Map:
            def addLayerToGroup(self, group, layer_file):
                layers = layer_file.listLayers()
                self_outer.assertEqual(len(layers), 10)
                self_outer.assertTrue(all(layer.isRasterLayer and not layer.isBroken for layer in layers))
                calls.append(group)
        self_outer = self
        success, failures = self.tool._add_raster_batch(Map(), "group", paths, self.messages)
        self.assertEqual(success, paths)
        self.assertFalse(failures)
        self.assertEqual(calls, ["group"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
