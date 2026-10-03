"""Tests for resolving the Esri credentials false-alarm and accurate batch reporting."""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_raster_import import FakeLayer, FakeMap, load_toolbox


class CredentialsAndMapFailuresTests(unittest.TestCase):
    def setUp(self):
        self.arcpy = types.ModuleType("arcpy")
        self.arcpy.env = types.SimpleNamespace(workspace="", scratchGDB="")
        self.arcpy.management = types.SimpleNamespace(
            ClearWorkspaceCache=lambda *_args: None,
            Delete=lambda *_args: None,
        )
        self.module = load_toolbox(self.arcpy)
        self.tool = self.module.UniversalImportTool()
        self.logged = []
        self.tool.log = lambda messages, text, level="INFO": self.logged.append((level, text))

    def test_sanitize_name_prefixes_digits_with_t_not_n(self):
        self.assertEqual(self.tool.sanitize_name("1111_1111"), "t_1111_1111")
        self.assertEqual(self.tool.sanitize_name("1111_1111_2"), "t_1111_1111_2")
        self.assertEqual(self.tool.sanitize_name("123"), "t_123")
        self.assertEqual(self.tool.sanitize_name("roads_2026"), "roads_2026")

    def test_sanitize_name_rewrites_esri_network_pattern(self):
        # n_<digits>_ pattern triggers Esri network dataset credentials bug
        self.assertEqual(self.tool.sanitize_name("n_1111_1111"), "t_1111_1111")
        self.assertEqual(self.tool.sanitize_name("N_1_EDGE"), "t_1_edge")
        # plain n_ without second underscore is not an Esri network pattern
        self.assertEqual(self.tool.sanitize_name("n_roads"), "n_roads")
        self.assertEqual(self.tool.sanitize_name("n_1111"), "n_1111")

    def test_resolve_output_path_prevents_n_digits_pattern(self):
        self.arcpy.ValidateTableName = lambda name, _loc: name
        self.arcpy.Exists = lambda _path: False
        out_name, check_path = self.tool._resolve_output_path("C:/data.gdb", "n_1111_1111", False)
        self.assertEqual(out_name, "t_1111_1111")
        self.assertTrue(check_path.endswith("t_1111_1111"))

    def test_log_batch_summary_reports_warning_when_map_additions_fail(self):
        self.tool._log_batch_summary(
            None,
            "Tuonti",
            11,
            ["file" + str(i) for i in range(11)],
            [],
            map_failures=[
                ("C:/data.gdb/layer1", "Failed to add data. Possible credentials issue."),
                ("C:/data.gdb/layer2", "Failed to add data. Possible credentials issue."),
            ],
        )
        levels = [level for level, _ in self.logged]
        texts = [text for _, text in self.logged]
        self.assertIn("WARNING", levels)
        self.assertFalse(any(text.startswith("Tuonti valmis: 11/11 onnistui.") for text in texts))
        self.assertTrue(any("valmis varoituksin" in text for text in texts))
        self.assertTrue(any("KARTTALISÄYS EPÄONNISTUI" in text and "layer1" in text for text in texts))
        self.assertTrue(any("KARTTALISÄYS EPÄONNISTUI" in text and "layer2" in text for text in texts))

    def test_log_batch_summary_reports_clean_success_when_no_map_failures(self):
        self.tool._log_batch_summary(
            None,
            "Tuonti",
            11,
            ["file" + str(i) for i in range(11)],
            [],
            map_failures=[],
        )
        levels = [level for level, _ in self.logged]
        texts = [text for _, text in self.logged]
        self.assertEqual(levels, ["INFO"])
        self.assertEqual(texts, ["Tuonti valmis: 11/11 onnistui."])

    def test_add_data_to_map_with_fallback_recovers_from_credentials_error(self):
        active_map = FakeMap()
        target_path = "C:/test.gdb/n_1111_1111"

        def failing_add(path):
            if path == target_path:
                raise RuntimeError("Failed to add data. Possible credentials issue.")
            # Fallback path (.lyrx) succeeds
            return FakeLayer("fallback_layer", data_source=str(path))

        active_map.addDataFromPath = failing_add

        saved_files = []
        self.arcpy.Describe = lambda _p: types.SimpleNamespace(
            baseName="n_1111_1111",
            dataType="FeatureClass"
        )
        self.arcpy.management.MakeFeatureLayer = lambda path, name: None
        self.arcpy.management.SaveToLayerFile = lambda name, out_lyrx: saved_files.append(out_lyrx)
        self.arcpy.Exists = lambda _p: False

        layer = self.tool._add_data_to_map_with_fallback(active_map, target_path)
        self.assertIsNotNone(layer)
        self.assertEqual(layer.name, "n_1111_1111")
        self.assertEqual(len(saved_files), 1)


if __name__ == "__main__":
    unittest.main()
