"""Background jobs with private projects and immutable feature snapshots."""

import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeatureRequest,
    QgsProject,
    QgsRasterLayer,
    QgsTask,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
)

from . import core


def style_xml(layer):
    if not isinstance(layer, QgsVectorLayer):
        return ""
    from qgis.PyQt.QtXml import QDomDocument

    document = QDomDocument("qgis")
    error = layer.exportNamedStyle(document)
    if error:
        raise RuntimeError(error)
    return document.toString()


def apply_style_xml(layer, text):
    if not text:
        return
    from qgis.PyQt.QtXml import QDomDocument

    document = QDomDocument("qgis")
    document.setContent(text)
    imported, error = layer.importNamedStyle(document)
    if not imported:
        raise RuntimeError(error)


def layer_spec(layer, group=""):
    return {
        "source": layer.source(),
        "name": layer.name(),
        "crs": layer.crs().toWkt(),
        "raster": isinstance(layer, QgsRasterLayer),
        "group": group,
        "paths": layer.customProperty("muuntaja/source_paths", []),
        "style": style_xml(layer),
    }


def raster_snapshot(project):
    result = []
    for node in project.layerTreeRoot().findLayers():
        layer = node.layer()
        if isinstance(layer, QgsRasterLayer) and layer.customProperty(
            "muuntaja/source_paths", []
        ):
            spec = layer_spec(layer, node.parent().name())
            spec["prior_id"] = layer.id()
            result.append(spec)
    return result


def publish_layers(project, specs, removed):
    """Called on the GUI thread, after all output providers have been validated."""
    pending = []
    try:
        for spec in specs:
            layer = (
                QgsRasterLayer(spec["source"], spec["name"])
                if spec["raster"]
                else QgsVectorLayer(spec["source"], spec["name"], "ogr")
            )
            pending.append((layer, spec))
            if not layer.isValid():
                raise RuntimeError(f"Tulostasoa ei voitu avata: {spec['source']}")
            layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(spec["crs"]))
            layer.setCustomProperty("muuntaja/source_paths", spec["paths"])
            if spec["raster"]:
                layer.setCustomProperty("muuntaja/managed", True)
            apply_style_xml(layer, spec.get("style", ""))
        for layer, spec in pending:
            core._add_project_layer(project, layer, not bool(spec["group"]))
            if spec["group"]:
                group = project.layerTreeRoot().findGroup(
                    spec["group"]
                ) or project.layerTreeRoot().addGroup(spec["group"])
                group.addLayer(layer)
        for identity in removed:
            project.removeMapLayer(identity)
    except Exception:
        for layer, _spec in pending:
            if project.mapLayer(layer.id()) is None:
                core._dispose(layer)
        raise


class ConversionTask(QgsTask):
    progressUpdate = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)

    def __init__(self, operation, arguments, project, layers=()):
        super().__init__("Muuntaja: " + operation, QgsTask.CanCancel)
        self.operation = operation
        self.arguments = arguments
        self.project_crs = QgsCoordinateReferenceSystem(project.crs())
        self.context = QgsCoordinateTransformContext(project.transformContext())
        self.rasters = raster_snapshot(project) if operation == "Tuonti" else []
        self.group_names = [
            child.name() for child in project.layerTreeRoot().children()
        ]
        # Construct snapshots on the owning thread. No main-thread QObject is
        # used from run(), including when exporting edited memory providers.
        self.sources = [
            (
                layer.name(),
                QgsVectorLayerFeatureSource(layer),
                layer.wkbType(),
                list(layer.selectedFeatureIds()),
                style_xml(layer),
            )
            for layer in layers
        ]
        self.setDependentLayers(list(layers))
        self.result = None

    def _progress(self, index, total, label):
        if self.isCanceled():
            raise core.OperationCanceled("Käyttäjä keskeytti")
        self.setProgress(100 * max(index - 1, 0) / max(total, 1))
        self.progressUpdate.emit(index, total, label)

    def _stage_source(self, name, source, wkb_type, selected, style, path, project):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "snapshot"
        writer = QgsVectorFileWriter.create(
            str(path),
            source.fields(),
            wkb_type,
            source.crs(),
            project.transformContext(),
            options,
        )
        try:
            if writer.hasError() != QgsVectorFileWriter.NoError:
                raise RuntimeError(writer.errorMessage())
            request = (
                QgsFeatureRequest().setFilterFids(selected)
                if selected
                else QgsFeatureRequest()
            )
            batch = []
            for feature in source.getFeatures(request):
                if self.isCanceled():
                    raise core.OperationCanceled("Käyttäjä keskeytti")
                batch.append(feature)
                if len(batch) >= 1000:
                    if not writer.addFeatures(batch):
                        raise RuntimeError(writer.errorMessage())
                    batch.clear()
            if batch and not writer.addFeatures(batch):
                raise RuntimeError(writer.errorMessage())
        finally:
            del writer
        layer = QgsVectorLayer(str(path), name, "ogr")
        if not layer.isValid():
            core._dispose(layer)
            raise RuntimeError(f"Vientitasoa ei voitu valmistella: {name}")
        apply_style_xml(layer, style)
        return layer

    def run(self):
        project = QgsProject()
        project.setCrs(self.project_crs)
        project.setTransformContext(self.context)
        token = core._operation_project.set(project)
        export_layers = []
        notes = []
        try:
            self._progress(1, 1, "Valmistellaan aineistoja…")
            for name in self.group_names:
                project.layerTreeRoot().addGroup(name)
            if self.operation == "Tuonti":
                prior = {}
                for spec in self.rasters:
                    layer = QgsRasterLayer(spec["source"], spec["name"])
                    if not layer.isValid():
                        core._dispose(layer)
                        continue
                    layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(spec["crs"]))
                    layer.setCustomProperty("muuntaja/source_paths", spec["paths"])
                    project.addMapLayer(layer, False)
                    group = project.layerTreeRoot().findGroup(
                        spec["group"]
                    ) or project.layerTreeRoot().addGroup(spec["group"])
                    group.addLayer(layer)
                    prior[layer.id()] = spec["prior_id"]
                successes, failures = core.import_data(
                    progress=self._progress, notes=notes, **self.arguments
                )
                specs = []
                for node in project.layerTreeRoot().findLayers():
                    if node.layerId() not in prior:
                        group = (
                            node.parent().name()
                            if node.parent() != project.layerTreeRoot()
                            else ""
                        )
                        specs.append(layer_spec(node.layer(), group))
                removed = [
                    identity
                    for local, identity in prior.items()
                    if project.mapLayer(local) is None
                ]
                self.result = dict(
                    successes=successes, failures=failures, specs=specs, removed=removed
                )
            elif self.operation == "CAD-tuonti":
                core.cad.import_cad(project=project, notes=notes, **self.arguments)
                specs = [
                    layer_spec(node.layer(), node.parent().name())
                    for node in project.layerTreeRoot().findLayers()
                ]
                self.result = dict(
                    successes=[str(self.arguments["path"])],
                    failures=[],
                    specs=specs,
                    removed=[],
                )
            else:
                with tempfile.TemporaryDirectory(
                    prefix="muuntaja_export_snapshot_"
                ) as folder:
                    try:
                        for index, snapshot in enumerate(self.sources):
                            self._progress(index + 1, len(self.sources), snapshot[0])
                            export_layers.append(
                                self._stage_source(
                                    *snapshot, Path(folder) / f"{index}.gpkg", project
                                )
                            )
                        successes, failures = core.export_data(
                            export_layers,
                            progress=self._progress,
                            notes=notes,
                            **self.arguments,
                        )
                        self.result = dict(
                            successes=successes, failures=failures, specs=[], removed=[]
                        )
                    finally:
                        for layer in export_layers:
                            core._dispose(layer)
                        export_layers.clear()
            self._progress(1, 1, "Valmis")
            self.result["notes"] = notes
            return True
        except core.OperationCanceled:
            self.result = {"canceled": True}
            return False
        except core.cad.CrsNotDetected:
            self.result = {"needs_crs": True}
            return False
        except Exception as exc:
            self.result = {"error": str(exc)}
            return False
        finally:
            project.removeAllMapLayers()
            core._operation_project.reset(token)
            core._dispose(project)

    def finished(self, success):
        # Release source snapshots even if the closed progress dialog or task
        # manager still retains the Python task wrapper.
        self.sources.clear()
        self.rasters.clear()
        self.completed.emit(
            self.result or {"canceled": self.isCanceled(), "error": "Ajo keskeytyi"}
        )
