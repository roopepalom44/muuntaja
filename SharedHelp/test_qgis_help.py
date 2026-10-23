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
from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction, QMainWindow, QToolBar

APP = QgsApplication.instance() or QgsApplication([], False)
ROOT = Path(__file__).resolve().parent
KEYS = ("suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat")


class Iface:
    def __init__(self):
        self.window = QMainWindow()
        self.toolbar = QToolBar(self.window)
        self.menu = self.window.menuBar().addMenu("Plugins")
    def mainWindow(self):
        return self.window
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
            modules = {}
            for key in KEYS:
                path = Path(tmp) / key
                shutil.copytree(ROOT, path, ignore=shutil.ignore_patterns("__pycache__", "Images"))
                spec = importlib.util.spec_from_file_location("help_" + key, path / "__init__.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules[key] = module
            for order in itertools.permutations(KEYS):
                iface = Iface()
                other = QAction("Unrelated", iface.window)
                iface.addToolBarIcon(other)
                actions = {key: QAction(key, iface.window) for key in KEYS}
                for key in order:
                    iface.addToolBarIcon(actions[key])
                    modules[key].register(iface, key, actions[key])
                    APP.processEvents()
                    help_actions = [a for a in iface.toolbar.actions() if a.text() == "Avaa ohje"]
                    self.assertEqual(len(help_actions), 1)
                    self.assertIs(iface.toolbar.actions()[-1], help_actions[0])
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
                iface.addToolBarIcon(actions[first])
                modules[first].register(iface, first, actions[first])
                APP.processEvents()
                for key in reversed(order):
                    modules[key].unregister(iface, key)
                    iface.removeToolBarIcon(actions[key])
                    APP.processEvents()
                self.assertEqual([a.text() for a in iface.toolbar.actions()], ["Unrelated", "Another"])
                self.assertFalse(hasattr(iface.window, "_paikkatieto_shared_help_v1"))
                iface.window.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    os._exit(0 if result.wasSuccessful() else 1)
