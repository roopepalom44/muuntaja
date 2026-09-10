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

    def test_mode_switch_keeps_conditional_inputs_optional_for_arcgis_validator(self):
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

        self.assertEqual(parameters[1].parameterType, "Optional")
        self.assertEqual(parameters[15].parameterType, "Optional")

        parameters[0].value = "Vienti"
        parameters[0].valueAsText = "Vienti"
        parameters[1].values = [r"C:\data\old.gpkg"]
        parameters[15].values = ["Vanha taso"]
        self.tool._list_export_layer_options = lambda: self.fail(
            "Vientimoodin validaatio ei saa avata aktiivista karttaa"
        )
        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[1].parameterType, "Optional")
        self.assertEqual(parameters[15].parameterType, "Optional")
        self.assertEqual(parameters[1].values, [])
        self.assertEqual(parameters[15].values, [])

    def test_missing_input_error_is_applied_only_to_active_mode(self):
        class Parameter:
            def __init__(self, value="", values=None):
                self.value = value
                self.values = values
                self.valueAsText = value
                self.enabled = True
                self.parameterType = "Optional"
                self.filter = types.SimpleNamespace(list=[])
                self.error = None

            def setErrorMessage(self, message):
                self.error = message

        parameters = [Parameter("Tuonti"), Parameter(), Parameter()]
        parameters.extend(Parameter() for _ in range(14))

        self.tool.updateMessages(parameters)

        self.assertIn("tiedosto tai kansio", parameters[1].error)
        self.assertIsNone(parameters[15].error)

        parameters[0].value = "Vienti"
        parameters[0].valueAsText = "Vienti"
        self.tool.updateMessages(parameters)

        self.assertIn("aktiivisen kartan taso", parameters[15].error)

    def test_import_mode_restores_project_default_geodatabase_when_output_is_empty(self):
        project_gdb = r"C:\project\Project.gdb"
        self.fake_arcpy.mp = types.SimpleNamespace(
            ArcGISProject=lambda _: types.SimpleNamespace(defaultGeodatabase=project_gdb)
        )

        class Parameter:
            def __init__(self, value=""):
                self.value = value
                self.valueAsText = value
                self.values = None
                self.enabled = True
                self.filter = types.SimpleNamespace(list=[])

        parameters = [Parameter("Tuonti"), Parameter(), Parameter()]
        parameters.extend(Parameter() for _ in range(14))

        self.tool.updateParameters(parameters)

        self.assertEqual(parameters[2].value, project_gdb)

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
            parameters[16].valueAsText = self.module.MULTI_EXPORT_PACKAGING_SEPARATE

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

    def test_dwg_export_can_create_one_file_per_layer(self):
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
            parameters[7].valueAsText = "DWG"
            parameters[8].valueAsText = ""
            parameters[9].value = False
            parameters[10].values = None
            parameters[16].valueAsText = self.module.MULTI_EXPORT_PACKAGING_SEPARATE

            exported = []
            self.tool._prepare_export_feature_class = (
                lambda source, _target_sr, _messages, copy_source=True: source
            )
            self.tool._export_source_label = lambda source: Path(source).stem
            self.tool._export_to_cad = (
                lambda pairs, out_path, _messages, **_kwargs: exported.append(
                    (str(out_path), pairs)
                ) or str(out_path)
            )

            input_paths = [str(folder / "roads"), str(folder / "water")]
            self.tool._execute_export(parameters, Messages(), input_paths)

            self.assertEqual(len(exported), 2)
            self.assertTrue(all(Path(path).suffix == ".dwg" for path, _pairs in exported))
            self.assertTrue(all(len(pairs) == 1 for _path, pairs in exported))

    def test_gpkg_export_defaults_to_one_shared_file(self):
        param = types.SimpleNamespace(valueAsText=None)

        self.assertEqual(
            self.tool._multi_export_packaging_from_param(param, 2, "GPKG"),
            self.module.MULTI_EXPORT_PACKAGING_COMBINED,
        )

        self.assertEqual(
            self.tool._multi_export_packaging_from_param(param, 2, "Shapefile"),
            self.module.MULTI_EXPORT_PACKAGING_SEPARATE,
        )

    def test_shapefile_wide_records_get_a_reduced_field_mapping(self):
        class Field:
            def __init__(self, name, field_type="String", length=254, required=False):
                self.name = name
                self.type = field_type
                self.length = length
                self.required = required

        source_fields = [Field(f"attribute_{index}") for index in range(20)]
        self.fake_arcpy.ListFields = lambda _path: source_fields

        class FakeFieldMap:
            def __init__(self, field):
                self.outputField = field

        class FakeFieldMappings:
            def __init__(self):
                self.fieldValidationWorkspace = None
                self._fields = []

            @property
            def fields(self):
                return list(self._fields)

            def addTable(self, _path):
                self._fields = [
                    Field(field.name, field.type, field.length, field.required)
                    for field in source_fields
                ]

            def findFieldMapIndex(self, name):
                for index, field in enumerate(self._fields):
                    if field.name == name:
                        return index
                return -1

            def getFieldMap(self, index):
                return FakeFieldMap(self._fields[index])

            def replaceFieldMap(self, index, field_map):
                self._fields[index] = field_map.outputField

            def removeFieldMap(self, index):
                self._fields.pop(index)

        self.fake_arcpy.FieldMappings = FakeFieldMappings
        messages = types.SimpleNamespace(
            addMessage=lambda _message: None,
            addWarningMessage=lambda _message: None,
            addErrorMessage=lambda _message: None,
        )

        mappings = self.tool._build_shapefile_field_mappings(
            r"C:\\data\\wide", r"C:\\data", messages
        )

        self.assertIsNotNone(mappings)
        record_length = 1 + sum(self.tool._shapefile_field_width(field) for field in mappings.fields)
        self.assertLessEqual(record_length, self.module.SHAPEFILE_SAFE_RECORD_LENGTH)
        self.assertLess(len(mappings.fields), len(source_fields))

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
