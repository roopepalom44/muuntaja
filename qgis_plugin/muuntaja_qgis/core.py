"""Native QGIS import/export operations. No ArcPy dependency."""

from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsVectorLayer,
)

from . import cad, dgn, processing

from .processing import (  # noqa: F401
    _operation_project, _project, _dispose, _workspace_names, _write_vector,
    _add_project_layer, gdb_safe_name,
)
from .formats import (  # noqa: F401  (julkinen rajapinta lisäosalle ja testeille)
    CAD_EXTENSIONS, RASTER_EXTENSIONS, VECTOR_EXTENSIONS, classify_finnish_xy, dfsu_matches,
    COMMON_EXPORT_CRS, WGS84_ONLY_EXPORT_FORMATS, dfsu_wkb, find_libredwg_tool, has_georeference,
    raster_group, safe_name, scan_inputs,
    unique_name, unique_path,
)
from .qgisutil import (  # noqa: F401
    add_layers_as_group, add_project_layer, assign_source_crs, copy_style, ensure_project_crs, field_type, inferred_crs,
    save_style, source_style, write_vector,
)

DRIVERS = {"GPKG": ("GPKG", ".gpkg"), "GeoJSON": ("GeoJSON", ".geojson"),
           "Shapefile": ("ESRI Shapefile", ".shp"), "KML": ("LIBKML", ".kml"),
           "KMZ": ("LIBKML", ".kmz")}
# DWG kirjoitetaan QGISin DXF-viennistä lisäosan mukana tulevalla
# ACadSharp-ohjelmalla (LibreDWG:n DWG-kirjoitus kadottaa viivat ja tekstit).
CAD_FORMATS = ("DXF", "DWG", "DGN")
EXPORT_FORMATS = list(DRIVERS) + list(CAD_FORMATS)
MANAGED_PROPERTY = "muuntaja/managed"
SOURCE_PATHS_PROPERTY = "muuntaja/source_paths"


class OperationCanceled(Exception):
    pass


_open_vector_layers = processing._open_vector_layers
_add_raster_group = processing._add_raster_group


def _import_dfsu(path, destination, workspace, source_crs, target_crs, filter_column, filter_operator,
                 filter_value, project=None, existing_names=None, progress=None):
    return processing._import_dfsu(path, destination, workspace, source_crs, target_crs,
                                  filter_column, filter_operator, filter_value, existing_names, progress)


def _apply_source_style(source, output, path, save_as_default, notes=None):
    """Carry the source file's own style (.qml or GeoPackage style) over to the imported layer."""
    style = source_style(path, source.name())
    if not style:
        return
    try:
        copy_style(source, output, save_as_default=save_as_default)
        if notes is not None:
            notes.append(f"Tyyli otettiin käyttöön tasolle {output.name()} ({style}).")
    except Exception as exc:
        if notes is not None:
            notes.append(f"Tason {output.name()} tyyliä ({style}) ei voitu ottaa käyttöön: {exc}")


def _import_vector(path, destination, workspace, file_gdb, source_crs, target_crs, project, taken_names,
                   notes=None):
    outputs = []
    layers = _open_vector_layers(path)
    try:
        for layer in layers:
            if layer.featureCount() == 0:
                continue
            assign_source_crs(layer, path, source_crs)
            name = (gdb_safe_name if file_gdb else safe_name)(f"{path.stem}_{layer.name()}")
            if workspace:
                name = unique_name(name, taken_names, 80)
                write_vector(layer, destination, "OpenFileGDB" if file_gdb else "GPKG",
                             name, target_crs, destination.exists())
                taken_names.add(name)
                output = QgsVectorLayer(f"{destination}|layername={name}", name, "ogr")
            else:
                output_path = unique_path(destination / f"{name}.gpkg")
                write_vector(layer, output_path, "GPKG", name, target_crs)
                output = QgsVectorLayer(str(output_path), name, "ogr")
            if not output.isValid():
                _dispose(output)
                raise RuntimeError("Kirjoitettua tasoa ei voitu avata")
            _apply_source_style(layer, output, path, save_as_default=not file_gdb, notes=notes)
            outputs.append(output)
        if not outputs:
            raise RuntimeError("Tiedostossa ei ollut tuotavia kohteita")
        # Monitasoinen tiedosto (GPKG, KML, GPX …) tulee yhdeksi tiedostonimen
        # mukaiseksi ryhmäksi kuten CAD-tuonnissa; yksittäinen taso ilman ryhmää.
        if len(outputs) > 1:
            add_layers_as_group(project, outputs, path.name)
        else:
            add_project_layer(project, outputs[0])
        outputs.clear()
    finally:
        for layer in layers:
            _dispose(layer)
        for output in outputs:
            _dispose(output)


def import_data(paths, destination, source_crs=None, target_crs=None, clean_cad=False,
                progress=None, dfsu_filter_column="", dfsu_filter_operator="=", dfsu_filter_value="",
                notes=None):
    """Import vectors to a GeoPackage/FileGDB or folder; add located rasters by reference.

    Lähteen oma tyyli (.qml tai GeoPackagen tyyli) siirtyy tuotuun tasoon; tiedot
    lisätään ``notes``-listaan käyttäjälle näytettäviksi.
    """
    project = _project()
    items = scan_inputs(paths, progress)
    if not items:
        raise ValueError("Tuettavia tiedostoja ei löytynyt.")
    destination = Path(destination)
    file_gdb = destination.suffix.lower() == ".gdb"
    workspace = file_gdb or destination.suffix.lower() == ".gpkg"
    if workspace:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    taken_names = _workspace_names(destination) if workspace else set()
    successes, failures = [], []
    raster_groups = {}
    for index, path in enumerate(items, 1):
        if progress:
            progress(index, len(items), str(path))
        suffix = path.suffix.lower()
        try:
            if suffix in RASTER_EXTENSIONS:
                raster_groups.setdefault(raster_group(path), []).append(path)
                continue
            if suffix == ".dfsu":
                _import_dfsu(path, destination, workspace, source_crs, target_crs,
                             dfsu_filter_column, dfsu_filter_operator, dfsu_filter_value, project, taken_names, progress)
            elif suffix in CAD_EXTENSIONS:
                layers = cad.import_cad(path, destination, source_crs, target_crs, clean_cad,
                                        project=project, notes=notes)
                taken_names.update(layer.name() for layer in layers)
            else:
                _import_vector(path, destination, workspace, file_gdb, source_crs, target_crs,
                               project, taken_names, notes)
            successes.append(str(path))
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((str(path), str(exc)))
    group_names = list(raster_groups)
    for number, group_name in enumerate(group_names, 1):
        group_paths = raster_groups[group_name]
        if progress:
            progress(len(items), len(items), f"Rasteriryhmä {number}/{len(group_names)}: {group_name}")
        try:
            successes.extend(_add_raster_group(project, group_name, group_paths, destination, source_crs, failures, progress))
        except OperationCanceled:
            raise
        except Exception as exc:
            failed_paths = {path for path, _reason in failures}
            failures.extend((str(path), str(exc)) for path in group_paths if str(path) not in failed_paths)
    if not successes:
        raise RuntimeError("Yksikään tiedosto ei onnistunut: " + "; ".join(f"{p}: {e}" for p, e in failures))
    return successes, failures


def export_data(layers, folder, format_name, combined=False, progress=None,
                symbology_scale=None, target_crs=None, notes=None, include_styles=True, dwg_version="2018"):
    """Export layers; ``target_crs`` reprojects every format except KML/KMZ (always WGS84).

    Kun ``include_styles`` on päällä, tason tyyli tallennetaan vientiin
    (GeoPackageen sisäisesti, Shapefilen ja GeoJSONin viereen .qml, KML:ään tyyleinä). Tyylin ja muunnoksen tiedot
    lisätään ``notes``-listaan käyttäjälle näytettäviksi.
    """
    if format_name not in EXPORT_FORMATS:
        raise ValueError(f"Tuntematon vientimuoto: {format_name}")
    layers = [layer for layer in layers or [] if layer is not None]
    if not layers:
        raise ValueError("Valitse vähintään yksi vektoritaso.")
    target_crs = target_crs if target_crs is not None and target_crs.isValid() else None
    if format_name in WGS84_ONLY_EXPORT_FORMATS:
        if target_crs is not None and notes is not None:
            notes.append(f"{format_name} viedään aina WGS84:ään (KML-standardi); "
                         "kohdekoordinaatiston valinta ei koske sitä.")
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    elif format_name == "GeoJSON" and target_crs is None:
        # RFC 7946: GeoJSON on oletuksena WGS84.
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    if format_name in CAD_FORMATS:
        writer = None
        if format_name == "DGN":
            writer = dgn.write_dgn
        elif format_name == "DWG":
            def writer(group, path, crs, project, notes):
                return cad.write_dwg(group, path, crs, project, notes, symbology_scale, dwg_version)
        return cad.export_cad(layers, folder, combined, progress, symbology_scale,
                              project=_project(), target_crs=target_crs,
                              format_name=format_name, writer=writer, notes=notes)
    driver, extension = DRIVERS[format_name]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    combined = combined and format_name == "GPKG"
    common_path = (unique_path(folder / f"{cad.combined_export_name(layers, _project())}{extension}")
                   if combined else None)
    successes, failures = [], []
    used_names = set()
    for index, layer in enumerate(layers, 1):
        name = layer.name()
        if progress:
            progress(index, len(layers), name)
        try:
            if not layer.isValid():
                raise RuntimeError("Taso ei ole kelvollinen")
            path = common_path or unique_path(folder / f"{safe_name(name)}{extension}")
            layer_name = unique_name(safe_name(name), used_names, 80)
            used_names.add(layer_name)
            if target_crs is not None and not layer.crs().isValid():
                raise RuntimeError(f"{format_name}-vienti koordinaatistoon {target_crs.authid()} vaatii "
                                   "tunnetun lähtökoordinaatiston")
            write_vector(layer, path, driver, layer_name if format_name == "GPKG" else None,
                         target_crs=target_crs, append=bool(common_path and path.exists()),
                         symbology=include_styles and format_name in WGS84_ONLY_EXPORT_FORMATS,
                         symbology_scale=symbology_scale)
            successes.append(str(path))
            if include_styles:
                try:
                    style = save_style(layer, path, format_name, layer_name)
                    if style and notes is not None:
                        notes.append(f"Tyyli tallennettu: {style}")
                except Exception as exc:
                    if notes is not None:
                        notes.append(f"Tason {name} tyyliä ei voitu tallentaa ({exc}); aineisto vietiin ilman tyyliä.")
        except OperationCanceled:
            raise
        except Exception as exc:
            failures.append((name, str(exc)))
    if not successes:
        raise RuntimeError("Yksikään vienti ei onnistunut: " + "; ".join(f"{n}: {e}" for n, e in failures))
    return successes, failures
