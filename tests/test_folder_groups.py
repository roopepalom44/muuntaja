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
            root = Path(directory).resolve()
            for value in folders.values():
                self.assertTrue(Path(value).resolve().is_relative_to(root))
            self.assertEqual(Path(folders[("Äänekoski", "Shared")]).resolve().relative_to(root).parts, ("Äänekoski", "Shared"))
            self.assertEqual(Path(folders[("CON",)]).name, "_CON")

    def test_sibling_allocation_does_not_depend_on_selection_order(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = [("A:B",), ("A?B",), ("a_b",)]
            self.assertEqual(self.tool._export_group_folders(directory, groups),
                             self.tool._export_group_folders(directory, reversed(groups)))

    def test_existing_cad_file_is_preserved_and_export_gets_a_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Topeliuksenpuisto.dgn"
            source.write_bytes(b"original CAD drawing")
            folders = self.tool._export_group_folders(directory, [(), (source.name,)])
            destination = Path(folders[(source.name,)])
            self.assertEqual(destination.name, "Topeliuksenpuisto.dgn_2")
            destination.mkdir(parents=True, exist_ok=True)
            self.assertEqual(source.read_bytes(), b"original CAD drawing")
            self.assertEqual(Path(folders[()]), Path(directory).resolve())

    def test_nested_conflicts_use_the_allocated_parent_and_reuse_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Outer.dgn").write_bytes(b"outer")
            parent = root / "Outer.dgn_2"
            parent.mkdir()
            (parent / "Inner.dgn").write_bytes(b"inner")
            (parent / "keep.shp").write_bytes(b"previous export")
            parts = ("Outer.dgn", "Inner.dgn")
            destination = Path(self.tool._export_group_folders(directory, [parts])[parts])
            self.assertEqual(destination, (parent / "Inner.dgn_2").resolve())
            destination.mkdir(parents=True, exist_ok=True)
            self.assertEqual((parent / "Inner.dgn").read_bytes(), b"inner")
            self.assertEqual((parent / "keep.shp").read_bytes(), b"previous export")
            self.assertEqual(Path(self.tool._export_group_folders(directory, [parts])[parts]), destination)

    def test_file_fallback_does_not_take_another_selected_groups_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("drawing.dgn", "drawing.dgn_2"):
                (root / name).write_bytes(b"keep")
            groups = [("drawing.dgn",), ("drawing.dgn_3",)]
            folders = self.tool._export_group_folders(directory, groups)
            self.assertEqual(Path(folders[groups[0]]).name, "drawing.dgn_4")
            self.assertEqual(Path(folders[groups[1]]).name, "drawing.dgn_3")
            self.assertEqual(folders, self.tool._export_group_folders(directory, reversed(groups)))

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

    def test_native_parameter_keeps_layer_objects(self):
        layer = types.SimpleNamespace(longName="Ryhmä\\roads", URI="unique")
        parameter = types.SimpleNamespace(values=[layer], valueAsText="roads")
        self.assertIs(self.tool._export_paths_from_param(parameter)[0], layer)

    def test_native_gp_copy_recovers_map_group_by_uri(self):
        active_map = FakeMap()
        group = active_map.createGroupLayer("A")
        layer = active_map.addLayerToGroup(group, active_map.addDataFromPath("roads.shp"))[0]
        layer.URI = "original"
        gp_copy = types.SimpleNamespace(longName="roads", URI="original")
        self.arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _: types.SimpleNamespace(activeMap=active_map))
        self.assertIs(self.tool._resolve_export_sources([gp_copy])[0], layer)


if __name__ == "__main__":
    unittest.main()
