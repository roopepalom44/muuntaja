"""Shapefile-kenttäkartan regressiotestit ilman ArcGIS-asennusta."""

import copy
import importlib.machinery
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FieldMappings:
    def __init__(self, fields):
        self.fields = copy.deepcopy(fields)

    def addTable(self, _path):
        pass

    def findFieldMapIndex(self, name):
        return next(i for i, field in enumerate(self.fields) if field.name == name)

    def getFieldMap(self, index):
        return types.SimpleNamespace(outputField=copy.deepcopy(self.fields[index]))

    def replaceFieldMap(self, index, field_map):
        self.fields[index] = copy.deepcopy(field_map.outputField)

    def removeFieldMap(self, index):
        self.fields.pop(index)


def field(name, field_type, length=8):
    return types.SimpleNamespace(name=name, type=field_type, length=length, required=False)


class ShapefileExportTests(unittest.TestCase):
    def setUp(self):
        self.source = []
        self.arcpy = types.ModuleType("arcpy")
        self.arcpy.ListFields = lambda _path: self.source
        self.arcpy.FieldMappings = lambda: FieldMappings(self.source)
        toolbox = Path(__file__).resolve().parents[1] / "Toolboxes" / "Muuntaja.pyt"
        loader = importlib.machinery.SourceFileLoader("muuntaja_shapefile_tests", str(toolbox))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"arcpy": self.arcpy}):
            loader.exec_module(self.module)
        self.tool = self.module.UniversalImportTool()
        self.logs = []
        self.tool.log = lambda _messages, text, level="INFO": self.logs.append((level, text))

    def mappings(self):
        return self.tool._build_shapefile_field_mappings("source", "output", None)

    def test_small_big_integer_dataset_also_requires_mapping(self):
        self.source = [field("identifier", "BigInteger"), field("value", "Double")]
        mappings = self.mappings()
        self.assertEqual(mappings.fields[0].type, "String")
        self.assertEqual(mappings.fields[0].length, 20)
        self.assertEqual(mappings.fields[1].type, "Double")
        self.assertEqual(self.source[0].type, "BigInteger")
        self.assertTrue(any(level == "WARNING" and "identifier" in text for level, text in self.logs))

    def test_new_date_types_and_identifiers_have_supported_output_types(self):
        self.source = [field(name, name) for name in
                       ("DateOnly", "TimeOnly", "TimestampOffset", "GUID", "GlobalID")]
        mappings = self.mappings()
        self.assertTrue(all(item.type == "String" for item in mappings.fields))
        self.assertGreaterEqual(mappings.fields[2].length, len("2026-09-30T18:12:22.123456+03:00"))
        self.assertEqual(mappings.fields[3].length, 38)

    def test_binary_fields_are_removed_with_a_warning(self):
        self.source = [field("image", "Raster"), field("bytes", "Blob"), field("value", "Integer")]
        mappings = self.mappings()
        self.assertEqual([item.name for item in mappings.fields], ["value"])
        self.assertTrue(any("image" in text and "bytes" in text for _level, text in self.logs))

    def test_wide_records_use_converted_width_and_keep_short_identifiers(self):
        self.source = [field(f"text_{i}", "String", 1000) for i in range(20)]
        self.source += [field("identifier", "BigInteger")]
        mappings = self.mappings()
        self.assertLessEqual(1 + sum(self.tool._shapefile_field_width(item) for item in mappings.fields),
                             self.module.SHAPEFILE_SAFE_RECORD_LENGTH)
        self.assertTrue(any(item.name == "identifier" and item.type == "String"
                            for item in mappings.fields))
        self.assertTrue(all(item.length <= 254 for item in mappings.fields))

    def test_supported_small_schema_keeps_default_conversion(self):
        self.source = [field("name", "String", 100), field("value", "Integer")]
        self.assertIsNone(self.mappings())


if __name__ == "__main__":
    unittest.main()
