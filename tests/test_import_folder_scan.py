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

    def test_export_layers_use_arcgis_native_multivalue_feature_layer_parameter(self):
        class Filter:
            def __init__(self):
                self.type = None
                self.list = []

        class Parameter:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
                self.value = None
                self.values = []
                self.valueAsText = None
                self.enabled = True
                self.multiValue = False
                self.filter = Filter()

        self.fake_arcpy.Parameter = Parameter
        self.fake_arcpy.mp = types.SimpleNamespace(
            ArcGISProject=lambda _: types.SimpleNamespace(
                defaultGeodatabase=r"C:\project\Project.gdb",
                activeMap=None,
            )
        )

        parameters = self.tool.getParameterInfo()
        export_layers = parameters[15]

        self.assertEqual(export_layers.datatype, "GPFeatureLayer")
        self.assertTrue(export_layers.multiValue)
        self.assertFalse(export_layers.enabled)
        self.assertEqual(parameters[10].datatype, "GPValueTable")
        self.assertEqual(
            parameters[10].columns,
            [["GPFeatureLayer", "Taso"], ["Field", "Taulukkoon vietävä kenttä"]],
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
        self.fake_arcpy.mp = types.SimpleNamespace(
            ArcGISProject=lambda _: self.fail(
                "Vientimoodin vaihto ei saa avata aktiivista karttaa"
            )
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

            def clearMessage(self):
                self.error = None

        parameters = [Parameter("Tuonti"), Parameter(), Parameter()]
        parameters.extend(Parameter() for _ in range(14))

        self.tool.updateMessages(parameters)

        self.assertIn("tiedosto tai kansio", parameters[1].error)
        self.assertIsNone(parameters[15].error)

        parameters[0].value = "Vienti"
        parameters[0].valueAsText = "Vienti"
        self.tool.updateMessages(parameters)

        self.assertIn("aktiivisen kartan taso", parameters[15].error)
        self.assertIsNone(parameters[1].error)

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

    def test_duplicate_export_layers_are_removed_preserving_order(self):
        param = types.SimpleNamespace(values=["Roads", "Water", "Roads"], valueAsText=None)

        self.assertEqual(
            self.tool._export_paths_from_param(param),
            ["Roads", "Water"],
        )

    def test_cad_table_fields_are_selected_separately_for_each_layer(self):
        specs = [
            ("Roads", "name"),
            ("Roads", "speed"),
            ("Water", "depth"),
        ]

        self.assertEqual(
            self.tool._cad_table_fields_for_source(specs, "Roads"),
            ["name", "speed"],
        )
        self.assertEqual(
            self.tool._cad_table_fields_for_source(specs, "Water"),
            ["depth"],
        )

    def test_cad_table_rows_follow_selected_export_layers(self):
        param = types.SimpleNamespace(
            values=[["Roads", "name"], ["Roads", "speed"]],
            valueAsText=None,
        )

        self.tool._sync_cad_table_rows(param, ["Roads", "Water"])

        self.assertEqual(
            param.values,
            [["Roads", "name"], ["Roads", "speed"], ["Water", None]],
        )

    def test_cad_tables_are_positioned_side_by_side(self):
        self.fake_arcpy.Exists = lambda _path: False
        exported = []
        self.fake_arcpy.conversion = types.SimpleNamespace(
            ExportCAD=lambda *args: exported.append(args)
        )
        self.tool._cad_get_point_pdsize = lambda *_args, **_kwargs: None
        self.tool._cad_attribute_table_layout_origin = lambda *_args: (100.0, 200.0, 10.0)
        self.tool._export_source_label = lambda source: source
        prepared = []

        def prepare_pair(
            fc_path,
            in_src,
            _messages,
            _cad_label,
            _symbology,
            _height,
            _emit_table,
            fields,
            anchor,
            layer_name,
            title,
        ):
            prepared.append((in_src, list(fields), anchor, layer_name, title))
            return fc_path, None, [f"{fc_path}_table"], 50.0

        self.tool._cad_prepare_pair_for_export = prepare_pair
        messages = types.SimpleNamespace(
            addMessage=lambda _message: None,
            addWarningMessage=lambda _message: None,
            addErrorMessage=lambda _message: None,
        )

        self.tool._export_to_cad(
            [("roads_fc", "Roads"), ("water_fc", "Water")],
            r"C:\output\combined.dwg",
            messages,
            emit_attr_table=True,
            attr_table_specs=[
                ("Roads", "name"),
                ("Roads", "speed"),
                ("Water", "depth"),
            ],
        )

        self.assertEqual(prepared[0][1], ["name", "speed"])
        self.assertEqual(prepared[1][1], ["depth"])
        self.assertEqual(prepared[0][2], (100.0, 200.0))
        self.assertEqual(prepared[1][2], (160.0, 200.0))
        self.assertNotEqual(prepared[0][3], prepared[1][3])
        self.assertEqual(len(exported), 1)

    def test_export_does_not_add_outputs_to_active_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.fake_arcpy.Exists = lambda _path: False
            self.fake_arcpy.mp = types.SimpleNamespace(
                ArcGISProject=lambda _: self.fail("Vienti ei saa avata aktiivista karttaa")
            )
            parameters = [types.SimpleNamespace(value=None, valueAsText=None) for _ in range(17)]
            parameters[5].value = "stale-import-crs"
            parameters[6].valueAsText = temp_dir
            parameters[7].valueAsText = "GeoJSON"
            parameters[8].valueAsText = ""
            parameters[9].value = False
            parameters[10].values = []
            parameters[16].valueAsText = self.module.MULTI_EXPORT_PACKAGING_COMBINED
            target_values = []

            def prepare(source, target_sr, _messages, copy_source=True):
                target_values.append(target_sr)
                return source

            self.tool._prepare_export_feature_class = prepare
            self.tool._export_source_label = lambda _source: "roads"
            self.tool._export_to_geojson = lambda _fc, out, _messages: out
            messages = types.SimpleNamespace(
                addMessage=lambda _message: None,
                addWarningMessage=lambda _message: None,
                addErrorMessage=lambda _message: None,
            )

            self.tool._execute_export(parameters, messages, ["Roads"])

            self.assertEqual(target_values, [None])

    def test_geopackage_schema_prefix_is_not_used_as_layer_name(self):
        self.assertEqual(
            self.tool._geopackage_import_output_name(
                r"C:\data\nopeusrajoitus_20260911.gpkg",
                "main.Nopeusrajoitus",
            ),
            "nopeusrajoitus",
        )
        self.assertEqual(
            self.tool._geopackage_import_output_name(
                r"C:\data\nopeusrajoitus_20260911.gpkg",
                "main",
            ),
            "nopeusrajoitus_20260911",
        )

    def test_combined_geopackage_does_not_overwrite_duplicate_layer_name(self):
        out_path = os.path.normpath(r"C:\output\combined.gpkg")
        first_target = os.path.join(out_path, "roads")
        existing = {
            os.path.normcase(out_path),
            os.path.normcase(first_target),
        }
        copied = []
        self.fake_arcpy.Exists = lambda path: os.path.normcase(os.path.normpath(str(path))) in existing
        self.fake_arcpy.Describe = lambda _path: types.SimpleNamespace(name="roads")
        self.fake_arcpy.management = types.SimpleNamespace(
            CopyFeatures=lambda source, target: copied.append((source, target)),
            CreateSQLiteDatabase=lambda *_args: None,
        )
        messages = types.SimpleNamespace(
            addMessage=lambda _message: None,
            addWarningMessage=lambda _message: None,
            addErrorMessage=lambda _message: None,
        )

        target = self.tool._export_to_geopackage(
            "roads_fc", out_path, messages, source_label="roads"
        )

        self.assertEqual(target, os.path.join(out_path, "roads_2"))
        self.assertEqual(copied, [("roads_fc", target)])

    def test_combined_geopackage_counts_as_one_output_file(self):
        paths = [
            r"C:\output\combined.gpkg\roads",
            r"C:\output\combined.gpkg\water",
        ]

        self.assertEqual(
            self.tool._export_output_file_paths(paths),
            [r"C:\output\combined.gpkg"],
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
