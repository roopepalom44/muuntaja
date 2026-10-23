"""Shared offline manual. Keep this directory identical in all four repositories."""
from pathlib import Path
import hashlib
import json


def guide_info(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    page = directory / "index.html"
    if manifest.get("schema") != 1 or not isinstance(manifest.get("revision"), int):
        raise ValueError("Ohjeen versiotieto on virheellinen.")
    if hashlib.sha256(page.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Ohjetiedoston tarkistussumma ei täsmää.")
    return manifest["revision"], manifest["sha256"], page


def newest_guide(directories):
    valid = []
    for directory in directories:
        try:
            valid.append(guide_info(directory))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not valid:
        raise ValueError("Ehjää käyttöohjetta ei löytynyt. Asenna lisäosa uudelleen.")
    return max(valid, key=lambda item: (item[0], item[1], str(item[2])))[2]


def register(iface, key, action):
    """One manager per main window, even when imported from different plugins."""
    from qgis.PyQt.QtCore import QEvent, QObject, QTimer, QUrl
    from qgis.PyQt.QtGui import QDesktopServices, QIcon
    from qgis.PyQt.QtWidgets import QAction, QMessageBox

    window = iface.mainWindow()
    manager = getattr(window, "_paikkatieto_shared_help_v1", None)
    if manager is None:
        class Manager(QObject):
            def __init__(self):
                super().__init__(window)
                self.entries = {}
                self.pending = False
                self.closed = False
                self.action = QAction(QIcon(str(Path(__file__).parent / "Icons" / "help.svg")), "Avaa ohje", window)
                self.action.setObjectName("Paikkatietotyokalut_AvaaOhje")
                self.action.setToolTip("Avaa neljän paikkatietotyökalun yhteinen käyttöohje")
                self.action.triggered.connect(self.open)
                iface.addPluginToMenu("Paikkatietotyökalut", self.action)
                iface.addToolBarIcon(self.action)
                self.toolbar = iface.pluginToolBar()
                self.toolbar.installEventFilter(self)

            def eventFilter(self, watched, event):
                if event.type() == QEvent.ActionAdded and not self.pending:
                    self.pending = True
                    QTimer.singleShot(0, self.reorder)
                return False

            def reorder(self):
                if self.closed:
                    return
                # Reinsert only our actions, preserving everyone else's relative order.
                self.toolbar.removeEventFilter(self)
                order = ("suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat")
                for name in order:
                    if name in self.entries:
                        item = self.entries[name][0]
                        self.toolbar.removeAction(item)
                        self.toolbar.addAction(item)
                self.toolbar.removeAction(self.action)
                self.toolbar.addAction(self.action)
                self.pending = False
                self.toolbar.installEventFilter(self)

            def open(self):
                try:
                    path = newest_guide(entry[1] for entry in self.entries.values())
                    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                        raise ValueError("Selain ei avautunut. Avaa ohje tästä tiedostosta:\n" + str(path))
                except (OSError, ValueError) as error:
                    QMessageBox.warning(window, "Avaa ohje", str(error))

            def close(self):
                self.closed = True
                self.toolbar.removeEventFilter(self)
                iface.removePluginMenu("Paikkatietotyökalut", self.action)
                iface.removeToolBarIcon(self.action)
                self.action.deleteLater()
                self.deleteLater()

        manager = Manager()
        window._paikkatieto_shared_help_v1 = manager
    manager.entries[key] = (action, Path(__file__).parent)
    manager.reorder()


def unregister(iface, key):
    window = iface.mainWindow()
    manager = getattr(window, "_paikkatieto_shared_help_v1", None)
    if manager is None:
        return
    manager.entries.pop(key, None)
    if manager.entries:
        manager.reorder()
    else:
        manager.close()
        delattr(window, "_paikkatieto_shared_help_v1")
