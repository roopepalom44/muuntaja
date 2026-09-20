# -*- coding: utf-8 -*-
"""Testit DFSU:n WKB-geometrialle ja eräajon virheensiedolle."""

import importlib.machinery
import importlib.util
import pathlib
import struct
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLBOX = ROOT / "Toolboxes" / "Muuntaja.pyt"


def load_toolbox_module():
    old_arcpy = sys.modules.get("arcpy")
    fake_arcpy = types.ModuleType("arcpy")
    fake_arcpy.env = types.SimpleNamespace()
    fake_arcpy.da = types.SimpleNamespace()

    class ExecuteError(Exception):
        pass

    fake_arcpy.ExecuteError = ExecuteError
    sys.modules["arcpy"] = fake_arcpy
    try:
        loader = importlib.machinery.SourceFileLoader("muuntaja_toolbox_test", str(TOOLBOX))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        if old_arcpy is None:
            sys.modules.pop("arcpy", None)
        else:
            sys.modules["arcpy"] = old_arcpy


MODULE = load_toolbox_module()
TOOL = MODULE.UniversalImportTool


def unpack_point(wkb):
    endian, geom_type, x, y = struct.unpack("<BIdd", wkb)
    return endian, geom_type, x, y


class DfsuWkbTests(unittest.TestCase):
    """WKB-tavujen on vastattava OGC-määrittelyä ja vanhaa geometriaa."""

    def setUp(self):
        self.tool = TOOL.__new__(TOOL)

    def test_point_wkb_has_correct_header_and_coordinates(self):
        wkb = self.tool._wkb_point(123.5, -45.25)
        endian, geom_type, x, y = unpack_point(wkb)
        self.assertEqual(1, endian)   # little endian
        self.assertEqual(1, geom_type)  # wkbPoint
        self.assertAlmostEqual(123.5, x)
        self.assertAlmostEqual(-45.25, y)
        self.assertEqual(21, len(wkb))

    def test_linestring_wkb_keeps_point_order(self):
        points = [(0.0, 0.0), (10.0, 5.0)]
        wkb = self.tool._wkb_linestring(points)
        endian, geom_type, count = struct.unpack("<BII", wkb[:9])
        self.assertEqual(1, endian)
        self.assertEqual(2, geom_type)  # wkbLineString
        self.assertEqual(2, count)
        coords = struct.unpack("<dddd", wkb[9:])
        self.assertEqual((0.0, 0.0, 10.0, 5.0), coords)

    def test_polygon_ring_is_closed_automatically(self):
        triangle = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        wkb = self.tool._wkb_polygon(triangle)
        endian, geom_type, rings, count = struct.unpack("<BIII", wkb[:13])
        self.assertEqual(1, endian)
        self.assertEqual(3, geom_type)  # wkbPolygon
        self.assertEqual(1, rings)
        self.assertEqual(4, count)  # kolmio + sulkeva piste
        coords = struct.unpack("<" + "d" * 8, wkb[13:])
        self.assertEqual(coords[0:2], coords[6:8])  # eka == vika

    def test_polygon_already_closed_is_not_double_closed(self):
        closed = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]
        wkb = self.tool._wkb_polygon(closed)
        _, _, _, count = struct.unpack("<BIII", wkb[:13])
        self.assertEqual(4, count)

    def test_element_xy_reads_nodes_through_element_table(self):
        node_coords = [(0.0, 0.0), (1.0, 0.0), (0.0, 2.0)]
        element_table = [[0, 1, 2]]
        points = TOOL._dfsu_element_xy(0, node_coords, element_table, "POLYGON")
        self.assertEqual([(0.0, 0.0), (1.0, 0.0), (0.0, 2.0)], points)

    def test_element_xy_falls_back_to_element_coordinates(self):
        points = TOOL._dfsu_element_xy(
            0, None, None, "POINT", element_coordinates=[(5.0, 6.0, 7.0)]
        )
        self.assertEqual([(5.0, 6.0)], points)

    def test_point_from_multi_node_element_is_the_centroid(self):
        node_coords = [(0.0, 0.0), (4.0, 0.0), (2.0, 6.0)]
        element_table = [[0, 1, 2]]
        wkb = self.tool._make_dfsu_wkb(0, node_coords, element_table, "POINT")
        _, _, x, y = unpack_point(wkb)
        self.assertAlmostEqual(2.0, x)
        self.assertAlmostEqual(2.0, y)

    def test_polygon_with_too_few_nodes_raises(self):
        node_coords = [(0.0, 0.0), (1.0, 1.0)]
        element_table = [[0, 1]]
        with self.assertRaises(ValueError):
            self.tool._make_dfsu_wkb(0, node_coords, element_table, "POLYGON")

    def test_missing_geometry_sources_raise(self):
        with self.assertRaises(ValueError):
            self.tool._make_dfsu_wkb(0, None, None, "POINT")


class DfsuColumnTests(unittest.TestCase):
    """Sarakelista ei saa keksiä kenttiä, joita tiedostossa ei ole."""

    def setUp(self):
        self.tool = TOOL.__new__(TOOL)

    def test_missing_mikeio_returns_empty_list(self):
        original = sys.modules.get("mikeio")
        sys.modules["mikeio"] = None  # import mikeio -> ImportError
        try:
            self.assertEqual([], self.tool._read_dfsu_columns_uncached("x.dfsu"))
        finally:
            if original is None:
                sys.modules.pop("mikeio", None)
            else:
                sys.modules["mikeio"] = original

    def test_item_names_are_read_from_mikeio(self):
        fake = types.ModuleType("mikeio")
        fake.open = lambda path: types.SimpleNamespace(
            items=[
                types.SimpleNamespace(name=" Water Depth "),
                types.SimpleNamespace(name="Velocity"),
                types.SimpleNamespace(name=""),
            ]
        )
        original = sys.modules.get("mikeio")
        sys.modules["mikeio"] = fake
        try:
            self.assertEqual(
                ["Water Depth", "Velocity"],
                self.tool._read_dfsu_columns_uncached("x.dfsu"),
            )
        finally:
            if original is None:
                sys.modules.pop("mikeio", None)
            else:
                sys.modules["mikeio"] = original


class BatchSummaryTests(unittest.TestCase):
    """Eräajo jatkaa virheen yli ja kaatuu vasta jos mikään ei onnistunut."""

    def setUp(self):
        self.tool = TOOL.__new__(TOOL)
        self.logged = []
        self.tool.log = lambda messages, text, level="INFO": self.logged.append((level, text))

    def test_all_succeeded_is_reported_without_warning(self):
        self.tool._log_batch_summary(None, "Tuonti", 3, ["a", "b", "c"], [])
        self.assertTrue(any(level == "INFO" for level, _ in self.logged))
        self.assertFalse(any(level == "ERROR" for level, _ in self.logged))

    def test_partial_failure_warns_but_does_not_raise(self):
        self.tool._log_batch_summary(
            None, "Tuonti", 3, ["a", "b"], [("c.dwg", "rikki")]
        )
        levels = [level for level, _ in self.logged]
        self.assertIn("WARNING", levels)
        self.assertNotIn("ERROR", levels)
        self.assertTrue(any("c.dwg" in text for _, text in self.logged))

    def test_total_failure_raises_execute_error(self):
        with self.assertRaises(MODULE.arcpy.ExecuteError):
            self.tool._log_batch_summary(
                None, "Tuonti", 2, [], [("a.dwg", "rikki"), ("b.dwg", "rikki")]
            )
        self.assertTrue(any(level == "ERROR" for level, _ in self.logged))

    def test_single_success_is_quiet(self):
        self.tool._log_batch_summary(None, "Vienti", 1, ["a"], [])
        self.assertEqual([], self.logged)


if __name__ == "__main__":
    unittest.main()
