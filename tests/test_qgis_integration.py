"""Run with QGIS Python: python -m unittest discover -s tests -p test_qgis_integration.py."""

import gc
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from osgeo import gdal, ogr, osr
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsVectorLayer,
    )
    from qgis.PyQt.QtCore import QVariant
except ImportError:
    QgsApplication = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(QgsApplication is not None, "Requires a real QGIS runtime")
class QgisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance()
        if cls.app is None:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()
        gdal.UseExceptions()
        sys.path.insert(0, str(ROOT / "qgis_plugin"))
        from muuntaja_qgis import core, tasks

        cls.core, cls.tasks = core, tasks

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="muuntaja_audit_")
        self.root = Path(self.temp.name)
        self.layers = []
        QgsProject.instance().removeAllMapLayers()
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:3067"))

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()
        for layer in self.layers:
            self.core._dispose(layer)
        self.layers.clear()
        gc.collect()
        self.temp.cleanup()  # Windows verifies that providers released their locks.

    def points(self, name="points", crs="EPSG:3067", coordinates=((385000, 6670000),)):
        layer = QgsVectorLayer(f"Point?crs={crs}", name, "memory")
        self.layers.append(layer)
        features = []
        for x, y in coordinates:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        layer.updateExtents()
        return layer

    def source_file(self, name="50v flood.gpkg", layer=None):
        layer = layer or self.points()
        path = self.root / name
        self.core._write_vector(layer, path, "GPKG", "points")
        return path

    def raster(self, name, x=385000, located=True):
        path = self.root / name
        dataset = gdal.GetDriverByName("GTiff").Create(
            str(path), 2, 2, 1, gdal.GDT_Byte
        )
        if located:
            dataset.SetGeoTransform([x, 4, 0, 6670000, 0, -4])
            sr = osr.SpatialReference()
            sr.ImportFromEPSG(3067)
            dataset.SetProjection(sr.ExportToWkt())
        dataset.GetRasterBand(1).Fill(1)
        dataset = None
        return path

    def test_numeric_filegdb_and_source_lock_disposal(self):
        path = self.source_file()
        output = self.root / "test.gdb"
        success, failures = self.core.import_data([path], output)
        self.assertEqual(success, [str(path)])
        self.assertFalse(failures)
        result = next(iter(QgsProject.instance().mapLayers().values()))
        self.assertTrue(result.name().startswith("_50v"))
        renamed = path.with_name("renamed.gpkg")
        path.rename(renamed)
        renamed.unlink()

    def test_mixed_crs_dxf_coordinates_are_transformed(self):
        metric = self.points("metric")
        degrees = self.points("degrees", "EPSG:4326", ((24.928567, 60.15072),))
        outputs, failures = self.core.export_data(
            [metric, degrees], self.root, "DXF", combined=True, target_crs=metric.crs()
        )
        self.assertFalse(failures)
        path = Path(outputs[0])
        dataset = ogr.Open(str(path))
        coordinates = [
            (
                feature.GetGeometryRef().Centroid().GetX(),
                feature.GetGeometryRef().Centroid().GetY(),
            )
            for feature in dataset.GetLayer(0)
        ]
        dataset = None
        self.assertGreaterEqual(len(coordinates), 2)
        self.assertTrue(
            all(abs(x - 385000) < 2 and abs(y - 6670000) < 2 for x, y in coordinates),
            coordinates,
        )

    def test_raster_group_keeps_valid_tiles_and_reports_only_bad_tile(self):
        first, second = self.raster("1.tif"), self.raster("2.tif", 385008)
        bad = self.raster("unlocated.tif", located=False)
        success, failures = self.core.import_data(
            [first, bad, second], self.root / "out"
        )
        self.assertEqual(set(success), {str(first), str(second)})
        self.assertEqual([path for path, _error in failures], [str(bad)])
        result = next(iter(QgsProject.instance().mapLayers().values()))
        self.assertEqual(
            result.customProperty("muuntaja/source_paths"), [str(first), str(second)]
        )

    def test_repeated_vrt_import_replaces_without_overwriting_locked_vrt(self):
        first, second = self.raster("1.tif"), self.raster("2.tif", 385008)
        self.core.import_data([first], self.root / "out")
        original = next(iter(QgsProject.instance().mapLayers().values())).source()
        held = gdal.Open(original)
        self.assertIsNotNone(held)
        self.core.import_data([second], self.root / "out")
        layers = list(QgsProject.instance().mapLayers().values())
        self.assertEqual(len(layers), 1)
        self.assertNotEqual(layers[0].source(), original)
        self.assertEqual(len(layers[0].customProperty("muuntaja/source_paths")), 2)
        held = None

    def test_partial_batch_and_corrupt_formats(self):
        good = [self.source_file(f"good{index}.gpkg") for index in range(3)]
        bad = []
        for extension, data in (
            ("geojson", '{"features":'),
            ("gpx", "<gpx><trk>"),
            ("kmz", "not a zip"),
            ("dxf", "broken cad"),
        ):
            path = self.root / f"broken.{extension}"
            path.write_text(data)
            bad.append(path)
        success, failures = self.core.import_data(good + bad, self.root / "out.gpkg")
        self.assertEqual(set(success), {str(path) for path in good})
        self.assertEqual(
            {path for path, _error in failures}, {str(path) for path in bad}
        )
        for path in good + bad:
            path.unlink()

    def test_missing_shapefile_sidecars_and_missing_crs(self):
        path = self.root / "roads.shp"
        self.core._write_vector(self.points(), path, "ESRI Shapefile")
        path.with_suffix(".shx").unlink()
        with self.assertRaisesRegex(ValueError, "shx"):
            self.core._open_vector_layers(path)
        self.core._write_vector(self.points(), path, "ESRI Shapefile")
        path.with_suffix(".dbf").unlink()
        with self.assertRaisesRegex(ValueError, "dbf"):
            self.core._open_vector_layers(path)

    def test_wide_shapefile_keeps_columns_unique_names_and_utf8_values(self):
        layer = self.points()
        layer.dataProvider().addAttributes(
            [QgsField(f"lämpötila_{i}", QVariant.String, len=254) for i in range(20)]
        )
        layer.updateFields()
        for feature in layer.getFeatures():
            layer.dataProvider().changeAttributeValues(
                {feature.id(): {i: "ä" * 200 for i in range(20)}}
            )
        path = self.root / "wide.shp"
        self.core._write_vector(layer, path, "ESRI Shapefile")
        output = QgsVectorLayer(str(path), "output", "ogr")
        try:
            self.assertTrue(output.isValid())
            self.assertEqual(len(output.fields()), 20)
            self.assertEqual(len(set(output.fields().names())), 20)
            self.assertTrue(all(len(field.name()) <= 10 for field in output.fields()))
            self.assertTrue(
                all(
                    len(value.encode("utf-8")) <= 80
                    for value in next(output.getFeatures()).attributes()
                )
            )
        finally:
            self.core._dispose(output)

    def test_cad_origin_entities_do_not_dominate_crs_vote(self):
        coordinates = [(385000 + index, 6670000) for index in range(50)] + [(0, 0)] * 20
        layer = self.points(coordinates=coordinates)
        self.assertEqual(
            self.core.inferred_crs(layer, "drawing.dxf").authid(), "EPSG:3067"
        )

    def test_cad_cleanup_is_case_insensitive(self):
        source = self.points(
            coordinates=((385000, 6670000), (385001, 6670000), (385002, 6670000))
        )
        source.dataProvider().addAttributes([QgsField("Layer", QVariant.String)])
        source.updateFields()
        for feature, name in zip(source.getFeatures(), ("defpoints", "0", "roads")):
            source.dataProvider().changeAttributeValues({feature.id(): {0: name}})
        path = self.root / "drawing.dxf"
        self.core._write_vector(source, path, "DXF")
        self.core.import_data([path], self.root / "out", clean_cad=True)
        output = list(QgsProject.instance().mapLayers().values())
        self.assertEqual(sum(layer.featureCount() for layer in output), 1)

    def test_dfsu_transactions_vector_filter_nan_and_numeric_name(self):
        import numpy as np

        count = 10001
        coordinates = np.column_stack(
            (np.arange(count) + 385000, np.full(count, 6670000))
        )
        values = np.arange(count, dtype=float)
        values[2] = np.nan

        class Dataset:
            geometry = types.SimpleNamespace(
                element_coordinates=coordinates, projection_string="EPSG:3067"
            )
            items = [types.SimpleNamespace(name="Depth")]

            def __getitem__(self, name):
                return types.SimpleNamespace(to_numpy=lambda: values)

        mikeio = types.SimpleNamespace(read=lambda *args, **kwargs: Dataset())
        with patch.dict(sys.modules, mikeio=mikeio):
            self.core._import_dfsu(
                self.root / "50v.dfsu",
                self.root / "mesh.gdb",
                True,
                None,
                None,
                "depth",
                ">=",
                "5000",
                existing_names=set(),
            )
        result = next(iter(QgsProject.instance().mapLayers().values()))
        self.assertEqual(result.featureCount(), 5001)
        self.assertTrue(result.name().startswith("_50v"))

    def test_background_import_publishes_on_main_thread(self):
        path = self.source_file()
        task = self.tasks.ConversionTask(
            "Tuonti",
            dict(paths=[path], destination=self.root / "out.gpkg"),
            QgsProject.instance(),
        )
        completed = []
        task.completed.connect(completed.append)
        QgsApplication.taskManager().addTask(task)
        deadline = time.monotonic() + 30
        while not completed and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(completed, "Background task timed out")
        self.assertNotIn("error", completed[0])
        self.assertFalse(QgsProject.instance().mapLayers())
        self.tasks.publish_layers(
            QgsProject.instance(), completed[0]["specs"], completed[0]["removed"]
        )
        self.assertEqual(len(QgsProject.instance().mapLayers()), 1)

    def test_background_export_preserves_edited_memory_features(self):
        layer = self.points()
        layer.startEditing()
        feature = next(layer.getFeatures())
        layer.changeGeometry(
            feature.id(), QgsGeometry.fromPointXY(QgsPointXY(385100, 6670100))
        )
        task = self.tasks.ConversionTask(
            "Vienti",
            dict(folder=self.root / "out", format_name="GPKG"),
            QgsProject.instance(),
            [layer],
        )
        self.assertTrue(task.run(), task.result)
        output = QgsVectorLayer(task.result["successes"][0], "export", "ogr")
        try:
            point = next(output.getFeatures()).geometry().asPoint()
            self.assertEqual((point.x(), point.y()), (385100, 6670100))
        finally:
            self.core._dispose(output)
            layer.rollBack()

    def test_cancellation_disposes_task_layers_and_temp_files(self):
        task = self.tasks.ConversionTask(
            "Vienti",
            dict(folder=self.root / "out", format_name="GPKG"),
            QgsProject.instance(),
            [self.points()],
        )
        task.cancel()
        self.assertFalse(task.run())
        self.assertTrue(task.result["canceled"])
        self.assertFalse((self.root / "out").exists())

    def test_fifty_thousand_feature_export_throughput(self):
        layer = self.points(
            coordinates=((385000 + index, 6670000) for index in range(50000))
        )
        started = time.monotonic()
        success, failures = self.core.export_data([layer], self.root / "large", "GPKG")
        elapsed = time.monotonic() - started
        self.assertFalse(failures)
        output = QgsVectorLayer(success[0], "large", "ogr")
        try:
            self.assertEqual(output.featureCount(), 50000)
        finally:
            self.core._dispose(output)
        print(f"50,000 feature export: {elapsed:.2f}s", flush=True)
        self.assertLess(elapsed, 15)

    def test_thousand_tile_mosaic_uses_bounded_raster_handles(self):
        paths = [
            self.raster(f"tile_{index}.tif", 385000 + index * 8)
            for index in range(1000)
        ]
        started = time.monotonic()
        success, failures = self.core.import_data(paths, self.root / "mosaic")
        self.assertFalse(failures)
        self.assertEqual(len(success), 1000)
        self.assertEqual(len(QgsProject.instance().mapLayers()), 1)
        print(f"1,000 tile mosaic: {time.monotonic() - started:.2f}s", flush=True)

    @unittest.skipUnless(
        os.environ.get("MUUNTAJA_DFSU_STRESS_FILE"),
        "Set MUUNTAJA_DFSU_STRESS_FILE for the real mesh benchmark",
    )
    def test_real_dfsu_mesh_memory_and_disposal(self):
        import threading

        if os.environ.get("MUUNTAJA_AUDIT_DEPENDENCIES"):
            sys.path.insert(0, os.environ["MUUNTAJA_AUDIT_DEPENDENCIES"])
        import mikeio
        import psutil

        path = Path(os.environ["MUUNTAJA_DFSU_STRESS_FILE"])
        mesh = mikeio.open(str(path))
        expected = mesh.geometry.n_elements
        del mesh
        process = psutil.Process()
        baseline, samples = process.memory_info().rss, []
        stop = threading.Event()

        def sample_memory():
            while not stop.wait(0.05):
                samples.append(process.memory_info().rss)

        monitor = threading.Thread(target=sample_memory, daemon=True)
        monitor.start()
        started = time.monotonic()
        try:
            self.core._import_dfsu(
                path,
                self.root / "real_mesh.gpkg",
                True,
                None,
                None,
                "",
                "=",
                "",
                existing_names=set(),
            )
            result = next(iter(QgsProject.instance().mapLayers().values()))
            self.assertEqual(result.featureCount(), expected)
        finally:
            stop.set()
            monitor.join()
        peak = max(samples + [baseline]) - baseline
        print(
            f"Real DFSU: {path.stat().st_size / 1e6:.1f} MB, {expected:,} features, "
            f"{time.monotonic() - started:.2f}s, RSS growth {peak / 1e6:.1f} MB",
            flush=True,
        )
        self.assertLess(peak, 2048 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main(verbosity=2)
