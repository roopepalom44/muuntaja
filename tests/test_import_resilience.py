"""Regression tests for batch severity and isolation of native CAD crashes."""

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ImportResilienceTests(unittest.TestCase):
    def setUp(self):
        self.arcpy = types.ModuleType("arcpy")
        self.arcpy.management = types.SimpleNamespace(ClearWorkspaceCache=lambda *_args: None)
        loader = importlib.machinery.SourceFileLoader("muuntaja_resilience", str(
            Path(__file__).resolve().parents[1] / "Toolboxes" / "Muuntaja.pyt"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"arcpy": self.arcpy}):
            loader.exec_module(self.module)
        self.messages = []
        self.sink = types.SimpleNamespace(
            addMessage=lambda text: self.messages.append(("INFO", text)),
            addWarningMessage=lambda text: self.messages.append(("WARNING", text)),
            addErrorMessage=lambda text: self.messages.append(("ERROR", text)),
        )
        self.tool = self.module.UniversalImportTool()

    def test_item_error_is_warning_until_batch_summary(self):
        item = self.module.ImportItemMessages(self.sink)
        item.addErrorMessage("bad file")
        item.addMessage("next file succeeded")
        self.assertEqual(self.messages, [("WARNING", "bad file"), ("INFO", "next file succeeded")])
        self.sink.addErrorMessage("all files failed")
        self.assertEqual(self.messages[-1][0], "ERROR")

    def test_native_worker_crash_becomes_python_exception(self):
        with patch.object(self.module.subprocess, "run", return_value=types.SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "CAD-lukija keskeytyi"):
                self.tool.process_cad("input.dwg", "output.gdb", False, False, None, None, self.sink)

    def test_worker_timeout_becomes_actionable_exception(self):
        with patch.object(self.module.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 3600)):
            with self.assertRaisesRegex(RuntimeError, "aikaraja"):
                self.tool.process_cad("input.dwg", "output.gdb", False, False, None, None, self.sink)

    def test_successful_worker_copies_staged_features_and_preserves_crs(self):
        captured = []
        sr = types.SimpleNamespace(exportToString=lambda: "EPSG:3067")

        def worker(command, **kwargs):
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            self.assertEqual(request["input_sr"], "EPSG:3067")
            self.assertTrue(kwargs["capture_output"])
            Path(command[-1]).write_text(json.dumps({"paths": ["staged.gdb/roads"],
                "messages": [["WARNING", "one empty layer skipped"]]}), encoding="utf-8")
            return types.SimpleNamespace(returncode=0)

        self.tool._bulk_convert_and_add = lambda *args: captured.append(args) or ["output.gdb/roads"]
        with patch.object(self.module.subprocess, "run", side_effect=worker):
            result = self.tool.process_cad("input.dwg", "output.gdb", False, True, sr, None, self.sink)
        self.assertEqual(result, ["output.gdb/roads"])
        self.assertEqual(captured[0][0], [("staged.gdb/roads", "roads")])
        self.assertTrue(any(level == "WARNING" for level, _text in self.messages))

    def test_worker_rejection_does_not_copy_partial_features(self):
        def worker(command, **_kwargs):
            Path(command[-1]).write_text(json.dumps({"paths": ["partial.gdb/roads"],
                "error": "invalid input", "messages": [["ERROR", "invalid input"]]}), encoding="utf-8")
            return types.SimpleNamespace(returncode=1)

        self.tool._bulk_convert_and_add = lambda *_args: self.fail("Must not copy partial worker output")
        with patch.object(self.module.subprocess, "run", side_effect=worker):
            with self.assertRaisesRegex(RuntimeError, "invalid input"):
                self.tool.process_cad("input.dwg", "output.gdb", False, False, None, None, self.sink)
        self.assertFalse(any(level == "ERROR" for level, _text in self.messages))

    def test_folder_import_uses_shapefile_schema_adapter(self):
        self.tool._resolve_output_path = lambda *_args: ("data", "output/data.shp")
        self.tool._count_safe = lambda _path: 2
        calls = []
        self.tool._export_to_shapefile = lambda *args: calls.append(args) or args[1]
        result = self.tool.save_and_reproject("input", "output", "data", True,
            None, None, None, self.sink, add_to_map=False)
        self.assertEqual(result, "output/data.shp")
        self.assertEqual(calls[0][:2], ("input", "output/data.shp"))

    def test_failed_mapping_partial_output_does_not_block_copy_fallback(self):
        class ExecuteError(Exception):
            pass

        existing = set()
        self.arcpy.ExecuteError = ExecuteError
        self.arcpy.Exists = lambda path: path in existing
        self.arcpy.management.Delete = lambda path: existing.remove(path)
        self.tool._resolve_output_path = lambda *_args: ("data", "output/data")
        self.tool._count_safe = lambda _path: 2

        def convert(*_args, **_kwargs):
            existing.add("output/data")
            raise ExecuteError("invalid geometry after output creation")

        def copy(_source, target):
            self.assertNotIn(target, existing, "Partial GP output blocked fallback")
            existing.add(target)

        self.arcpy.conversion = types.SimpleNamespace(FeatureClassToFeatureClass=convert)
        self.arcpy.management.CopyFeatures = copy
        result = self.tool.save_and_reproject("input", "output", "data", False,
            object(), None, None, self.sink, add_to_map=False)
        self.assertEqual(result, "output/data")
        self.assertEqual(existing, {"output/data"})

    def test_embedded_raster_crs_enables_mosaic_without_world_file(self):
        sr = types.SimpleNamespace(name="TM35FIN", factoryCode=3067)
        self.arcpy.Describe = lambda _path: types.SimpleNamespace(spatialReference=sr)
        self.tool._guess_raster_epsg = lambda _path: self.fail("Known embedded CRS must be used")
        self.assertIs(self.tool._common_raster_spatial_reference(["one.tif", "two.tif"], None), sr)

    def test_mixed_raster_crs_uses_individual_import(self):
        self.arcpy.Describe = lambda path: types.SimpleNamespace(spatialReference=
            types.SimpleNamespace(name=path, factoryCode=3067 if path == "one.tif" else 3877))
        self.assertIsNone(self.tool._common_raster_spatial_reference(["one.tif", "two.tif"], None))


if __name__ == "__main__":
    unittest.main()
