"""Offline regression tests. Run: python SharedHelp/test_shared_help.py"""
from pathlib import Path
import base64
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import tempfile
import unittest
import itertools
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("shared_help_under_test", ROOT / "__init__.py")
help_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(help_module)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.images = []
        self.anchors = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs)
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])


class GuideTests(unittest.TestCase):
    def fixture(self, name, revision, text):
        path = self.temp / name
        path.mkdir()
        data = text.encode("utf-8")
        (path / "index.html").write_bytes(data)
        (path / "manifest.json").write_text(json.dumps({"schema": 1, "revision": revision,
            "sha256": hashlib.sha256(data).hexdigest()}), encoding="utf-8")
        return path
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.temp = Path(self.context.name)
    def test_newest_revision_wins_in_both_registration_orders(self):
        old = self.fixture("old", 9, "vanha")
        new = self.fixture("new", 10, "uusi")
        for paths in ([old, new], [new, old]):
            self.assertEqual(help_module.newest_guide(paths), new / "index.html")
    def test_broken_newer_copy_falls_back_to_valid_older_copy(self):
        old = self.fixture("old", 9, "ehjä")
        broken = self.fixture("broken", 10, "rikki")
        (broken / "index.html").write_text("muuttunut", encoding="utf-8")
        self.assertEqual(help_module.newest_guide([broken, old]), old / "index.html")
    def test_removed_copy_is_ignored(self):
        valid = self.fixture("valid", 1, "sisältö")
        self.assertEqual(help_module.newest_guide([self.temp / "missing", valid]), valid / "index.html")
    def test_no_valid_copy_reports_error(self):
        with self.assertRaisesRegex(ValueError, "Ehjää"):
            help_module.newest_guide([self.temp / "missing"])
    def test_manual_is_complete_and_self_contained(self):
        self.assertEqual(help_module.guide_info(ROOT)[2], ROOT / "index.html")
        page = Page()
        text = (ROOT / "index.html").read_text(encoding="utf-8")
        page.feed(text)
        self.assertEqual(len(page.ids), len(set(page.ids)))
        self.assertTrue(set(page.anchors) <= set(page.ids))
        self.assertTrue({"suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuus"} <= set(page.ids))
        self.assertGreaterEqual(len(page.images), 12)
        for image in page.images:
            self.assertTrue(image.get("alt"))
            self.assertTrue(image["src"].startswith("data:image/png;base64,"))
            self.assertTrue(base64.b64decode(image["src"].split(",", 1)[1]).startswith(b"\x89PNG"))
        self.assertNotIn("{{image:", text)
        self.assertNotIn('<script src=', text)
    def test_all_qgis_mirrors_match(self):
        for metadata in (ROOT.parent / "qgis_plugin").glob("*/metadata.txt"):
            for filename in ("__init__.py", "index.html", "manifest.json", "Icons/help.svg"):
                self.assertEqual((ROOT / filename).read_bytes(),
                                 (metadata.parent / "shared_help" / filename).read_bytes(), str(metadata))
    def test_daml_has_one_ordered_toolbar_for_every_installed_subset(self):
        ns = {"d": "http://schemas.esri.com/DADF/Registry"}
        root = ET.parse(ROOT.parent / "Config.daml").getroot()
        groups = root.findall("d:modules/d:insertModule/d:groups/d:group", ns)
        conditions = {e.attrib["id"]: e for e in root.findall("d:conditions/d:insertCondition", ns)}
        keys = ("suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat")
        owner = next(iter(conditions)).split("_SharedHelp_")[0]
        buttons = {b.attrib["id"]: b for b in root.findall("d:modules/d:insertModule/d:controls/d:button", ns)}
        def applies(element, active):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "state":
                return element.attrib["id"] in active
            return all(applies(child, active) for child in element)
        for size in range(1, 5):
            for selected in itertools.combinations(keys, size):
                active = {"PaikkatietoOhje_Owner_" + owner, *("PaikkatietoOhje_Tool_" + k for k in selected)}
                visible = [g for g in groups if g.attrib.get("appearsOnAddInTab") == "true"
                           and applies(conditions[g.attrib["condition"]], active)]
                captions = [buttons[g.find("d:button", ns).attrib["refID"]].attrib["caption"] for g in visible]
                expected = [dict(zip(keys, ("Suomenväylät.fi", "Muuntaja", "Liikenneselvitys", "Saavutettavuuskartat")))[key] for key in selected] + ["Avaa ohje"]
                self.assertEqual(captions, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
