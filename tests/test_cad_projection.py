import importlib.machinery
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class ProjectRecorder:
    def __init__(self):
        self.calls = []

    def Project(self, *args):
        self.calls.append(args)


def load_toolbox(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    toolbox_path = Path(__file__).parents[1] / "Toolboxes" / "Muuntaja.pyt"
    loader = importlib.machinery.SourceFileLoader("muuntaja_toolbox", str(toolbox_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CadProjectionTests(unittest.TestCase):
    def setUp(self):
        self.management = ProjectRecorder()
        self.fake_arcpy = types.ModuleType("arcpy")
        self.fake_arcpy.management = self.management
        self.module = load_toolbox(self.fake_arcpy)
        self.tool = self.module.UniversalImportTool()
        self.tool._list_datum_transform = lambda source, target: "datum-transform"

    def test_unknown_scratch_crs_is_passed_to_project(self):
        unknown_sr = types.SimpleNamespace(name="Unknown")
        self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(spatialReference=unknown_sr)
        source_sr = object()
        target_sr = object()

        self.tool._project_cad_data("scratch/Polyline", "output/line", source_sr, target_sr)

        self.assertEqual(
            self.management.calls,
            [("scratch/Polyline", "output/line", target_sr, "datum-transform", source_sr)],
        )

    def test_known_scratch_crs_is_not_overridden(self):
        known_sr = types.SimpleNamespace(name="ETRS89 / TM35FIN(E,N)")
        self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(spatialReference=known_sr)
        source_sr = object()
        target_sr = object()

        self.tool._project_cad_data("scratch/Polyline", "output/line", source_sr, target_sr)

        self.assertEqual(
            self.management.calls,
            [("scratch/Polyline", "output/line", target_sr, "datum-transform")],
        )

    def test_unreadable_scratch_crs_uses_detected_source_crs(self):
        def describe_fails(path):
            raise RuntimeError("describe failed")

        self.fake_arcpy.Describe = describe_fails
        source_sr = object()
        target_sr = object()

        self.tool._project_cad_data("scratch/Polygon", "output/polygon", source_sr, target_sr)

        self.assertEqual(
            self.management.calls,
            [("scratch/Polygon", "output/polygon", target_sr, "datum-transform", source_sr)],
        )

    def test_polygon_does_not_emit_misleading_circle_warning(self):
        self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(shapeType="Polygon")
        messages = []
        self.tool.log = lambda target, message, level="INFO": target.append((level, message))

        self.tool._cad_force_point_entity_type("scratch/Polygon", messages)

        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
