"""Verify that Muuntaja exports real GeoJSON and can import it in ArcGIS Pro.

Run with ArcGIS Pro's propy.bat. The fixture and outputs live in a temporary
file geodatabase and are removed at the end of the run.
"""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import time

import arcpy


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLBOX = ROOT / "Toolboxes" / "Muuntaja.pyt"


class Messages:
    def addMessage(self, message):
        print(message)

    def addWarningMessage(self, message):
        print("WARNING: " + message)

    def addErrorMessage(self, message):
        print("ERROR: " + message)


def load_toolbox():
    loader = importlib.machinery.SourceFileLoader("muuntaja_arcgispro_smoke", str(TOOLBOX))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    arcpy.env.overwriteOutput = True
    directory = tempfile.mkdtemp(prefix="muuntaja_geojson_arcgispro_")
    try:
        gdb = os.path.join(directory, "data.gdb")
        arcpy.management.CreateFileGDB(directory, "data.gdb")
        source = os.path.join(gdb, "source")
        arcpy.management.CreateFeatureclass(gdb, "source", "POINT", spatial_reference=arcpy.SpatialReference(3067))
        arcpy.management.AddField(source, "name", "TEXT", field_length=80)
        with arcpy.da.InsertCursor(source, ["SHAPE@XY", "name"]) as cursor:
            cursor.insertRow([(385000.0, 6670000.0), "Äänekoski"])
            cursor.insertRow([(386000.0, 6671000.0), "Helsinki"])

        tool = load_toolbox().UniversalImportTool()
        messages = Messages()
        output = os.path.join(directory, "points.geojson")
        started = time.perf_counter()
        tool._export_to_geojson(source, output, messages)
        export_seconds = time.perf_counter() - started
        if not os.path.isfile(output):
            raise AssertionError(
                "GeoJSON exporter did not create the requested file; found {}".format(
                    sorted(os.listdir(directory))
                )
            )
        with open(output, encoding="utf-8-sig") as stream:
            payload = json.load(stream)
        if payload.get("type") != "FeatureCollection":
            raise AssertionError(
                "Exported .geojson is not GeoJSON: top-level keys {}".format(
                    sorted(payload.keys())
                )
            )
        features = payload.get("features") or []
        if len(features) != 2:
            raise AssertionError("Expected two GeoJSON features, got {}".format(len(features)))
        if any(not isinstance(feature.get("geometry"), dict) for feature in features):
            raise AssertionError("Exported GeoJSON has invalid geometries")
        for feature in features:
            x, y = feature["geometry"]["coordinates"][:2]
            if not (19.0 <= x <= 32.5 and 59.0 <= y <= 71.5):
                raise AssertionError(
                    "GeoJSON coordinates are not WGS84 longitude/latitude: {}".format(
                        (x, y)
                    )
                )
        exported_names = {feature["properties"].get("name") for feature in features}
        if exported_names != {"Äänekoski", "Helsinki"}:
            raise AssertionError("GeoJSON attributes changed: {}".format(exported_names))

        started = time.perf_counter()
        tool.process_geojson_flattened(output, gdb, False, messages)
        import_seconds = time.perf_counter() - started
        arcpy.env.workspace = gdb
        imported = [name for name in (arcpy.ListFeatureClasses() or []) if name != "source"]
        counts = {name: int(arcpy.management.GetCount(os.path.join(gdb, name))[0]) for name in imported}
        if sum(counts.values()) != 2:
            raise AssertionError("Imported feature count differs from source: {}".format(counts))
        imported_names = set()
        for name in imported:
            with arcpy.da.SearchCursor(os.path.join(gdb, name), ["name"]) as cursor:
                imported_names.update(row[0] for row in cursor)
        if imported_names != exported_names:
            raise AssertionError("Imported attributes changed: {}".format(imported_names))
        print(json.dumps({
            "arcgis_pro_version": arcpy.GetInstallInfo().get("Version"),
            "export_seconds": round(export_seconds, 3),
            "import_seconds": round(import_seconds, 3),
            "imported": counts,
            "result": "passed",
        }, ensure_ascii=False))
    finally:
        try:
            arcpy.management.ClearWorkspaceCache()
        except Exception:
            pass
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
