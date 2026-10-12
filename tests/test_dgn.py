"""DGN uses the CAD dispatch, controls, grouping and native V8 export type."""

import types
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("suffix", [".dgn", ".DGN"])
def test_dgn_import_uses_cad_worker_with_both_crs(arc_tool, tmp_path, suffix):
    tool, arcpy, _module = arc_tool
    path = tmp_path / ("design" + suffix)
    path.write_bytes(b"DGN")
    arcpy.Describe = lambda _path: types.SimpleNamespace(
        dataType="Workspace", workspaceType="LocalDatabase"
    )
    source, target = object(), object()
    tool._parse_input_sr = lambda _value: source
    tool._spatial_ref_from_param = lambda _value: target
    tool.process_cad = Mock()
    tool.process_generic = Mock(side_effect=AssertionError("DGN must use CAD import"))
    parameters = [types.SimpleNamespace(value=None, valueAsText="") for _ in range(16)]
    parameters[2].valueAsText = "output.gdb"
    parameters[3].value = True
    tool._execute_import(parameters, Mock(), [str(path)])
    tool.process_cad.assert_called_once()
    assert tool.process_cad.call_args.args[:6] == (
        str(path), "output.gdb", False, True, source, target,
    )


def test_dgn_catalog_subclass_and_import_crs_controls(arc_tool):
    tool, arcpy, _module = arc_tool
    assert tool._is_supported_import_catalog_path(r"C:\data\drawing.DGN\Polyline")

    class Parameter:
        def __init__(self, value=""):
            self.value = value
            self.valueAsText = value
            self.values = None
            self.enabled = True
            self.filter = types.SimpleNamespace(list=[])

    parameters = [Parameter() for _ in range(16)]
    parameters[0] = Parameter("Tuonti")
    parameters[1] = Parameter(r"C:\data\drawing.dgn")
    arcpy.mp = types.SimpleNamespace(
        ArcGISProject=lambda _key: types.SimpleNamespace(defaultGeodatabase="output.gdb")
    )
    tool.updateParameters(parameters)
    assert parameters[3].enabled  # CAD cleanup
    assert parameters[4].enabled  # Source CRS
    assert parameters[5].enabled  # Target CRS
    assert not parameters[7].enabled


def test_dgn_combined_export_dispatches_one_cad_file(arc_tool, tmp_path):
    tool, _arcpy, module = arc_tool
    parameters = [types.SimpleNamespace(value=None, valueAsText="") for _ in range(16)]
    parameters[6].valueAsText = str(tmp_path)
    parameters[7].valueAsText = "DGN"
    parameters[13].valueAsText = module.MULTI_EXPORT_PACKAGING_COMBINED
    parameters[14].valueAsText = module.EXPORT_CRS_KEEP
    tool._spatial_reference_names = lambda _paths: {"ETRS-TM35FIN"}
    tool._prepare_export_feature_class = Mock(side_effect=lambda src, *_args, **_kwargs: src)
    tool._export_to_cad = Mock(side_effect=lambda _pairs, path, _messages: path)
    tool._execute_export(parameters, Mock(), ["roads", "points"])
    tool._export_to_cad.assert_called_once()
    assert tool._export_to_cad.call_args.args[0] == [("roads", "roads"), ("points", "points")]
    assert tool._export_to_cad.call_args.args[1].endswith(".dgn")


def test_dgn_export_leaves_microstation_point_representation_to_arcgis(arc_tool):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock(side_effect=AssertionError("AutoCAD only"))
    tool._dgn_seed_file = Mock(return_value="template3d_Metric.dgn")
    arcpy.conversion.ExportCAD = Mock()
    tool._export_to_cad([("source", "Points")], "points.dgn", None)
    assert arcpy.conversion.ExportCAD.call_args.args[1] == "DGN_V8"
    tool._cad_force_point_entity_type.assert_not_called()


@pytest.mark.parametrize("has_z,unit,expected", [
    (False, 1.0, "template2d_Metric.dgn"),
    (True, 1.0, "template3d_Metric.dgn"),
    (True, 0.3048, "template3d_Intl_Feet.dgn"),
    (True, 1200.0 / 3937.0, "template3d_US_Feet.dgn"),
])
def test_dgn_seed_preserves_dimension_and_coordinate_units(arc_tool, tmp_path, has_z, unit, expected):
    tool, arcpy, _module = arc_tool
    seed = tmp_path / "Resources/ArcToolBox/Templates/CAD" / expected
    seed.parent.mkdir(parents=True)
    seed.touch()
    arcpy.GetInstallInfo = lambda: {"InstallDir": str(tmp_path)}
    arcpy.Describe = lambda _fc: types.SimpleNamespace(
        hasZ=has_z, spatialReference=types.SimpleNamespace(metersPerUnit=unit)
    )
    arcpy.ListFields = lambda _fc: []
    assert tool._dgn_seed_file(["source"], None) == str(seed)


def test_dgn_missing_seed_fails_instead_of_flattening_z(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool
    arcpy.GetInstallInfo = lambda: {"InstallDir": str(tmp_path)}
    arcpy.Describe = lambda _fc: types.SimpleNamespace(
        hasZ=True, spatialReference=types.SimpleNamespace(metersPerUnit=1)
    )
    with pytest.raises(RuntimeError, match="DGN-pohjaa ei löytynyt"):
        tool._dgn_seed_file(["source"], None)
