"""Real Qt lifecycle test, including independently imported plugin copies.

Run with QGIS Python: python-qgis-ltr.bat SharedHelp/test_qgis_help.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import importlib.util
import itertools
import tempfile
import unittest
import shutil
import gc
import weakref
from unittest.mock import patch
from qgis.core import QgsApplication
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction, QMainWindow, QToolBar, QWidget

APP = QgsApplication.instance() or QgsApplication([], False)
ROOT = Path(__file__).resolve().parent
KEYS = ("suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat")


class Iface:
    def __init__(self):
        self.window = QMainWindow()
        self.toolbar = QToolBar(self.window)
        self.menu = self.window.menuBar().addMenu("Plugins")
    def mainWindow(self):
        # Real interface calls may produce different Python wrappers around
        # one C++ window. The old wrapper-attribute singleton fails this test.
        return sip.cast(self.window, QWidget)
    def pluginToolBar(self):
        return self.toolbar
    def addPluginToMenu(self, name, action):
        self.menu.addAction(action)
    def removePluginMenu(self, name, action):
        self.menu.removeAction(action)
    def addToolBarIcon(self, action):
        self.toolbar.addAction(action)
    def removeToolBarIcon(self, action):
        self.toolbar.removeAction(action)


class Lifecycle(unittest.TestCase):
    def test_all_load_orders_unload_owner_reload_and_unrelated_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for key in KEYS:
                path = Path(tmp) / key
                paths[key] = path
                for filename in ("__init__.py", "index.html", "manifest.json", "Icons/help.svg"):
                    target = path / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / filename, target)
            def load_module(key):
                spec = importlib.util.spec_from_file_location("help_" + key, paths[key] / "__init__.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            modules = {key: load_module(key) for key in KEYS}
            for order in itertools.permutations(KEYS):
                iface = Iface()
                first_wrapper, second_wrapper = iface.mainWindow(), iface.mainWindow()
                self.assertIsNot(first_wrapper, second_wrapper)
                self.assertEqual(sip.unwrapinstance(first_wrapper), sip.unwrapinstance(second_wrapper))
                other = QAction("Unrelated", iface.window)
                iface.addToolBarIcon(other)
                actions = {key: QAction(key, iface.window) for key in KEYS}
                for key in order:
                    iface.addToolBarIcon(actions[key])
                    modules[key].register(iface, key, actions[key])
                    gc.collect()
                    APP.processEvents()
                    help_actions = [a for a in iface.toolbar.actions() if a.text() == "Avaa ohje"]
                    self.assertEqual(len(help_actions), 1)
                    self.assertIs(iface.toolbar.actions()[-1], help_actions[0])
                    # A visible QAction alone is insufficient: verify its slot
                    # survives GC and opens the complete, installed manual.
                    with patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
                        help_actions[0].trigger()
                        APP.processEvents()
                        opened.assert_called_once()
                        actual = Path(opened.call_args[0][0].toLocalFile())
                        self.assertEqual(actual.read_bytes(), (ROOT / "index.html").read_bytes())
                self.assertEqual([a.text() for a in iface.toolbar.actions()], ["Unrelated", *KEYS, "Avaa ohje"])
                # Toolbar additions by unrelated plugins must leave help at the right.
                another = QAction("Another", iface.window)
                iface.addToolBarIcon(another)
                APP.processEvents()
                self.assertEqual(iface.toolbar.actions()[-1].text(), "Avaa ohje")
                # The plugin whose implementation created the manager can be disabled.
                first = order[0]
                modules[first].unregister(iface, first)
                iface.removeToolBarIcon(actions[first])
                APP.processEvents()
                self.assertEqual(sum(a.text() == "Avaa ohje" for a in iface.toolbar.actions()), 1)
                # Remove the implementation module too, as QGIS does on unload.
                first_module = weakref.ref(modules[first])
                modules.pop(first)
                gc.collect()
                self.assertIsNone(first_module())
                with patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
                    next(a for a in iface.toolbar.actions() if a.text() == "Avaa ohje").trigger()
                    APP.processEvents()
                    opened.assert_called_once()
                iface.addToolBarIcon(actions[first])
                modules[first] = load_module(first)
                modules[first].register(iface, first, actions[first])
                APP.processEvents()
                for key in reversed(order):
                    modules[key].unregister(iface, key)
                    iface.removeToolBarIcon(actions[key])
                    APP.processEvents()
                self.assertEqual([a.text() for a in iface.toolbar.actions()], ["Unrelated", "Another"])
                self.assertFalse(modules[first]._shared_registry().managers)
                iface.window.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    os._exit(0 if result.wasSuccessful() else 1)
