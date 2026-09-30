# -*- coding: utf-8 -*-
"""Regressiotestit auditoinnin ArcGIS-löydöksille (fake-arcpy)."""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

TOOLBOX = Path(__file__).resolve().parents[1] / "Toolboxes" / "Muuntaja.pyt"


def load_toolbox(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    loader = importlib.machinery.SourceFileLoader("muuntaja_fixes_toolbox", str(TOOLBOX))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


class ArcGisFixTests(unittest.TestCase):
    def setUp(self):
        self.arcpy = types.ModuleType("arcpy")

        class ExecuteError(Exception):
            pass

        self.arcpy.ExecuteError = ExecuteError
        self.arcpy.env = types.SimpleNamespace(scratchGDB=r"C:\scratch.gdb")
        self.arcpy.management = Recorder()
        self.arcpy.conversion = Recorder()
        self.arcpy.Exists = lambda _path: False
        self.arcpy.ValidateTableName = lambda name, _workspace: name
        self.arcpy.SpatialReference = lambda code=None: types.SimpleNamespace(name=f"EPSG:{code}", factoryCode=code)
        self.module = load_toolbox(self.arcpy)
        self.tool = self.module.UniversalImportTool()
        self.logged = []
        self.tool.log = lambda _messages, text, level="INFO": self.logged.append((level, text))

    # 1.4 ---------------------------------------------------------------
    def test_cad_copy_without_projection_stamps_detected_crs(self):
        unknown = types.SimpleNamespace(name="Unknown")
        self.arcpy.Describe = lambda _path: types.SimpleNamespace(
            spatialReference=unknown, featureType="Simple", shapeType="Polyline"
        )
        detected = types.SimpleNamespace(name="ETRS89 / TM35FIN", factoryCode=3067)

        result = self.tool._save_cad_layer(
            r"C:\cad\drawing.dwg\Polyline", r"C:\out.gdb", "drawing_line", False,
            None, detected, None, None,
        )

        names = [name for name, _args, _kwargs in self.arcpy.management.calls]
        self.assertEqual(names, ["CopyFeatures", "DefineProjection"])
        self.assertEqual(self.arcpy.management.calls[1][1], (result, detected))

    def test_cad_copy_keeps_crs_that_the_drawing_already_has(self):
        known = types.SimpleNamespace(name="ETRS89 / TM35FIN")
        self.arcpy.Describe = lambda _path: types.SimpleNamespace(
            spatialReference=known, featureType="Simple", shapeType="Polyline"
        )

        self.tool._save_cad_layer(
            r"C:\cad\drawing.dwg\Polyline", r"C:\out.gdb", "drawing_line", False,
            None, object(), None, None,
        )

        names = [name for name, _args, _kwargs in self.arcpy.management.calls]
        self.assertEqual(names, ["CopyFeatures"])

    def test_projected_cad_import_gives_detected_crs_to_cad_conversion(self):
        # Tuntemattomaan koordinaatistoon muunnetun feature datasetin tasoja
        # ArcGIS ei projisoi (ERROR 000289/000599), joten CRS annetaan jo
        # CADToGeodatabaselle.
        self.arcpy.env = types.SimpleNamespace(scratchGDB=r"C:\scratch.gdb", workspace=None)
        self.arcpy.ListFeatureClasses = lambda: ["Point", "Polyline"]
        self.arcpy.Describe = lambda _path: types.SimpleNamespace(shapeType="Polyline", featureType="Simple")
        detected = types.SimpleNamespace(name="ETRS89 / TM35FIN", factoryCode=3067)
        target = types.SimpleNamespace(name="ETRS89 / GK25", factoryCode=3879)
        detections = []

        def detect(path, _messages, input_path=None):
            detections.append(path)
            return detected

        saved = []
        self.tool.detect_finnish_crs = detect
        self.tool._count_safe = lambda _path: 3
        self.tool._is_remote_output = lambda _output: False
        self.tool._add_layers_to_map = lambda _paths, _messages: None
        self.tool._save_cad_layer = lambda *args, **_kwargs: saved.append(args) or args[2]

        self.tool.process_cad(r"C:\cad\drawing.dwg", r"C:\out.gdb", False, False, None, target, None)

        conversion = [args for name, args, _kwargs in self.arcpy.conversion.calls if name == "CADToGeodatabase"]
        self.assertEqual(len(conversion), 1)
        self.assertIs(conversion[0][-1], detected)
        self.assertEqual(len(detections), 1)
        self.assertTrue(saved and all(args[5] is detected for args in saved))

    def test_fallback_projection_does_not_overwrite_earlier_layer(self):
        existing = {os.path.join(r"C:\out.gdb", "drawing_line_proj")}
        self.arcpy.Exists = lambda path: path in existing
        source = types.SimpleNamespace(name="TM35FIN", factoryCode=3067)
        target = types.SimpleNamespace(name="GK25", factoryCode=3879)
        self.arcpy.ListTransformations = lambda *_args: []

        result = self.tool._save_cad_layer_fallback(
            r"C:\cad\drawing.dwg\Polyline", r"C:\out.gdb", "drawing_line", False,
            None, source, target, None, r"C:\out.gdb\drawing_line",
        )

        projects = [args for name, args, _kwargs in self.arcpy.management.calls if name == "Project"]
        self.assertEqual(result, os.path.join(r"C:\out.gdb", "drawing_line_proj_2"))
        self.assertEqual(projects[0][1], result)

    def test_reprojected_import_does_not_overwrite_earlier_layer(self):
        existing = {os.path.join(r"C:\out.gdb", "roads_proj")}
        self.arcpy.Exists = lambda path: path in existing
        self.tool._count_safe = lambda _path: 3
        source = types.SimpleNamespace(name="TM35FIN", factoryCode=3067)
        target = types.SimpleNamespace(name="GK25", factoryCode=3879)

        result = self.tool.save_and_reproject(
            r"C:\in.gdb\roads", r"C:\out.gdb", "roads", False, None, source, target, None,
            add_to_map=False,
        )

        self.assertEqual(result, os.path.join(r"C:\out.gdb", "roads_proj_2"))

    # Viennin kohdekoordinaatisto ja tyyli ---------------------------------
    def test_export_crs_list_has_common_finnish_systems(self):
        self.assertIn("ETRS-GK23 (3877)", self.module.EXPORT_CRS_LIST)
        self.assertIn("ETRS-TM35FIN (3067)", self.module.EXPORT_CRS_LIST)
        self.assertEqual(self.module.EXPORT_CRS_LIST[0], self.module.EXPORT_CRS_KEEP)
        self.assertIsNone(self.tool._parse_input_sr(self.module.EXPORT_CRS_KEEP))
        self.assertEqual(self.tool._parse_input_sr("ETRS-GK23 (3877)").factoryCode, 3877)
        self.assertIn("shapefile", self.module.EXPORT_MODE_LABEL)

    def test_export_of_layer_without_crs_to_target_crs_fails_clearly(self):
        unknown = types.SimpleNamespace(spatialReference=types.SimpleNamespace(name="Unknown"))
        target = types.SimpleNamespace(name="ETRS-GK23", factoryCode=3877)

        with self.assertRaisesRegex(RuntimeError, "koordinaatisto on tuntematon"):
            self.tool._export_needs_projection(unknown, target, "tasot")

    def test_export_skips_projection_when_crs_already_matches(self):
        same = types.SimpleNamespace(spatialReference=types.SimpleNamespace(name="GK23", factoryCode=3877))
        target = types.SimpleNamespace(name="ETRS-GK23", factoryCode=3877)

        self.assertFalse(self.tool._export_needs_projection(same, target, "tasot"))

    def test_style_file_is_named_after_the_export(self):
        self.assertEqual(self.tool._style_file_path(os.path.join("C:", "vienti", "tiet.shp")),
                         os.path.join("C:", "vienti", "tiet.lyrx"))
        self.assertEqual(self.tool._style_file_path(os.path.join("C:", "vienti", "kaikki.gpkg", "tiet")),
                         os.path.join("C:", "vienti", "kaikki_tiet.lyrx"))

    # 1.5 ---------------------------------------------------------------
    def test_dfsu_without_projection_is_detected_from_coordinates(self):
        geometry = types.SimpleNamespace(projection_string="NON-UTM")
        nodes = [(385000.0 + i, 6672000.0 + i) for i in range(50)]

        sr = self.tool._dfsu_source_spatial_reference(geometry, nodes, None, None, None)

        self.assertEqual(sr.factoryCode, 3067)

    def test_dfsu_with_unknown_crs_fails_instead_of_using_target(self):
        geometry = types.SimpleNamespace(projection_string="NON-UTM")
        nodes = [(10.0, 20.0), (11.0, 21.0)]

        with self.assertRaisesRegex(RuntimeError, "Lähtökoordinaatisto"):
            self.tool._dfsu_source_spatial_reference(geometry, nodes, None, None, None)

    def test_dfsu_long_lat_projection_is_wgs84(self):
        geometry = types.SimpleNamespace(projection_string="LONG/LAT")

        sr = self.tool._dfsu_source_spatial_reference(geometry, None, None, None, None)

        self.assertEqual(sr.factoryCode, 4326)

    def test_explicit_input_crs_wins_for_dfsu(self):
        chosen = types.SimpleNamespace(name="KKJ3")
        geometry = types.SimpleNamespace(projection_string="LONG/LAT")

        self.assertIs(
            self.tool._dfsu_source_spatial_reference(geometry, None, None, chosen, None),
            chosen,
        )

    # 2.1 ---------------------------------------------------------------
    def test_save_errors_are_not_swallowed(self):
        self.arcpy.GetCount = None
        self.tool._count_safe = lambda _path: 3

        def fail(*_args, **_kwargs):
            raise RuntimeError("lukittu")

        self.arcpy.management = types.SimpleNamespace(CopyFeatures=fail)

        with self.assertRaisesRegex(RuntimeError, "lukittu"):
            self.tool.save_and_reproject(
                r"C:\in.gdb\roads", r"C:\out.gdb", "roads", False, None, None, None, None
            )

    def test_bulk_import_fails_when_no_layer_could_be_saved(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("ei tilaa")

        self.tool.save_and_reproject = fail

        with self.assertRaisesRegex(RuntimeError, "Yhtään tasoa"):
            self.tool._bulk_convert_and_add([("a", "a"), ("b", "b")], r"C:\out.gdb", False, None)

    def test_bulk_import_warns_about_partial_failures(self):
        def save(src, *_args, **_kwargs):
            if src == "b":
                raise RuntimeError("rikki")
            return src

        self.tool.save_and_reproject = save
        self.tool._add_layers_to_map = lambda _paths, _messages: None

        saved = self.tool._bulk_convert_and_add([("a", "a"), ("b", "b")], r"C:\out.gdb", False, None)

        self.assertEqual(saved, ["a"])
        self.assertIn(("WARNING", "  > Taso 'b' jäi tuomatta: rikki"), self.logged)

    # 2.2 ---------------------------------------------------------------
    def test_geojson_without_geometry_is_a_failure(self):
        def json_to_features(*_args, **_kwargs):
            raise RuntimeError("no features")

        self.arcpy.conversion = types.SimpleNamespace(JSONToFeatures=json_to_features)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.geojson"
            path.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "geometriaa"):
                self.tool.process_geojson_flattened(str(path), r"C:\out.gdb", False, None)

    # 2.3 ---------------------------------------------------------------
    def test_folder_scan_skips_non_spatial_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
            (root / "roads.json").write_text(
                '{ "type" : "FeatureCollection", "features": [] }', encoding="utf-8"
            )
            (root / "esri.json").write_text(
                '{"geometryType": "esriGeometryPoint", "features": []}', encoding="utf-8"
            )

            found = sorted(Path(p).name for p in self.tool._list_supported_import_files(str(root)))

        self.assertEqual(found, ["esri.json", "roads.json"])

    def test_folder_file_count_uses_expanded_paths(self):
        expanded = [r"/data/a/one.gpkg", r"/data/a/b/two.shp", r"/data/other/three.gpx"]

        self.assertEqual(self.tool._count_files_under("/data/a", expanded), 2)
        self.assertEqual(self.tool._count_files_under("/data/none", expanded), 0)

    def test_majority_vote_ignores_outliers(self):
        points = [(385000.0, 6672000.0)] * 9 + [(0.0, 0.0)]

        self.assertEqual(self.module.vote_finnish_epsg(points), 3067)
        self.assertIsNone(self.module.vote_finnish_epsg([(1.0, 1.0)]))


class SharedCrsRuleTests(unittest.TestCase):
    """ArcGIS- ja QGIS-toteutus tunnistavat Suomen koordinaatistot samoin."""

    CASES = (
        ((24.94, 60.17), 4326), ((2776000, 8437000), 3857), ((385000, 6672000), 3067),
        ((1500000, 6700000), 2391), ((2500000, 6700000), 2392), ((3385000, 6672000), 2393),
        ((4400000, 7000000), 2394), ((19500000, 6700000), 3873), ((25497000, 6672000), 3879),
        ((31500000, 7000000), 3885), ((500, 500), None), ((385000, 100000), None),
    )

    def test_both_implementations_agree(self):
        toolbox = load_toolbox(types.ModuleType("arcpy"))
        spec = importlib.util.spec_from_file_location(
            "muuntaja_formats_shared",
            Path(__file__).resolve().parents[1] / "qgis_plugin" / "muuntaja_qgis" / "formats.py")
        formats = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(formats)
        for (x, y), expected in self.CASES:
            with self.subTest(x=x, y=y):
                self.assertEqual(toolbox.classify_finnish_xy(x, y), expected)
                self.assertEqual(formats.classify_finnish_xy(x, y), expected)


if __name__ == "__main__":
    unittest.main()
