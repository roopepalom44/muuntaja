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
        QgsProject, QgsRasterLayer, QgsRuleBasedRenderer, QgsVectorLayer,
    )
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

    def test_converter_timeout_is_reported_in_finnish(self):
        import subprocess
        with mock.patch.object(formats.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(RuntimeError, "ei valmistunut"):
                formats.run_converter(["x"], "Testimuunnin")

    def test_bundled_libredwg_is_used_on_windows(self):
        with mock.patch.object(formats.sys, "platform", "win32"), \
                mock.patch.object(formats.shutil, "which", return_value=None):
            for name in ("dwg2dxf", "dxf2dwg"):
                self.assertEqual(formats.find_libredwg_tool(name),
                                 str(formats.BUNDLED_LIBREDWG / f"{name}.exe"))

    def test_bundled_libredwg_has_its_libraries_and_licenses(self):
        names = {path.name for path in formats.BUNDLED_LIBREDWG.iterdir()}
        self.assertTrue({"dwg2dxf.exe", "dxf2dwg.exe", "dwgrewrite.exe", "libredwg-0.dll", "libiconv-2.dll",
                         "COPYING.txt", "COPYING.LIB.txt", "README.txt"} <= names)

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
        self.temp = tempfile.TemporaryDirectory()
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

    def test_real_area_export_keeps_fills_and_warns_about_outlines(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:3067", "alueet", "memory")
        features = []
        for index in range(6):
            feature = QgsFeature(layer.fields())
            x = 385000 + index * 50
            feature.setGeometry(QgsGeometry.fromWkt(
                f"POLYGON(({x} 6672000, {x + 30} 6672000, {x + 30} 6672030, {x} 6672030, {x} 6672000))"))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        warnings = []
        written, failures = self.core.export_data([layer], self.folder, "DWG", warnings=warnings)
        self.assertEqual(failures, [])
        self.assertEqual(formats.dwg_version(written[0]), "AC1015")
        self.assertTrue(any("kaikki 6 aluetta" in warning for warning in warnings), warnings)

    def test_real_line_export_stops_with_details(self):
        layer = QgsVectorLayer("LineString?crs=EPSG:3067", "viivat", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(385000 6672000, 385030 6672030)"))
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        self.project.addMapLayer(layer)
        with self.assertRaisesRegex(RuntimeError, r"viivat 0/1"):
            self.core.export_data([layer], self.folder, "DWG")


class CadExportTests(QgisTestCase):
    def test_combined_dxf_reprojects_layers_to_one_crs(self):
        metric = self.point_layer("EPSG:3067", [(385000, 6672000)], "metrinen")
        degrees = self.point_layer("EPSG:4326", [(24.93, 60.17)], "asteet")
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:3067"))

        written, failures = self.core.export_data([metric, degrees], self.folder, "DXF", combined=True)

        self.assertEqual(failures, [])
        check = QgsVectorLayer(written[0], "tarkistus", "ogr")
        extent = check.extent()
        self.assertGreater(extent.xMinimum(), 300000)
        self.assertGreater(extent.yMinimum(), 6600000)

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

    def libredwg_stand_ins(self, dwg_bytes=None, drop=()):
        """dxf2dwg writes the DXF behind a DWG header (without ``drop`` entities); dwg2dxf strips it.

        dwgrewrite copies the file and leaves a marker, so the test sees that it ran.
        """
        writer = write_script(self.folder, "dxf2dwg", f"""
            import sys
            from pathlib import Path
            target, source = sys.argv[sys.argv.index("-o") + 1], sys.argv[-1]
            body = {dwg_bytes!r}
            if body is None:
                lines = Path(source).read_text(encoding="utf-8", errors="replace").splitlines()
                kept, skip, in_entities = [], False, False
                for code, value in zip(lines[::2], lines[1::2]):
                    if code.strip() == "2" and value.strip() == "ENTITIES":
                        in_entities = True
                    if code.strip() == "0":
                        skip = in_entities and value.strip() in {tuple(drop)!r}
                        if value.strip() == "ENDSEC":
                            in_entities = False
                    if not skip:
                        kept += [code, value]
                body = b"AC1015" + "\\n".join(kept).encode("utf-8")
            Path(target).write_bytes(body)
        """)
        rewriter = write_script(self.folder, "dwgrewrite", """
            import sys
            from pathlib import Path
            source, target = sys.argv[-2], sys.argv[-1]
            Path(target).write_bytes(Path(source).read_bytes())
            Path(target + ".rewritten").write_text("ok")
        """)
        reader = write_script(self.folder, "dwg2dxf", """
            import sys
            from pathlib import Path
            target, source = sys.argv[sys.argv.index("-o") + 1], sys.argv[-1]
            Path(target).write_bytes(Path(source).read_bytes()[6:])
        """)
        return {"dxf2dwg": str(writer), "dwgrewrite": str(rewriter), "dwg2dxf": str(reader)}

    def polygon_layer(self, count=3, name="alueet"):
        layer = QgsVectorLayer("Polygon?crs=EPSG:3067&field=nimi:string", name, "memory")
        features = []
        for index in range(count):
            feature = QgsFeature(layer.fields())
            x = 385000 + index * 50
            feature.setGeometry(QgsGeometry.fromWkt(
                f"POLYGON(({x} 6672000, {x + 30} 6672000, {x + 30} 6672030, {x} 6672000))"))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        return layer

    def test_dwg_export_uses_libredwg_and_checks_the_result(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385010, 6672010)])
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=self.libredwg_stand_ins().get):
            written, failures = self.core.export_data([layer], self.folder / "dwg", "DWG")
        self.assertEqual(failures, [])
        self.assertEqual(Path(written[0]).name, "pisteet.dwg")
        self.assertEqual(formats.dwg_version(written[0]), "AC1015")
        # ArcGIS Pro kaatui suoraan dxf2dwg:n tuloksiin: tulos kirjoitetaan uudelleen.
        self.assertTrue(Path(written[0] + ".rewritten").exists())
        # LibreDWG hylkää QGISin MTEXT-kohteet, joten DWG:n pohjana on TEXT-DXF.
        self.assertNotIn(b"\nMTEXT", Path(written[0]).read_bytes().replace(b"\r", b""))

    def test_areas_without_outlines_are_accepted_with_a_warning(self):
        layer = self.polygon_layer(3)
        warnings = []
        tools = self.libredwg_stand_ins(drop=("LWPOLYLINE",))
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=tools.get):
            written, failures = self.core.export_data([layer], self.folder / "dwg", "DWG", warnings=warnings)
        self.assertEqual(failures, [])
        self.assertTrue(Path(written[0]).is_file())
        self.assertEqual(len(warnings), 1)
        self.assertIn("reunaviivat puuttuvat (3 kpl)", warnings[0])
        self.assertIn("kaikki 3 aluetta", warnings[0])

    def test_lost_lines_that_are_not_outlines_stop_the_export(self):
        layer = QgsVectorLayer("LineString?crs=EPSG:3067", "viivat", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(385000 6672000, 385030 6672030)"))
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        self.project.addMapLayer(layer)
        tools = self.libredwg_stand_ins(drop=("LWPOLYLINE", "POLYLINE"))
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=tools.get):
            with self.assertRaisesRegex(RuntimeError, r"viivat 0/1"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")
        self.assertEqual(list((self.folder / "dwg").glob("*.dwg")), [])

    def test_lost_fills_stop_the_export_even_if_outlines_remain(self):
        layer = self.polygon_layer(2)
        tools = self.libredwg_stand_ins(drop=("HATCH",))
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=tools.get):
            with self.assertRaisesRegex(RuntimeError, r"alueet 0/2"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")

    def test_broken_converter_output_is_rejected(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385010, 6672010)])
        tools = self.libredwg_stand_ins(dwg_bytes=b"not a dwg")
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=tools.get):
            with self.assertRaisesRegex(RuntimeError, "kelvollista DWG"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")

    def test_libredwg_output_that_loses_entities_is_rejected(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000), (385010, 6672010)])
        writer = write_script(self.folder, "dxf2dwg", """
            import sys
            from pathlib import Path
            Path(sys.argv[sys.argv.index("-o") + 1]).write_bytes(b"AC1015" + b"\\0" * 1000)
        """)
        empty_dxf = self.folder / "tyhja.dxf"
        empty_dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        reader = write_script(self.folder, "dwg2dxf", f"""
            import shutil, sys
            shutil.copy({str(empty_dxf)!r}, sys.argv[sys.argv.index("-o") + 1])
        """)
        tools = {"dxf2dwg": str(writer), "dwg2dxf": str(reader)}
        with mock.patch.object(formats_module(), "find_libredwg_tool", side_effect=tools.get):
            with self.assertRaisesRegex(RuntimeError, r"pisteet 0/\d+"):
                self.core.export_data([layer], self.folder / "dwg", "DWG")
        self.assertEqual(list((self.folder / "dwg").glob("*.dwg")), [])

    def test_dwg_export_without_converter_explains_what_to_install(self):
        layer = self.point_layer("EPSG:3067", [(385000, 6672000)])
        with self.assertRaisesRegex(RuntimeError, "LibreDWG"):
            self.core.export_data([layer], self.folder, "DWG")

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

        self.assertIn(("insertAddLayerAction", "Lisää DWG/DXF-taso (Muuntaja)…"), calls)
        self.assertIn("Vie tasot DWG/DXF-muotoon (Muuntaja)…", [action.text() for action in menu.actions()])
        handler = next(call[1] for call in calls if call[0] == "register")
        with mock.patch.object(plugin, "import_cad_files") as imported:
            self.assertFalse(handler.handleFileDrop("/data/tiet.shp"))
            self.assertTrue(handler.handleFileDrop("/data/piirustus.DWG"))
            imported.assert_called_once_with(["/data/piirustus.DWG"])

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
            ask.assert_called_once()
            layers = list(QgsProject.instance().mapLayers().values())
            self.assertTrue(layers and all(layer.crs() == chosen for layer in layers))
            with mock.patch.object(plugin, "_ask_crs", return_value=None):
                plugin.import_cad_files([str(source)])
            QgsProject.instance().clear()

    def test_export_warnings_are_shown_in_the_result(self):
        from muuntaja_qgis import plugin as plugin_module
        QgsProject.instance().clear()
        layer = QgsVectorLayer("Polygon?crs=EPSG:3067", "alueet", "memory")
        QgsProject.instance().addMapLayer(layer)
        dialog = plugin_module.MuuntajaDialog()
        dialog.refresh_layers()
        dialog.layers.item(0).setCheckState(plugin_module.Qt.Checked)
        dialog.format.setCurrentText("DWG")
        dialog.export_folder.setText(tempfile.gettempdir())

        def export(layers, folder, format_name, combined, progress, scale, warnings):
            warnings.append("alueet.dwg: alueiden reunaviivat puuttuvat (6 kpl)")
            return [str(Path(folder) / "alueet.dwg")], []

        with mock.patch.object(plugin_module, "export_data", side_effect=export), \
                mock.patch.object(plugin_module.QMessageBox, "information") as shown:
            dialog._run_export()
        self.assertIn("reunaviivat puuttuvat", shown.call_args[0][2])
        dialog.close()
        QgsProject.instance().clear()

    def test_export_dialog_lists_dxf_and_dwg(self):
        from muuntaja_qgis.plugin import MuuntajaDialog
        dialog = MuuntajaDialog()
        formats_in_dialog = [dialog.format.itemText(i) for i in range(dialog.format.count())]
        self.assertEqual(formats_in_dialog[-2:], ["DXF", "DWG"])
        dialog.format.setCurrentText("DXF")
        self.assertTrue(dialog.combined.isEnabled())
        self.assertIn("symbologia", dialog.dwg_hint.text())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
