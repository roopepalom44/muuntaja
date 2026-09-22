"""Small native Qt interface for the Muuntaja QGIS plugin."""

from pathlib import Path
from qgis.PyQt.QtGui import QIcon

from qgis.PyQt.QtWidgets import (
    QAction, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QProgressDialog, QTabWidget, QVBoxLayout, QWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer

from .core import DRIVERS, OperationCanceled, export_data, import_data


class MuuntajaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Muuntaja — QGIS")
        self.resize(620, 550)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        tabs.addTab(self._import_tab(), "Tuonti")
        tabs.addTab(self._export_tab(), "Vienti")
        self.tabs = tabs
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _import_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Valitse tiedostoja tai kansio. Kansiot käydään läpi alikansioineen."))
        self.inputs = QListWidget()
        layout.addWidget(self.inputs)
        row = QHBoxLayout()
        files = QPushButton("Lisää tiedostoja…")
        files.clicked.connect(self._add_files)
        row.addWidget(files)
        folder = QPushButton("Lisää kansio…")
        folder.clicked.connect(self._add_folder)
        row.addWidget(folder)
        remove = QPushButton("Poista valittu")
        remove.clicked.connect(lambda: [self.inputs.takeItem(self.inputs.row(item)) for item in self.inputs.selectedItems()])
        row.addWidget(remove)
        layout.addLayout(row)
        form = QFormLayout()
        outrow = QHBoxLayout()
        self.import_output = QLineEdit()
        self.import_output.setPlaceholderText("Kohdekansio tai .gpkg-tiedosto")
        outrow.addWidget(self.import_output)
        browse = QPushButton("Selaa…")
        browse.clicked.connect(self._choose_import_folder)
        outrow.addWidget(browse)
        form.addRow("Tallennuspaikka", outrow)
        self.source_crs = QLineEdit()
        self.source_crs.setPlaceholderText("Automaattinen tai EPSG:3067")
        form.addRow("Lähtö-CRS, tarvittaessa", self.source_crs)
        self.target_crs = QLineEdit()
        self.target_crs.setPlaceholderText("Alkuperäinen CRS tai EPSG:3067")
        form.addRow("Kohde-CRS, tarvittaessa", self.target_crs)
        self.clean_cad = QCheckBox("Ohita CADin Defpoints/0-tasot")
        form.addRow(self.clean_cad)
        self.dfsu_column = QLineEdit()
        self.dfsu_column.setPlaceholderText("Tyhjä = ei suodatusta")
        form.addRow("DFSU: suodatinsarake", self.dfsu_column)
        self.dfsu_operator = QComboBox()
        self.dfsu_operator.addItems(["=", "≠", ">", ">=", "<", "<=", "contains", "starts with", "ends with"])
        form.addRow("DFSU: operaattori", self.dfsu_operator)
        self.dfsu_value = QLineEdit()
        form.addRow("DFSU: arvo", self.dfsu_value)
        layout.addLayout(form)
        run = QPushButton("Tuo aineistot")
        run.clicked.connect(self._run_import)
        layout.addWidget(run)
        return page

    def _export_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Valitse projektista vietävät vektoritasot."))
        self.layers = QListWidget()
        layout.addWidget(self.layers)
        refresh = QPushButton("Päivitä tasolista")
        refresh.clicked.connect(self.refresh_layers)
        layout.addWidget(refresh)
        form = QFormLayout()
        row = QHBoxLayout()
        self.export_folder = QLineEdit()
        row.addWidget(self.export_folder)
        browse = QPushButton("Selaa…")
        browse.clicked.connect(self._choose_export_folder)
        row.addWidget(browse)
        form.addRow("Vientikansio", row)
        self.format = QComboBox()
        self.format.addItems(list(DRIVERS))
        form.addRow("Formaatti", self.format)
        self.combined = QCheckBox("Kaikki tasot yhteen tiedostoon (GPKG/DXF)")
        form.addRow(self.combined)
        layout.addLayout(form)
        layout.addWidget(QLabel("DWG-vienti vaatii erillisen DWG-kirjoittimen. DXF-vienti toimii ilman lisäasennuksia."))
        run = QPushButton("Vie tasot")
        run.clicked.connect(self._run_export)
        layout.addWidget(run)
        self.refresh_layers()
        return page

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Valitse tiedostot")
        for path in files:
            if not self.inputs.findItems(path, Qt.MatchExactly):
                self.inputs.addItem(path)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Valitse kansio")
        if path and not self.inputs.findItems(path, Qt.MatchExactly):
            self.inputs.addItem(path)

    def _choose_import_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Valitse tallennuskansio")
        if path:
            self.import_output.setText(path)

    def _choose_export_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Valitse vientikansio")
        if path:
            self.export_folder.setText(path)

    def refresh_layers(self):
        self.layers.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                item = QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.layers.addItem(item)

    @staticmethod
    def _crs(text):
        if not text.strip():
            return None
        crs = QgsCoordinateReferenceSystem(text.strip())
        if not crs.isValid():
            raise ValueError(f"Tuntematon koordinaatisto: {text}")
        return crs

    def _progress(self, index, total, label):
        self.progress.setMaximum(total)
        self.progress.setValue(index - 1)
        self.progress.setLabelText(label)
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()
        if self.progress.wasCanceled():
            raise OperationCanceled("Käyttäjä keskeytti")

    def _run_import(self):
        paths = [self.inputs.item(i).text() for i in range(self.inputs.count())]
        destination = self.import_output.text().strip()
        if not paths or not destination:
            QMessageBox.warning(self, "Muuntaja", "Valitse syötteet ja tallennuspaikka.")
            return
        self.progress = QProgressDialog("Tuodaan…", "Keskeytä", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModal)
        try:
            successes, failures = import_data(paths, destination, self._crs(self.source_crs.text()),
                                               self._crs(self.target_crs.text()), self.clean_cad.isChecked(),
                                               self._progress, self.dfsu_column.text().strip(),
                                               self.dfsu_operator.currentText(), self.dfsu_value.text())
            self._show_result("Tuonti", successes, failures)
        except Exception as exc:
            QMessageBox.critical(self, "Muuntaja", str(exc))
        finally:
            self.progress.close()

    def _run_export(self):
        layers = [QgsProject.instance().mapLayer(self.layers.item(i).data(Qt.UserRole))
                  for i in range(self.layers.count()) if self.layers.item(i).checkState() == Qt.Checked]
        folder = self.export_folder.text().strip()
        if not layers or not folder:
            QMessageBox.warning(self, "Muuntaja", "Valitse tasot ja vientikansio.")
            return
        self.progress = QProgressDialog("Viedään…", "Keskeytä", 0, len(layers), self)
        self.progress.setWindowModality(Qt.WindowModal)
        try:
            successes, failures = export_data(layers, folder, self.format.currentText(),
                                              self.combined.isChecked(), self._progress)
            self._show_result("Vienti", successes, failures)
        except Exception as exc:
            QMessageBox.critical(self, "Muuntaja", str(exc))
        finally:
            self.progress.close()

    def _show_result(self, operation, successes, failures):
        details = "\n".join(f"{path}: {error}" for path, error in failures)
        message = f"{operation}: {len(successes)} onnistui, {len(failures)} epäonnistui."
        if details:
            message += "\n\n" + details
        QMessageBox.information(self, "Muuntaja", message)


class MuuntajaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        self.action = QAction(QIcon(str(Path(__file__).parent / "icon.png")), "Muuntaja", self.iface.mainWindow())
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu("Muuntaja", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu("Muuntaja", self.action)
        self.iface.removeToolBarIcon(self.action)

    def open(self):
        self.dialog = MuuntajaDialog(self.iface.mainWindow())
        self.dialog.show()
