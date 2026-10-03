"""Real ArcGIS Pro folder/group round trips, including persisted map hierarchy.

Run with Pro Python and --output-dir, or call run_current(output_dir) in Pro's
Python window to test the registered geoprocessing tool against CURRENT.
"""

import argparse
import json
import time
import types
from pathlib import Path
from unittest.mock import patch

import arcpy
import numpy as np

from arcgis_matrix_smoke import Matrix, Messages, params


def count(source):
    return int(arcpy.management.GetCount(source if hasattr(source, "longName") else str(source))[0])


def feature_layers(active_map):
    layers = active_map.listLayers()
    composites = [layer.longName + "\\" for layer in layers
                  if getattr(arcpy.Describe(layer), "dataType", "") == "MosaicLayer"]
    return [layer for layer in layers if layer.isFeatureLayer
            and not any(layer.longName.startswith(prefix) for prefix in composites)]


def parent_counts(active_map):
    result = {}
    for layer in feature_layers(active_map):
        parent = tuple(layer.longName.split("\\")[:-1])
        result.setdefault(parent, []).append(count(layer))
    return {"/".join(parent): sorted(values) for parent, values in result.items()}


def make_sources(matrix):
    root = matrix.output / "source"
    root.mkdir()
    for relative, geometry, fmt in [
        ((), "POINT", "GeoJSON"),
        (("Äänekoski",), "POINT", "Shapefile"),
        (("Äänekoski",), "POLYLINE", "GPKG"),
        (("Äänekoski", "Yhteiset"), "POLYGON", "GeoJSON"),
        (("Jyväskylä", "Yhteiset"), "POINT", "GeoJSON"),
    ]:
        folder = root.joinpath(*relative)
        folder.mkdir(parents=True, exist_ok=True)
        tool = matrix.module.UniversalImportTool()
        messages = Messages()
        source = matrix.fixtures[geometry]
        path = str(folder / ("aineisto" + matrix.module.EXPORT_FORMAT_TO_EXT[fmt]))
        if fmt == "GeoJSON":
            tool._export_to_geojson(source, path, messages)
        elif fmt == "Shapefile":
            tool._export_to_shapefile(source, path, messages)
        else:
            tool._export_to_geopackage(source, path, messages, source_label="viivat")
    for index, parent in enumerate(("Äänekoski", "Jyväskylä")):
        path = root / parent / "Yhteiset" / "tausta.tif"
        raster = arcpy.NumPyArrayToRaster(np.ones((10, 10), dtype=np.uint8),
                                       arcpy.Point(385000 + index * 10, 6672000), 1, 1)
        raster.save(str(path))
        arcpy.management.DefineProjection(str(path), arcpy.SpatialReference(3067))
    return root


EXPECTED = {"": [2], "Äänekoski": [2, 2], "Äänekoski/Yhteiset": [2], "Jyväskylä/Yhteiset": [2]}


def import_folder(matrix, active_map, root, label, folder_output=False):
    destination = matrix.output / label
    if folder_output:
        destination.mkdir()
    else:
        destination = Path(str(arcpy.management.CreateFileGDB(str(matrix.output), label + ".gdb")[0]))
    p = params()
    p[2].valueAsText = str(destination)
    messages = Messages()
    matrix.module.UniversalImportTool()._execute_import(p, messages, [str(root)])
    actual = parent_counts(active_map)
    assert actual == EXPECTED, (actual, messages.entries)
    assert not any(level == "ERROR" for level, _text in messages.entries), messages.entries
    return {"parents": actual, "messages": messages.entries}


def export_groups(matrix, active_map, fmt, separate, sources=None, label=None):
    folder = matrix.output / (label or f"groups_{fmt}_{separate}")
    folder.mkdir()
    sources = sources if sources is not None else feature_layers(active_map)
    p = params()
    p[6].valueAsText, p[7].valueAsText = str(folder), fmt
    p[13].valueAsText = (matrix.module.MULTI_EXPORT_PACKAGING_SEPARATE if separate
                         else matrix.module.MULTI_EXPORT_PACKAGING_COMBINED)
    p[15].value = True
    messages = Messages()
    matrix.module.UniversalImportTool()._execute_export(p, messages, sources)
    files = list(folder.rglob("*" + matrix.module.EXPORT_FORMAT_TO_EXT[fmt]))
    grouped = {}
    for path in files:
        parent = path.parent.relative_to(folder).as_posix()
        parent = "" if parent == "." else parent
        grouped.setdefault(parent, []).append(path)
        assert path.stat().st_size > 0
    assert set(grouped) == set(EXPECTED), (grouped, messages.entries)
    for parent, paths in grouped.items():
        expected_files = len(EXPECTED[parent]) if separate or fmt not in ("GPKG", "DWG", "DXF") else 1
        assert len(paths) == expected_files, (parent, paths, expected_files, messages.entries)
        actual_counts = []
        source_geometries = {arcpy.Describe(source).shapeType for source in sources
                             if "/".join(source.longName.split("\\")[:-1]) == parent}
        for path in paths:
            if fmt == "Shapefile":
                actual_counts.append(count(path))
                assert path.with_suffix(".lyrx").is_file()
            elif fmt == "GeoJSON":
                actual_counts.append(len(json.loads(path.read_text(encoding="utf-8-sig"))["features"]))
            elif fmt == "GPKG":
                with arcpy.EnvManager(workspace=str(path)):
                    names = arcpy.ListFeatureClasses() or []
                actual_counts.extend(count(path / name) for name in names)
                assert list(path.parent.glob(path.stem + "*.lyrx"))
            elif fmt in ("DWG", "DXF"):
                # CAD polygon readers expose the same closed entities as both
                # Polygon and Polyline; count the exported source geometries.
                actual_counts.append(sum(count(path / geometry) for geometry in source_geometries
                                         if arcpy.Exists(str(path / geometry))))
        if fmt in ("DWG", "DXF"):
            assert sum(actual_counts) == sum(EXPECTED[parent]), (parent, actual_counts)
        elif actual_counts:
            assert sorted(actual_counts) == EXPECTED[parent], (parent, actual_counts, messages.entries)
    assert not any(level == "ERROR" for level, _text in messages.entries), messages.entries
    return {"files": [str(path) for path in files], "messages": messages.entries}


def run(output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    matrix = Matrix(output)
    blank = Path(arcpy.GetInstallInfo()["InstallDir"]) / "Resources/ArcToolBox/Services/routingservices/data/Blank.aprx"
    project = arcpy.mp.ArcGISProject(str(blank))
    active_map = project.createMap("Muuntaja kansioryhmät", "MAP")
    current = types.SimpleNamespace(activeMap=active_map, defaultGeodatabase=matrix.gdb)
    original_project = arcpy.mp.ArcGISProject
    with arcpy.EnvManager(scratchWorkspace=matrix.gdb, addOutputsToMap=False), patch.object(
        arcpy.mp, "ArcGISProject", side_effect=lambda path: current if path == "CURRENT" else original_project(path)
    ):
        root = make_sources(matrix)
        matrix.run("folder_import_vectors_and_nested_mosaics", lambda: import_folder(matrix, active_map, root, "imported"))
        def mosaics():
            layers = [layer for layer in active_map.listLayers()
                      if getattr(arcpy.Describe(layer), "dataType", "") == "MosaicLayer"]
            assert len(layers) == 2, [(layer.name, layer.longName) for layer in layers]
            assert len({layer.dataSource for layer in layers}) == 2
            assert {tuple(layer.longName.split("\\")[:-1]) for layer in layers} == {
                ("Äänekoski", "Yhteiset"), ("Jyväskylä", "Yhteiset")}
            assert all(count(layer.dataSource) == 1 for layer in layers)
            messages = Messages()
            paths = [str(path) for path in root.rglob("*.tif")]
            ok, failures = matrix.module.UniversalImportTool()._import_rasters(
                paths, [str(root)], None, messages, output_loc=str(output / "imported.gdb"), is_folder=False)
            assert len(ok) == 2 and not failures, messages.entries
            assert len([layer for layer in active_map.listLayers()
                        if getattr(arcpy.Describe(layer), "dataType", "") == "MosaicLayer"]) == 2
            return {"mosaics": [layer.dataSource for layer in layers]}
        matrix.run("same_named_nested_rasters_and_repeat", mosaics)
        for fmt in matrix.module.EXPORT_FORMAT_LIST:
            for separate in ((False, True) if fmt in ("GPKG", "DWG", "DXF") else (True,)):
                matrix.run(f"groups_export_{fmt}_{separate}",
                           lambda fmt=fmt, separate=separate: export_groups(matrix, active_map, fmt, separate))
        matrix.run("resolve_native_picker_group_paths", lambda: export_groups(
            matrix, active_map, "Shapefile", True, [layer.longName for layer in feature_layers(active_map)], "picker_paths"))
        def roundtrip():
            current.activeMap = project.createMap("Takaisintuonti", "MAP")
            return import_folder(matrix, current.activeMap, output / "groups_GPKG_False", "roundtrip")
        matrix.run("gpkg_groups_roundtrip", roundtrip)
        def folder_destination():
            current.activeMap = project.createMap("Kansiokohde", "MAP")
            return import_folder(matrix, current.activeMap, root, "folder_destination", folder_output=True)
        matrix.run("folder_destination_and_individual_rasters", folder_destination)
        def collision_and_selection():
            current.activeMap = project.createMap("Erikoisnimet ja valinnat", "MAP")
            tool = matrix.module.UniversalImportTool()
            names = ["A:B", "A?B", "CON", ".."]
            selected = []
            for name in names:
                group = current.activeMap.createGroupLayer(name)
                layer = current.activeMap.addDataFromPath(matrix.fixtures["POINT"])
                layer.name = "Sama nimi"
                layer.definitionQuery = "number = 1"
                added = current.activeMap.addLayerToGroup(group, layer)[0]
                current.activeMap.removeLayer(layer)
                selected.append(added)
            folder = output / "safe_names"
            folder.mkdir()
            p = params()
            p[6].valueAsText, p[7].valueAsText = str(folder), "Shapefile"
            tool._execute_export(p, Messages(), selected)
            files = list(folder.rglob("*.shp"))
            assert len(files) == 4 and len({path.parent for path in files}) == 4, files
            assert all(count(path) == 1 for path in files)
            assert all(path.is_relative_to(folder) for path in files)
            return {"files": [str(path) for path in files], "counts": [count(path) for path in files]}
        matrix.run("unsafe_group_names_collisions_and_definition_query", collision_and_selection)
    project.saveACopy(str(output / "Muuntaja_kansioryhmat.aprx"))
    (output / "environment.json").write_text(json.dumps(arcpy.GetInstallInfo(), indent=2), encoding="utf-8")
    assert all(result["status"] == "PASS" for result in matrix.results), "See report.json"
    return matrix.results


def run_current(output_dir):
    """Run the native GP tool in a separate open test project with no CURRENT patch."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    with arcpy.EnvManager(addOutputsToMap=False):
        matrix = Matrix(output)
        root = make_sources(matrix)
    project = arcpy.mp.ArcGISProject("CURRENT")
    assert project.activeMap is not None, "Open a test map first"
    active_map = project.activeMap
    for layer in list(active_map.listLayers()):
        if layer.isFeatureLayer:
            raise RuntimeError("Use an empty test map")
    started = time.perf_counter()
    native_toolbox = arcpy.ImportToolbox(str(Path(__file__).resolve().parents[1] / "Toolboxes/Muuntaja.pyt"))
    with arcpy.EnvManager(scratchWorkspace=matrix.gdb, addOutputsToMap=False):
        imported = str(arcpy.management.CreateFileGDB(str(output), "imported.gdb")[0])
        result = native_toolbox.UniversalImportTool(operation_mode=matrix.module.IMPORT_MODE_LABEL,
                                                  input_file=str(root), output_location=imported)
        actual = parent_counts(active_map)
        assert actual == EXPECTED, actual
        export = output / "export"
        export.mkdir()
        result = native_toolbox.UniversalImportTool(operation_mode=matrix.module.EXPORT_MODE_LABEL,
                                                  export_layers=[layer.longName for layer in feature_layers(active_map)],
                                                  export_output_folder=str(export), export_format="Shapefile")
        files = list(export.rglob("*.shp"))
        actual_export = {}
        for path in files:
            parent = path.parent.relative_to(export).as_posix()
            actual_export.setdefault("" if parent == "." else parent, []).append(count(path))
        actual_export = {parent: sorted(values) for parent, values in actual_export.items()}
        assert actual_export == EXPECTED, (actual_export, result.getMessages())
    project.save()
    report = {"status": "PASS", "environment": arcpy.GetInstallInfo(), "seconds": time.perf_counter() - started,
              "imported_parents": actual, "exported_parents": actual_export, "gp_messages": result.getMessages()}
    (output / "ui_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: ArcGIS Pro native GP folder import + grouped Shapefile export", actual_export)
    return report


def run_cad_recheck(output_dir, project_path):
    """Recheck CAD counts from the persisted real import after test correction."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    matrix = Matrix(output)
    project = arcpy.mp.ArcGISProject(str(project_path))
    active_map = project.listMaps("Muuntaja kansioryhmät")[0]
    current = types.SimpleNamespace(activeMap=active_map, defaultGeodatabase=matrix.gdb)
    original_project = arcpy.mp.ArcGISProject
    with arcpy.EnvManager(scratchWorkspace=matrix.gdb, addOutputsToMap=False), patch.object(
        arcpy.mp, "ArcGISProject", side_effect=lambda path: current if path == "CURRENT" else original_project(path)
    ):
        for fmt in ("DWG", "DXF"):
            for separate in (False, True):
                matrix.run(f"groups_export_{fmt}_{separate}",
                           lambda fmt=fmt, separate=separate: export_groups(matrix, active_map, fmt, separate))
    assert all(result["status"] == "PASS" for result in matrix.results), "See report.json"
    return matrix.results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cad-project")
    arguments = parser.parse_args()
    if arguments.cad_project:
        run_cad_recheck(arguments.output_dir, arguments.cad_project)
    else:
        run(arguments.output_dir)
