# -*- coding: utf-8 -*-
"""QGIS-lisäosan testit. Ajetaan QGISin Pythonilla (esim. python3-qgis):

    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_qgis_plugin

Puhtaat muotoapufunktiot testataan aina; QGIS-riippuvaiset testit ohitetaan,
jos qgis-kirjastoa ei ole saatavilla.
"""

import os
import shutil
import stat
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
sys.path.insert(0, str(ROOT / "qgis_plugin"))

import importlib.util  # noqa: E402

_FORMATS_SPEC = importlib.util.spec_from_file_location(
    "muuntaja_formats_standalone", ROOT / "qgis_plugin" / "muuntaja_qgis" / "formats.py")
formats = importlib.util.module_from_spec(_FORMATS_SPEC)
_FORMATS_SPEC.loader.exec_module(formats)

try:
    from qgis.core import (
        QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY,
        QgsLineSymbol, QgsProject, QgsRasterLayer, QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsVectorLayer,
    )
    from qgis.PyQt.QtGui import QColor
    HAVE_QGIS = True
except Exception:  # pragma: no cover - riippuu ympäristöstä
    HAVE_QGIS = False

_APP = None


def setUpModule():
    global _APP
    if HAVE_QGIS and QgsApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _APP = QgsApplication([], False)
        _APP.initQgis()


def write_script(folder, name, body):
    """Create a small executable Python script (a stand-in for a converter)."""
    path = Path(folder) / name
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    if sys.platform == "win32":
        # Windows ei aja shebang-skriptejä: käynnistä skripti .cmd-kääreellä.
        wrapper = path.with_name(name + ".cmd")
        wrapper.write_text(f'@"{sys.executable}" "{path}" %*\r\n', encoding="utf-8")
        return wrapper
    return path


class FormatHelperTests(unittest.TestCase):
    def test_style_string_parsing(self):
        label = formats.parse_ogr_style('LABEL(f:"Arial",t:"Kauppa, katu",p:7,a:30,s:4g,c:#FF0000FF)')
        self.assertEqual(label["text"], "Kauppa, katu")
        self.assertEqual((label["text_size"], label["angle"], label["anchor"]), (4.0, 30.0, 7))
        self.assertEqual(label["color"], "#ff0000")
        self.assertEqual(formats.parse_ogr_style("BRUSH(fc:#0000ff)")["color"], "#0000ff")
        self.assertIsNone(formats.parse_ogr_style('LABEL(t:"x",s:12pt)')["text_size"])

    def test_dwg_version_is_read_from_header(self):
        self.assertEqual(formats.dwg_version(DATA / "cad_sample_r2000.dwg"), "AC1015")
        self.assertEqual(formats.dwg_version(DATA / "cad_sample.dxf"), "")
        self.assertEqual(formats.dwg_version_label("AC1032"), "AutoCAD 2018")

    def test_unique_name_is_case_insensitive(self):
        self.assertEqual(formats.unique_name("Tiet", {"tiet", "TIET_2"}), "Tiet_3")
        self.assertEqual(formats.unique_name("uusi", set()), "uusi")

    def test_majority_vote_ignores_outliers_at_origin(self):
        self.assertEqual(formats.vote_finnish_epsg([(385000, 6672000)] * 5 + [(0, 0)]), 3067)
        self.assertIsNone(formats.vote_finnish_epsg([(1, 1), (2, 2)]))

    def test_folder_scan_skips_non_spatial_json_but_keeps_selected_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "asetukset.json").write_text('{"theme": "dark"}', encoding="utf-8")
            (root / "tiet.json").write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
            names = [path.name for path in formats.scan_inputs([str(root)])]
            self.assertEqual(names, ["tiet.json"])
            self.assertEqual(len(formats.scan_inputs([str(root / "asetukset.json")])), 1)

    def test_mtext_formatting_is_removed_from_imported_text(self):
        self.assertEqual(formats.strip_mtext(r"\fDejaVu Sans|i0|b0;\H3.57;Kauppakatu"), "Kauppakatu")
        self.assertEqual(formats.strip_mtext(r"{\C1;Talo}\~A\Privi 2"), "Talo A\nrivi 2")
        self.assertEqual(formats.strip_mtext("5.17"), "5.17")

    def test_dwg_writer_platform_names(self):
        self.assertEqual(formats.dwg_writer_platform("win32", "AMD64"), "win-x64")
        self.assertEqual(formats.dwg_writer_platform("linux", "x86_64"), "linux-x64")
        self.assertEqual(formats.dwg_writer_platform("linux", "aarch64"), "linux-arm64")
        self.assertEqual(formats.dwg_writer_platform("darwin", "arm64"), "osx-arm64")
        self.assertEqual(formats.dwg_writer_platform("darwin", "x86_64"), "osx-x64")
        self.assertEqual(formats.dwg_writer_platform("sunos5", "sparc"), "")

    def test_bundled_dwg_writer_gets_its_execute_bit_back(self):
        with tempfile.TemporaryDirectory() as temp:
            rid = formats.dwg_writer_platform()
            name = "muuntaja-dwg.exe" if sys.platform == "win32" else "muuntaja-dwg"
            tool = Path(temp) / rid / name
            tool.parent.mkdir()
            tool.write_bytes(b"")
            tool.chmod(0o644)
            with mock.patch.object(formats, "BUNDLED_DWG_WRITER", Path(temp)), \
                    mock.patch.dict(os.environ, {"MUUNTAJA_DWG_WRITER": ""}):
                self.assertEqual(formats.find_dwg_writer(), str(tool))
            if sys.platform != "win32":
                self.assertTrue(os.access(tool, os.X_OK))

    def test_converter_timeout_is_reported_in_finnish(self):
        import subprocess
        with mock.patch.object(formats.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(RuntimeError, "ei valmistunut"):
                formats.run_converter(["x"], "Testimuunnin")

    def test_bundled_libredwg_is_used_on_windows(self):
        with mock.patch.object(formats.sys, "platform", "win32"), \
                mock.patch.object(formats.shutil, "which", return_value=None):
            self.assertEqual(formats.find_libredwg_tool("dwg2dxf"),
                             str(formats.BUNDLED_LIBREDWG / "dwg2dxf.exe"))

    def test_bundled_libredwg_has_its_libraries_and_licenses(self):
        names = {path.name for path in formats.BUNDLED_LIBREDWG.iterdir()}
        self.assertTrue({"dwg2dxf.exe", "libredwg-0.dll", "libiconv-2.dll",
                         "COPYING.txt", "COPYING.LIB.txt", "README.txt"} <= names)
        # DWG-vientiä ei ole, joten kirjoitustyökaluja ei jaeta.
        self.assertFalse({"dxf2dwg.exe", "dwgrewrite.exe"} & names)

    def test_windows_binaries_are_not_used_on_other_platforms(self):
        with mock.patch.object(formats.sys, "platform", "linux"), \
                mock.patch.object(formats.shutil, "which", return_value=None), \
                mock.patch.dict(os.environ, {"ProgramFiles": "", "ProgramW6432": "", "ProgramFiles(x86)": ""}):
            self.assertEqual(formats.find_libredwg_tool("dwg2dxf"), "")

    def test_converter_output_that_is_not_utf8_does_not_crash(self):
        script = "import sys; sys.stderr.buffer.write(b'ty\\xf6kalut'); sys.exit(3)"
        with self.assertRaisesRegex(RuntimeError, "exit 3"):
            formats.run_converter([sys.executable, "-c", script], "Testimuunnin")


@unittest.skipUnless(HAVE_QGIS, "QGIS Python -kirjastot puuttuvat")
class QgisTestCase(unittest.TestCase):
    def setUp(self):
        from muuntaja_qgis import cad, core
        self.cad, self.core = cad, core
        self.project = QgsProject.instance()
        self.project.clear()
        # QGISin OGR-yhteysvaranto pitää luetut lähdetiedostot hetken auki (Windows).
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.folder = Path(self.temp.name)
        # Ei oikeita muuntimia testeissä, ellei testi itse anna niitä.
        self.no_tools = [
            mock.patch.object(formats_module(), "find_libredwg_tool", return_value=""),
        ]
        for patcher in self.no_tools:
            patcher.start()

    def tearDown(self):
        for patcher in self.no_tools:
            patcher.stop()
        self.project.clear()
        self.temp.cleanup()

    def point_layer(self, authid, points, name="pisteet"):
        layer = QgsVectorLayer(f"Point?crs={authid}&field=nimi:string", name, "memory")
        features = []
        for index, (x, y) in enumerate(points):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([f"P{index}"])
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        return layer


def dxf_pairs(path):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return [(lines[index].strip(), lines[index + 1].strip()) for index in range(0, len(lines) - 1, 2)]


def entity_codes(pairs, name):
    """Group codes of the first ``name`` entity in the ENTITIES section."""
    start = pairs.index(("2", "ENTITIES"))
    first = next(index for index in range(start, len(pairs)) if pairs[index] == ("0", name))
    end = next(index for index in range(first + 1, len(pairs)) if pairs[index][0] == "0")
    return {code: value for code, value in pairs[first + 1:end]}


def formats_module():
    from muuntaja_qgis import formats as plugin_formats
    return plugin_formats


class CadImportTests(QgisTestCase):
    def import_sample(self, **kwargs):
        return self.cad.import_cad(DATA / "cad_sample.dxf", self.folder / "tuonti.gpkg", **kwargs)

    def test_dxf_becomes_grouped_styled_layers(self):
        layers = self.import_sample(clean_cad=True)

        names = [layer.name() for layer in layers]
        self.assertEqual(names, ["cad_sample_tekstit", "cad_sample_pisteet", "cad_sample_viivat",
                                 "cad_sample_alueet"])
        group = self.project.layerTreeRoot().findGroup("cad_sample.dxf")
        self.assertEqual([child.name() for child in group.children()], names)
        self.assertTrue(all(layer.crs().authid() == "EPSG:3067" for layer in layers))
        self.assertEqual(self.project.crs().authid(), "EPSG:3067")

        texts, points, lines, areas = layers
        self.assertTrue(texts.labelsEnabled())
        self.assertEqual(texts.renderer().type(), "nullSymbol")
        by_text = {feature["text"]: feature for feature in texts.getFeatures()}
        self.assertEqual(by_text["Kauppakatu"]["text_angle"], 30.0)
        self.assertEqual(by_text["Kauppakatu"]["text_size"], 4.0)

        self.assertIsInstance(lines.renderer(), QgsRuleBasedRenderer)
        rules = [rule.label() for rule in lines.renderer().rootRule().children()]
        self.assertEqual(rules, ["Puut", "Rakennukset", "Tiet"])
        colors = {feature["cad_layer"]: feature["cad_color"] for feature in areas.getFeatures()}
        self.assertEqual(colors, {"Rakennukset": "#0000ff"})
        self.assertEqual(points.featureCount(), 1)
        cad_layers = {feature["cad_layer"] for layer in layers for feature in layer.getFeatures()}
        self.assertNotIn("Defpoints", cad_layers)
        self.assertNotIn("0", cad_layers)

    def test_paper_space_is_not_imported(self):
        layers = self.import_sample()
        origins = [feature for layer in layers for feature in layer.getFeatures()
                   if feature.geometry().boundingBox().xMinimum() < 1000]
        self.assertEqual(origins, [])

    def test_second_import_does_not_overwrite_case_insensitively(self):
        self.import_sample()
        second = self.import_sample()
        self.assertEqual(second[0].name(), "cad_sample_tekstit_2")
        first = QgsVectorLayer(f"{self.folder / 'tuonti.gpkg'}|layername=cad_sample_tekstit", "x", "ogr")
        self.assertEqual(first.featureCount(), 2)

    def test_forced_source_and_target_crs(self):
        layers = self.import_sample(source_crs=QgsCoordinateReferenceSystem("EPSG:3067"),
                                    target_crs=QgsCoordinateReferenceSystem("EPSG:4326"))
        extent = layers[2].extent()
        self.assertEqual(layers[2].crs().authid(), "EPSG:4326")
        self.assertTrue(19 < extent.xMinimum() < 32 and 59 < extent.yMinimum() < 71)

    def test_unknown_location_asks_for_crs(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "paikaton.dxf"
            text = (DATA / "cad_sample.dxf").read_text(encoding="utf-8")
            source.write_text(text.replace("385", "90").replace("6672", "90"), encoding="utf-8")
            with self.assertRaises(self.cad.CrsNotDetected):
                self.cad.import_cad(source, self.folder / "tuonti.gpkg")

    def test_autocad_2000_dwg_is_read_without_converter(self):
        layers = self.cad.import_cad(DATA / "cad_sample_r2000.dwg", self.folder)
        self.assertTrue(layers)
        self.assertEqual(Path(layers[0].source().split("|")[0]).name, "cad_sample_r2000.gpkg")

    def test_newer_dwg_without_converter_names_the_version(self):
        dwg = self.folder / "uusi.dwg"
        dwg.write_bytes(b"AC1032" + b"\0" * 600)
        with self.assertRaisesRegex(RuntimeError, "AutoCAD 2018.*LibreDWG"):
            self.cad.import_cad(dwg, self.folder / "tuonti.gpkg")

    def test_newer_dwg_is_converted_with_libredwg(self):
        dwg = self.folder / "uusi.dwg"
        dwg.write_bytes(b"AC1032" + b"\0" * 600)
        reader = write_script(self.folder, "dwg2dxf", f"""
            import shutil, sys
            assert sys.argv[1:3] == ["-y", "-o"], sys.argv
            shutil.copy({str(DATA / 'cad_sample.dxf')!r}, sys.argv[3])
        """)
        with mock.patch.object(formats_module(), "find_libredwg_tool",
                               side_effect={"dwg2dxf": str(reader)}.get):
            layers = self.cad.import_cad(dwg, self.folder / "tuonti.gpkg")
        self.assertEqual(layers[0].name(), "uusi_tekstit")

    def test_import_data_routes_cad_files(self):
        successes, failures = self.core.import_data([str(DATA / "cad_sample.dxf")],
                                                    str(self.folder / "tuonti.gpkg"))
        self.assertEqual((len(successes), failures), (1, []))


@unittest.skipUnless(formats.find_libredwg_tool("dwg2dxf"), "LibreDWG puuttuu (Windowsissa se tulee lisäosan mukana)")
class RealLibreDwgTests(QgisTestCase):
    """Oikea LibreDWG: Windowsissa lisäosan mukana tuleva, muualla järjestelmän oma."""

    def setUp(self):
        super().setUp()
        for patcher in self.no_tools:
            patcher.stop()
        self.no_tools = []

    def test_autocad_2018_dwg_is_imported(self):
        layers = self.cad.import_cad(DATA / "cad_sample_r2018.dwg", self.folder / "tuonti.gpkg", clean_cad=True)
        names = [layer.name() for layer in layers]
        self.assertEqual(names[:2], ["cad_sample_r2018_tekstit", "cad_sample_r2018_pisteet"])
        texts = {feature["text"] for layer in layers for feature in layer.getFeatures() if feature["text"]}
        self.assertEqual(texts, {"Kauppakatu", "Talo A"})
        cad_layers = {feature["cad_layer"] for layer in layers for feature in layer.getFeatures()}
        self.assertTrue({"Tiet", "Rakennukset", "Tekstit", "Puut"} <= cad_layers)
        self.assertTrue(all(layer.crs().authid() == "EPSG:3067" for layer in layers))

    def test_autocad_2000_dwg_keeps_hatches_through_libredwg(self):
        layers = self.cad.import_cad(DATA / "cad_sample_r2000.dwg", self.folder / "tuonti.gpkg")
        self.assertIn("cad_sample_r2000_alueet", [layer.name() for layer in layers])



class CadExportTests(QgisTestCase):
    def test_combined_dxf_reprojects_layers_to_the_chosen_crs(self):
        metric = self.point_layer("EPSG:3067", [(385000, 6672000)], "metrinen")
        degrees = self.point_layer("EPSG:4326", [(24.93, 60.17)], "asteet")

        written, failures = self.core.export_data([metric, degrees], self.folder, "DXF", combined=True,
                                                  target_crs=QgsCoordinateReferenceSystem("EPSG:3067"))

        self.assertEqual(failures, [])
        check = QgsVectorLayer(written[0], "tarkistus", "ogr")
        extent = check.extent()
        del check
        self.assertGreater(extent.xMinimum(), 300000)
        self.assertGreater(extent.yMinimum(), 6600000)

    def test_combined_dxf_of_mixed_crs_asks_for_a_target_crs(self):
        metric = self.point_layer("EPSG:3067", [(385000, 6672000)], "metrinen")
        gk25 = self.point_layer("EPSG:3879", [(25496000, 6672000)], "gk25")
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:3067"))
        with self.assertRaisesRegex(RuntimeError, "eri koordinaatistoissa.*EPSG:3067.*EPSG:3879"):
            self.core.export_data([metric, gk25], self.folder, "DXF", combined=True)

    def test_every_layer_keeps_its_own_crs_in_multi_layer_export(self):
        from osgeo import ogr
        metric = self.point_layer("EPSG:3067", [(385000, 6672000)], "metrinen")
        gk25 = self.point_layer("EPSG:3879", [(25496000, 6672000)], "gk25")
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:3067"))
        expected = {"metrinen": 385000, "gk25": 25496000}
        for format_name, combined in (("DXF", False), ("GPKG", True), ("GPKG", False), ("Shapefile", False)):
            with self.subTest(format_name=format_name, combined=combined):
                folder = self.folder / f"{format_name}_{combined}"
                written, failures = self.core.export_data([metric, gk25], folder, format_name, combined=combined)
                self.assertEqual(failures, [])
                found = {}
                for path in sorted(set(written)):
                    dataset = ogr.Open(path)
                    for index in range(dataset.GetLayerCount()):
                        layer = dataset.GetLayer(index)
                        if layer.GetName() == "layer_styles":
                            continue
                        for feature in layer:
                            name = layer.GetName() if format_name == "GPKG" else Path(path).stem
                            found[name] = feature.GetGeometryRef().GetEnvelope()[0]
                    dataset = None
                # DXF:n pistesymbolilla on koko, joten sallitaan muutaman metrin ero.
                self.assertEqual(set(found), set(expected))
                for name, x in expected.items():
                    self.assertAlmostEqual(found[name], x, delta=5)

    def test_single_point_layer_exports(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        written, _failures = self.core.export_data([layer], self.folder, "DXF")
        self.assertTrue(Path(written[0]).stat().st_size > 1000)
        self.assertIn("pisteet", Path(written[0]).read_text(encoding="utf-8", errors="ignore"))

    def test_cad_round_trip_keeps_cad_layer_names_and_texts(self):
        layers = self.cad.import_cad(DATA / "cad_sample.dxf", self.folder / "tuonti.gpkg", clean_cad=True)
        written, _failures = self.core.export_data(layers, self.folder / "vienti", "DXF", combined=True)

        from osgeo import ogr
        dataset = ogr.Open(written[0])
        source = dataset.GetLayer(0)
        cad_layers = {feature.GetField("Layer") for feature in source}
        source.ResetReading()
        texts = {feature.GetField("Text") for feature in source if feature.GetField("Text")}
        self.assertTrue({"Tiet", "Rakennukset", "Tekstit", "Puut"} <= cad_layers)
        self.assertTrue({"Kauppakatu", "Talo A"} <= texts)

    def wide_road(self, width_mm="1.66"):
        layer = QgsVectorLayer("LineString?crs=EPSG:3067", "Eurooppatienumero (Digiroad)", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(385000, 6672000), QgsPointXY(400000, 6700000)]))
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
            {"line_color": "152,125,183", "line_width": width_mm})))
        self.project.addMapLayer(layer)
        return layer

    def test_dxf_strokes_become_line_weights_instead_of_kilometre_wide_bands(self):
        # Koko Suomen näkymästä (1:5 000 000) QGIS kirjoittaisi 1,66 mm viivan 8,3 km leveäksi.
        written, _failures = self.core.export_data([self.wide_road()], self.folder, "DXF", symbology_scale=5000000)
        pairs = dxf_pairs(written[0])
        polyline = entity_codes(pairs, "LWPOLYLINE")
        self.assertEqual(float(polyline["43"]), 0.0)
        self.assertEqual(polyline["370"], "158")
        self.assertIn(("9", "$INSUNITS"), pairs)
        self.assertEqual(pairs[pairs.index(("9", "$INSUNITS")) + 1], ("70", "6"))
        from osgeo import ogr
        dataset = ogr.Open(written[0])
        self.assertEqual(dataset.GetLayer(0).GetFeatureCount(), 1)

    def test_dxf_strokes_in_geographic_crs_use_degrees_per_millimetre(self):
        road = self.wide_road("0.5")
        written, _failures = self.core.export_data([road], self.folder, "DXF", symbology_scale=100000,
                                                   target_crs=QgsCoordinateReferenceSystem("EPSG:4326"))
        pairs = dxf_pairs(written[0])
        self.assertEqual(entity_codes(pairs, "LWPOLYLINE")["370"], "50")
        self.assertNotIn(("9", "$INSUNITS"), pairs)

    def fake_dwg_writer(self, body=None):
        """Stand-in for the bundled ACadSharp writer: records its arguments."""
        record = self.folder / "writer_args.txt"
        body = body or f"""
            import json, sys
            from pathlib import Path
            source, target = sys.argv[1], sys.argv[2]
            Path({str(record)!r}).write_text("\\n".join(sys.argv[1:]), encoding="utf-8")
            assert Path(source).read_text(encoding="utf-8", errors="ignore").count("ENTITIES") == 1
            Path(target).write_bytes(b"AC1032" + b"\\0" * 1000)
            print(json.dumps({{"version": "AC1032", "entities": 2, "layers": 3, "warnings": []}}))
        """
        writer = write_script(self.folder, "muuntaja-dwg", body)
        return writer, record

    def test_dwg_export_uses_the_bundled_writer_on_qgis_dxf(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385010, 6672010)])
        writer, record = self.fake_dwg_writer()
        notes = []
        with mock.patch.dict(os.environ, {"MUUNTAJA_DWG_WRITER": str(writer)}):
            written, failures = self.core.export_data([layer], self.folder / "dwg", "DWG", notes=notes,
                                                      dwg_version="2013", symbology_scale=5000000)

        self.assertEqual(failures, [])
        output = Path(written[0])
        self.assertEqual(output.name, "pisteet.dwg")
        self.assertEqual(formats.dwg_version(output), "AC1032")
        arguments = record.read_text(encoding="utf-8").splitlines()
        self.assertTrue(arguments[0].endswith(".dxf"))
        self.assertEqual(arguments[1:], [str(output), "--version", "2013"])
        self.assertIn("EPSG:3067", output.with_suffix(".prj").read_text(encoding="utf-8") + notes[0])
        self.assertIn("2 CAD-kohdetta", notes[0])
        self.assertFalse(Path(arguments[0]).exists())

    def test_dwg_export_rejects_broken_writer_output(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385010, 6672010)])
        writer, _record = self.fake_dwg_writer("""
            import sys
            from pathlib import Path
            Path(sys.argv[2]).write_bytes(b"not a dwg")
        """)
        with mock.patch.dict(os.environ, {"MUUNTAJA_DWG_WRITER": str(writer)}):
            with self.assertRaisesRegex(RuntimeError, "kelvollista DWG"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")
        self.assertEqual(list((self.folder / "dwg").glob("*.dwg")), [])

    def test_dwg_writer_failure_is_reported(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        writer, _record = self.fake_dwg_writer("""
            import sys
            sys.stderr.write("Kirjoitetusta DWG:stä puuttuu kohteita: Insert 0/1")
            sys.exit(2)
        """)
        with mock.patch.dict(os.environ, {"MUUNTAJA_DWG_WRITER": str(writer)}):
            with self.assertRaisesRegex(RuntimeError, "puuttuu kohteita"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")

    def test_missing_dwg_writer_explains_what_to_do(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        with mock.patch.object(formats_module(), "find_dwg_writer", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "DWG-kirjoitin puuttuu"):
                self.core.export_data([layer], self.folder, "DWG")

    def test_combined_export_is_named_after_the_layers(self):
        name = self.cad.combined_export_name
        first = self.point_layer("EPSG:3067", [(385000, 6672000)], "topelius_JM_line")
        second = self.point_layer("EPSG:3067", [(385000, 6672000)], "topelius_JM_point")
        self.assertEqual(name([first]), "topelius_JM_line")
        self.assertEqual(name([first, second]), "topelius_JM")
        roads = self.point_layer("EPSG:3067", [(385000, 6672000)], "Eurooppatienumero (Digiroad)")
        stations = self.point_layer("EPSG:3067", [(385000, 6672000)], "LAM-piste")
        self.assertEqual(name([roads, stations]), "Eurooppatienumero_Digiroad_ja_1_muuta")
        with mock.patch.object(self.project, "fileName", return_value="/tmp/Liikenne.qgz"), \
                mock.patch.object(self.project, "baseName", return_value="Liikenne"):
            self.assertEqual(name([roads, stations]), "Liikenne")
        # Saman ryhmän tasot (tuotu tiedosto) saavat ryhmän nimen ilman päätettä.
        root = self.project.layerTreeRoot()
        group = root.addGroup("suunnitelma.dgn")
        for layer in (roads, stations):
            node = root.findLayer(layer.id())
            group.addLayer(layer)
            node.parent().removeChildNode(node)
        self.assertEqual(name([roads, stations]), "suunnitelma")

    def test_combined_geopackage_uses_the_combined_name(self):
        first = self.point_layer("EPSG:3067", [(385000, 6672000)], "kaivot_2024")
        second = self.point_layer("EPSG:3067", [(385000, 6672000)], "kaivot_2025")
        written, _failures = self.core.export_data([first, second], self.folder, "GPKG", combined=True)
        self.assertEqual(Path(written[0]).name, "kaivot.gpkg")

    def test_removed_layers_are_ignored(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        written, failures = self.core.export_data([None, layer], self.folder, "GPKG")
        self.assertEqual((len(written), failures), (1, []))

    def test_geojson_is_wgs84(self):
        import json
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        written, _failures = self.core.export_data([layer], self.folder, "GeoJSON")
        x, y = json.loads(Path(written[0]).read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"]
        self.assertTrue(19 < x < 32 and 59 < y < 71)


@unittest.skipUnless(formats.find_dwg_writer(), "ACadSharp-kirjoitin puuttuu (python qgis_plugin/build_dwgwriter.py)")
class RealDwgWriterTests(QgisTestCase):
    """The bundled ACadSharp writer itself, checked with independent readers."""

    def export(self, version, combined=True):
        layers = self.cad.import_cad(DATA / "cad_sample.dxf", self.folder / "lahde.gpkg", clean_cad=False)
        notes = []
        written, failures = self.core.export_data(layers, self.folder / f"dwg{version}", "DWG", combined=combined,
                                                  notes=notes, dwg_version=version)
        self.assertEqual(failures, [])
        self.project.clear()
        return [Path(path) for path in dict.fromkeys(written)], notes

    def test_autocad_2018_dwg_is_written_and_reported(self):
        written, notes = self.export("2018")
        self.assertEqual(formats.dwg_version(written[0]), "AC1032")
        self.assertTrue(written[0].with_suffix(".prj").is_file())
        self.assertRegex(notes[0], r"DWG AutoCAD 2018 \(AC1032\): cad_sample\.dwg, \d+ CAD-kohdetta")

    def test_autocad_2000_dwg_round_trips_through_gdal_cad_driver(self):
        written, _notes = self.export("2000")
        self.assertEqual(formats.dwg_version(written[0]), "AC1015")
        # GDAL:n CAD-ajuri lukee AutoCAD 2000 -DWG:n ilman ACadSharpia tai LibreDWG:tä.
        layers = self.cad.import_cad(written[0], self.folder / "takaisin.gpkg",
                                     source_crs=QgsCoordinateReferenceSystem("EPSG:3067"))
        cad_layers = {feature["cad_layer"] for layer in layers for feature in layer.getFeatures()}
        self.assertTrue({"Tiet", "Rakennukset", "Puut"} <= cad_layers, cad_layers)
        texts = {feature["text"] for layer in layers for feature in layer.getFeatures() if feature["text"]}
        self.assertIn("Kauppakatu", texts)

    def test_every_supported_version_is_written(self):
        for version, _label in formats.DWG_EXPORT_VERSIONS:
            with self.subTest(version=version):
                written, _notes = self.export(version, combined=False)
                self.assertTrue(all(formats.dwg_version(path) for path in written))


class ExportCrsAndStyleTests(QgisTestCase):
    GK23 = "EPSG:3877"

    def styled_layer(self):
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385100, 6672100)])
        categories = []
        for value, color in (("P0", "#ff0000"), ("P1", "#0000ff")):
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(QColor(color))
            categories.append(QgsRendererCategory(value, symbol, value))
        layer.setRenderer(QgsCategorizedSymbolRenderer("nimi", categories))
        return layer

    def xs(self, path, layer_name=None):
        from osgeo import ogr
        dataset = ogr.Open(str(path))
        layer = dataset.GetLayerByName(layer_name) if layer_name else dataset.GetLayer(0)
        # Envelope toimii myös DXF:n pistesymboleille (lohkoviittauksille).
        xs = [feature.GetGeometryRef().GetEnvelope()[0] for feature in layer]
        dataset = None
        return xs

    def test_every_format_is_reprojected_to_the_chosen_crs(self):
        layer = self.styled_layer()
        target = QgsCoordinateReferenceSystem(self.GK23)
        for format_name in ("GPKG", "Shapefile", "GeoJSON", "DXF"):
            with self.subTest(format_name=format_name):
                written, failures = self.core.export_data([layer], self.folder / format_name, format_name,
                                                          target_crs=target)
                self.assertEqual(failures, [])
                xs = self.xs(written[0])
                # Helsingin seutu ETRS-GK23:ssa: itäkoordinaatti noin 23 6xx xxx.
                self.assertTrue(xs and all(23_450_000 < x < 23_750_000 for x in xs), xs)
                if format_name != "DXF":
                    check = QgsVectorLayer(written[0], "tarkistus", "ogr")
                    self.assertEqual(check.crs().authid(), self.GK23)
                    del check

    def test_kml_stays_in_wgs84_and_tells_why(self):
        layer = self.styled_layer()
        for format_name in ("KML", "KMZ"):
            with self.subTest(format_name=format_name):
                notes = []
                written, _failures = self.core.export_data(
                    [layer], self.folder / format_name, format_name,
                    target_crs=QgsCoordinateReferenceSystem(self.GK23), notes=notes)
                xs = self.xs(written[0])
                self.assertTrue(xs and all(24 < x < 26 for x in xs), xs)
                self.assertTrue(any("aina WGS84" in note for note in notes), notes)

    def test_geojson_without_chosen_crs_is_still_wgs84(self):
        layer = self.styled_layer()
        written, _failures = self.core.export_data([layer], self.folder, "GeoJSON")
        self.assertTrue(all(24 < x < 26 for x in self.xs(written[0])))

    def test_layer_without_crs_cannot_be_reprojected(self):
        layer = QgsVectorLayer("Point?field=nimi:string", "tuntematon", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(385000, 6672000)))
        layer.dataProvider().addFeatures([feature])
        self.project.addMapLayer(layer)
        layer.setCrs(QgsCoordinateReferenceSystem())  # QGIS antaa uudelle tasolle oletus-CRS:n
        with self.assertRaisesRegex(RuntimeError, "tunnetun lähtökoordinaatiston"):
            self.core.export_data([layer], self.folder, "Shapefile", target_crs=QgsCoordinateReferenceSystem(self.GK23))

    def test_style_is_stored_inside_the_geopackage(self):
        layer = self.styled_layer()
        notes = []
        written, _failures = self.core.export_data([layer], self.folder, "GPKG", notes=notes)
        reopened = QgsVectorLayer(f"{written[0]}|layername=pisteet", "tarkistus", "ogr")
        self.assertEqual(reopened.renderer().type(), "categorizedSymbol")
        del reopened
        from osgeo import ogr
        dataset = ogr.Open(written[0])
        styles = dataset.GetLayerByName("layer_styles")
        self.assertIsNotNone(styles)
        self.assertEqual(styles.GetFeatureCount(), 1)
        styles = dataset = None
        self.assertTrue(any("layer_styles" in note for note in notes), notes)

    def test_style_is_written_next_to_shapefile_and_geojson(self):
        layer = self.styled_layer()
        for format_name in ("Shapefile", "GeoJSON"):
            with self.subTest(format_name=format_name):
                written, _failures = self.core.export_data([layer], self.folder / format_name, format_name)
                self.assertTrue(Path(written[0]).with_suffix(".qml").is_file())
                reopened = QgsVectorLayer(written[0], "tarkistus", "ogr")
                self.assertEqual(reopened.renderer().type(), "categorizedSymbol")
                del reopened

    def test_styles_are_left_out_when_not_wanted(self):
        layer = self.styled_layer()
        for format_name in ("GPKG", "Shapefile", "GeoJSON"):
            with self.subTest(format_name=format_name):
                notes = []
                written, _failures = self.core.export_data([layer], self.folder / format_name, format_name,
                                                           notes=notes, include_styles=False)
                self.assertFalse(Path(written[0]).with_suffix(".qml").exists())
                self.assertFalse(any("Tyyli" in note for note in notes), notes)
                if format_name == "GPKG":
                    from osgeo import ogr
                    dataset = ogr.Open(written[0])
                    self.assertIsNone(dataset.GetLayerByName("layer_styles"))
                    dataset = None

    def imported_layers(self):
        return [layer for layer in self.project.mapLayers().values()
                if isinstance(layer, QgsVectorLayer) and "tuonti" in layer.source()]

    def test_import_applies_style_from_shapefile_qml_and_geopackage(self):
        layer = self.styled_layer()
        shp, _ = self.core.export_data([layer], self.folder / "shp", "Shapefile")
        gpkg, _ = self.core.export_data([layer], self.folder / "gpkg", "GPKG")
        self.project.removeMapLayer(layer.id())
        for source, mode in ((shp[0], "gpkg"), (gpkg[0], "gpkg"), (shp[0], "folder")):
            with self.subTest(source=Path(source).suffix, mode=mode):
                destination = self.folder / f"tuonti_{Path(source).suffix[1:]}_{mode}"
                destination = destination.with_suffix(".gpkg") if mode == "gpkg" else destination
                notes = []
                successes, failures = self.core.import_data([source], str(destination), notes=notes)
                self.assertEqual((len(successes), failures), (1, []))
                imported = [item for item in self.imported_layers() if str(destination) in item.source()]
                self.assertEqual(len(imported), 1)
                self.assertEqual(imported[0].renderer().type(), "categorizedSymbol")
                self.assertTrue(any("Tyyli otettiin käyttöön" in note for note in notes), notes)
                # Tyyli tallentuu tuonnin GeoPackageen, joten taso avautuu tyylillä myöhemminkin.
                reopened = QgsVectorLayer(imported[0].source(), "uudelleen", "ogr")
                self.assertEqual(reopened.renderer().type(), "categorizedSymbol")
                del reopened

    def test_import_without_source_style_keeps_default_style(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        shp, _ = self.core.export_data([layer], self.folder / "shp", "Shapefile", include_styles=False)
        notes = []
        self.core.import_data([shp[0]], str(self.folder / "tuonti.gpkg"), notes=notes)
        imported = self.imported_layers()
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0].renderer().type(), "singleSymbol")
        self.assertFalse(any("Tyyli" in note for note in notes), notes)

    def test_kml_contains_the_layer_style(self):
        layer = self.styled_layer()
        written, _failures = self.core.export_data([layer], self.folder, "KML")
        text = Path(written[0]).read_text(encoding="utf-8", errors="ignore")
        self.assertIn("<Style", text)
        self.assertIn("ff0000ff", text.lower())  # KML-väri aabbggrr: punainen


class ImportRegressionTests(QgisTestCase):
    def test_dfsu_into_geopackage_with_existing_layers_opens_right_layer(self):
        existing = self.point_layer("EPSG:3067", [(385000, 6672000)], "olemassa")
        target = self.folder / "tuonti.gpkg"
        self.core.write_vector(existing, target, "GPKG", "olemassa")
        dfsu = self.folder / "malli.dfsu"
        dfsu.write_bytes(b"fake")

        class Values:
            def __init__(self, values):
                self.values = values

            def to_numpy(self):
                import numpy
                return numpy.array([self.values])

        items = {"syvyys": Values([1.0, 2.0]), "nopeus": Values([0.5, 0.7])}

        class Dataset:
            geometry = types.SimpleNamespace(
                element_table=[[0, 1, 2], [1, 3, 2]],
                node_coordinates=[[385000, 6670000], [385001, 6670000], [385000, 6670001], [385001, 6670001]],
                projection_string="EPSG:3067")
            items = [types.SimpleNamespace(name="syvyys"), types.SimpleNamespace(name="nopeus")]

            def __getitem__(self, name):
                return items[name]

        fake = types.SimpleNamespace(read=lambda *_args, **_kwargs: Dataset())
        with mock.patch.dict(sys.modules, {"mikeio": fake}):
            successes, failures = self.core.import_data([str(dfsu)], str(target))

        self.assertEqual((len(successes), failures), (1, []))
        names = [layer.name() for layer in self.project.mapLayers().values()]
        self.assertIn("malli", names)
        layer = next(layer for layer in self.project.mapLayers().values() if layer.name() == "malli")
        self.assertEqual(layer.featureCount(), 2)
        self.assertEqual(layer.fields().names(), ["fid", "element_id", "syvyys", "nopeus"])

    def test_raster_group_keeps_users_own_layers(self):
        from osgeo import gdal, osr
        tiles = self.folder / "data"
        tiles.mkdir()
        spatial = osr.SpatialReference()
        spatial.ImportFromEPSG(3067)
        for index in range(2):
            raster = gdal.GetDriverByName("GTiff").Create(str(tiles / f"{index}.tif"), 2, 2, 1)
            raster.SetGeoTransform([385000 + index * 2, 1, 0, 6672000, 0, -1])
            raster.SetProjection(spatial.ExportToWkt())
            raster = None
        own = self.point_layer("EPSG:3067", [(385000, 6672000)], "oma_taso")
        root = self.project.layerTreeRoot()
        group = root.addGroup("data")
        root.findLayer(own.id()).parent().removeChildNode(root.findLayer(own.id()))
        group.addLayer(own)

        self.core.import_data([str(tiles)], str(self.folder / "tulos"))
        self.core.import_data([str(tiles)], str(self.folder / "tulos"))

        names = sorted(node.layer().name() for node in group.findLayers())
        self.assertEqual(names, ["data", "oma_taso"])
        self.assertIsNotNone(self.project.mapLayer(own.id()))
        mosaic = next(node.layer() for node in group.findLayers() if node.layer().name() == "data")
        self.assertIsInstance(mosaic, QgsRasterLayer)


@unittest.skipUnless(HAVE_QGIS, "QGIS Python -kirjastot puuttuvat")
class PluginTests(unittest.TestCase):
    def wait_for_cad(self, plugin):
        import time
        deadline = time.monotonic() + 30
        while (plugin._cad_task is not None or plugin._cad_queue) and time.monotonic() < deadline:
            QgsApplication.instance().processEvents()
            time.sleep(0.01)
        self.assertIsNone(plugin._cad_task, "CAD task did not finish")

    def make_iface(self):
        from qgis.PyQt.QtWidgets import QMenu
        calls = []

        class MessageBar:
            def pushMessage(self, *args, **kwargs):
                calls.append(("message", args, kwargs))

        class Canvas:
            def scale(self):
                return 2000.0

        menu = QMenu()

        class Iface:
            def mainWindow(self): return None
            def addPluginToMenu(self, *args): calls.append(("addPluginToMenu",) + args)
            def removePluginMenu(self, *args): calls.append(("removePluginMenu",) + args)
            def addToolBarIcon(self, *args): calls.append(("addToolBarIcon",) + args)
            def removeToolBarIcon(self, *args): calls.append(("removeToolBarIcon",) + args)
            def insertAddLayerAction(self, action): calls.append(("insertAddLayerAction", action.text()))
            def removeAddLayerAction(self, action): calls.append(("removeAddLayerAction", action.text()))
            def projectImportExportMenu(self): return menu
            def registerCustomDropHandler(self, handler): calls.append(("register", handler))
            def unregisterCustomDropHandler(self, handler): calls.append(("unregister", handler))
            def messageBar(self): return MessageBar()
            def mapCanvas(self): return Canvas()

        return Iface(), calls, menu

    def test_plugin_registers_native_cad_entry_points_and_cleans_up(self):
        from muuntaja_qgis import classFactory
        iface, calls, menu = self.make_iface()
        plugin = classFactory(iface)
        plugin.initGui()

        self.assertIn(("insertAddLayerAction", "Lisää DWG/DXF/DGN-taso (Muuntaja)…"), calls)
        self.assertIn("Vie tasot DXF-muotoon (Muuntaja)…", [action.text() for action in menu.actions()])
        self.assertIn("Vie tasot DGN-muotoon (Muuntaja)…", [action.text() for action in menu.actions()])
        self.assertIn("Vie tasot DWG-muotoon (Muuntaja)…", [action.text() for action in menu.actions()])
        handler = next(call[1] for call in calls if call[0] == "register")
        with mock.patch.object(plugin, "import_cad_files") as imported:
            self.assertFalse(handler.handleFileDrop("/data/tiet.shp"))
            self.assertTrue(handler.handleFileDrop("/data/piirustus.DWG"))
            imported.assert_called_once_with(["/data/piirustus.DWG"])
            imported.reset_mock()
            self.assertTrue(handler.handleFileDrop("/data/piirustus.DGN"))
            imported.assert_called_once_with(["/data/piirustus.DGN"])

        first = plugin._dialog()
        self.assertIs(plugin._dialog(), first)
        self.assertEqual(first._symbology_scale(), 2000.0)
        plugin.unload()
        self.assertIn(("unregister", handler), calls)
        self.assertEqual(menu.actions(), [])
        self.assertIsNone(plugin.dialog)

    def test_dropped_dwg_is_imported_next_to_unsaved_project(self):
        from muuntaja_qgis import classFactory
        QgsProject.instance().clear()
        iface, calls, _menu = self.make_iface()
        plugin = classFactory(iface)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "piirustus.dxf"
            shutil.copy(DATA / "cad_sample.dxf", source)
            plugin.import_cad_files([str(source)])
            self.wait_for_cad(plugin)
            self.assertTrue((Path(temp) / "piirustus.gpkg").is_file())
            # Windows ei poista projektissa avoinna olevaa GeoPackagea.
            QgsProject.instance().clear()
        messages = [call for call in calls if call[0] == "message"]
        self.assertIn("4 tasoa lisätty", messages[-1][1][1])

    def test_dropped_dwg_without_crs_asks_for_it(self):
        from muuntaja_qgis import classFactory
        QgsProject.instance().clear()
        iface, calls, _menu = self.make_iface()
        plugin = classFactory(iface)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "paikaton.dxf"
            text = (DATA / "cad_sample.dxf").read_text(encoding="utf-8")
            source.write_text(text.replace("385", "90").replace("6672", "90"), encoding="utf-8")
            chosen = QgsCoordinateReferenceSystem("EPSG:3067")
            with mock.patch.object(plugin, "_ask_crs", return_value=chosen) as ask:
                plugin.import_cad_files([str(source)])
                self.wait_for_cad(plugin)
            ask.assert_called_once()
            layers = list(QgsProject.instance().mapLayers().values())
            self.assertTrue(layers and all(layer.crs() == chosen for layer in layers))
            with mock.patch.object(plugin, "_ask_crs", return_value=None):
                plugin.import_cad_files([str(source)])
                self.wait_for_cad(plugin)
            QgsProject.instance().clear()

    def test_export_dialog_offers_dxf_dwg_and_dgn(self):
        from muuntaja_qgis.plugin import MuuntajaDialog
        dialog = MuuntajaDialog()
        formats_in_dialog = [dialog.format.itemText(i) for i in range(dialog.format.count())]
        self.assertEqual(formats_in_dialog[-3:], ["DXF", "DWG", "DGN"])
        dialog.format.setCurrentText("DWG")
        self.assertTrue(dialog.combined.isEnabled())
        self.assertFalse(dialog.dwg_version.isHidden())
        self.assertEqual(dialog.dwg_version.currentData(), "2018")
        dialog.format.setCurrentText("DXF")
        self.assertTrue(dialog.dwg_version.isHidden())
        self.assertTrue(dialog.combined.isEnabled())
        dialog.format.setCurrentText("DGN")
        self.assertTrue(dialog.combined.isEnabled())
        dialog.close()

    def test_export_dialog_offers_common_crs_and_locks_kml_to_wgs84(self):
        from muuntaja_qgis.plugin import MuuntajaDialog
        dialog = MuuntajaDialog()
        labels = [dialog.export_crs.itemText(i) for i in range(dialog.export_crs.count())]
        self.assertIn("ETRS-GK23 (EPSG:3877)", labels)
        self.assertIn("ETRS-TM35FIN (EPSG:3067)", labels)
        self.assertEqual(labels[-1], "Muu koordinaatisto…")
        self.assertEqual(labels[0], "Tason oma")
        self.assertIsNone(dialog._export_target_crs())
        self.assertTrue(dialog.include_styles.isChecked())
        dialog.format.setCurrentText("DXF")
        self.assertFalse(dialog.include_styles.isEnabled())
        dialog.format.setCurrentText("GPKG")
        self.assertTrue(dialog.include_styles.isEnabled())
        dialog.export_crs.setCurrentIndex(labels.index("ETRS-GK23 (EPSG:3877)"))
        self.assertEqual(dialog._export_target_crs().authid(), "EPSG:3877")
        dialog.format.setCurrentText("KML")
        self.assertFalse(dialog.export_crs.isEnabled())
        dialog.format.setCurrentText("Shapefile")
        self.assertTrue(dialog.export_crs.isEnabled())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
