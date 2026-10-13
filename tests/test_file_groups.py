"""Imports that produce several layers are grouped by their file name in ArcGIS Pro."""

import types
from unittest.mock import Mock

from test_raster_import import FakeMap


def run_import(tool, arcpy, tmp_path, outputs_by_file, folder=False):
    active_map = FakeMap()
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _name: types.SimpleNamespace(activeMap=active_map))
    arcpy.Exists = lambda _path: True
    arcpy.Describe = lambda _path: types.SimpleNamespace(dataType="Workspace", workspaceType="LocalDatabase")
    tool._parse_input_sr = lambda _value: None
    tool._spatial_ref_from_param = lambda _value: None
    root = tmp_path / "aineisto"
    root.mkdir(exist_ok=True)
    paths = []
    for name in outputs_by_file:
        path = (root / "Piirustukset" / name) if folder else (tmp_path / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
        paths.append(str(path))

    def produce(input_path, *_args, **_kwargs):
        name = input_path.replace("\\", "/").rsplit("/", 1)[-1]
        # Kuten CAD-tuonti: tasot tallentuvat ja lisätään kartalle useassa erässä.
        for output in outputs_by_file[name]:
            tool._add_layers_to_map([f"output.gdb/{output}"], Mock())

    tool.process_cad = Mock(side_effect=produce)
    tool.process_geopackage = Mock(side_effect=produce)
    parameters = [types.SimpleNamespace(value=None, valueAsText="") for _ in range(16)]
    parameters[2].valueAsText = "output.gdb"
    tool._execute_import(parameters, Mock(), [str(root)] if folder else paths)
    return active_map


def tree(layers):
    return [(layer.name, tree(layer.children)) if layer.isGroupLayer else layer.name for layer in layers]


def test_multi_layer_file_gets_its_own_group_and_single_layer_file_does_not(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool

    active_map = run_import(tool, arcpy, tmp_path, {
        "topelius_JM.dgn": ["topelius_JM_line", "topelius_JM_point", "topelius_JM_anno"],
        "yksi.gpkg": ["yksi_kaivot"],
    })

    assert tree(active_map.layers) == [
        "yksi_kaivot",
        ("topelius_JM.dgn", ["topelius_JM_line", "topelius_JM_point", "topelius_JM_anno"]),
    ]


def test_file_group_is_nested_in_the_folder_group(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool

    active_map = run_import(tool, arcpy, tmp_path, {"suunnitelma.dgn": ["a", "b"]}, folder=True)

    assert tree(active_map.layers) == [("Piirustukset", [("suunnitelma.dgn", ["a", "b"])])]


def test_reimport_creates_a_new_group_instead_of_mixing_layers(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool
    active_map = FakeMap()
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _name: types.SimpleNamespace(activeMap=active_map))
    arcpy.Exists = lambda _path: True

    tool._flush_file_layers(r"C:\data\piirustus.dgn", [("a", None), ("b", None)], Mock())
    tool._flush_file_layers(r"C:\data\piirustus.dgn", [("a_2", None), ("b_2", None)], Mock())

    assert [layer.name for layer in active_map.layers] == ["piirustus.dgn (2)", "piirustus.dgn"]


def test_layers_are_deferred_while_a_file_is_being_imported(arc_tool):
    tool, arcpy, _module = arc_tool
    arcpy.mp = types.SimpleNamespace(ArcGISProject=Mock(side_effect=AssertionError("map must not be touched")))
    tool._deferred_map_additions = []

    assert tool._add_layers_to_map(["output.gdb/a"], Mock(), {"output.gdb/a": "style.lyrx"}) == []
    assert tool._deferred_map_additions == [("output.gdb/a", "style.lyrx")]
