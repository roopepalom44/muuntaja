"""Real ArcGIS import/export matrix; run with ArcGIS Pro Python.

Creates fixtures and a JSON report in --output-dir. It does not use or alter
the user's current project. Optional --downloads and --dfsu test real inputs.
"""

import argparse
import importlib.machinery
import importlib.util
import json
import sys
import time
import traceback
import types
import zipfile
from pathlib import Path

import arcpy

ROOT = Path(__file__).resolve().parents[1]


class Messages:
    def __init__(self):
        self.entries = []

    def addMessage(self, message):
        self.entries.append(("INFO", message))

    def addWarningMessage(self, message):
        self.entries.append(("WARNING", message))

    def addErrorMessage(self, message):
        self.entries.append(("ERROR", message))


def toolbox():
    loader = importlib.machinery.SourceFileLoader("muuntaja_matrix", str(ROOT / "Toolboxes" / "Muuntaja.pyt"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def params():
    return [types.SimpleNamespace(value=None, valueAsText=None) for _ in range(16)]


def count(path):
    return int(arcpy.management.GetCount(str(path))[0])


class Matrix:
    def __init__(self, output):
        self.output = output
        self.results = []
        self.module = toolbox()
        self.gdb = str(arcpy.management.CreateFileGDB(str(output), "fixtures.gdb")[0])
        self.fixtures = {}
        self.exported = {}
        for geometry in ("POINT", "POLYLINE", "POLYGON"):
            fc = str(arcpy.management.CreateFeatureclass(self.gdb, geometry.lower(), geometry, spatial_reference=3067)[0])
            arcpy.management.AddField(fc, "name", "TEXT", field_length=100)
            arcpy.management.AddField(fc, "number", "LONG")
            arcpy.management.AddField(fc, "value", "DOUBLE")
            rows = []
            for index in range(2):
                x, y = 385000 + index * 100, 6672000
                if geometry == "POINT":
                    shape = arcpy.PointGeometry(arcpy.Point(x, y), arcpy.SpatialReference(3067))
                else:
                    points = [(x, y), (x + 20, y + 20)]
                    if geometry == "POLYGON":
                        points = [(x, y), (x, y + 20), (x + 20, y + 20), (x + 20, y), (x, y)]
                    array = arcpy.Array([arcpy.Point(*xy) for xy in points])
                    shape = (arcpy.Polygon if geometry == "POLYGON" else arcpy.Polyline)(array, arcpy.SpatialReference(3067))
                rows.append((shape, ("Äänekoski", "Öljy – 中文")[index], index + 1, 2.5 + index))
            with arcpy.da.InsertCursor(fc, ["SHAPE@", "name", "number", "value"]) as cursor:
                for row in rows:
                    cursor.insertRow(row)
            self.fixtures[geometry] = fc

    def run(self, name, action, expected_error=False):
        started = time.perf_counter()
        result = {"name": name}
        try:
            details = action()
            if expected_error:
                raise AssertionError("Invalid input was reported as a success")
            result.update(status="PASS", details=details)
        except Exception as error:
            if expected_error and not isinstance(error, AssertionError):
                result.update(status="PASS", expected_error=str(error))
            else:
                result.update(status="FAIL", error=str(error), traceback=traceback.format_exc())
        result["seconds"] = round(time.perf_counter() - started, 3)
        self.results.append(result)
        (self.output / "report.json").write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(result["status"], name, result.get("error", ""), flush=True)

    def export(self, sources, fmt, label, target="Tason oma", separate=False, expected_counts=None):
        folder = self.output / label
        folder.mkdir()
        tool = self.module.UniversalImportTool()
        messages = Messages()
        p = params()
        p[6].valueAsText, p[7].valueAsText = str(folder), fmt
        p[13].valueAsText = (self.module.MULTI_EXPORT_PACKAGING_SEPARATE if separate
                            else self.module.MULTI_EXPORT_PACKAGING_COMBINED)
        p[14].valueAsText = target
        p[15].value = True
        tool._execute_export(p, messages, sources)
        paths = list(folder.glob("*" + self.module.EXPORT_FORMAT_TO_EXT[fmt]))
        assert paths, messages.entries
        expected_files = len(sources) if (separate or fmt not in ("GPKG", "DWG", "DXF")) else 1
        assert len(paths) == expected_files, (paths, expected_files)
        counts = []
        for path in paths:
            assert path.stat().st_size > 0
            if fmt == "Shapefile":
                counts.append(count(path))
                assert path.with_suffix(".lyrx").is_file()
                if target != "Tason oma":
                    assert arcpy.Describe(str(path)).spatialReference.factoryCode == 3877
            elif fmt == "GPKG":
                with arcpy.EnvManager(workspace=str(path)):
                    fcs = arcpy.ListFeatureClasses() or []
                assert fcs
                counts.extend(count(path / fc) for fc in fcs)
                assert list(folder.glob(path.stem + "*.lyrx"))
            elif fmt == "GeoJSON":
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                assert data["type"] == "FeatureCollection"
                counts.append(len(data["features"]))
            elif fmt in ("KML", "KMZ"):
                if fmt == "KMZ":
                    with zipfile.ZipFile(path) as archive:
                        assert any(name.lower().endswith(".kml") for name in archive.namelist())
                else:
                    assert b"<kml" in path.read_bytes(), "KML extension must contain XML"
            elif fmt in ("DWG", "DXF"):
                assert any(arcpy.Exists(str(path / geometry)) and count(path / geometry) > 0
                           for geometry in ("Point", "Polyline", "Polygon"))
        if expected_counts is not None and counts:
            assert sorted(counts) == sorted(expected_counts), (counts, expected_counts)
        self.exported[label] = paths
        return {"files": [str(path) for path in paths], "counts": counts,
                "warnings": [text for level, text in messages.entries if level == "WARNING"]}

    def import_paths(self, paths, label, expected_total=None, folder_output=False, require_warning=False):
        destination = self.output / label
        if folder_output:
            destination.mkdir()
        else:
            destination = Path(str(arcpy.management.CreateFileGDB(str(self.output), label + ".gdb")[0]))
        tool = self.module.UniversalImportTool()
        messages = Messages()
        saved = []
        tool._add_layers_to_map = lambda paths, _messages, _styles=None: saved.extend(paths)
        original = tool.save_and_reproject

        def save(*args, **kwargs):
            kwargs["add_to_map"] = False
            result = original(*args, **kwargs)
            if result not in saved:
                saved.append(result)
            return result

        tool.save_and_reproject = save
        p = params()
        p[2].valueAsText = str(destination)
        p[4].valueAsText = "ETRS-TM35FIN (3067)" if any(str(path).lower().endswith((".dwg", ".dxf")) for path in paths) else "Automaattinen"
        tool._execute_import(p, messages, [str(path) for path in paths])
        unique = list(dict.fromkeys(saved))
        counts = [count(path) for path in unique]
        assert unique and sum(counts) > 0, messages.entries
        if expected_total is not None:
            assert sum(counts) == expected_total, (counts, expected_total)
        assert not any(level == "ERROR" for level, _text in messages.entries), messages.entries
        if require_warning:
            assert any(level == "WARNING" for level, _text in messages.entries), messages.entries
        return {"counts": counts, "warnings": [text for level, text in messages.entries if level == "WARNING"]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--dfsu", type=Path)
    parser.add_argument("--only", help="Run only cases whose names contain this text")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    matrix = Matrix(args.output_dir)

    def run(name, action, **kwargs):
        if not args.only or args.only in name:
            matrix.run(name, action, **kwargs)

    with arcpy.EnvManager(scratchWorkspace=matrix.gdb, addOutputsToMap=False):
        for geometry, fc in matrix.fixtures.items():
            for fmt in matrix.module.EXPORT_FORMAT_LIST:
                label = f"export_{geometry}_{fmt}"
                run(label, lambda fc=fc, fmt=fmt, label=label: matrix.export([fc], fmt, label, expected_counts=[2]))
        for fmt in ("Shapefile", "GeoJSON", "GPKG"):
            label = "projected_" + fmt
            run(label, lambda fmt=fmt, label=label: matrix.export([matrix.fixtures["POLYLINE"]], fmt, label,
                target="ETRS-GK23 (3877)", expected_counts=[2]))
        sources = list(matrix.fixtures.values())
        for fmt in ("GPKG", "DWG", "DXF", "Shapefile", "GeoJSON", "KML", "KMZ"):
            for separate in ((False, True) if fmt in ("GPKG", "DWG", "DXF") else (False,)):
                label = f"multi_{fmt}_{separate}"
                run(label, lambda fmt=fmt, separate=separate, label=label: matrix.export(sources, fmt, label,
                    separate=separate, expected_counts=[2, 2, 2]))
        layer = str(arcpy.management.MakeFeatureLayer(matrix.fixtures["POINT"], "matrix_selection", "number = 2")[0])
        run("selection", lambda: matrix.export([layer], "Shapefile", "selection", expected_counts=[1]))
        for geometry in matrix.fixtures:
            for fmt in ("GPKG", "Shapefile", "GeoJSON", "KML", "KMZ", "DWG", "DXF"):
                key = f"export_{geometry}_{fmt}"
                if key in matrix.exported:
                    run("import_" + key, lambda key=key: matrix.import_paths(matrix.exported[key], "import_" + key,
                        expected_total=2 if fmt not in ("DWG", "DXF") else None))
        for name in ("cad_sample.dxf", "cad_sample_r2000.dwg", "cad_sample_r2018.dwg"):
            if name.endswith(".dxf"):
                run("import_" + name, lambda name=name: matrix.import_paths([ROOT / "tests" / "data" / name],
                    "import_" + name.replace(".", "_")))
        invalid = args.output_dir / "invalid.geojson"
        invalid.write_text('{"type":"FeatureCollection","features":[BROKEN', encoding="utf-8")
        empty = args.output_dir / "empty.geojson"
        empty.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        run("invalid_only", lambda: matrix.import_paths([invalid], "invalid_only"), expected_error=True)
        run("empty_only", lambda: matrix.import_paths([empty], "empty_only"), expected_error=True)
        good = args.output_dir / "valid.geojson"
        good.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [24.94, 60.17]}, "properties": {"name": "Äänekoski"}}]},
            ensure_ascii=False), encoding="utf-8")
        run("mixed_invalid_valid", lambda: matrix.import_paths([invalid, good, empty], "mixed_invalid_valid", expected_total=1))
        broken_dfsu = args.output_dir / "broken.dfsu"
        broken_dfsu.write_bytes(b"invalid DFSU header")
        run("mixed_invalid_dfsu_valid", lambda: matrix.import_paths([broken_dfsu, good], "mixed_invalid_dfsu_valid",
            expected_total=1, require_warning=True))
        for name in ("cad_sample_r2000.dwg", "cad_sample_r2018.dwg"):
            run("native_cad_failure_" + name, lambda name=name: matrix.import_paths(
                [ROOT / "tests" / "data" / name, good], "native_cad_" + name.replace(".", "_"),
                require_warning=name == "cad_sample_r2000.dwg"))
        run("folder_shapefile", lambda: matrix.import_paths([good], "folder_shapefile", expected_total=1, folder_output=True))
        nested = args.output_dir / "nested_source" / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "valid.geojson").write_bytes(good.read_bytes())
        (nested.parent / "invalid.geojson").write_bytes(invalid.read_bytes())
        run("nested_folder", lambda: matrix.import_paths([nested.parent.parent], "nested_folder", expected_total=1))
        if args.downloads:
            for name in ("Väylä_tiestotiedot_aidat (2).gpkg", "Tilastokeskus_postialue_pno_tilasto_2026.gpkg",
                         "Tasaus_Roope_Palomaa.gpkg"):
                source = args.downloads / name
                if source.is_file():
                    run("real_" + name, lambda source=source: matrix.import_paths([source], "real_" + source.stem.replace(" ", "_")),
                        expected_error=name == "Tasaus_Roope_Palomaa.gpkg")
                    if "aidat" in name:
                        run("real_folder_big_integer", lambda source=source: matrix.import_paths([source], "real_folder_big_integer",
                            expected_total=6098, folder_output=True))
            for source in args.downloads.glob("*.gpx"):
                run("real_gpx_" + source.stem, lambda source=source: matrix.import_paths([source], "real_gpx"))
        if args.dfsu:
            run("real_dfsu", lambda: matrix.import_paths([args.dfsu], "real_dfsu"))
        arcpy.management.Delete(layer)
    failures = [result for result in matrix.results if result["status"] == "FAIL"]
    print(f"RESULT: {len(matrix.results) - len(failures)}/{len(matrix.results)} PASS; report: {args.output_dir / 'report.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
