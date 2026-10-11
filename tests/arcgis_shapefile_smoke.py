"""Aja ArcGIS Pron Pythonilla: python tests/arcgis_shapefile_smoke.py [--source FC]."""

import argparse
import datetime
import importlib.machinery
import importlib.util
import sys
import tempfile
import types
from pathlib import Path

import arcpy


def load_toolbox(path):
    loader = importlib.machinery.SourceFileLoader("muuntaja_live_shapefile", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.UniversalImportTool()


class Messages:
    def addMessage(self, text):
        print(text)

    addWarningMessage = addMessage
    addErrorMessage = addMessage


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Valinnainen oikea feature class / GPKG-taso")
    parser.add_argument("--output-dir")
    parser.add_argument("--toolbox", default=str(Path(__file__).resolve().parents[1] / "Toolboxes" / "Muuntaja.pyt"))
    args = parser.parse_args()
    output = Path(args.output_dir or tempfile.mkdtemp(prefix="muuntaja-shapefile-smoke-"))
    output.mkdir(parents=True, exist_ok=True)
    tool = load_toolbox(args.toolbox)
    messages = Messages()
    gdb = str(arcpy.management.CreateFileGDB(str(output), "smoke.gdb")[0])
    with arcpy.EnvManager(scratchWorkspace=gdb, overwriteOutput=False, addOutputsToMap=False):
        if args.source:
            # Sama koko vientipolku kuin dialogissa: kohde-CRS ja tyyli mukana.
            params = [types.SimpleNamespace(valueAsText=None, value=None) for _ in range(16)]
            params[6].valueAsText = str(output)
            params[7].valueAsText = "Shapefile"
            params[14].valueAsText = "ETRS-GK23 (3877)"
            params[15].value = True
            tool._execute_export(params, messages, [args.source])
            result = next(output.glob("*.shp"))
            assert int(arcpy.management.GetCount(str(result))[0]) == int(arcpy.management.GetCount(args.source)[0])
            assert arcpy.Describe(str(result)).spatialReference.factoryCode == 3877
            assert result.with_suffix(".lyrx").is_file()
            source_names = [f.name for f in arcpy.ListFields(args.source) if f.type == "BigInteger"]
            mappings = tool._build_shapefile_field_mappings(args.source, str(output), messages)
            mapped_names = []
            for index in range(mappings.fieldCount):
                fmap = mappings.getFieldMap(index)
                if fmap.getInputFieldName(0) in source_names:
                    mapped_names.append((fmap.getInputFieldName(0), fmap.outputField.name))
            assert len(mapped_names) == len(source_names)
            actual = list(arcpy.da.SearchCursor(str(result), [name for _src, name in mapped_names]))
            expected = [tuple("" if value is None else str(value) for value in row)
                        for row in arcpy.da.SearchCursor(args.source, [src for src, _name in mapped_names])]
            assert actual == expected, "BigInteger-arvot muuttuivat viennissä"
            print(f"SOURCE PASS: {len(actual)} kohdetta, {len(mapped_names)} tarkkaa tunnistekenttää, EPSG:3877 ja tyyli")

        # Pieni rakenne varmistaakin tyypit, vaikka 4 000 tavun raja ei ylity.
        fc = str(arcpy.management.CreateFeatureclass(gdb, "types", "POINT", spatial_reference=3067)[0])
        specs = [("large_id", "BIGINTEGER"), ("day", "DATEONLY"),
                 ("clock", "TIMEONLY"), ("offset", "TIMESTAMPOFFSET"), ("guid", "GUID")]
        for name, field_type in specs:
            arcpy.management.AddField(fc, name, field_type)
        values = (9007199254740991, datetime.date(2026, 9, 30), datetime.time(18, 12, 22, 123000),
                  datetime.datetime.fromisoformat("2026-09-30T18:12:22.123+03:00"),
                  "{12345678-1234-1234-1234-123456789ABC}")
        with arcpy.da.InsertCursor(fc, ["SHAPE@XY"] + [name for name, _kind in specs]) as cursor:
            cursor.insertRow(((385000, 6672000),) + values)
        result = tool._export_to_shapefile(fc, str(output / "types.shp"), messages)
        actual = next(iter(arcpy.da.SearchCursor(result, [name for name, _kind in specs])))
        print("TYPE VALUES:", repr(actual))
        assert actual[0] == str(values[0]), "Pitkä tunniste pyöristyi"
        assert all(f.type in ("OID", "Geometry", "String") for f in arcpy.ListFields(result))
        assert all(value and value.strip() for value in actual), "Kentän arvo katosi"
        assert "+03" in actual[3], "Aikaleiman aikavyöhyke katosi"
        assert actual[4].upper() == values[4]
        print("TYPES PASS: BigInteger, DateOnly, TimeOnly, TimestampOffset, GUID")
    print("OUTPUT:", output)


if __name__ == "__main__":
    main()
