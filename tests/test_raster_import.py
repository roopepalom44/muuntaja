import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


def load_toolbox(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    toolbox_path = Path(__file__).parents[1] / "Toolboxes" / "Muuntaja.pyt"
    loader = importlib.machinery.SourceFileLoader("muuntaja_raster_toolbox", str(toolbox_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


MML_20K = (
    "Maanmittauslaitos_Tiedostopalvelu_REST-20260921T195713180972954",
    "taustakarttasarja_jhs180", "taustakartta_20k", "4m", "etrs89", "png", "R4", "R43",
)
MML_5K = (
    "Maanmittauslaitos_Tiedostopalvelu_REST-20260921T195715441328953",
    "taustakarttasarja_jhs180", "taustakartta_5k", "0_5m", "etrs89", "png", "R4", "R43",
)


def write_tile(folder, name, x=428002.0, y=7193998.0, world=True):
    folder.mkdir(parents=True, exist_ok=True)
    png = folder / (name + ".png")
    png.write_bytes(b"png")
    if world:
        (folder / (name + ".pgw")).write_text(
            f"4.0\n0.0\n0.0\n-4.0\n{x:.2f}\n{y:.2f}\n", encoding="ascii"
        )
    return png


class FakeLayer:
    def __init__(self, name, data_source=None, is_group=False):
        self.name = name
        self.longName = name
        self.dataSource = data_source
        self.isGroupLayer = is_group
        self.children = []

    def supports(self, prop):
        return prop == "DATASOURCE" and self.dataSource is not None

    def listLayers(self):
        return list(self.children)


class FakeMap:
    def __init__(self):
        self.layers = []
        self.created_groups = []

    def listLayers(self):
        out = []
        for layer in self.layers:
            out.append(layer)
            out.extend(layer.children)
        return out

    def createGroupLayer(self, name):
        group = FakeLayer(name, is_group=True)
        self.layers.insert(0, group)
        self.created_groups.append(name)
        return group

    def addDataFromPath(self, path):
        layer = FakeLayer(Path(path).stem, data_source=str(path))
        self.layers.insert(0, layer)
        return layer

    def addLayerToGroup(self, group, layer):
        group.children.append(FakeLayer(layer.name, data_source=layer.dataSource))

    def removeLayer(self, layer):
        self.layers.remove(layer)


class RasterImportTests(unittest.TestCase):
    def setUp(self):
        self.fake_arcpy = types.ModuleType("arcpy")
        self.module = load_toolbox(self.fake_arcpy)
        self.tool = self.module.UniversalImportTool()
        self.logs = []
        self.tool.log = lambda messages, text, level="INFO": self.logs.append((level, text))

    def test_folder_scan_includes_georeferenced_rasters_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tile = write_tile(root.joinpath(*MML_20K), "R4324")
            geotiff = root / "dem" / "L4133.tif"
            geotiff.parent.mkdir()
            geotiff.write_bytes(b"tif")
            screenshot = root / "screenshot.png"
            screenshot.write_bytes(b"png")

            found = [Path(p) for p in self.tool._list_supported_import_files(str(root))]

            self.assertIn(tile, found)
            self.assertIn(geotiff, found)
            self.assertNotIn(screenshot, found)
            # World-tiedosto ei ole oma syötteensä.
            self.assertFalse(any(p.suffix.lower() == ".pgw" for p in found))

    def test_group_name_uses_taustakartta_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tile20 = write_tile(root.joinpath(*MML_20K), "R4324")
            tile5 = write_tile(root.joinpath(*MML_5K), "R4324D")

            self.assertEqual(self.tool._raster_group_name(str(tile20), [str(root)]), "taustakartta_20k")
            self.assertEqual(self.tool._raster_group_name(str(tile5), [str(root)]), "taustakartta_5k")

    def test_group_name_fallback_skips_mml_download_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tile = write_tile(
                root / "Maanmittauslaitos_Tiedostopalvelu_REST-1" / "ortokuva" / "P4" / "P41", "P4131"
            )

            self.assertEqual(self.tool._raster_group_name(str(tile), [str(root)]), "ortokuva")
            # Yksittäin valittu tiedosto ryhmitellään oman kansionsa mukaan.
            self.assertEqual(self.tool._raster_group_name(str(tile), []), "P41")

    def test_same_group_from_separate_downloads_is_merged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = write_tile(root.joinpath(*MML_20K), "R4324")
            other_download = ("Maanmittauslaitos_Tiedostopalvelu_REST-2",) + MML_20K[1:]
            second = write_tile(root.joinpath(*other_download), "R4342")

            groups = self.tool._group_raster_paths([str(first), str(second)], [str(root)])

            self.assertEqual(list(groups), ["taustakartta_20k"])
            self.assertEqual(len(groups["taustakartta_20k"]), 2)

    def test_group_order_puts_most_detailed_scale_last(self):
        names = ["taustakartta_5k", "taustakartta_20k", "taustakartta_100k", "muut"]
        ordered = sorted(names, key=self.tool._raster_group_sort_key)
        self.assertEqual(ordered, ["muut", "taustakartta_100k", "taustakartta_20k", "taustakartta_5k"])

    def test_epsg_is_guessed_from_world_file_then_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tm35 = write_tile(root / "a", "tile")
            gk25 = write_tile(root / "b", "tile", x=25496000.0, y=6672000.0)
            no_world_in_etrs = write_tile(root / "etrs89" / "png", "tile", world=False)
            unknown = write_tile(root / "c", "tile", world=False)

            self.assertEqual(self.tool._guess_raster_epsg(str(tm35)), (3067, "world-tiedosto"))
            self.assertEqual(self.tool._guess_raster_epsg(str(gk25))[0], 3879)
            self.assertEqual(self.tool._guess_raster_epsg(str(no_world_in_etrs)), (3067, "kansiopolku"))
            self.assertEqual(self.tool._guess_raster_epsg(str(unknown)), (None, None))

    def test_import_rasters_groups_layers_defines_crs_and_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tiles20 = [write_tile(root.joinpath(*MML_20K), n) for n in ("R4324", "R4342")]
            tiles5 = [write_tile(root.joinpath(*MML_5K), n) for n in ("R4323D", "R4323F")]
            raster_paths = [str(p) for p in tiles20 + tiles5]

            fake_map = FakeMap()
            defined = []
            self.fake_arcpy.mp = types.SimpleNamespace(
                ArcGISProject=lambda _: types.SimpleNamespace(activeMap=fake_map)
            )
            self.fake_arcpy.Describe = lambda path: types.SimpleNamespace(
                spatialReference=types.SimpleNamespace(name="Unknown")
            )
            self.fake_arcpy.SpatialReference = lambda code: types.SimpleNamespace(
                name=f"EPSG:{code}", factoryCode=code
            )
            self.fake_arcpy.management = types.SimpleNamespace(
                DefineProjection=lambda path, sr: defined.append((path, sr.factoryCode))
            )

            ok, failures = self.tool._import_rasters(raster_paths, [str(root)], None, None)

            self.assertEqual(failures, [])
            self.assertEqual(len(ok), 4)
            self.assertEqual(fake_map.created_groups, ["taustakartta_20k", "taustakartta_5k"])
            # Karttaan jää vain ryhmätasot, 5k ylimpänä.
            self.assertEqual([layer.name for layer in fake_map.layers], ["taustakartta_5k", "taustakartta_20k"])
            by_name = {layer.name: layer for layer in fake_map.layers}
            self.assertEqual(
                sorted(Path(l.dataSource).name for l in by_name["taustakartta_20k"].children),
                ["R4324.png", "R4342.png"],
            )
            self.assertEqual(len(by_name["taustakartta_5k"].children), 2)
            self.assertEqual(sorted(code for _, code in defined), [3067] * 4)

            # Uudelleenajo käyttää samoja ryhmiä eikä tuplaa karttalehtiä.
            ok_again, failures_again = self.tool._import_rasters(raster_paths, [str(root)], None, None)
            self.assertEqual(failures_again, [])
            self.assertEqual(len(ok_again), 4)
            self.assertEqual(fake_map.created_groups, ["taustakartta_20k", "taustakartta_5k"])
            self.assertEqual(len(by_name["taustakartta_20k"].children), 2)

    def test_import_rasters_without_active_map_fails_each_raster(self):
        self.fake_arcpy.mp = types.SimpleNamespace(
            ArcGISProject=lambda _: types.SimpleNamespace(activeMap=None)
        )
        ok, failures = self.tool._import_rasters(["a.tif", "b.tif"], [], None, None)
        self.assertEqual(ok, [])
        self.assertEqual([path for path, _ in failures], ["a.tif", "b.tif"])


if __name__ == "__main__":
    unittest.main()
