import importlib.machinery
import importlib.util
import os
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
        parameters.extend(Parameter() for _ in range(14))
        parameters[15].enabled = False

        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[1].parameterType, "Required")
        self.assertEqual(parameters[15].parameterType, "Optional")

        parameters[0].value = "Vienti"
        parameters[0].valueAsText = "Vienti"
        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[1].parameterType, "Optional")
        self.assertEqual(parameters[15].parameterType, "Required")

    def test_gpkg_export_can_create_one_file_per_layer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            self.fake_arcpy.Exists = lambda path: Path(str(path)).exists()

            class Messages:
                def addMessage(self, _message):
                    pass

                def addWarningMessage(self, _message):
                    pass

                def addErrorMessage(self, _message):
                    pass

            parameters = [types.SimpleNamespace(value=None, valueAsText=None) for _ in range(17)]
            parameters[5].value = None
            parameters[6].valueAsText = str(folder)
            parameters[7].valueAsText = "GPKG"
            parameters[8].valueAsText = ""
            parameters[9].value = False
            parameters[10].values = None
            parameters[16].valueAsText = self.module.GPKG_EXPORT_PACKAGING_SEPARATE

            exported = []
            self.tool._prepare_export_feature_class = (
                lambda source, _target_sr, _messages, copy_source=True: source
            )
            self.tool._export_source_label = lambda source: Path(source).stem

            def fake_export(_fc_work, out_path, _messages, source_label=None):
                exported.append((str(out_path), source_label))
                return os.path.join(str(out_path), source_label or "layer")

            self.tool._export_to_geopackage = fake_export
            input_paths = [str(folder / "roads"), str(folder / "water")]

            self.tool._execute_export(parameters, Messages(), input_paths)

            self.assertEqual([label for _path, label in exported], ["roads", "water"])
            self.assertEqual(len({path for path, _label in exported}), 2)
            self.assertTrue(all(Path(path).suffix == ".gpkg" for path, _label in exported))

    def test_gpkg_export_defaults_to_one_shared_file(self):
        param = types.SimpleNamespace(valueAsText=None)

        self.assertEqual(
            self.tool._gpkg_export_packaging_from_param(param, 2),
            self.module.GPKG_EXPORT_PACKAGING_COMBINED,
        )

    def test_read_only_export_reuses_source_without_scratch_copy(self):
        self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(
            dataType="FeatureClass",
            catalogPath=path,
            spatialReference=None,
        )

        result = self.tool._prepare_export_feature_class(
            r"C:\data\roads", None, types.SimpleNamespace(), copy_source=False
        )

        self.assertEqual(result, r"C:\data\roads")


if __name__ == "__main__":
    unittest.main()
