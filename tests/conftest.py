"""Scoped GIS test fixtures; never leave fake modules in other test sessions."""

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def arc_tool(monkeypatch):
    arcpy = types.ModuleType("arcpy")
    arcpy.ExecuteError = type("ExecuteError", (Exception,), {})
    arcpy.env = types.SimpleNamespace(workspace=None, scratchGDB="scratch.gdb")
    arcpy.management = types.SimpleNamespace()
    arcpy.conversion = types.SimpleNamespace()
    arcpy.da = types.SimpleNamespace()
    arcpy.Exists = lambda _path: False
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)
    module = load_module("audit_arc_toolbox", ROOT / "Toolboxes/Muuntaja.pyt")
    tool = module.UniversalImportTool()
    tool.logs = []
    tool.log = lambda _messages, text, level="INFO": tool.logs.append((level, text))
    return tool, arcpy, module


@pytest.fixture
def mock_qgis(monkeypatch):
    class CRS:
        def __init__(self, name=""):
            self.name = name

        def authid(self):
            return self.name

        def isValid(self):
            return bool(self.name)

        def __eq__(self, other):
            return isinstance(other, CRS) and self.name == other.name

    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")
    for name in (
        "QgsCoordinateTransform",
        "QgsFeature",
        "QgsField",
        "QgsFields",
        "QgsGeometry",
        "QgsRasterLayer",
        "QgsVectorLayer",
        "QgsWkbTypes",
    ):
        setattr(core, name, type(name, (), {}))
    core.QgsCoordinateReferenceSystem = CRS
    core.QgsProject = types.SimpleNamespace(instance=lambda: object())
    core.QgsVectorFileWriter = type(
        "Writer", (), {"FieldValueConverter": type("Converter", (), {})}
    )
    qt = types.ModuleType("qgis.PyQt.QtCore")
    qt.QVariant = types.SimpleNamespace(String=10, Int=2, Double=6)
    deleted = []
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.sip = types.SimpleNamespace(
        isdeleted=lambda value: value in deleted, delete=deleted.append
    )
    for name, value in {
        "qgis": qgis,
        "qgis.core": core,
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtCore": qt,
    }.items():
        monkeypatch.setitem(sys.modules, name, value)
    package = types.ModuleType("audit_qgis")
    package.__path__ = [str(ROOT / "qgis_plugin/muuntaja_qgis")]
    monkeypatch.setitem(sys.modules, "audit_qgis", package)
    module = load_module(
        "audit_qgis.processing", ROOT / "qgis_plugin/muuntaja_qgis/processing.py"
    )
    return module, deleted
