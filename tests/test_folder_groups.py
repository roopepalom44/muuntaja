"""Folder/group boundary cases without an ArcGIS license."""

import tempfile
import types
import unittest
from pathlib import Path

from test_raster_import import FakeMap, load_toolbox


class FolderGroupTests(unittest.TestCase):
    def setUp(self):
        self.arcpy = types.ModuleType("arcpy")
        self.module = load_toolbox(self.arcpy)
        self.tool = self.module.UniversalImportTool()

    def test_relative_hierarchy_root_and_direct_file(self):
        root = Path(tempfile.gettempdir()) / "inputs"
        self.assertEqual(self.tool._import_folder_parts(str(root / "a/b/file.shp"), [str(root)]), ("a", "b"))
        self.assertEqual(self.tool._import_folder_parts(str(root / "file.shp"), [str(root)]), ())
        self.assertEqual(self.tool._import_folder_parts(str(root / "a/file.shp"), []), ())
        self.assertEqual(self.tool._import_folder_parts(str(root.with_name("inputs_other") / "file.shp"), [str(root)]), ())

    def test_overlapping_roots_choose_closest_selected_folder(self):
        root = Path(tempfile.gettempdir()) / "inputs"
        self.assertEqual(self.tool._import_folder_parts(str(root / "a/b/file.shp"), [str(root), str(root / "a")]), ("b",))

    def test_same_leaf_name_under_different_parents_stays_separate(self):
        active_map = FakeMap()
        first = self.tool._get_or_create_group_path(active_map, ("A", "Shared"))
        second = self.tool._get_or_create_group_path(active_map, ("B", "Shared"))
        self.assertIsNot(first, second)
        self.assertIs(self.tool._get_or_create_group_path(active_map, ("A", "Shared")), first)
        self.assertEqual(len(active_map.created_groups), 4)

    def test_unsafe_names_and_collisions_are_distinct_and_within_root(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = [(), ("A:B",), ("A?B",), ("CON",), ("..",), ("Äänekoski", "Shared")]
            folders = self.tool._export_group_folders(directory, groups)
            self.assertEqual(len({value.casefold() for value in folders.values()}), len(groups))
            for value in folders.values():
                self.assertTrue(Path(value).is_relative_to(Path(directory)))
            self.assertEqual(Path(folders[("Äänekoski", "Shared")]).relative_to(directory).parts, ("Äänekoski", "Shared"))
            self.assertEqual(Path(folders[("CON",)]).name, "_CON")

    def test_sibling_allocation_does_not_depend_on_selection_order(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = [("A:B",), ("A?B",), ("a_b",)]
            self.assertEqual(self.tool._export_group_folders(directory, groups),
                             self.tool._export_group_folders(directory, reversed(groups)))

    def test_export_resolution_preserves_layer_identity(self):
        active_map = FakeMap()
        group = active_map.createGroupLayer("A")
        layer = active_map.addLayerToGroup(group, active_map.addDataFromPath("roads.shp"))[0]
        self.arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _: types.SimpleNamespace(activeMap=active_map))
        self.assertIs(self.tool._resolve_export_sources(["A\\roads"])[0], layer)
        self.assertIs(self.tool._resolve_export_sources([layer])[0], layer)

    def test_ambiguous_short_names_do_not_export_the_wrong_layer(self):
        active_map = FakeMap()
        for name in ("A", "B"):
            group = active_map.createGroupLayer(name)
            layer = active_map.addDataFromPath("roads.shp")
            active_map.addLayerToGroup(group, layer)
            active_map.removeLayer(layer)
        self.arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _: types.SimpleNamespace(activeMap=active_map))
        with self.assertRaisesRegex(ValueError, "moniselitteinen"):
            self.tool._resolve_export_sources(["roads"])

    def test_picker_does_not_merge_groups_differing_by_case(self):
        paths = ["A\\roads", "a\\roads", "A\\roads"]
        self.assertEqual(self.tool._export_paths_from_param(None, paths), paths[:2])


if __name__ == "__main__":
    unittest.main()
