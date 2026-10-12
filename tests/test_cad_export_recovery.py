"""Recover the real ExportCAD 000520 field collision without changing sources."""

import types
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("extension,cad_type", [
    ("dwg", "DWG_R2018"), ("dxf", "DXF_R2018"), ("dgn", "DGN_V8"),
])
def test_topoengine_retry_replaces_only_colliding_inputs(arc_tool, extension, cad_type):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock()
    tool._dgn_seed_file = Mock(return_value="seed3d.dgn")
    tool._cad_copy_without_layer_field_collision = Mock(side_effect=["safe_paths", None])
    arcpy.conversion.ExportCAD = Mock(
        side_effect=[arcpy.ExecuteError("ERROR 000520: Unexpected TopoEngine Error"), None]
    )
    output = f"export.{extension}"
    arcpy.Exists = lambda path: path == output and arcpy.conversion.ExportCAD.call_count > 0
    arcpy.management.Delete = Mock()
    assert tool._export_to_cad([("paths", "Paths"), ("points", "Points")], output, None) == output
    calls = arcpy.conversion.ExportCAD.call_args_list
    assert len(calls) == 2
    assert calls[0].args[0] == ["paths", "points"]
    assert calls[1].args == (
        ["safe_paths", "points"], cad_type, output,
        "Ignore_Filenames_in_Tables", "Overwrite_Existing_Files",
    ) + (("seed3d.dgn",) if extension == "dgn" else ())
    arcpy.management.Delete.assert_called_once_with(output)


def test_successful_cad_overrides_are_left_intact(arc_tool):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock()
    tool._cad_copy_without_layer_field_collision = Mock()
    arcpy.conversion.ExportCAD = Mock()
    tool._export_to_cad([("cad_with_layer", "CAD")], "cad.dwg", None)
    tool._cad_copy_without_layer_field_collision.assert_not_called()
    arcpy.conversion.ExportCAD.assert_called_once()


@pytest.mark.parametrize("error", ["000210: Cannot create output", "000732: Missing input"])
def test_other_cad_errors_propagate_without_changing_inputs(arc_tool, error):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock()
    tool._cad_copy_without_layer_field_collision = Mock()
    arcpy.conversion.ExportCAD = Mock(side_effect=arcpy.ExecuteError(error))
    with pytest.raises(arcpy.ExecuteError, match=error):
        tool._export_to_cad([("source", "Source")], "cad.dwg", None)
    tool._cad_copy_without_layer_field_collision.assert_not_called()


def test_topoengine_without_collision_keeps_original_failure(arc_tool):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock()
    arcpy.ListFields = lambda _fc: [
        types.SimpleNamespace(name="name", aliasName="name", required=False)
    ]
    original = arcpy.ExecuteError("000520: invalid geometry")
    arcpy.conversion.ExportCAD = Mock(side_effect=original)
    with pytest.raises(arcpy.ExecuteError) as caught:
        tool._export_to_cad([("source", "Source")], "cad.dwg", None)
    assert caught.value is original
    arcpy.conversion.ExportCAD.assert_called_once()


def test_cad_retry_failure_is_not_reported_as_success_or_retried_forever(arc_tool):
    tool, arcpy, _module = arc_tool
    tool._cad_force_point_entity_type = Mock()
    tool._cad_copy_without_layer_field_collision = Mock(return_value="safe_copy")
    arcpy.conversion.ExportCAD = Mock(
        side_effect=[arcpy.ExecuteError("000520"), arcpy.ExecuteError("retry failed")]
    )
    with pytest.raises(arcpy.ExecuteError, match="retry failed"):
        tool._export_to_cad([("source", "Source")], "cad.dwg", None)
    assert arcpy.conversion.ExportCAD.call_count == 2
    assert not any("CAD-vienti valmis" in text for _level, text in tool.logs)
