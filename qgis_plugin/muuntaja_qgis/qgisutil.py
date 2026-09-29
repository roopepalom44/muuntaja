"""Shared QGIS helpers for the import/export modules."""

import math
from pathlib import Path

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsVectorFileWriter,
)

from . import formats


def field_type(name):
    """QgsField type that works on Qt5 (QVariant) and Qt6/QGIS 4 (QMetaType)."""
    if Qgis.versionInt() >= 33800:
        from qgis.PyQt.QtCore import QMetaType
        return {"int": QMetaType.Type.Int, "double": QMetaType.Type.Double,
                "string": QMetaType.Type.QString}[name]
    from qgis.PyQt.QtCore import QVariant
    return {"int": QVariant.Int, "double": QVariant.Double, "string": QVariant.String}[name]


def inferred_crs(layer, path=None):
    try:
        extent = layer.extent()
        code = formats.classify_finnish_xy(extent.center().x(), extent.center().y())
        if code:
            return QgsCoordinateReferenceSystem(f"EPSG:{code}")
    except Exception:
        pass
    if path and "etrs89" in str(path).casefold():
        return QgsCoordinateReferenceSystem("EPSG:3067")
    return None


def _center_in_finland(layer, crs):
    try:
        point = QgsCoordinateTransform(
            crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
        ).transform(layer.extent().center())
        return (math.isfinite(point.x()) and math.isfinite(point.y())
                and 18 <= point.x() <= 33 and 59 <= point.y() <= 72)
    except Exception:
        return False


def assign_source_crs(layer, path, source_crs=None):
    """Assign a known CRS or stop when its location conflicts with Finnish coordinates."""
    if source_crs and source_crs.isValid():
        layer.setCrs(source_crs)
        return
    guessed = inferred_crs(layer, path)
    current = layer.crs()
    if current.isValid():
        if (guessed and guessed.isValid() and current != guessed
                and _center_in_finland(layer, guessed)
                and not _center_in_finland(layer, current)):
            raise RuntimeError(
                f"Tason koordinaatisto on {current.authid()}, mutta koordinaatit näyttävät "
                f"järjestelmältä {guessed.authid()}. Aseta oikea lähtö-CRS "
                "lisäasetusten Lähtö-CRS (pakota) -kentässä.")
        return
    if guessed:
        layer.setCrs(guessed)
        return
    raise RuntimeError("Lähtökoordinaatistoa ei tunnistettu. Aseta lähtö-CRS lisäasetuksissa.")


def ensure_project_crs(project, layer):
    """Turn on coordinate transformations in projects saved without a CRS."""
    if not layer.crs().isValid():
        raise RuntimeError(f"Tason koordinaatistoa ei tunnistettu: {layer.name()}")
    if not project.crs().isValid():
        project.setCrs(layer.crs())


def add_project_layer(project, layer, add_to_legend=True):
    ensure_project_crs(project, layer)
    project.addMapLayer(layer, add_to_legend)


def add_layers_as_group(project, layers, group_name):
    """Add layers under a new top-level group, like QGIS does for multi-layer files."""
    if not layers:
        return None
    ensure_project_crs(project, layers[0])
    root = project.layerTreeRoot()
    names = {child.name() for child in root.children()}
    name, number = group_name, 2
    while name in names:
        name = f"{group_name} ({number})"
        number += 1
    group = root.insertGroup(0, name)
    for layer in layers:
        project.addMapLayer(layer, False)
        group.addLayer(layer)
    return group


def write_vector(layer, path, driver, layer_name=None, target_crs=None, append=False):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    if driver == "OpenFileGDB":
        options.layerOptions = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"]
    if layer_name:
        options.layerName = layer_name
    if append:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    if target_crs and target_crs.isValid() and layer.crs() != target_crs:
        options.ct = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), QgsProject.instance().transformContext(), options)
    if result[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(result[1] or f"Kirjoitusvirhe: {result[0]}")
    return Path(path)
