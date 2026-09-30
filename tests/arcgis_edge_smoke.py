"""Additional real ArcGIS edge cases, including raster mosaic and CAD projection."""

import argparse
import datetime
import sys
import types
from pathlib import Path
from unittest.mock import patch

import arcpy
import numpy as np

from arcgis_matrix_smoke import Matrix, Messages, count


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cad", type=Path)
    parser.add_argument("--only")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True)
    matrix = Matrix(args.output_dir)
    original_run = matrix.run
    matrix.run = lambda name, action, **kwargs: original_run(name, action, **kwargs) if not args.only or args.only in name else None
    with arcpy.EnvManager(scratchWorkspace=matrix.gdb, addOutputsToMap=False):
        empty = str(arcpy.management.CreateFeatureclass(matrix.gdb, "empty", "POINT", spatial_reference=3067)[0])
        for fmt in ("Shapefile", "GPKG", "GeoJSON"):
            matrix.run("empty_export_" + fmt, lambda fmt=fmt: matrix.export([empty], fmt, "empty_" + fmt, expected_counts=[0]))
        nulls = str(arcpy.management.CreateFeatureclass(matrix.gdb, "nulls", "POINT", spatial_reference=3067)[0])
        with arcpy.da.InsertCursor(nulls, ["SHAPE@XY"]) as cursor:
            cursor.insertRow(((385000, 6672000),))
            cursor.insertRow((None,))
        matrix.run("null_geometry_shapefile", lambda: matrix.export([nulls], "Shapefile", "nulls", expected_counts=[2]))
        unknown = str(arcpy.management.CreateFeatureclass(matrix.gdb, "unknown", "POINT")[0])
        with arcpy.da.InsertCursor(unknown, ["SHAPE@XY"]) as cursor:
            cursor.insertRow(((500, 500),))
        matrix.run("unknown_crs_projection_rejected", lambda: matrix.export([unknown], "Shapefile", "unknown",
            target="ETRS-GK23 (3877)"), expected_error=True)
        wide = str(arcpy.management.CreateFeatureclass(matrix.gdb, "wide", "POINT", spatial_reference=3067)[0])
        for index in range(20):
            arcpy.management.AddField(wide, f"long_{index}", "TEXT", field_length=1000)
        arcpy.management.AddField(wide, "identifier", "BIGINTEGER")
        arcpy.management.AddField(wide, "offset", "TIMESTAMPOFFSET")
        with arcpy.da.InsertCursor(wide, ["SHAPE@XY", "identifier", "offset", "long_0"]) as cursor:
            cursor.insertRow(((385000, 6672000), 9007199254740991,
                datetime.datetime.fromisoformat("2026-09-30T18:12:22.123+03:00"), "ä" * 1000))
        matrix.run("wide_unicode_big_integer", lambda: matrix.export([wide], "Shapefile", "wide", expected_counts=[1]))
        matrix.run("wide_folder_import", lambda: matrix.import_paths([wide], "wide_folder", expected_total=1, folder_output=True))

        def locked_schema():
            with arcpy.da.UpdateCursor(matrix.fixtures["POINT"], ["number"]) as cursor:
                next(cursor)
                # Input locks may coexist with read-only export; row count must survive.
                return matrix.export([matrix.fixtures["POINT"]], "Shapefile", "locked_input", expected_counts=[2])

        matrix.run("locked_input_read", locked_schema)

        def duplicate_import():
            result = matrix.import_paths([matrix.fixtures["POINT"]], "collision", expected_total=2)
            tool = matrix.module.UniversalImportTool()
            tool._add_layers_to_map = lambda *_args: None
            tool.process_generic(matrix.fixtures["POINT"], str(args.output_dir / "collision.gdb"), False, Messages())
            with arcpy.EnvManager(workspace=str(args.output_dir / "collision.gdb")):
                fcs = arcpy.ListFeatureClasses()
            assert len(fcs) == 2
            assert all(count(args.output_dir / "collision.gdb" / fc) == 2 for fc in fcs)
            return result

        matrix.run("import_name_collision", duplicate_import)

        def raster_mosaic():
            folder = args.output_dir / "raster_source" / "taustakartta_20k"
            folder.mkdir(parents=True)
            paths = []
            for index in range(2):
                path = folder / f"tile_{index}.tif"
                raster = arcpy.NumPyArrayToRaster(np.ones((10, 10), dtype=np.uint8),
                    arcpy.Point(385000 + index * 10, 6672000), 1, 1)
                raster.save(str(path))
                arcpy.management.DefineProjection(str(path), arcpy.SpatialReference(3067))
                paths.append(str(path))
            project_path = Path(arcpy.GetInstallInfo()["InstallDir"]) / "Resources" / "ArcToolBox" / "Services" / "routingservices" / "data" / "Blank.aprx"
            project = arcpy.mp.ArcGISProject(str(project_path))
            active_map = project.createMap("Muuntaja tests", "MAP")
            # Only replace CURRENT: all raster conversion, mosaicking and map APIs are real.
            original_project = arcpy.mp.ArcGISProject
            current = types.SimpleNamespace(activeMap=active_map, defaultGeodatabase=matrix.gdb)
            tool = matrix.module.UniversalImportTool()
            messages = Messages()
            with patch.object(arcpy.mp, "ArcGISProject", side_effect=lambda path: current if path == "CURRENT" else original_project(path)):
                succeeded, failures = tool._import_rasters(paths, [str(folder.parent)], None, messages,
                    output_loc=matrix.gdb, is_folder=False)
                assert len(succeeded) == 2 and not failures, messages.entries
                with arcpy.EnvManager(workspace=matrix.gdb):
                    datasets = arcpy.ListDatasets(feature_type="Mosaic") or []
                assert len(datasets) == 1, messages.entries
                mosaic_path = str(Path(matrix.gdb) / datasets[0])
                mosaic_layers = [layer for layer in active_map.listLayers() if layer.name == datasets[0]]
                assert len(mosaic_layers) == 1, messages.entries
                assert count(mosaic_path) == 2
                succeeded, failures = tool._import_rasters(paths, [str(folder.parent)], None, messages,
                    output_loc=matrix.gdb, is_folder=False)
                assert not failures
                assert count(mosaic_path) == 2
                assert len([layer for layer in active_map.listLayers() if layer.name == datasets[0]]) == 1, [
                    (layer.name, layer.longName, layer.dataSource if layer.supports("DATASOURCE") else "")
                    for layer in active_map.listLayers()]
                bad = folder.parent / "bad" / "invalid.tif"
                bad.parent.mkdir()
                bad.write_bytes(b"invalid raster")
                succeeded, failures = tool._import_rasters([paths[0], str(bad)], [str(folder.parent)], None, messages,
                    output_loc=str(args.output_dir), is_folder=True)
                assert len(succeeded) == 1 and len(failures) == 1, messages.entries
            return {"tiles": 2, "mosaic_layers": 1, "duplicate_import": "no duplicates",
                    "invalid_raster": "warning and next file continues"}

        matrix.run("raster_mosaic_duplicate_and_invalid", raster_mosaic)
        if args.cad:
            matrix.run("real_cad", lambda: matrix.import_paths([args.cad], "real_cad"))

        def cad_projection():
            tool = matrix.module.UniversalImportTool()
            saved = []
            tool._add_layers_to_map = lambda paths, _messages, _styles=None: saved.extend(paths)
            tool.process_cad(str(Path(__file__).parent / "data" / "cad_sample.dxf"), matrix.gdb,
                False, True, arcpy.SpatialReference(3067), arcpy.SpatialReference(3877), Messages())
            assert saved
            assert all(arcpy.Describe(path).spatialReference.factoryCode == 3877 for path in saved)
            return {"layers": len(saved), "epsg": 3877}

        matrix.run("cad_projection_and_field_mapping", cad_projection)
    failures = [result for result in matrix.results if result["status"] == "FAIL"]
    print(f"RESULT: {len(matrix.results) - len(failures)}/{len(matrix.results)} PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
