"""Native Qt interface for the Muuntaja QGIS plugin."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer
from qgis.gui import QgsCustomDropHandler

from . import cad
from .core import EXPORT_FORMATS, OperationCanceled, export_data, import_data
from .formats import COMMON_EXPORT_CRS, STYLE_EXPORT_FORMATS

OTHER_CRS = "__muu__"


class MuuntajaDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self._automatic_import_destination = ""
        self.setWindowTitle("Muuntaja — QGIS")
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._import_tab(), "Tuo aineistoja")
        self.tabs.addTab(self._export_tab(), "Vie tasoja")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _project_directory():
        project_file = QgsProject.instance().fileName()
        return str(Path(project_file).parent) if project_file else ""

    def _default_import_destination(self, mode):
        directory = self._project_directory()
        if not directory:
            return ""
        if mode == "gpkg":
            return str(Path(directory) / "muuntaja_tuonti.gpkg")
        if mode == "gdb":
            return str(Path(directory) / "muuntaja_tuonti.gdb")
        return directory

    @staticmethod
    def _scroll_page(content, layout):
        content.setLayout(layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        return scroll

    @staticmethod
    def _row_widget(layout):
        row = QWidget()
        row.setLayout(layout)
        return row

    def _import_tab(self):
        page = QWidget()
        layout = QVBoxLayout()
        intro = QLabel("Valitse tiedostoja tai kansio. Kansio käydään läpi alikansioineen.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        inputs_group = QWidget()
        inputs_layout = QVBoxLayout(inputs_group)
        self.inputs = QListWidget()
        self.inputs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.inputs.setMinimumHeight(145)
        inputs_layout.addWidget(self.inputs)
        self.input_summary = QLabel("Ei syötteitä valittuna")
        self.input_summary.setStyleSheet("color: palette(mid); font-size: 10pt;")
        inputs_layout.addWidget(self.input_summary)
        input_buttons = QHBoxLayout()
        add_files = QPushButton("Lisää tiedostoja…")
        add_files.clicked.connect(self._add_files)
        input_buttons.addWidget(add_files)
        add_folder = QPushButton("Lisää kansio…")
        add_folder.clicked.connect(self._add_folder)
        input_buttons.addWidget(add_folder)
        remove = QPushButton("Poista valitut")
        remove.clicked.connect(self._remove_inputs)
        input_buttons.addWidget(remove)
        input_buttons.addStretch(1)
        inputs_layout.addLayout(input_buttons)
        layout.addWidget(inputs_group)

        output_group = QWidget()
        output_form = QFormLayout(output_group)
        output_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.destination_mode = QComboBox()
        self.destination_mode.addItem("Erilliset GeoPackage-tiedostot kansioon", "folder")
        self.destination_mode.addItem("Yksi GeoPackage-tiedosto", "gpkg")
        self.destination_mode.addItem("File Geodatabase (.gdb)", "gdb")
        self.destination_mode.currentIndexChanged.connect(self._update_import_destination_controls)
        output_form.addRow("Tallennustapa", self.destination_mode)
        self.import_output = QLineEdit()
        self.import_output.setPlaceholderText("Valitse kohdekansio")
        self._automatic_import_destination = self._default_import_destination("folder")
        self.import_output.setText(self._automatic_import_destination)
        self.import_browse = QPushButton("Valitse…")
        self.import_browse.clicked.connect(self._choose_import_destination)
        output_form.addRow("Tallennuspaikka", self._row_widget(self._line_and_button(self.import_output, self.import_browse)))
        output_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(output_group)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Lisäasetukset")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._set_import_advanced_visible)
        layout.addWidget(self.advanced_toggle)
        self.advanced_options = QWidget()
        advanced_form = QFormLayout(self.advanced_options)
        advanced_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.source_crs = QLineEdit()
        self.source_crs.setPlaceholderText("Tyhjä = automaattinen; esimerkiksi EPSG:3067")
        advanced_form.addRow("Lähtö-CRS (pakota)", self.source_crs)
        self.target_crs = QLineEdit()
        self.target_crs.setPlaceholderText("Tyhjä = säilytä lähteen koordinaatisto")
        advanced_form.addRow("Kohde-CRS", self.target_crs)

        self.clean_cad = QCheckBox("Ohita CADin Defpoints- ja 0-tasot")
        self.clean_cad.setEnabled(False)
        advanced_form.addRow("CAD", self.clean_cad)
        self.dfsu_filter_enabled = QCheckBox("Rajaa DFSU-aineistoa sarakkeen arvolla")
        self.dfsu_filter_enabled.setEnabled(False)
        self.dfsu_filter_enabled.toggled.connect(self._update_dfsu_controls)
        advanced_form.addRow("DFSU", self.dfsu_filter_enabled)
        self.dfsu_column = QLineEdit()
        self.dfsu_column.setPlaceholderText("Sarakkeen nimi")
        self.dfsu_operator = QComboBox()
        self.dfsu_operator.addItems(["=", "≠", ">", ">=", "<", "<=", "contains", "starts with", "ends with"])
        self.dfsu_value = QLineEdit()
        self.dfsu_value.setPlaceholderText("Vertailuarvo")
        self.dfsu_column_row = self._row_widget(QHBoxLayout())
        self.dfsu_column_row.layout().addWidget(self.dfsu_column)
        advanced_form.addRow("Suodatinsarake", self.dfsu_column_row)
        advanced_form.addRow("Operaattori", self.dfsu_operator)
        advanced_form.addRow("Arvo", self.dfsu_value)
        self.advanced_options.setVisible(False)
        layout.addWidget(self.advanced_options)

        run = QPushButton("Tuo aineistot")
        run.setDefault(True)
        run.clicked.connect(self._run_import)
        layout.addWidget(run)
        layout.addStretch(1)

        self.inputs.itemSelectionChanged.connect(self._update_input_summary)
        return self._scroll_page(page, layout)

    @staticmethod
    def _line_and_button(line_edit, button):
        row = QHBoxLayout()
        row.addWidget(line_edit)
        row.addWidget(button)
        return row

    def _export_tab(self):
        page = QWidget()
        layout = QVBoxLayout()
        intro = QLabel("Valitse projektista vietävät vektoritasot ja niiden tallennustapa.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.layers = QListWidget()
        self.layers.setMinimumHeight(180)
        layout.addWidget(self.layers)
        self.layer_summary = QLabel()
        self.layer_summary.setStyleSheet("color: palette(mid); font-size: 10pt;")
        layout.addWidget(self.layer_summary)
        refresh = QPushButton("Päivitä projektin tasot")
        refresh.clicked.connect(self.refresh_layers)
        layout.addWidget(refresh)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.export_folder = QLineEdit()
        self.export_folder.setPlaceholderText("Valitse vientikansio")
        self.export_folder.setText(self._project_directory())
        browse = QPushButton("Valitse…")
        browse.clicked.connect(self._choose_export_folder)
        form.addRow("Vientikansio", self._row_widget(self._line_and_button(self.export_folder, browse)))
        self.format = QComboBox()
        self.format.addItems(EXPORT_FORMATS)
        self.format.currentTextChanged.connect(self._update_export_controls)
        form.addRow("Tiedostomuoto", self.format)
        self.export_crs = QComboBox()
        self.export_crs.addItem("Tason oma", "")
        for label, code in COMMON_EXPORT_CRS:
            self.export_crs.addItem(f"{label} (EPSG:{code})", f"EPSG:{code}")
        self.export_crs.addItem("Muu koordinaatisto…", OTHER_CRS)
        self._export_crs_index = 0
        self.export_crs.activated.connect(self._choose_export_crs)
        form.addRow("Kohdekoordinaatisto", self.export_crs)
        self.include_styles = QCheckBox("Pakkaa tasojen tyylit mukaan")
        self.include_styles.setChecked(True)
        self.include_styles.setToolTip("GeoPackage: tyyli tallennetaan tiedoston sisään. Shapefile ja GeoJSON: "
                                       "samanniminen .qml viereen. KML/KMZ: tyylit tiedostoon.")
        form.addRow("Tyylit", self.include_styles)
        self.combined = QCheckBox("Vie valitut tasot samaan tiedostoon")
        self.combined.stateChanged.connect(self._update_export_controls)
        form.addRow("Useita tasoja", self.combined)
        self.cad_hint = QLabel("DXF tehdään QGISin omalla DXF-viennillä: tasojen symbologia, nimiöt ja "
                               "tuotujen CAD-tasojen nimet säilyvät. DXF avautuu AutoCADissa ja ArcGISissä.")
        self.cad_hint.setWordWrap(True)
        form.addRow("", self.cad_hint)
        layout.addLayout(form)

        run = QPushButton("Vie tasot")
        run.setDefault(True)
        run.clicked.connect(self._run_export)
        layout.addWidget(run)
        layout.addStretch(1)
        self.refresh_layers()
        self._update_export_controls()
        return self._scroll_page(page, layout)

    def _update_import_destination_controls(self, *_):
        mode = self.destination_mode.currentData()
        current = self.import_output.text().strip()
        default = self._default_import_destination(mode)
        if not current or current == self._automatic_import_destination:
            self.import_output.setText(default)
        self._automatic_import_destination = default
        placeholders = {
            "folder": "Kansio, johon tasot tallennetaan erillisinä GeoPackage-tiedostoina",
            "gpkg": "Esimerkiksi C:/Aineistot/tuonti.gpkg",
            "gdb": "Esimerkiksi C:/Aineistot/tuonti.gdb",
        }
        self.import_output.setPlaceholderText(placeholders[mode])
        self.import_browse.setText("Valitse kansio…" if mode == "folder" else "Tallenna nimellä…")

    def _set_import_advanced_visible(self, visible):
        self.advanced_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self.advanced_options.setVisible(visible)

    def _update_input_summary(self, *_):
        count = self.inputs.count()
        noun = "syöte" if count == 1 else "syötettä"
        self.input_summary.setText(f"{count} {noun} valittuna" if count else "Ei syötteitä valittuna")
        paths = [Path(self.inputs.item(index).text()) for index in range(count)]
        may_contain_cad = any(path.is_dir() or path.suffix.lower() in {".dwg", ".dxf"} for path in paths)
        may_contain_dfsu = any(path.is_dir() or path.suffix.lower() == ".dfsu" for path in paths)
        self.clean_cad.setEnabled(may_contain_cad)
        if not may_contain_cad:
            self.clean_cad.setChecked(False)
        self.dfsu_filter_enabled.setEnabled(may_contain_dfsu)
        if not may_contain_dfsu:
            self.dfsu_filter_enabled.setChecked(False)
        self._update_dfsu_controls()

    def _update_dfsu_controls(self, *_):
        enabled = self.dfsu_filter_enabled.isEnabled() and self.dfsu_filter_enabled.isChecked()
        for widget in (self.dfsu_column, self.dfsu_operator, self.dfsu_value):
            widget.setEnabled(enabled)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Valitse tuotavat aineistot",
            "",
            "Paikkatietoaineistot (*.gpkg *.geojson *.json *.kml *.kmz *.gpx *.shp *.dxf *.dwg *.dfsu *.tif *.tiff *.png *.jpg *.jpeg *.jp2 *.img);;Kaikki tiedostot (*)",
        )
        self._add_input_paths(files)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Valitse syötekansio")
        self._add_input_paths([path] if path else [])

    def _add_input_paths(self, paths):
        existing = {self.inputs.item(i).text() for i in range(self.inputs.count())}
        for path in paths:
            if path and path not in existing:
                self.inputs.addItem(path)
                existing.add(path)
        self._update_input_summary()

    def _remove_inputs(self):
        for item in self.inputs.selectedItems():
            self.inputs.takeItem(self.inputs.row(item))
        self._update_input_summary()

    def _choose_import_destination(self):
        mode = self.destination_mode.currentData()
        current = self.import_output.text().strip()
        if mode == "folder":
            path = QFileDialog.getExistingDirectory(self, "Valitse tallennuskansio", current if Path(current).is_dir() else "")
        else:
            extension = ".gpkg" if mode == "gpkg" else ".gdb"
            filter_name = "GeoPackage (*.gpkg)" if mode == "gpkg" else "File Geodatabase (*.gdb)"
            path, _ = QFileDialog.getSaveFileName(self, "Valitse tallennuspaikka", current, filter_name)
            if path and not path.lower().endswith(extension):
                path += extension
        if path:
            self.import_output.setText(path)

    def _choose_export_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Valitse vientikansio", self.export_folder.text().strip())
        if path:
            self.export_folder.setText(path)

    def _choose_export_crs(self, index):
        """Open QGIS' own CRS selector for "Muu koordinaatisto…"."""
        if self.export_crs.itemData(index) != OTHER_CRS:
            self._export_crs_index = index
            return
        from qgis.gui import QgsProjectionSelectionDialog
        dialog = QgsProjectionSelectionDialog(self)
        dialog.setWindowTitle("Viennin kohdekoordinaatisto")
        project_crs = QgsProject.instance().crs()
        dialog.setCrs(project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:3067"))
        if not dialog.exec() or not dialog.crs().isValid():
            self.export_crs.setCurrentIndex(self._export_crs_index)
            return
        crs = dialog.crs()
        existing = self.export_crs.findData(crs.authid())
        if existing < 0:
            existing = self.export_crs.count() - 1
            self.export_crs.insertItem(existing, f"{crs.description()} ({crs.authid()})", crs.authid())
        self.export_crs.setCurrentIndex(existing)
        self._export_crs_index = existing

    def _export_target_crs(self):
        authid = self.export_crs.currentData()
        return QgsCoordinateReferenceSystem(authid) if authid and authid != OTHER_CRS else None

    def _update_export_controls(self, *_):
        format_name = self.format.currentText()
        supports_combined = format_name in {"GPKG", "DXF"}
        self.combined.setEnabled(supports_combined)
        if not supports_combined:
            self.combined.setChecked(False)
        self.cad_hint.setVisible(format_name == "DXF")
        self.include_styles.setEnabled(format_name in STYLE_EXPORT_FORMATS)
        wgs84_only = format_name in {"KML", "KMZ"}
        self.export_crs.setEnabled(not wgs84_only)
        self.export_crs.setToolTip("KML/KMZ viedään aina WGS84:ään." if wgs84_only else
                                   "GeoJSON viedään WGS84:ään, jos koordinaatistoa ei valita." if format_name == "GeoJSON"
                                   else "")

    def refresh_layers(self):
        self.layers.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                item = QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.layers.addItem(item)
        count = self.layers.count()
        noun = "vektoritaso" if count == 1 else "vektoritasoa"
        self.layer_summary.setText(f"Projektissa {count} vietävää {noun}")

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
        QApplication.processEvents()
        if self.progress.wasCanceled():
            raise OperationCanceled("Käyttäjä keskeytti")

    def _run_import(self):
        paths = [self.inputs.item(i).text() for i in range(self.inputs.count())]
        destination = self.import_output.text().strip()
        mode = self.destination_mode.currentData()
        if not paths or not destination:
            QMessageBox.warning(self, "Muuntaja", "Valitse ensin syötteet ja tallennuspaikka.")
            return
        suffix = Path(destination).suffix.lower()
        if (mode == "folder" and suffix in {".gpkg", ".gdb"}) or (mode == "gpkg" and suffix != ".gpkg") or (mode == "gdb" and suffix != ".gdb"):
            QMessageBox.warning(self, "Muuntaja", "Tallennuspaikka ei vastaa valittua tallennustapaa.")
            return
        if mode == "gdb" and Path(destination).exists() and not Path(destination).is_dir():
            QMessageBox.warning(self, "Muuntaja", "Valittu File Geodatabase -polku on olemassa tiedostona.")
            return
        if mode == "gpkg" and Path(destination).exists() and Path(destination).is_dir():
            QMessageBox.warning(self, "Muuntaja", "Valittu GeoPackage-polku on kansio.")
            return
        self.progress = QProgressDialog("Valmistellaan tuontia…", "Keskeytä", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        project_crs_missing = not QgsProject.instance().crs().isValid()
        notes = []
        try:
            successes, failures = import_data(
                paths,
                destination,
                self._crs(self.source_crs.text()),
                self._crs(self.target_crs.text()),
                self.clean_cad.isChecked(),
                self._progress,
                self.dfsu_column.text().strip() if self.dfsu_filter_enabled.isChecked() else "",
                self.dfsu_operator.currentText(),
                self.dfsu_value.text(),
                notes,
            )
            project_crs = QgsProject.instance().crs()
            if project_crs_missing and project_crs.isValid():
                notes.insert(0, f"Projektin koordinaattijärjestelmä asetettiin: {project_crs.authid()}.")
            self._show_result("Tuonti", successes, failures, "\n".join(notes))
        except OperationCanceled:
            QMessageBox.information(self, "Muuntaja", "Tuonti keskeytettiin.")
        except Exception as exc:
            QMessageBox.critical(self, "Muuntaja", str(exc))
        finally:
            self.progress.close()

    def _run_export(self):
        checked = [self.layers.item(i) for i in range(self.layers.count())
                   if self.layers.item(i).checkState() == Qt.Checked]
        layers = [QgsProject.instance().mapLayer(item.data(Qt.UserRole)) for item in checked]
        missing = [item.text() for item, layer in zip(checked, layers) if layer is None]
        layers = [layer for layer in layers if layer is not None]
        folder = self.export_folder.text().strip()
        if missing:
            self.refresh_layers()
            QMessageBox.warning(self, "Muuntaja", "Nämä tasot on poistettu projektista, päivitä valinta: "
                                + ", ".join(missing))
            return
        if not layers or not folder:
            QMessageBox.warning(self, "Muuntaja", "Valitse vietävät tasot ja vientikansio.")
            return
        self.progress = QProgressDialog("Valmistellaan vientiä…", "Keskeytä", 0, len(layers), self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        try:
            notes = []
            successes, failures = export_data(
                layers,
                folder,
                self.format.currentText(),
                self.combined.isChecked(),
                self._progress,
                self._symbology_scale(),
                self._export_target_crs(),
                notes,
                self.include_styles.isChecked(),
            )
            self._show_result("Vienti", successes, failures, "\n".join(notes))
        except OperationCanceled:
            QMessageBox.information(self, "Muuntaja", "Vienti keskeytettiin.")
        except Exception as exc:
            QMessageBox.critical(self, "Muuntaja", str(exc))
        finally:
            self.progress.close()

    def _symbology_scale(self):
        try:
            scale = self.iface.mapCanvas().scale() if self.iface else 0
        except Exception:
            scale = 0
        return scale if scale and scale > 0 else None

    def show_export(self, format_name=None):
        self.refresh_layers()
        if format_name:
            self.format.setCurrentText(format_name)
        self.tabs.setCurrentIndex(1)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_import(self):
        self.tabs.setCurrentIndex(0)
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_result(self, operation, successes, failures, note=""):
        details = "\n".join(f"{path}: {error}" for path, error in failures)
        message = f"{operation}: {len(successes)} onnistui, {len(failures)} epäonnistui."
        if note:
            message += "\n" + note
        if details:
            message += "\n\n" + details
        QMessageBox.information(self, "Muuntaja", message)


class CadDropHandler(QgsCustomDropHandler):
    """Open dropped DWG files through Muuntaja (QGIS/GDAL reads only AutoCAD 2000 DWG)."""

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def customUriProviderKey(self):
        return "muuntaja_dwg"

    def handleFileDrop(self, file):
        if Path(file).suffix.lower() != ".dwg":
            return False
        self.plugin.import_cad_files([file])
        return True


class MuuntajaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.add_cad_action = None
        self.export_cad_action = None
        self.drop_handler = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(str(Path(__file__).parent / "icon.png"))
        self.action = QAction(icon, "Muuntaja", self.iface.mainWindow())
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu("Muuntaja", self.action)
        self.iface.addToolBarIcon(self.action)

        # DWG/DXF samoihin paikkoihin kuin QGISin omat tuonti- ja vientitoiminnot.
        self.add_cad_action = QAction(icon, "Lisää DWG/DXF-taso (Muuntaja)…", self.iface.mainWindow())
        self.add_cad_action.triggered.connect(self.choose_cad_files)
        if hasattr(self.iface, "insertAddLayerAction"):
            self.iface.insertAddLayerAction(self.add_cad_action)
        else:
            self.iface.addPluginToMenu("Muuntaja", self.add_cad_action)
        self.export_cad_action = QAction(icon, "Vie tasot DXF-muotoon (Muuntaja)…", self.iface.mainWindow())
        self.export_cad_action.triggered.connect(lambda: self._dialog().show_export("DXF"))
        menu = self.iface.projectImportExportMenu() if hasattr(self.iface, "projectImportExportMenu") else None
        if menu is not None:
            menu.addAction(self.export_cad_action)
        else:
            self.iface.addPluginToMenu("Muuntaja", self.export_cad_action)
        if hasattr(self.iface, "registerCustomDropHandler"):
            self.drop_handler = CadDropHandler(self)
            self.iface.registerCustomDropHandler(self.drop_handler)

    def unload(self):
        if self.drop_handler is not None:
            self.iface.unregisterCustomDropHandler(self.drop_handler)
            self.drop_handler = None
        if self.add_cad_action is not None:
            if hasattr(self.iface, "removeAddLayerAction"):
                self.iface.removeAddLayerAction(self.add_cad_action)
            self.iface.removePluginMenu("Muuntaja", self.add_cad_action)
        if self.export_cad_action is not None:
            menu = self.iface.projectImportExportMenu() if hasattr(self.iface, "projectImportExportMenu") else None
            if menu is not None:
                menu.removeAction(self.export_cad_action)
            self.iface.removePluginMenu("Muuntaja", self.export_cad_action)
        self.iface.removePluginMenu("Muuntaja", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def _dialog(self):
        # Yksi dialogi koko istunnolle: aiemmat valinnat säilyvät eikä
        # jokainen avaus jätä uutta ikkunaa muistiin.
        if self.dialog is None:
            self.dialog = MuuntajaDialog(self.iface.mainWindow(), self.iface)
        return self.dialog

    def open(self):
        dialog = self._dialog()
        dialog.refresh_layers()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def choose_cad_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.iface.mainWindow(), "Lisää DWG/DXF-taso", "", "CAD-piirustukset (*.dwg *.dxf *.DWG *.DXF)")
        if files:
            self.import_cad_files(files)

    def _cad_destination(self, path):
        project_file = QgsProject.instance().fileName()
        if project_file:
            return Path(project_file).parent / "muuntaja_tuonti.gpkg"
        return Path(path).with_suffix(".gpkg")

    def import_cad_files(self, files):
        """Import DWG/DXF like QGIS opens a layer: grouped, styled, labelled."""
        bar = self.iface.messageBar()
        for file in files:
            destination = self._cad_destination(file)
            source_crs = None
            while True:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    layers = cad.import_cad(file, destination, source_crs=source_crs)
                except cad.CrsNotDetected:
                    QApplication.restoreOverrideCursor()
                    source_crs = self._ask_crs(file)
                    if source_crs is None:
                        break
                    continue
                except Exception as exc:
                    QApplication.restoreOverrideCursor()
                    bar.pushMessage("Muuntaja", f"{Path(file).name}: {exc}",
                                    level=Qgis.MessageLevel.Critical, duration=0)
                    break
                QApplication.restoreOverrideCursor()
                bar.pushMessage("Muuntaja", f"{Path(file).name}: {len(layers)} tasoa lisätty "
                                f"({destination.name}).", level=Qgis.MessageLevel.Success, duration=6)
                break

    def _ask_crs(self, file):
        from qgis.gui import QgsProjectionSelectionDialog
        dialog = QgsProjectionSelectionDialog(self.iface.mainWindow())
        dialog.setWindowTitle(f"Valitse koordinaatisto: {Path(file).name}")
        project_crs = QgsProject.instance().crs()
        dialog.setCrs(project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:3067"))
        return dialog.crs() if dialog.exec() else None
