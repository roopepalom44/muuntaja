import json
import types
import zipfile
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("method,extension", [
    ("process_geopackage", ".gpkg"), ("process_geojson_flattened", ".geojson"),
    ("process_kml_flattened", ".kml"), ("process_gpx_flattened", ".gpx"), ("process_generic", ".shp"),
])
def test_import_dispatch_forwards_both_crs(arc_tool, tmp_path, method, extension):
    tool, arcpy, _module = arc_tool
    path = tmp_path / ("aineisto" + extension)
    path.write_text("{}")
    source, target = object(), object()
    tool._parse_input_sr = lambda _value: source
    tool._spatial_ref_from_param = lambda _value: target
    arcpy.Describe = lambda _path: types.SimpleNamespace(dataType="Workspace", workspaceType="LocalDatabase")
    called = Mock()
    setattr(tool, method, called)
    parameters = [types.SimpleNamespace(value=None, valueAsText="") for _ in range(16)]
    parameters[2].valueAsText = "output.gdb"
    tool._execute_import(parameters, Mock(), [str(path)])
    assert called.call_args.kwargs == dict(input_sr=source, target_sr=target)


def test_partial_batch_processes_every_file_and_reports_only_failures(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool
    arcpy.Describe = lambda _path: types.SimpleNamespace(dataType="Workspace", workspaceType="LocalDatabase")
    tool._parse_input_sr = lambda _value: None
    tool._spatial_ref_from_param = lambda _value: None
    paths = [tmp_path / f"{index}.geojson" for index in range(5)]
    for index, path in enumerate(paths):
        path.write_text('{"type":"FeatureCollection","features":[]}' if index < 3 else '{"broken":')
    visited = []
    def convert(path, *args, **kwargs):
        visited.append(path)
        json.loads(open(path).read())
    tool.process_geojson_flattened = convert
    parameters = [types.SimpleNamespace(value=None, valueAsText="") for _ in range(16)]
    parameters[2].valueAsText = "output.gdb"
    tool._execute_import(parameters, Mock(), [str(path) for path in paths])
    assert len(visited) == 5
    assert any("3/5" in text or "3 onnistui" in text for _level, text in tool.logs)
    assert sum("tuonti epäonnistui" in text for _level, text in tool.logs) == 2


def test_cad_fallback_precedes_python_executable_check(arc_tool, monkeypatch):
    tool, _arcpy, module = arc_tool
    monkeypatch.setattr(module.os.path, "isfile", lambda _path: False)
    tool._process_cad_in_process = Mock(return_value=["cad_result"])
    assert tool.process_cad("drawing.dxf", "out.gdb", False, False, None, None, Mock()) == ["cad_result"]


def test_generic_crs_and_style_survive_conversion(arc_tool):
    tool, _arcpy, _module = arc_tool
    tool._find_source_style = lambda _path: "roads.lyrx"
    tool.save_and_reproject = Mock(return_value="result")
    tool._add_layers_to_map = Mock()
    tool.process_generic("roads.shp", "out.gdb", False, Mock(), "source", "target")
    assert tool.save_and_reproject.call_args.args[5:7] == ("source", "target")
    assert tool.save_and_reproject.call_args.kwargs["add_to_map"] is False
    tool._add_layers_to_map.assert_called_once()


def test_gpkg_import_passes_crs_restores_workspace(arc_tool):
    tool, arcpy, _module = arc_tool
    arcpy.ListDatasets = lambda: []
    arcpy.ListFeatureClasses = lambda: ["main.points"]
    tool._count_safe = lambda _path: 3
    tool._find_source_style = lambda *args: None
    tool._bulk_convert_and_add = Mock()
    tool.process_geopackage("file.gpkg", "out.gdb", False, Mock(), "source", "target")
    assert arcpy.env.workspace is None
    assert tool._bulk_convert_and_add.call_args.kwargs["target_sr"] == "target"


@pytest.mark.parametrize("data", ['{"type":', '{"features":[}', "not json"])
def test_malformed_geojson_reports_parse_error(arc_tool, tmp_path, data):
    tool, _arcpy, _module = arc_tool
    path = tmp_path / "broken.geojson"
    path.write_text(data)
    with pytest.raises(ValueError, match="GeoJSON/JSON"):
        tool.process_geojson_flattened(str(path), "out.gdb", False, Mock())


def test_plain_kml_is_xml_and_uses_map_scale(arc_tool, tmp_path):
    tool, arcpy, _module = arc_tool
    arcpy.Describe = lambda _path: types.SimpleNamespace(dataType="FeatureLayer")
    arcpy.mp = types.SimpleNamespace(ArcGISProject=lambda _key: types.SimpleNamespace(
        activeView=types.SimpleNamespace(camera=types.SimpleNamespace(scale=2500))))
    def convert(_layer, path, scale):
        assert scale == 2500
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("doc.kml", '<kml xmlns="http://www.opengis.net/kml/2.2"/>')
    arcpy.conversion.LayerToKML = convert
    output = tmp_path / "tasot.kml"
    tool._export_to_kml("layer", str(output), Mock())
    assert output.read_text().startswith("<kml")
    assert not zipfile.is_zipfile(output)


def test_reprojection_uses_native_source_crs_and_queues_locked_intermediate(arc_tool):
    tool, arcpy, _module = arc_tool
    source = types.SimpleNamespace(name="native", factoryCode=4326)
    target = types.SimpleNamespace(name="target", factoryCode=3067)
    arcpy.Describe = lambda _path: types.SimpleNamespace(spatialReference=source)
    arcpy.management.CopyFeatures = Mock()
    arcpy.management.Project = Mock()
    arcpy.management.Delete = Mock(side_effect=RuntimeError("locked"))
    tool._resolve_output_path = lambda folder, name, _is_folder: (name, folder + "/" + name)
    tool._count_safe = lambda _path: 1
    output = tool.save_and_reproject("input", "out.gdb", "data", False, None, None, target, Mock(), False)
    assert output == "out.gdb/data_proj"
    assert tool._deferred_cleanup_paths == ["out.gdb/data"]
    arcpy.management.Project.assert_called_once()


@pytest.mark.parametrize("name,expected", [("lämpötila", "lampotila"), ("yö", "yo"), ("ÅäÖ", "AaO"), ("!!!", "field")])
def test_finnish_field_names(arc_tool, name, expected):
    assert arc_tool[0].sanitize_field_name(name) == expected


def test_world_file_read_is_cached(arc_tool, tmp_path, monkeypatch):
    tool, _arcpy, _module = arc_tool
    raster = tmp_path / "kartta.png"
    raster.with_suffix(".pgw").write_text("4\n0\n0\n-4\n385000\n6670000\n")
    import builtins
    real_open = builtins.open
    opened = Mock(side_effect=real_open)
    monkeypatch.setattr(builtins, "open", opened)
    assert tool._read_world_file_origin(raster) == (385000, 6670000)
    assert tool._read_world_file_origin(raster) == (385000, 6670000)
    assert opened.call_count == 1


@pytest.mark.parametrize("x,expected", [(492000, None), (385000, 3067), (25492000, 3879)])
def test_ambiguous_gk_range_in_both_engines(arc_tool, mock_qgis, x, expected):
    assert arc_tool[2].classify_finnish_xy(x, 6675000) == expected
    assert mock_qgis[0].classify_finnish_xy(x, 6675000) == expected


def test_scanner_unicode_spaces_sidecars_and_hidden_folders(mock_qgis, tmp_path):
    core, _deleted = mock_qgis
    folder = tmp_path / "yö työ ääkköset"
    folder.mkdir()
    valid = folder / "50v flood.gpkg"
    valid.touch()
    tile = folder / "kartta.PNG"
    tile.touch()
    tile.with_suffix(".PGW").touch()
    (folder / "kuva.png").touch()
    hidden = folder / ".git"
    hidden.mkdir()
    (hidden / "ignored.gpkg").touch()
    assert set(core.scan_inputs([tmp_path, valid])) == {valid, tile}


def test_disposal_and_numeric_gdb_names(mock_qgis):
    core, deleted = mock_qgis
    layer = object()
    core._dispose(layer)
    core._dispose(layer)
    assert deleted == [layer]
    assert core.gdb_safe_name("50v-flood") == "_50v_flood"
    assert core.gdb_safe_name("select") == "_select"


def test_known_foreign_crs_is_not_rejected(mock_qgis, monkeypatch):
    core, _deleted = mock_qgis
    CRS = core.QgsCoordinateReferenceSystem
    layer = types.SimpleNamespace(crs=lambda: CRS("EPSG:3301"), setCrs=Mock())
    monkeypatch.setattr(core, "inferred_crs", lambda *args: CRS("EPSG:3067"))
    monkeypatch.setattr(core, "_center_in_finland", lambda _layer, crs: crs.authid() == "EPSG:3067")
    core.assign_source_crs(layer, "estonian.gpkg")
    layer.setCrs.assert_not_called()


def test_destination_probe_is_deleted(mock_qgis, monkeypatch, tmp_path):
    core, deleted = mock_qgis
    tmp_path.joinpath("data.gpkg").touch()
    probe = types.SimpleNamespace(dataProvider=lambda: types.SimpleNamespace(subLayers=lambda: ["0!!::!!roads!!::!!2"]))
    class Probe(core.QgsVectorLayer):
        def __new__(cls, *args):
            return probe
    monkeypatch.setattr(core, "QgsVectorLayer", Probe)
    assert core._workspace_names(tmp_path / "data.gpkg") == {"roads"}
    assert deleted == [probe]
