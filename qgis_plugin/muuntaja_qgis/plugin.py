"""Native Qt interface for the Muuntaja QGIS plugin."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer

from .core import DRIVERS, OperationCanceled, export_data, find_oda_converter, import_data


class MuuntajaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Muuntaja — QGIS")
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._import_tab(), "Tuo aineistoja")
        tabs.addTab(self._export_tab(), "Vie tasoja")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        self.source_crs.setPlaceholderText("Automaattinen tai esimerkiksi EPSG:3067")
        advanced_form.addRow("Lähtö-CRS, jos puuttuu", self.source_crs)
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
        browse = QPushButton("Valitse…")
        browse.clicked.connect(self._choose_export_folder)
        form.addRow("Vientikansio", self._row_widget(self._line_and_button(self.export_folder, browse)))
        self.format = QComboBox()
        self.format.addItems(list(DRIVERS) + ["DWG"])
        self.format.currentTextChanged.connect(self._update_export_controls)
        form.addRow("Tiedostomuoto", self.format)
        self.combined = QCheckBox("Vie valitut tasot samaan tiedostoon")
        self.combined.stateChanged.connect(self._update_export_controls)
        form.addRow("Useita tasoja", self.combined)
        self.oda_converter = QLineEdit(find_oda_converter())
        self.oda_converter.setPlaceholderText("ODA File Converterin .exe-tiedosto")
        self.oda_browse = QPushButton("Valitse…")
        self.oda_browse.clicked.connect(self._choose_oda_converter)
        self.oda_row = self._row_widget(self._line_and_button(self.oda_converter, self.oda_browse))
        self.oda_label = QLabel("DWG-muunnin")
        form.addRow(self.oda_label, self.oda_row)
        self.dwg_hint = QLabel("DWG-vienti vaatii ODA File Converterin. DXF-vienti ei vaadi lisäohjelmaa.")
        self.dwg_hint.setWordWrap(True)
        form.addRow("", self.dwg_hint)
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

    def _choose_oda_converter(self):
        path, _ = QFileDialog.getOpenFileName(self, "Valitse ODA File Converter", "", "Ohjelmat (*.exe)")
        if path:
            self.oda_converter.setText(path)

    def _update_export_controls(self, *_):
        format_name = self.format.currentText()
        supports_combined = format_name in {"GPKG", "DXF", "DWG"}
        self.combined.setEnabled(supports_combined)
        if not supports_combined:
            self.combined.setChecked(False)
        is_dwg = format_name == "DWG"
        self.oda_converter.setEnabled(is_dwg)
        self.oda_browse.setEnabled(is_dwg)
        self.oda_row.setVisible(is_dwg)
        label = None
        self.oda_label.setVisible(is_dwg)
        self.dwg_hint.setVisible(is_dwg)

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
        from qgis.PyQt.QtWidgets import QApplication
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
            )
            self._show_result("Tuonti", successes, failures)
        except OperationCanceled:
            QMessageBox.information(self, "Muuntaja", "Tuonti keskeytettiin.")
        except Exception as exc:
            QMessageBox.critical(self, "Muuntaja", str(exc))
        finally:
            self.progress.close()

    def _run_export(self):
        layers = [
            QgsProject.instance().mapLayer(self.layers.item(i).data(Qt.UserRole))
            for i in range(self.layers.count())
            if self.layers.item(i).checkState() == Qt.Checked
        ]
        folder = self.export_folder.text().strip()
        if not layers or not folder:
            QMessageBox.warning(self, "Muuntaja", "Valitse vietävät tasot ja vientikansio.")
            return
        self.progress = QProgressDialog("Valmistellaan vientiä…", "Keskeytä", 0, len(layers), self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        try:
            successes, failures = export_data(
                layers,
                folder,
                self.format.currentText(),
                self.combined.isChecked(),
                self._progress,
                self.oda_converter.text().strip(),
            )
            self._show_result("Vienti", successes, failures)
        except OperationCanceled:
            QMessageBox.information(self, "Muuntaja", "Vienti keskeytettiin.")
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
