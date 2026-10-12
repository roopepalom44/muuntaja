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
        loader = importlib.machinery.SourceFileLoader(
            "audit_native_arcgis", str(ROOT / "Toolboxes/Muuntaja.pyt")
        )
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
        self.tool._add_layers_to_map = lambda paths, *args, **kwargs: self.paths.extend(
            paths
        )
        self.tool.log = lambda messages, text, level="INFO": self.logs.append(
            (level, text)
        )
        self.messages = type(
            "Messages",
            (),
            {
                "addMessage": lambda self, text: None,
                "addWarningMessage": lambda self, text: None,
                "addErrorMessage": lambda self, text: None,
            },
        )()

    def tearDown(self):
        self.tool._run_deferred_cleanup(self.messages)
        arcpy.env.workspace = self.old_workspace
        arcpy.env.scratchWorkspace = self.old_scratch
        arcpy.management.ClearWorkspaceCache()
        self.temp.cleanup()

    def points(self, code=4326):
        fc = os.path.join(self.gdb, "source")
        arcpy.management.CreateFeatureclass(
            self.gdb, "source", "POINT", spatial_reference=arcpy.SpatialReference(code)
        )
        with arcpy.da.InsertCursor(fc, ["SHAPE@XY"]) as cursor:
            cursor.insertRow(
                ([(24.94, 60.17) if code == 4326 else (385000, 6670000)][0],)
            )
        return fc

    def assert_target(self):
        self.assertTrue(self.paths)
        for path in self.paths:
            self.assertEqual(arcpy.Describe(path).spatialReference.factoryCode, 3067)

    def test_geojson_reprojection_with_native_crs(self):
        path = self.root / "aineisto.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Point",
                                "coordinates": [24.94, 60.17],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.tool.process_geojson_flattened(
            str(path),
            self.gdb,
            False,
            self.messages,
            target_sr=arcpy.SpatialReference(3067),
        )
        self.assert_target()

    def test_shapefile_forced_source_and_target_crs(self):
        source = self.points()
        path = self.root / "roads.shp"
        arcpy.management.CopyFeatures(source, str(path))
        path.with_suffix(".prj").unlink()
        self.tool.process_generic(
            str(path),
            self.gdb,
            False,
            self.messages,
            input_sr=arcpy.SpatialReference(4326),
            target_sr=arcpy.SpatialReference(3067),
        )
        self.assert_target()

    def test_gpkg_reprojection(self):
        source = self.points()
        path = self.root / "roads.gpkg"
        self.tool._export_to_geopackage(source, str(path), self.messages)
        self.tool.process_geopackage(
            str(path),
            self.gdb,
            False,
            self.messages,
            target_sr=arcpy.SpatialReference(3067),
        )
        self.assert_target()

    def test_plain_kml_is_xml_and_import_reprojects(self):
        source = self.points()
        path = self.root / "roads.kml"
        self.tool._export_to_kml(source, str(path), self.messages)
        self.assertTrue(path.read_bytes().lstrip().startswith(b"<?xml"))
        self.tool.process_kml_flattened(
            str(path),
            self.gdb,
            False,
            self.messages,
            target_sr=arcpy.SpatialReference(3067),
        )
        self.assert_target()

    def test_gpx_points_and_tracks_reproject(self):
        path = self.root / "route.gpx"
        path.write_text(
            '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            '<wpt lat="60.17" lon="24.94"/><trk><trkseg><trkpt lat="60.17" lon="24.94"/>'
            '<trkpt lat="60.18" lon="24.95"/></trkseg></trk></gpx>',
            encoding="utf-8",
        )
        self.tool.process_gpx_flattened(
            str(path),
            self.gdb,
            False,
            self.messages,
            target_sr=arcpy.SpatialReference(3067),
        )
        self.assert_target()

    def test_cad_worker_reads_real_dxf(self):
        source = self.points(3067)
        path = self.root / "drawing.dxf"
        arcpy.conversion.ExportCAD(source, "DXF_R2018", str(path))
        self.tool.process_cad(
            str(path),
            self.gdb,
            False,
            False,
            arcpy.SpatialReference(3067),
            None,
            self.messages,
        )
        self.assert_target()

    def test_dgn_roundtrip_points_lines_polygons_and_projection(self):
        sr = arcpy.SpatialReference(3067)
        point = arcpy.PointGeometry(arcpy.Point(385000, 6670000, 5), sr, True)
        line = arcpy.Polyline(arcpy.Array([
            arcpy.Point(385000, 6670000, 5), arcpy.Point(385010, 6670010, 9)
        ]), sr, True)
        area = arcpy.Polygon(arcpy.Array([
            arcpy.Point(385000, 6670000), arcpy.Point(385010, 6670000),
            arcpy.Point(385010, 6670010), arcpy.Point(385000, 6670000),
        ]), sr)
        sources = []
        for name, shape_type, geometry in (
            ("dgn_points", "POINT", point),
            ("dgn_lines", "POLYLINE", line),
            ("dgn_areas", "POLYGON", area),
        ):
            arcpy.management.CreateFeatureclass(
                self.gdb, name, shape_type, has_z="ENABLED", spatial_reference=sr
            )
            fc = os.path.join(self.gdb, name)
            with arcpy.da.InsertCursor(fc, ["SHAPE@"]) as cursor:
                cursor.insertRow((geometry,))
            sources.append((fc, name))
        output = str(self.root / "piirustus.dgn")
        self.tool._export_to_cad(sources, output, self.messages)
        self.assertEqual(arcpy.Describe(output).spatialReference.factoryCode, 3067)
        for shape_type in ("Point", "Polyline", "Polygon"):
            self.assertGreater(
                int(arcpy.management.GetCount(os.path.join(output, shape_type))[0]), 0
            )
        with arcpy.da.SearchCursor(os.path.join(output, "Point"), ["SHAPE@"]) as cursor:
            exported_point = next(cursor)[0]
            self.assertAlmostEqual(exported_point.firstPoint.X, 385000, places=3)
            self.assertAlmostEqual(exported_point.firstPoint.Z, 5, places=3)
        target = arcpy.SpatialReference(3857)
        self.tool.process_cad(
            output, self.gdb, False, False, None, target, self.messages
        )
        self.assertTrue(self.paths)
        imported_types = set()
        projected_point = point.projectAs(target).firstPoint
        for path in self.paths:
            desc = arcpy.Describe(path)
            self.assertEqual(desc.spatialReference.factoryCode, 3857)
            imported_types.add(desc.shapeType)
            if desc.shapeType == "Point":
                with arcpy.da.SearchCursor(path, ["SHAPE@"]) as cursor:
                    imported_point = next(cursor)[0].firstPoint
                    self.assertAlmostEqual(imported_point.X, projected_point.X, places=3)
                    self.assertAlmostEqual(imported_point.Y, projected_point.Y, places=3)
                    self.assertAlmostEqual(imported_point.Z, 5, places=3)
        self.assertTrue({"Point", "Polyline", "Polygon"}.issubset(imported_types))
        for fc, _name in sources:
            self.assertEqual(int(arcpy.management.GetCount(fc)[0]), 1)

    def test_dgn_2d_export_respects_layer_selection(self):
        source = self.points(3067)
        with arcpy.da.InsertCursor(source, ["SHAPE@XY"]) as cursor:
            cursor.insertRow(((385100, 6670100),))
        layer = "dgn_selected_points"
        arcpy.management.MakeFeatureLayer(source, layer, "OBJECTID > 1")
        prepared = self.tool._prepare_export_feature_class(layer, self.messages)
        output = str(self.root / "selected.dgn")
        self.tool._export_to_cad([(prepared, layer)], output, self.messages)
        cad_points = os.path.join(output, "Point")
        self.assertEqual(int(arcpy.management.GetCount(cad_points)[0]), 1)
        with arcpy.da.SearchCursor(cad_points, ["SHAPE@XY"]) as cursor:
            self.assertEqual(next(cursor)[0], (385100, 6670100))
        self.assertEqual(int(arcpy.management.GetCount(source)[0]), 2)
        arcpy.management.Delete(layer)

    def test_dgn_elevation_field_preserves_height_on_2d_source(self):
        source = self.points(3067)
        self.assertFalse(arcpy.Describe(source).hasZ)
        arcpy.management.AddField(source, "Elevation", "DOUBLE")
        arcpy.management.CalculateField(source, "Elevation", "12.5", "PYTHON3")
        output = str(self.root / "elevated.dgn")
        self.tool._export_to_cad([(source, "Points")], output, self.messages)
        with arcpy.da.SearchCursor(os.path.join(output, "Point"), ["SHAPE@"]) as cursor:
            self.assertAlmostEqual(next(cursor)[0].firstPoint.Z, 12.5, places=3)

    def test_shapefile_wide_table_preserves_all_attribute_columns(self):
        source = self.points(3067)
        for index in range(20):
            arcpy.management.AddField(
                source, f"attribute_{index}", "TEXT", field_length=254
            )
        path = self.root / "wide.shp"
        self.tool._export_to_shapefile(source, str(path), self.messages)
        attrs = [
            field for field in arcpy.ListFields(str(path)) if field.type == "String"
        ]
        self.assertEqual(len(attrs), 20)
        self.assertTrue(all(field.length <= 80 for field in attrs))

    def test_cad_field_collision_preserves_selection_attributes_and_z(self):
        source = os.path.join(self.gdb, "osm_paths")
        sr = arcpy.SpatialReference(3067)
        arcpy.management.CreateFeatureclass(
            self.gdb, "osm_paths", "POLYLINE", has_z="ENABLED", spatial_reference=sr
        )
        for name in ("layer", "level", "layer_value", "label"):
            arcpy.management.AddField(source, name, "TEXT", field_length=255)
        arcpy.management.AddField(source, "code", "LONG")
        with arcpy.da.InsertCursor(
            source, ["SHAPE@", "layer", "level", "layer_value", "label", "code"]
        ) as cursor:
            for code in (1, 2, 3):
                geometry = arcpy.Polyline(
                    arcpy.Array([
                        arcpy.Point(385000 + code, 6670000, 7),
                        arcpy.Point(385010 + code, 6670010, 9),
                    ]), sr, True,
                )
                cursor.insertRow((geometry, "0", "1", "existing", "polku ä😀", code))
        layer = arcpy.management.MakeFeatureLayer(
            source, "selected_paths", "code >= 2"
        ).getOutput(0)
        arcpy.management.SelectLayerByAttribute(layer, "NEW_SELECTION", "code = 2")
        prepared = self.tool._cad_copy_without_layer_field_collision(layer, self.messages)
        self.assertEqual(int(arcpy.management.GetCount(prepared)[0]), 1)
        fields = {field.name: field.aliasName for field in arcpy.ListFields(prepared)}
        self.assertNotIn("layer", fields)
        self.assertNotIn("level", fields)
        self.assertEqual(fields["layer_value_2"], "layer_value_2")
        with arcpy.da.SearchCursor(
            prepared, ["layer_value_2", "level_value", "layer_value", "label", "code", "SHAPE@"]
        ) as cursor:
            row = next(cursor)
            self.assertEqual(row[:5], ("0", "1", "existing", "polku ä😀", 2))
            self.assertEqual((row[5].firstPoint.Z, row[5].lastPoint.Z), (7, 9))
            self.assertEqual(row[5].spatialReference.factoryCode, 3067)
        self.assertEqual(int(arcpy.management.GetCount(source)[0]), 3)
        self.assertIn("layer", [field.name for field in arcpy.ListFields(source)])
        for extension in ("dwg", "dxf"):
            with self.subTest(extension=extension):
                output = str(self.root / ("paths." + extension))
                self.tool._export_to_cad([(prepared, layer)], output, self.messages)
                self.assertEqual(
                    int(arcpy.management.GetCount(os.path.join(output, "Polyline"))[0]), 1
                )
        arcpy.management.Delete(layer)

    def test_raster_batch_builds_valid_layers_without_root_insertion(self):
        import numpy as np

        paths = []
        for index in range(10):
            path = self.root / f"tile{index}.tif"
            raster = arcpy.NumPyArrayToRaster(
                np.ones((2, 2), dtype="uint8"),
                arcpy.Point(385000 + index * 8, 6670000),
                4,
                4,
            )
            raster.save(str(path))
            del raster
            arcpy.management.DefineProjection(str(path), arcpy.SpatialReference(3067))
            paths.append(str(path))
        calls = []

        class Map:
            def addLayerToGroup(self, group, layer_file):
                layers = layer_file.listLayers()
                self_outer.assertEqual(len(layers), 10)
                self_outer.assertTrue(
                    all(layer.isRasterLayer and not layer.isBroken for layer in layers)
                )
                calls.append(group)

        self_outer = self
        success, failures = self.tool._add_raster_batch(
            Map(), "group", paths, self.messages
        )
        self.assertEqual(success, paths)
        self.assertFalse(failures)
        self.assertEqual(calls, ["group"])

    def test_dfsu_preserves_numpy_buffers_without_computing_unused_centers(self):
        import numpy as np
        import types

        class Geometry:
            element_table = np.array([[0, 1, 2], [1, 3, 2]])
            node_coordinates = np.array(
                [
                    [385000, 6670000],
                    [385004, 6670000],
                    [385000, 6670004],
                    [385004, 6670004],
                ]
            )
            projection_string = arcpy.SpatialReference(3067).exportToString()

            @property
            def element_coordinates(self):
                raise AssertionError("Unused mesh centroids must not be computed")

        class Buffer(np.ndarray):
            def tolist(self):
                raise AssertionError("DFSU arrays must not be boxed into lists")

        values = np.array([1.0, np.nan], dtype=np.float32).view(Buffer)

        class Dataset:
            geometry = Geometry()
            items = [types.SimpleNamespace(name="lämpötila")]

            def __getitem__(self, _name):
                return types.SimpleNamespace(to_numpy=lambda: values)

        reader = types.SimpleNamespace(read=lambda **kwargs: Dataset())
        self.tool._ensure_python_module = lambda _name: types.SimpleNamespace(
            open=lambda _path: reader
        )
        self.tool.process_dfsu("mesh.dfsu", self.gdb, False, self.messages)
        self.assert_target()
        self.assertEqual(int(arcpy.management.GetCount(self.paths[0])[0]), 2)
        with arcpy.da.SearchCursor(self.paths[0], ["lampotila"]) as cursor:
            self.assertEqual([row[0] for row in cursor], [1.0, None])


if __name__ == "__main__":
    unittest.main(verbosity=2)
