import importlib.machinery
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


def load_toolbox(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    toolbox_path = Path(__file__).parents[1] / "Toolboxes" / "Muuntaja.pyt"
    loader = importlib.machinery.SourceFileLoader("muuntaja_folder_toolbox", str(toolbox_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ImportFolderScanTests(unittest.TestCase):
    def setUp(self):
        self.fake_arcpy = types.ModuleType("arcpy")
        self.module = load_toolbox(self.fake_arcpy)
        self.tool = self.module.UniversalImportTool()

    def test_folder_scan_is_recursive_and_ignores_sidecars(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "Nested"
            deeper = nested / "Deeper"
            deeper.mkdir(parents=True)

            supported = [
                root / "surface.GPKG",
                nested / "roads.SHP",
                deeper / "model.DFSU",
                deeper / "track.GpX",
            ]
            for path in supported:
                path.write_text("test", encoding="utf-8")

            # Shapefilen sivutiedosto ja tuntematon tiedostomuoto eivät ole
            # erillisiä tuontisyötteitä.
            (nested / "roads.dbf").write_text("sidecar", encoding="utf-8")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            actual = [Path(path) for path in self.tool._list_supported_import_files(str(root))]

            self.assertEqual(actual, sorted(supported, key=lambda path: str(path.relative_to(root)).casefold()))

    def test_expansion_deduplicates_overlapping_folder_and_file_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            first = root / "first.gpkg"
            second = nested / "second.shp"
            first.write_text("test", encoding="utf-8")
            second.write_text("test", encoding="utf-8")

            expanded = self.tool._expand_import_paths([str(root), str(nested), str(first)])

            self.assertEqual(
                [Path(path) for path in expanded],
                [first, second],
            )

    def test_output_name_collision_uses_next_available_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            (output_folder / "roads.shp").write_text("existing", encoding="utf-8")
            (output_folder / "roads_2.shp").write_text("existing", encoding="utf-8")
            self.fake_arcpy.Exists = lambda path: Path(path).exists()

            name, path = self.tool._resolve_output_path(str(output_folder), "roads", True)

            self.assertEqual(name, "roads_3")
            self.assertEqual(Path(path), output_folder / "roads_3.shp")

    def test_export_layer_options_include_group_layers_and_resolve_sources(self):
        class FakeLayer:
            def __init__(self, name, source=None, children=None):
                self.name = name
                self.dataSource = source or ""
                self.isGroupLayer = children is not None
                self.isFeatureLayer = children is None
                self.isBasemapLayer = False
                self.isBroken = False
                self._children = children or []

            def listLayers(self):
                return self._children

        roads = FakeLayer("Roads", r"C:\data.gdb\roads")
        grouped_roads = FakeLayer("Roads", r"C:\other.gdb\roads")
        group = FakeLayer("Transport", children=[grouped_roads])
        project = types.SimpleNamespace(activeMap=types.SimpleNamespace(listLayers=lambda: [roads, group]))
        self.fake_arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _: project)
        self.fake_arcpy.Describe = lambda layer: types.SimpleNamespace(
            catalogPath=layer.dataSource,
            dataType="FeatureLayer",
            shapeFieldName="Shape",
        )

        class Filter:
            type = None
            list = []

        param = types.SimpleNamespace(filter=Filter(), values=None, valueAsText=None)
        paths = self.tool._configure_export_layer_choices(param)

        self.assertEqual(param.filter.list, ["Roads", "Transport / Roads"])
        self.assertEqual(paths, [])

        param.values = ["Transport / Roads"]
        self.assertEqual(
            self.tool._export_paths_from_param(param),
            [r"C:\other.gdb\roads"],
        )

    def test_shapefile_source_is_valid_export_input(self):
        self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(
            dataType="Shapefile",
            shapeFieldName="Shape",
        )

        self.assertEqual(self.tool._bulk_export_mode([r"C:\data\roads.shp"]), "export")

    def test_mode_switch_marks_only_active_input_as_required(self):
        class Parameter:
            def __init__(self, value="", values=None):
                self.value = value
                self.values = values
                self.valueAsText = value
                self.enabled = True
                self.parameterType = "Optional"
                self.filter = types.SimpleNamespace(list=[])

            def setErrorMessage(self, _message):
                pass

        parameters = [Parameter("Tuonti"), Parameter(), Parameter()]
        parameters.extend(Parameter() for _ in range(13))
        parameters[15].enabled = False

        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[1].parameterType, "Required")
        self.assertEqual(parameters[15].parameterType, "Optional")

        parameters[0].value = "Vienti"
        parameters[0].valueAsText = "Vienti"
        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[1].parameterType, "Optional")
        self.assertEqual(parameters[15].parameterType, "Required")


if __name__ == "__main__":
    unittest.main()
