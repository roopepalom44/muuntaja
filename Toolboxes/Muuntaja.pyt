# -*- coding: utf-8 -*-
# Tekijä: Roope Palomaa
import arcpy
import os
import re
import time
import datetime
import traceback
import subprocess
import sys
import importlib
import xml.etree.ElementTree as ET
import json
import zipfile

class Toolbox(object):
    def __init__(self):
        self.label = "Muuntaja Toolkit"
        self.alias = "Muuntaja"
        self.tools = [UniversalImportTool]

# Tuonti: nämä tiedostopäätteet → syöte tulkitaan tiedostoksi (tuonti)
IMPORT_FILE_EXTENSIONS = (
    ".gpkg", ".geojson", ".json", ".kml", ".kmz", ".gpx", ".dwg", ".dxf", ".dfsu", ".shp"
)
# Vientiformaatit (dropdown) → tiedostopääte
EXPORT_FORMAT_TO_EXT = {
    "GPKG": ".gpkg",
    "DWG": ".dwg",
    "DXF": ".dxf",
    "GeoJSON": ".geojson",
    "Shapefile": ".shp",
    "KML": ".kml",
    "KMZ": ".kmz",
}
EXPORT_FORMAT_LIST = list(EXPORT_FORMAT_TO_EXT.keys())
# Usean tason GPKG-viennin paketointitavat. Yhteinen paketti säilyttää
# nykyisen oletustoiminnan.
GPKG_EXPORT_PACKAGING_COMBINED = "Kaikki tasot samaan GPKG-tiedostoon"
GPKG_EXPORT_PACKAGING_SEPARATE = "Oma GPKG jokaiselle tasolle"
GPKG_EXPORT_PACKAGING_OPTIONS = [
    GPKG_EXPORT_PACKAGING_COMBINED,
    GPKG_EXPORT_PACKAGING_SEPARATE,
]
# ArcGIS Pron multivalue-string-ohjain, jossa vaihtoehdot näkyvät
# valintaruutuina ja mukana on myös Select All -painike.
EXPORT_LAYER_CHECKBOX_CONTROL_CLSID = "{38C34610-C7F7-11D5-A693-0008C711C8C1}"

# AutoCAD Index Color → RGB — osajoukko Euclidean-lähimmäistä määritystä Esri-symbolin väreille (Color-kenttä).
_CAD_ACI_SAMPLES = (
    (1, 255, 0, 0), (2, 255, 255, 0), (3, 0, 255, 0), (4, 0, 255, 255), (5, 0, 0, 255), (6, 255, 0, 255),
    (7, 255, 255, 255), (8, 64, 64, 64), (9, 128, 128, 128), (250, 51, 51, 51), (251, 80, 80, 80),
    (252, 105, 105, 105), (253, 128, 128, 128), (254, 153, 153, 153), (255, 178, 178, 178),
    (40, 255, 128, 0), (50, 255, 192, 0), (230, 255, 192, 0), (231, 255, 255, 174), (241, 255, 217, 0),
    (20, 255, 147, 0), (220, 255, 80, 0), (242, 255, 128, 0), (246, 255, 192, 0),
    (10, 255, 0, 0), (210, 255, 0, 51), (11, 255, 64, 0), (210, 255, 64, 0),
    (30, 255, 255, 0), (232, 128, 0, 0), (233, 255, 0, 255), (234, 0, 0, 255),
    (235, 0, 255, 255), (236, 0, 128, 0), (160, 0, 32, 128), (132, 0, 153, 0),
)


class UniversalImportTool(object):
    def __init__(self):
        self.label = "Muuntaja"
        self.description = (
            "Tuonti tai vienti — syötteenä voi valita useita rivejä (checkbox-monivalinta). "
            "Tuonti: valitse tiedostoja tai kansio; kansio skannataan myös alikansioineen ja kaikki tuetut muodot "
            "tuodaan tiedosto kerrallaan GDB:hen (CAD, GPKG, GeoJSON, KML, GPX, DFSU ja Shapefile). "
            "DFSU-tuontiin voi lisätä suodattimen sarake-arvo-operaattorilla. "
            "Vienti: aktiivisen kartan feature-tasot valitaan valintaruutulistasta. "
            "CAD-vienti: tekstit (TxtValue), symbologia ja attribuuttitaulukko DWG/DXF:ään. "
            "Muut viennit: GeoJSON, Shapefile, GPKG (usealle tasolle yhteinen tai oma paketti), KML."
        )
        self.canRunInBackground = False
        # DFSU-sarakelistan cache UI:lle (polku+mtime -> sarakkeet); updateParameters kutsuu usein.
        self._dfsu_col_cache = {}
        # Kansiopolkujen laajennus cachetetaan UI-päivitysten ajaksi. Varsinainen
        # suoritus tekee aina tuoreen skannauksen, jotta ajon aikana lisätyt
        # tiedostotkin tulevat mukaan.
        self._import_expansion_cache_key = None
        self._import_expansion_cache_value = None
        self._export_layer_sources = {}
        self._last_operation_mode = None

    def getParameterInfo(self):
        # 0. Mitä haluat tehdä? (MODE) — tuonti tai vienti
        param0 = arcpy.Parameter(
            displayName="Mitä haluat tehdä?",
            name="operation_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        param0.filter.type = "ValueList"
        param0.filter.list = [
            "Tuonti (gpkg, geojson, json, kml, kmz, gpx, dwg, dxf, dfsu, shp)",
            "Vienti (gpkg, dwg, dxf, geojson, shp, kml, kmz)"
        ]
        param0.value = "Tuonti (gpkg, geojson, json, kml, kmz, gpx, dwg, dxf, dfsu, shp)"

        # 1. Tuonnin syöte: tiedosto(t) tai kansio(t)
        param1 = arcpy.Parameter(
            displayName="Syöte - tiedosto(t) tai kansio(t) (kansio skannataan alikansioineen)",
            name="input_file",
            datatype=["DEFile", "DEFolder", "DEFeatureClass", "DEFeatureDataset", "DECadDrawingDataset", "GPFeatureLayer"],
            parameterType="Required",
            direction="Input")
        param1.multiValue = True
        # Huomio: ArcGIS Pro:n tiedostoselain ei tunnista DFSU-tiedostoja oletuksena.
        # Ratkasu: älä suodata tiedostoja — anna käyttäjän valita mikä tahansa tiedosto.
        # Validointi tapahtuu updateMessages()-metodissa.

        # 2. Tallennuspaikka (oletuksena projektin default-GDB, tuonnissa)
        param2 = arcpy.Parameter(
            displayName="Tuonti: Tallennuspaikka (GDB tai Kansio)",
            name="output_location",
            datatype="DEWorkspace",
            parameterType="Optional",
            direction="Input")
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            if aprx.defaultGeodatabase:
                param2.value = aprx.defaultGeodatabase
        except Exception:
            pass

        # 3. Mapper (tuonti)
        param3 = arcpy.Parameter(
            displayName=" Haluatko siivota CAD-tiedostosta turhat tasot pois? (esim. Defpoints)",
            name="use_cad_mapper",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        param3.value = False

        # 4. Input SR - value-list jossa "Automaattinen" oletuksena ja Suomen CRS:t valmiina (tuonti)
        param4 = arcpy.Parameter(
            displayName="[CAD] Lähtökoordinaatisto",
            name="input_sr",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param4.filter.type = "ValueList"
        param4.filter.list = [
            "Automaattinen",
            "ETRS-TM35FIN (3067)",
            "ETRS-GK19 (3873)",
            "ETRS-GK20 (3874)",
            "ETRS-GK21 (3875)",
            "ETRS-GK22 (3876)",
            "ETRS-GK23 (3877)",
            "ETRS-GK24 (3878)",
            "ETRS-GK25 (3879)",
            "ETRS-GK26 (3880)",
            "ETRS-GK27 (3881)",
            "ETRS-GK28 (3882)",
            "ETRS-GK29 (3883)",
            "ETRS-GK30 (3884)",
            "ETRS-GK31 (3885)",
            "KKJ Yhtenäiskoordinaatisto (2393)"
        ]
        param4.value = "Automaattinen"

        # 5. Target SR (vain DWG-tuonnissa näkyvissä)
        param5 = arcpy.Parameter(
            displayName="[Valinnainen] Kohde-CRS (vain CAD-tuonti, tyhjä = alkuperäinen CRS)",
            name="target_sr",
            datatype="GPCoordinateSystem",
            parameterType="Optional",
            direction="Input")
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            if active_map and active_map.spatialReference and active_map.spatialReference.name != "Unknown":
                param5.value = active_map.spatialReference
        except Exception:
            pass

        # 6. Vientikansio (uusi tiedosto luodaan automaattisesti — ei ylikirjoita vanhoja)
        param6 = arcpy.Parameter(
            displayName="Vienti: Vientikansio (tiedosto nimetään automaattisesti)",
            name="export_output_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")
        param6.enabled = False

        # 7. Vientiformaatti
        param7 = arcpy.Parameter(
            displayName="Vienti: Vientiformaatti",
            name="export_format",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param7.filter.type = "ValueList"
        param7.filter.list = EXPORT_FORMAT_LIST
        param7.value = "GPKG"
        param7.enabled = False

        # 8. Vain CAD-vientiin: labelkenttä
        param8 = arcpy.Parameter(
            displayName="[CAD-vienti] Teksti-/labelkenttä (sisältö → CAD Text, tyhjä = ei tekstiä kartalle)",
            name="cad_label_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param8.filter.type = "ValueList"
        param8.filter.list = []
        param8.enabled = False

        # 9. CAD-vienti: luo DWG:hen visuaalinen attribuuttitaulukko (viivat + tekstit)
        param9 = arcpy.Parameter(
            displayName="[CAD-vienti] Luo attribuuttitaulukko DWG:hen (viivat + tekstit)",
            name="cad_emit_attribute_text_table",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        param9.value = False
        param9.enabled = False

        # 10. CAD-vienti: valittavat attribuuttikentät DWG-taulukkoon
        param10 = arcpy.Parameter(
            displayName="[CAD-vienti] Taulukkoon vietävät kentät (monivalinta)",
            name="cad_attribute_text_fields",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param10.multiValue = True
        param10.filter.type = "ValueList"
        param10.filter.list = []
        param10.enabled = False

        # 11. DFSU-suodatin: käytössä?
        param11 = arcpy.Parameter(
            displayName="[DFSU] Suodata rivejä?",
            name="dfsu_enable_filter",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        param11.value = False
        param11.enabled = False

        # 12. DFSU-suodatin: sarake
        param12 = arcpy.Parameter(
            displayName="[DFSU] Suodatettava sarake",
            name="dfsu_filter_column",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param12.filter.type = "ValueList"
        param12.filter.list = []
        param12.enabled = False

        # 13. DFSU-suodatin: operaattori
        param13 = arcpy.Parameter(
            displayName="[DFSU] Operaattori",
            name="dfsu_filter_operator",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param13.filter.type = "ValueList"
        param13.filter.list = ["=", "≠", ">", ">=", "<", "<=", "contains", "starts with", "ends with"]
        param13.value = "="
        param13.enabled = False

        # 14. DFSU-suodatin: arvo
        param14 = arcpy.Parameter(
            displayName="[DFSU] Arvo tai teksti",
            name="dfsu_filter_value",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param14.enabled = False

        # 15. Vientiin vietävät aktiivisen kartan tasot. Tämä on erillinen
        # parametri, jotta tuonnin tiedosto-/kansioselainparametrin datatypea
        # ei tarvitse vaihtaa kesken ArcGIS Pron validoinnin.
        param15 = arcpy.Parameter(
            displayName="Vienti - valitse mukaan vietävät tasot",
            name="export_layers",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        param15.multiValue = True
        param15.filter.type = "ValueList"
        param15.filter.list = []
        param15.controlCLSID = EXPORT_LAYER_CHECKBOX_CONTROL_CLSID
        param15.enabled = False

        # 16. Usean tason GPKG-viennin paketointitapa.
        param16 = arcpy.Parameter(
            displayName="Vienti: GPKG-paketointi (useita tasoja)",
            name="gpkg_export_packaging",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param16.filter.type = "ValueList"
        param16.filter.list = GPKG_EXPORT_PACKAGING_OPTIONS
        param16.value = GPKG_EXPORT_PACKAGING_COMBINED
        param16.enabled = False

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9, param10, param11, param12, param13, param14, param15, param16]

    def updateParameters(self, parameters):
        """Mode-perustainen parametrienhallinta: tuonti vs. vienti sekä DFSU-suodatin."""
        # Parametriindeksit (uusi rakenne)
        p_mode = parameters[0]        # Mitä haluat tehdä?
        p_input = parameters[1]       # Syöte
        p_output_loc = parameters[2]  # Tuonti: Tallennuspaikka
        p_mapper = parameters[3]      # Mapper
        p_input_sr = parameters[4]    # Input SR
        p_target_sr = parameters[5]   # Target SR
        p_export_folder = parameters[6]   # Vienti: Vientikansio
        p_export_fmt = parameters[7]  # Vienti: Vientiformaatti
        p_cad_label = parameters[8]   # CAD: labelkenttä
        p_cad_emit_table = parameters[9]  # CAD: emit table
        p_cad_attr_fields = parameters[10] # CAD: attribute fields
        p_dfsu_filter_en = parameters[11]  # DFSU: enable filter
        p_dfsu_filter_col = parameters[12] # DFSU: column
        p_dfsu_filter_op = parameters[13]  # DFSU: operator
        p_dfsu_filter_val = parameters[14] # DFSU: value
        p_export_layers = parameters[15]  # Vienti: checkbox-lista tasoille
        p_gpkg_packaging = parameters[16]  # Vienti: usean tason GPKG-paketointi
        
        # Lue käyttäjän valittu moodi
        mode = (p_mode.valueAsText or "Tuonti").strip()
        is_import = mode.startswith("Tuonti")
        
        # Tuonti-/vientiparametrit
        selection_param = p_input if is_import else p_export_layers
        raw_paths = self._input_paths_from_param(selection_param)
        mode_changed = (
            self._last_operation_mode is not None
            and mode != self._last_operation_mode
        )
        if mode_changed:
            # Tiedostopolut ja checkbox-listan tasovalinnat eivät ole
            # keskenään yhteensopivia.
            try:
                p_input.values = None
                p_export_layers.values = None
            except Exception:
                pass
            raw_paths = []

        # UI-suorituskyky: vältä kansioiden sisältöjen laajaa skannausta jokaisella näppäilyllä/dragilla.
        if is_import:
            if any(os.path.isdir(p) for p in raw_paths):
                paths = self._expand_import_paths(raw_paths, use_cache=True)
            else:
                paths = list(raw_paths)
        else:
            paths = self._configure_export_layer_choices(p_export_layers, raw_paths)
        has_dfsu = any(str(p).lower().endswith(".dfsu") for p in paths) if paths else False
        has_dwg = (
            any(self._path_contains_extension(p, (".dwg", ".dxf")) for p in paths)
            if is_import
            else bool(paths)
        )
       
        # ===== TUONTI-HAARA =====
        if is_import:
            p_input.enabled = True
            p_input.parameterType = "Required"
            p_export_layers.enabled = False
            p_export_layers.parameterType = "Optional"

            p_output_loc.enabled = True
            p_output_loc.parameterType = "Optional"
            # DWG-parametrit näkyvät vain jos on DWG-tiedostoja
            p_mapper.enabled = has_dwg
            p_input_sr.enabled = has_dwg
            p_target_sr.enabled = has_dwg
            
            p_export_folder.enabled = False
            p_export_folder.parameterType = "Optional"
            p_export_fmt.enabled = False
            p_export_fmt.parameterType = "Optional"
            p_cad_label.enabled = False
            p_cad_emit_table.enabled = False
            p_cad_attr_fields.enabled = False
            p_gpkg_packaging.enabled = False
            p_gpkg_packaging.parameterType = "Optional"
            
            # DFSU-suodatin näkyy vain DFSU-tuonnissa
            if has_dfsu:
                p_dfsu_filter_en.enabled = True
                filter_enabled = bool(p_dfsu_filter_en.value)
                
                if filter_enabled:
                    # Yritä lukea DFSU-sarakkeet
                    dfsu_cols = []
                    dfsu_paths = [str(p) for p in paths if str(p).lower().endswith(".dfsu")]

                    # 1) Kokeile ensin cachea kaikille DFSU-poluille (ei I/O viivettä).
                    for p_path in dfsu_paths:
                        cols = self._read_dfsu_columns_cached_only(p_path)
                        if cols:
                            dfsu_cols = cols
                            break

                    # 2) Jos cache ei riitä, lue vähintään ensimmäinen DFSU myös monitiedostoajossa,
                    # jotta suodatus toimii varmasti usean tiedoston tapauksessa.
                    if not dfsu_cols and dfsu_paths:
                        try:
                            dfsu_cols = self._read_dfsu_columns(dfsu_paths[0]) or []
                        except Exception:
                            dfsu_cols = []

                    # 3) Säilytä aiempi lista fallbackina, jos uusi luku epäonnistui.
                    if not dfsu_cols and p_dfsu_filter_col.filter.list:
                        dfsu_cols = list(p_dfsu_filter_col.filter.list)
                    
                    p_dfsu_filter_col.enabled = True
                    p_dfsu_filter_col.filter.list = dfsu_cols if dfsu_cols else []
                    p_dfsu_filter_op.enabled = True
                    p_dfsu_filter_val.enabled = True
                else:
                    p_dfsu_filter_col.enabled = False
                    p_dfsu_filter_col.filter.list = []
                    p_dfsu_filter_op.enabled = False
                    p_dfsu_filter_val.enabled = False
            else:
                p_dfsu_filter_en.enabled = False
                p_dfsu_filter_en.value = False
                p_dfsu_filter_col.enabled = False
                p_dfsu_filter_col.filter.list = []
                p_dfsu_filter_op.enabled = False
                p_dfsu_filter_val.enabled = False
        
        # ===== VIENTI-HAARA =====
        else:
            p_input.enabled = False
            p_input.parameterType = "Optional"
            p_export_layers.enabled = True
            p_export_layers.parameterType = "Required"
            p_output_loc.enabled = False
            p_output_loc.parameterType = "Optional"
            p_mapper.enabled = False
            p_input_sr.enabled = False
            p_target_sr.enabled = False
            p_export_folder.enabled = True
            p_export_folder.parameterType = "Required"
            p_export_fmt.enabled = True
            p_export_fmt.parameterType = "Required"
            p_gpkg_packaging.parameterType = "Optional"
            p_gpkg_packaging.enabled = (
                (p_export_fmt.valueAsText or "").strip() == "GPKG"
                and len(paths) > 1
            )
            if p_gpkg_packaging.enabled:
                p_gpkg_packaging.filter.type = "ValueList"
                p_gpkg_packaging.filter.list = GPKG_EXPORT_PACKAGING_OPTIONS
                current_packaging = (p_gpkg_packaging.valueAsText or "").strip()
                if current_packaging not in GPKG_EXPORT_PACKAGING_OPTIONS:
                    p_gpkg_packaging.value = GPKG_EXPORT_PACKAGING_COMBINED
            
            # CAD-parametrit näkyvät CAD-viennissä, kun vähintään yksi taso on valittu
            fmt_cad = (p_export_fmt.valueAsText or "").strip() in ("DWG", "DXF")
            p_cad_label.enabled = fmt_cad and has_dwg
            p_cad_emit_table.enabled = fmt_cad and has_dwg
            p_cad_attr_fields.enabled = fmt_cad and has_dwg and bool(p_cad_emit_table.value)
            
            # DFSU-parametrit piilotetaan viennissä
            p_dfsu_filter_en.enabled = False
            p_dfsu_filter_col.enabled = False
            p_dfsu_filter_op.enabled = False
            p_dfsu_filter_val.enabled = False

            if fmt_cad and has_dwg and paths:
                opts = self._common_label_field_options(paths)
                p_cad_label.filter.list = opts
                p_cad_attr_fields.filter.list = opts
                # Jos aiempi arvo ei enää kelpaa, tyhjennä se
                cur = (p_cad_label.valueAsText or "").strip()
                if cur and cur not in opts:
                    p_cad_label.value = None
                cur_multi = self._multi_value_strings(p_cad_attr_fields)
                keep = [x for x in opts if x in cur_multi]
                p_cad_attr_fields.values = keep if keep else None
            else:
                p_cad_label.filter.list = []
                p_cad_attr_fields.filter.list = []
                p_cad_attr_fields.values = None
            
            # DFSU-suodatin pois päältä viennissä
            p_dfsu_filter_en.enabled = False
            p_dfsu_filter_en.value = False
            p_dfsu_filter_col.enabled = False
            p_dfsu_filter_col.filter.list = []
            p_dfsu_filter_op.enabled = False
            p_dfsu_filter_val.enabled = False

        self._last_operation_mode = mode

    def _common_label_field_options(self, export_paths):
        """Palauta valittujen tasojen yhteiset kentät dropdowniin (aakkosjärjestys)."""
        if not export_paths:
            return []
        common_lc = None
        display_by_lc = {}
        skip_types = {"Geometry", "OID", "Blob", "Raster"}
        skip_names_lc = {"shape", "objectid", "fid", "globalid"}

        for p in export_paths:
            try:
                catalog = self._resolve_export_catalog_path(p)
                fields = arcpy.ListFields(catalog)
                desc = arcpy.Describe(catalog)
            except Exception:
                return []
            this_set = set()
            for f in fields:
                nm = getattr(f, "name", None)
                if not nm:
                    continue
                if f.type in skip_types:
                    continue
                nml = nm.lower()
                if nml in skip_names_lc:
                    continue
                this_set.add(nml)
                if nml not in display_by_lc:
                    display_by_lc[nml] = nm
            try:
                if getattr(desc, "OIDFieldName", None):
                    this_set.add("objectid")
                    display_by_lc["objectid"] = "OBJECTID"
            except Exception:
                pass
            if common_lc is None:
                common_lc = this_set
            else:
                common_lc &= this_set

        if not common_lc:
            return []
        out = [display_by_lc[k] for k in sorted(common_lc)]
        return out

    def _read_dfsu_columns(self, dfsu_path):
        """Lue DFSU-sarakkeet; tulos cachetetaan polun+muokkausajan mukaan (UI kutsuu usein)."""
        try:
            mtime = os.path.getmtime(dfsu_path)
        except Exception:
            mtime = "NO_MTIME"
        cache = getattr(self, "_dfsu_col_cache", None)
        if cache is None:
            cache = {}
            self._dfsu_col_cache = cache
        key = (dfsu_path, mtime)
        if key in cache:
            return list(cache[key])
        cols = self._read_dfsu_columns_uncached(dfsu_path)
        if len(cache) >= 50:
            cache.pop(next(iter(cache)))
        cache[key] = list(cols) if cols else []
        return list(cache[key])

    def _read_dfsu_columns_cached_only(self, dfsu_path):
        """Palauta DFSU-sarakkeet vain cachesta ilman tiedostolukua (UI-viiveen minimointi)."""
        try:
            mtime = os.path.getmtime(dfsu_path)
        except Exception:
            mtime = "NO_MTIME"
        cache = getattr(self, "_dfsu_col_cache", None) or {}
        key = (dfsu_path, mtime)
        if key in cache:
            return list(cache[key])
        return []

    def _read_dfsu_columns_uncached(self, dfsu_path):
        """Lue DFSU-tiedoston sarakkeet/attribuutit.

        DFSU on DHI MIKE SHE/FEFLOW -hydrologisen mallin binäärimuoto.
        Yritetään lukea sarakkeiden nimet tiedostosta.

        Returns: lista sarakkeiden/attribuuttien nimistä
        """
        try:
            try:
                import mikeio
                dfs = mikeio.open(dfsu_path)
                cols = []
                for item in getattr(dfs, "items", []) or []:
                    name = getattr(item, "name", None)
                    if name:
                        cols.append(str(name).strip())
                cols = [c for c in cols if c]
                if cols:
                    return cols
            except Exception:
                pass

            columns = []
            
            with open(dfsu_path, 'rb') as f:
                data = f.read(8192)  # Lue riittävä osa headeria
                
                if len(data) < 100:
                    return []
                
                # DFSU-binääri: etsi tekstiosuuksia jotka ovat todennäköisesti sarakkeiden nimiä
                # Erotel ASCII-teksti puusta-ja epäpuhdasta datasta
                text_sections = []
                current_text = b''
                
                for i, byte_val in enumerate(data):
                    # ASCII-tulostettavat merkit (32-126)
                    if 32 <= byte_val <= 126 or byte_val in (9, 10, 13):  # Myös whitespace
                        current_text += bytes([byte_val])
                    else:
                        # Sanaväli: jos keräsimme tekstiä, tallenna se
                        if len(current_text) > 2:
                            try:
                                text_str = current_text.decode('ascii', errors='ignore').strip()
                                if text_str and 3 <= len(text_str) <= 50:
                                    text_sections.append(text_str)
                            except:
                                pass
                        current_text = b''
                
                # Viimeinen teksti
                if len(current_text) > 2:
                    try:
                        text_sections.append(current_text.decode('ascii', errors='ignore').strip())
                    except:
                        pass
                
                # Suodata pois yleiset systemisanat, säilytä todennäköiset sarakkeiden nimet
                exclude = {'system', 'data', 'file', 'header', 'version', 'type', 'item', 'info', 
                          'unit', 'time', 'dfs', 'element', 'node', 'face', 'code', 'name',
                          'none', 'float', 'int', 'double', 'long', 'byte', 'short'}
                
                columns = [s for s in text_sections 
                          if s and s.lower() not in exclude 
                          and not s.isdigit()
                          and not s.replace('.', '').isdigit()  # Ei numeroita desimaalin kanssa
                          and not all(c in '0123456789._-' for c in s)]  # Ei paljoko numeroita
                
                # Säilytä uniikit, max 20
                columns = list(dict.fromkeys(columns))[:20]
            
            if columns:
                return columns
            
            # Fallback: yleiset DFSU-sarakkeet
            return ["Element ID", "X", "Y", "Z", "Value"]
        
        except Exception as e:
            # Jos kaikkea muu epäonnistuu, palauta perus-sarakkeet
            return ["Element ID", "X", "Y", "Z"]

    def _ensure_python_module(self, import_name, package_name=None, messages=None, auto_install=False):
        """Tuo Python-moduuli; haluttaessa yritä asentaa se aktiiviseen Python-ympäristöön."""
        package_name = package_name or import_name
        # ArcGIS Prossa sys.executable voi osoittaa ArcGISPro.exe:hen; etsitään varsinainen python.exe.
        python_cmd = sys.executable or ""
        exe_name = os.path.basename(python_cmd).lower()
        if not exe_name.startswith("python"):
            candidates = []
            if getattr(sys, "exec_prefix", None):
                candidates.append(os.path.join(sys.exec_prefix, "python.exe"))
            if getattr(sys, "prefix", None):
                candidates.append(os.path.join(sys.prefix, "python.exe"))

            for candidate in candidates:
                if candidate and os.path.exists(candidate):
                    python_cmd = candidate
                    break

        if not python_cmd or not os.path.exists(python_cmd):
            python_cmd = "python"

        def _append_path_if_exists(path_value):
            if path_value and os.path.exists(path_value) and path_value not in sys.path:
                sys.path.append(path_value)

        def _prime_site_paths():
            # Nykyisen prosessin tavallisimmat site-packages-polut
            _append_path_if_exists(os.path.join(sys.prefix, "Lib", "site-packages"))
            _append_path_if_exists(os.path.join(sys.exec_prefix, "Lib", "site-packages"))
            try:
                import site
                _append_path_if_exists(site.getusersitepackages())
            except Exception:
                pass

            # Lisäksi haetaan käyttäjä-site juuri siltä Pythonilta, jolla pip ajetaan.
            try:
                usersite_result = subprocess.run(
                    [python_cmd, "-c", "import site; print(site.getusersitepackages())"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if usersite_result.returncode == 0:
                    lines = [x.strip() for x in (usersite_result.stdout or "").splitlines() if x.strip()]
                    if lines:
                        _append_path_if_exists(lines[-1])
            except Exception:
                pass

        # Yritä tuoda ensin normaalisti, sitten path-primeyksen jälkeen.
        try:
            return importlib.import_module(import_name)
        except Exception as first_error:
            _prime_site_paths()
            importlib.invalidate_caches()
            try:
                return importlib.import_module(import_name)
            except Exception:
                if not auto_install:
                    raise first_error

            if messages:
                self.log(messages, f"Puuttuva Python-kirjasto '{package_name}' havaittu. Yritetään asentaa automaattisesti...", "WARNING")
                self.log(messages, "  > Asennus voi kestää tyypillisesti noin 30 sekunnista muutamaan minuuttiin riippuen verkosta ja ympäristön oikeuksista.")
                self.log(messages, f"  > Asennuskomento: {python_cmd} -m pip install {package_name}")

            try:
                result = subprocess.run(
                    [python_cmd, "-m", "pip", "install", "--disable-pip-version-check", package_name],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    raise RuntimeError(f"pip install epäonnistui: {result.stderr}")
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Asennus aikakatkaistiin 5 minuutin jälkeen komennolla '{python_cmd} -m pip install {package_name}'. "
                    f"Yritä asentaa käsin samalla Python-tulkilla."
                )
            except Exception as install_error:
                raise RuntimeError(
                    f"Kirjaston '{package_name}' asennus epäonnistui: {install_error}. "
                    f"Yritä asentaa käsin komennolla: python -m pip install {package_name}"
                )

            if messages:
                pip_text = f"{(result.stdout or '').strip()}\n{(result.stderr or '').strip()}".lower()
                if "requirement already satisfied" in pip_text or "already satisfied" in pip_text:
                    self.log(messages, f"Kirjasto '{package_name}' oli jo asennettuna (pip: requirement already satisfied).")
                else:
                    self.log(messages, f"Kirjasto '{package_name}' asennettiin onnistuneesti.")

            _prime_site_paths()
            importlib.invalidate_caches()
            try:
                return importlib.import_module(import_name)
            except Exception:
                # Varmista erillisessä python-prosessissa, onko paketti oikeasti asennettu.
                verify = subprocess.run(
                    [python_cmd, "-c", f"import {import_name}; print('OK')"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if verify.returncode == 0:
                    raise RuntimeError(
                        f"Kirjasto '{package_name}' on asennettuna, mutta nykyinen ArcGIS Pro -prosessi ei saanut sitä käyttöön. "
                        f"Sulje ArcGIS Pro ja käynnistä se uudelleen, sitten aja työkalu uudestaan."
                    )
                raise RuntimeError(
                    f"Kirjaston '{package_name}' asennus valmistui, mutta tuonti epäonnistui silti. "
                    f"Python-tulkin varmistusvirhe: {(verify.stderr or verify.stdout or '').strip()}"
                )

    def _queue_deferred_cleanup(self, path):
        """Lisää poistettava polku jonoon (siivotaan turvallisesti eräajon lopussa)."""
        p = str(path or "").strip()
        if not p:
            return
        q = getattr(self, "_deferred_cleanup_paths", None)
        if q is None:
            q = []
            self._deferred_cleanup_paths = q
        if p not in q:
            q.append(p)

    def _run_deferred_cleanup(self, messages):
        """Poista jonossa olevat väliaikaiset aineistot. Suunniteltu kutsuttavaksi ajon lopussa."""
        q = list(getattr(self, "_deferred_cleanup_paths", []) or [])
        if not q:
            return
        self._deferred_cleanup_paths = []
        removed = 0
        for p in q:
            try:
                if arcpy.Exists(p):
                    arcpy.management.Delete(p)
                    removed += 1
            except Exception:
                # Ei kaadeta ajoa siivousvirheeseen.
                pass
        if removed:
            self.log(messages, f"  > Siivottiin {removed} väliaikaista CAD-aineistoa ajon lopussa.")

    def updateMessages(self, parameters):
        p_mode = parameters[0]
        p_input = parameters[1]
        p_export_folder = parameters[6]
        p_export_fmt = parameters[7]
        p_cad_label = parameters[8]
        p_cad_emit_table = parameters[9]
        p_cad_attr_fields = parameters[10]
        p_export_layers = parameters[15]
        p_gpkg_packaging = parameters[16]
        
        mode = (p_mode.valueAsText or "Tuonti").strip()
        is_import = mode.startswith("Tuonti")
        
        selection_param = p_input if is_import else p_export_layers
        raw_paths = self._input_paths_from_param(selection_param)
        if is_import:
            paths = raw_paths
            import_paths = self._expand_import_paths(paths, use_cache=True)
        else:
            paths = self._export_paths_from_param(p_export_layers, raw_paths)
            import_paths = []
        # Tuontitilassa vältetään raskaat Describe-kutsut UI-vaiheessa (sujuvampi drag/drop).
        if not is_import:
            if self._bulk_export_mode(paths) != "export":
                p_export_layers.setErrorMessage(
                    "Älä sekoita tuontitiedostoja ja vientitason valintoja samaan ajoon — valitse joko pelkkiä tiedostoja "
                    "tai pelkkiä tasoja/feature classeja."
                )
                return
        if not paths:
            return
        
        # VIENTI-VALIDOINTI
        if not is_import:
            p6t = (p_export_folder.valueAsText or "").strip()
            if not p6t:
                p_export_folder.setErrorMessage("Valitse vientikansio (esim. C:\\Data\\Vienti).")
                return
            if not os.path.isdir(p6t):
                p_export_folder.setErrorMessage("Polun pitää olla olemassa oleva kansio.")
                return
            fmt = (p_export_fmt.valueAsText or "").strip()
            if fmt and fmt not in EXPORT_FORMAT_TO_EXT:
                p_export_fmt.setErrorMessage("Valitse tuettu vientiformaatti listasta.")
            if fmt == "GPKG" and len(paths) > 1:
                packaging = (p_gpkg_packaging.valueAsText or "").strip()
                if packaging not in GPKG_EXPORT_PACKAGING_OPTIONS:
                    p_gpkg_packaging.setErrorMessage(
                        "Valitse, viedäänkö kaikki tasot samaan GPKG-tiedostoon "
                        "vai tehdäänkö jokaiselle oma GPKG."
                    )
                    return
            cad_lbl = (p_cad_label.valueAsText or "").strip()
            emit_attr_tbl = bool(p_cad_emit_table.value)
            attr_fields = self._multi_value_strings(p_cad_attr_fields) if emit_attr_tbl else []
            if fmt in ("DWG", "DXF") and cad_lbl:
                for pv in paths:
                    try:
                        catalog = self._resolve_export_catalog_path(pv)
                        if not self._cad_resolve_field_name(catalog, cad_lbl):
                            p_cad_label.setErrorMessage(
                                f"Kenttää '{cad_lbl}' ei löydy tasosta '{pv}'. Käytä samaa labelkentän nimeä "
                                "kaikissa tasossa tai tyhjennä parametri."
                            )
                            return
                    except Exception as e:
                        p_cad_label.setErrorMessage(f"Labelkentän tarkistus epäonnistui ({pv}): {e}")
                        return
            if fmt in ("DWG", "DXF") and emit_attr_tbl and not attr_fields:
                p_cad_attr_fields.setErrorMessage("Valitse vähintään yksi kenttä DWG-taulukkoon.")
                return
            if fmt in ("DWG", "DXF") and emit_attr_tbl and attr_fields:
                for pv in paths:
                    try:
                        catalog = self._resolve_export_catalog_path(pv)
                        miss = [f for f in attr_fields if not self._cad_resolve_field_name(catalog, f)]
                        if miss:
                            p_cad_attr_fields.setErrorMessage(
                                f"Tasosta '{pv}' puuttuu kenttä(t): {', '.join(miss)}"
                            )
                            return
                    except Exception as e:
                        p_cad_attr_fields.setErrorMessage(f"Attribuuttikenttien tarkistus epäonnistui ({pv}): {e}")
                        return
            for pv in paths:
                try:
                    d = arcpy.Describe(pv)
                    dt = (d.dataType or "").upper()
                    if dt not in ("FEATURECLASS", "FEATURELAYER", "SHAPEFILE"):
                        p_export_layers.setErrorMessage(
                            f"Vienti — '{pv}': tyyppi ei ole pisteviiva/alue (nykyinen tyyppi: {d.dataType})."
                        )
                        return
                    if not getattr(d, "shapeFieldName", None):
                        p_export_layers.setErrorMessage(
                            f"Vienti — '{pv}': geometriaa ei ole (pelkkä taulu ei kelpaa)."
                        )
                        return
                except Exception as e:
                    p_export_layers.setErrorMessage(f"Syötettä ei voitu tulkita tasoksi ({pv}): {e}")
        
        # TUONTI-VALIDOINTI
        else:
            for pv in paths:
                if self._is_supported_import_catalog_path(pv):
                    continue
                if os.path.isdir(pv):
                    folder_files = self._list_supported_import_files(pv)
                    if not folder_files:
                        p_input.setErrorMessage(
                            f"Tuonti: kansiosta '{pv}' ei löytynyt tuettuja tiedostoja ({', '.join(IMPORT_FILE_EXTENSIONS)})."
                        )
                        return
                    continue
                ext = os.path.splitext(pv)[1].lower()
                if ext and ext not in IMPORT_FILE_EXTENSIONS:
                    p_input.setErrorMessage(
                        "Tuonti: valitse tuettu tiedosto tai kansio (esim. "
                        + ", ".join(IMPORT_FILE_EXTENSIONS)
                        + ")."
                    )
                    return
            # Kansiosyöte on jo laajennettu tiedostoiksi, jotta myös alikansioiden
            # DFSU-tiedostot saavat saman validoinnin kuin yksittäin valitut tiedostot.
            if any(str(p).lower().endswith(".dfsu") for p in import_paths):
                dfsu_filter_enabled = bool(parameters[11].value)
                dfsu_filter_column = (parameters[12].valueAsText or "").strip()
                if dfsu_filter_enabled and not dfsu_filter_column:
                    parameters[12].setErrorMessage("Valitse DFSU-suodattimelle sarake.")
                    return

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        p_input = parameters[1]  # Input file/layer is now at index 1 (after mode parameter)
        p_export_layers = parameters[15]
        mode_param = (parameters[0].valueAsText or "Tuonti").strip()
        is_import_mode = mode_param.startswith("Tuonti")
        selection_param = p_input if is_import_mode else p_export_layers
        raw_paths = self._input_paths_from_param(selection_param)
        paths = raw_paths if is_import_mode else self._export_paths_from_param(p_export_layers, raw_paths)
        if not paths:
            self.log(messages, "Syöte puuttuu (valitse vähintään yksi tiedosto tai taso).", "ERROR")
            return

        if is_import_mode:
            detected_mode = self._bulk_operation_mode(paths)
            if detected_mode == "mixed":
                self.log(
                    messages,
                    "Sekoitettu syöte: älä yhdistä tuontitiedostoja ja vientitasoja samaan ajoon.",
                    "ERROR",
                )
                return
            if detected_mode != "import":
                self.log(messages, "Tuonti-tilassa syötteen pitää olla tiedostoja tai kansioita.", "ERROR")
                return
        elif self._bulk_export_mode(paths) != "export":
            self.log(messages, "Vienti-tilassa syötteen pitää olla karttatasoja tai feature classeja.", "ERROR")
            return

        if is_import_mode:
            self._execute_import(parameters, messages, paths)
        else:
            self._execute_export(parameters, messages, paths)
        return

    def _input_paths_from_param(self, param):
        """Monivalintaparametrin arvot listana (tyhjät pois)."""
        out = []
        try:
            vals = getattr(param, "values", None)
            if vals is not None:
                if isinstance(vals, (list, tuple)):
                    for v in vals:
                        if v is None:
                            continue
                        s = str(v).strip()
                        if s:
                            out.append(s)
        except Exception:
            pass
        if not out and param.valueAsText:
            for s in param.valueAsText.split(";"):
                s = s.strip()
                if s:
                    out.append(s)
        return out

    def _configure_export_layer_choices(self, param, previous_values=None):
        """Täytä vientiparametrin checkbox-lista aktiivisen kartan tasoilla.

        Parametrin arvot ovat käyttöliittymässä tasojen nimiä, mutta vientiin
        palautetaan niiden catalogPath-polut. Näin pitkä GDB-polku ei täytä
        valintalistaa ja samannimiset tasot voidaan silti näyttää erillisinä
        vaihtoehtoina.
        """
        if previous_values is None:
            previous_values = self._input_paths_from_param(param)

        options = self._list_export_layer_options()
        labels = [label for label, _source in options]
        self._export_layer_sources = {label: source for label, source in options}

        try:
            param.filter.type = "ValueList"
            param.filter.list = labels
        except Exception:
            pass

        # Säilytä jo tehdyt valinnat, jos karttaa tai parametria päivitetään.
        # Ensimmäisellä vientitilaan siirtymisellä lista jätetään tyhjäksi,
        # jotta käyttäjä päättää itse vietävät tasot.
        selected_labels = []
        source_to_label = {}
        for label, source in options:
            source_to_label.setdefault(self._export_path_key(source), label)
        label_set = set(labels)
        for value in previous_values or []:
            value = str(value).strip()
            if not value:
                continue
            if value in label_set:
                label = value
            else:
                label = source_to_label.get(self._export_path_key(value))
            if label and label not in selected_labels:
                selected_labels.append(label)

        try:
            param.values = selected_labels if selected_labels else None
        except Exception:
            pass

        return [self._export_layer_sources[label] for label in selected_labels]

    def _list_export_layer_options(self):
        """Palauta aktiivisen kartan vietävät feature layerit TOC-järjestyksessä."""
        options = []
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = getattr(aprx, "activeMap", None)
            maps = [active_map] if active_map else list(aprx.listMaps() or [])
        except Exception:
            return options

        for current_map in maps:
            if not current_map:
                continue
            try:
                layers = current_map.listLayers()
            except Exception:
                continue
            self._collect_export_layer_options(layers, (), options)

        # Varmista uniikit näytettävät nimet myös silloin, kun kaksi tasoa on
        # samanniminen tai sama taso on lisätty kartalle useammin kuin kerran.
        used = {}
        unique_options = []
        for base_label, source in options:
            base_label = base_label or "Taso"
            count = used.get(base_label, 0) + 1
            used[base_label] = count
            label = base_label if count == 1 else f"{base_label} ({count})"
            while any(existing == label for existing, _ in unique_options):
                count += 1
                used[base_label] = count
                label = f"{base_label} ({count})"
            unique_options.append((label, source))
        return unique_options

    def _collect_export_layer_options(self, layers, parents, output):
        """Kerää feature layerit myös ryhmäkerrosten sisältä."""
        for layer in layers or []:
            try:
                if getattr(layer, "isGroupLayer", False):
                    group_name = str(getattr(layer, "name", "") or "").strip()
                    try:
                        children = layer.listLayers()
                    except Exception:
                        children = []
                    self._collect_export_layer_options(
                        children,
                        parents + ((group_name,) if group_name else ()),
                        output,
                    )
                    continue
                if getattr(layer, "isBasemapLayer", False) or getattr(layer, "isBroken", False):
                    continue
            except Exception:
                continue

            name = str(getattr(layer, "name", "") or "").strip()
            if not name:
                name = "Taso"

            is_feature_layer = bool(getattr(layer, "isFeatureLayer", False))
            desc = None
            if not is_feature_layer:
                try:
                    desc = arcpy.Describe(layer)
                    data_type = (getattr(desc, "dataType", "") or "").upper()
                    is_feature_layer = data_type in ("FEATURELAYER", "FEATURECLASS", "SHAPEFILE")
                except Exception:
                    is_feature_layer = False
            if not is_feature_layer:
                continue

            source = ""
            try:
                if desc is None:
                    desc = arcpy.Describe(layer)
                source = str(getattr(desc, "catalogPath", "") or "").strip()
            except Exception:
                pass
            if not source:
                try:
                    source = str(getattr(layer, "dataSource", "") or "").strip()
                except Exception:
                    source = ""
            if not source:
                # Layer-nimi toimii viimeisenä fallbackina, koska aktiivisen
                # kartan layerit voidaan yleensä ratkaista ArcPyssa nimellä.
                source = name

            path_parts = tuple(part for part in parents if part)
            display_name = " / ".join(path_parts + (name,))
            output.append((display_name, source))

    def _export_path_key(self, value):
        """Normalisoi paikallisen polun vaihtoehtojen säilytystä varten."""
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return os.path.normcase(os.path.normpath(text))
        except Exception:
            return text.casefold()

    def _export_paths_from_param(self, param, values=None):
        """Muunna checkbox-listan näyttöarvot vientiin käytettäviksi poluiksi."""
        if values is None:
            values = self._input_paths_from_param(param)
        sources = getattr(self, "_export_layer_sources", {}) or {}
        if any(str(value).strip() not in sources for value in values if str(value).strip()):
            # Normaalisti lista rakennetaan updateParameters()-kutsussa, mutta
            # fallback tekee suorituksesta kestävän myös silloin, kun työkalu
            # käynnistetään suoraan ilman edeltävää UI-päivitystä.
            sources = dict(sources)
            for label, source in self._list_export_layer_options():
                sources.setdefault(label, source)
        return [sources.get(str(value).strip(), str(value).strip()) for value in values if str(value).strip()]

    def _list_supported_import_files(self, folder_path):
        """Palauta kansion ja sen alikansioiden tuetut tuontitiedostot.

        Skannaus palauttaa vain varsinaiset aineistotiedostot. Esimerkiksi
        Shapefilen .dbf/.shx/.prj-sivutiedostoja ei palauteta erillisinä
        syötteinä, koska tuonti käynnistetään aina .shp-tiedostosta.
        """
        try:
            root = os.path.abspath(os.path.normpath(str(folder_path).strip()))
        except Exception:
            return []

        if not os.path.isdir(root):
            return []

        out = []
        try:
            for current_root, dir_names, file_names in os.walk(
                root, topdown=True, followlinks=False
            ):
                # Vakioitu järjestys tekee eräajosta toistettavan ja helpottaa
                # lokin vertaamista seuraavilla ajoilla.
                dir_names.sort(key=lambda value: (str(value).casefold(), str(value)))
                file_names.sort(key=lambda value: (str(value).casefold(), str(value)))

                for file_name in file_names:
                    extension = os.path.splitext(file_name)[1].lower()
                    if extension not in IMPORT_FILE_EXTENSIONS:
                        continue
                    full_path = os.path.join(current_root, file_name)
                    try:
                        if os.path.isfile(full_path):
                            out.append(full_path)
                    except OSError:
                        # Yksittäinen lukukelvoton/poistunut tiedosto ei estä
                        # muun kansion käsittelyä.
                        continue
        except (OSError, IOError):
            return []

        # os.walk tuottaa jo järjestetyn tuloksen, mutta järjestetään vielä
        # suhteellisen polun mukaan, jotta eri käyttöjärjestelmät käyttäytyvät
        # samalla tavalla.
        out.sort(
            key=lambda value: (
                os.path.relpath(value, root).casefold(),
                os.path.relpath(value, root),
            )
        )
        return out

    def _expand_import_paths(self, paths, use_cache=False):
        """Laajenna kansiosyötteet tuettuihin tiedostoihin ilman duplikaatteja.

        ``use_cache`` on tarkoitettu ArcGIS Pron parametripäivityksiin, joita
        kutsutaan useita kertoja saman valinnan aikana. Ajon yhteydessä cache
        ohitetaan, jotta kansio luetaan aina uudelleen.
        """
        cache_key = tuple(str(p).strip() for p in (paths or []) if str(p).strip())
        if use_cache and cache_key == self._import_expansion_cache_key:
            return list(self._import_expansion_cache_value or [])

        expanded = []
        seen = set()
        for p in paths or []:
            p = str(p).strip()
            if not p:
                continue
            if os.path.isdir(p):
                candidates = self._list_supported_import_files(p)
            else:
                candidates = [p]

            for candidate in candidates:
                candidate = str(candidate).strip()
                if not candidate:
                    continue
                try:
                    identity = os.path.normcase(
                        os.path.realpath(os.path.abspath(candidate))
                    )
                except Exception:
                    identity = candidate.casefold()
                if identity in seen:
                    continue
                seen.add(identity)
                expanded.append(candidate)

        if use_cache:
            self._import_expansion_cache_key = cache_key
            self._import_expansion_cache_value = list(expanded)
        return expanded

    def _multi_value_strings(self, param):
        """Palauta GPString-multivalue valinnat listana työkalun listajärjestyksessä."""
        vals = []
        try:
            raw = getattr(param, "values", None)
            if isinstance(raw, (list, tuple)):
                for v in raw:
                    s = "" if v is None else str(v).strip()
                    if s:
                        vals.append(s)
        except Exception:
            pass
        if not vals and (param.valueAsText or "").strip():
            for s in param.valueAsText.split(";"):
                s = s.strip()
                if s:
                    vals.append(s)
        if not vals:
            return vals
        ordered = []
        seen = set()
        try:
            filter_list = list(getattr(getattr(param, "filter", None), "list", []) or [])
        except Exception:
            filter_list = []
        lower_lookup = {str(v).strip().lower(): str(v).strip() for v in vals if str(v).strip()}
        for item in filter_list:
            key = str(item).strip().lower()
            if key in lower_lookup and key not in seen:
                ordered.append(lower_lookup[key])
                seen.add(key)
        for item in vals:
            key = str(item).strip().lower()
            if key and key not in seen:
                ordered.append(str(item).strip())
                seen.add(key)
        return ordered

    def _path_contains_extension(self, value_text, extensions):
        s = str(value_text or "").lower().replace("/", "\\")
        for ext in extensions:
            if s.endswith(ext) or (ext + "\\") in s:
                return True
        return False

    def _is_supported_import_catalog_path(self, value_text):
        """True for files and ArcGIS catalog paths that the import branch can copy/read."""
        p = str(value_text or "").strip()
        if not p:
            return False
        if os.path.isdir(p):
            return bool(self._list_supported_import_files(p))
        ext = os.path.splitext(p)[1].lower()
        if ext in IMPORT_FILE_EXTENSIONS:
            return True
        if self._path_contains_extension(p, (".gpkg", ".shp", ".dwg", ".dxf")):
            return True
        try:
            d = arcpy.Describe(p)
            dt = (getattr(d, "dataType", "") or "").upper()
            catalog_path = getattr(d, "catalogPath", "") or p
            if self._path_contains_extension(catalog_path, (".gpkg", ".shp", ".dwg", ".dxf")):
                return True
            if "CAD" in dt:
                return True
        except Exception:
            pass
        return False

    def _classify_export_import_path(self, p):
        """Yksittäinen syöte: 'import' (tiedostopääte) tai 'export' (FC/taso) tai 'other'."""
        if self._is_supported_import_catalog_path(p):
            return "import"
        try:
            d = arcpy.Describe(p)
            dt = (d.dataType or "").upper()
            if dt in ("FEATURECLASS", "FEATURELAYER", "SHAPEFILE"):
                return "export"
        except Exception:
            pass
        return "other"

    def _bulk_operation_mode(self, paths):
        """'empty' | 'import' | 'export' | 'mixed' — kaikkien syötteiden yhteinen tila."""
        if not paths:
            return "empty"
        kinds = [self._classify_export_import_path(p) for p in paths]
        has_imp = any(k == "import" for k in kinds)
        has_exp = any(k == "export" for k in kinds)
        if has_imp and has_exp:
            return "mixed"
        if has_imp and not has_exp:
            if all(k == "import" for k in kinds):
                return "import"
            return "mixed"
        if has_exp and not has_imp:
            if all(k == "export" for k in kinds):
                return "export"
            return "mixed"
        return "mixed"

    def _classify_export_path(self, path):
        """Tarkista, onko polku geometrinen feature class/layer vientiä varten."""
        try:
            desc = arcpy.Describe(path)
            data_type = (getattr(desc, "dataType", "") or "").upper()
            if data_type not in ("FEATURECLASS", "FEATURELAYER", "SHAPEFILE"):
                return "other"
            return "export" if getattr(desc, "shapeFieldName", None) else "other"
        except Exception:
            return "other"

    def _bulk_export_mode(self, paths):
        """Palauta 'empty', 'export' tai 'other' vientiin annetuista poluista."""
        if not paths:
            return "empty"
        kinds = [self._classify_export_path(path) for path in paths]
        return "export" if all(kind == "export" for kind in kinds) else "other"

    def _gpkg_export_packaging_from_param(self, param, input_count):
        """Palauta usean tason GPKG-viennin paketointitapa.

        Yhden tason viennissä valinta ei vaikuta toimintaan. Puuttuva arvo
        käyttää nykyistä oletusta eli kaikkien tasojen yhteistä pakettia.
        """
        if input_count <= 1:
            return GPKG_EXPORT_PACKAGING_COMBINED
        try:
            value = (getattr(param, "valueAsText", None) or "").strip()
        except Exception:
            value = ""
        if value in GPKG_EXPORT_PACKAGING_OPTIONS:
            return value
        return GPKG_EXPORT_PACKAGING_COMBINED

    def _export_combined_stamp_label(self, paths):
        """Tiedostonimi monelle lähteelle (lyhyt yhdistelmä)."""
        if not paths:
            return "export"
        if len(paths) == 1:
            return self._export_source_label(paths[0])
        chunks = []
        for p in paths[:5]:
            chunks.append(self.sanitize_name(self._export_source_label(p))[:22] or "lyr")
        base = "_".join(chunks)[:42]
        if len(paths) > 5:
            base = (base + f"_+{len(paths) - 5}")[:48]
        suffix = "_multi"
        base = (base + suffix)[:50]
        return base or "export_multi"

    def _is_import_mode(self, value_text):
        """True = tiedostotuonti, False = vienti (taso / feature class)."""
        if not value_text:
            return True
        ext = os.path.splitext(value_text.strip())[1].lower()
        if ext in IMPORT_FILE_EXTENSIONS:
            return True
        try:
            d = arcpy.Describe(value_text)
            dt = (d.dataType or "").upper()
            if dt in ("FEATURECLASS", "FEATURELAYER", "SHAPEFILE"):
                return False
            # Ei tuontitiedosto — vientihaara (updateMessages torjuu jos ei geometriaa)
            if dt in ("TABLE", "RASTERDATASET", "RASTERLAYER", "RASTERBAND", "MOSAICDATASET"):
                return False
        except Exception:
            pass
        return True

    def _execute_import(self, parameters, messages, input_paths=None):
        if input_paths is None:
            input_paths = self._input_paths_from_param(parameters[1])  # Index shifted from 0 to 1
        raw_input_paths = list(input_paths or [])
        input_paths = self._expand_import_paths(raw_input_paths)
        output_loc = parameters[2].valueAsText  # Index shifted from 1 to 2
        use_mapper = parameters[3].value  # Index shifted from 2 to 3
        input_sr = self._parse_input_sr(parameters[4].valueAsText)  # Index shifted from 3 to 4
        target_sr = self._spatial_ref_from_param(parameters[5].value)  # Index shifted from 4 to 5
        
        # DFSU suodatin parametrit
        dfsu_filter_enabled = bool(parameters[11].value)  # New
        dfsu_filter_column = (parameters[12].valueAsText or "").strip()  # New
        dfsu_filter_operator = (parameters[13].valueAsText or "=").strip()  # New
        dfsu_filter_value = (parameters[14].valueAsText or "").strip()  # New

        # Oletussijainti
        if not output_loc:
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                output_loc = aprx.defaultGeodatabase
            except Exception:
                output_loc = arcpy.env.scratchGDB

        desc = arcpy.Describe(output_loc)
        is_folder = (desc.dataType == "Folder" or desc.workspaceType == "FileSystem")
        self.log(messages, f"Tuonti — kohde: {output_loc}")
        
        # Tarkista onko DFSU-tiedostoja ja asenna mikeio kerran alussa
        has_dfsu = any(f.lower().endswith('.dfsu') for f in input_paths)
        if has_dfsu:
            try:
                self._ensure_python_module("mikeio", package_name="mikeio", messages=messages, auto_install=True)
            except Exception as e:
                self.log(messages, f"DFSU-asennus epäonnistui: {str(e)}", "ERROR")
                raise
        
        for raw_path in raw_input_paths:
            if os.path.isdir(raw_path):
                folder_files = self._list_supported_import_files(raw_path)
                self.log(
                    messages,
                    f"Tuonti — kansio '{raw_path}' skannattu alikansioineen: "
                    f"{len(folder_files)} tuettua tiedostoa.",
                )
        if not input_paths:
            self.log(messages, "Tuonti: valituista kansioista/tiedostoista ei löytynyt käsiteltäviä tuontitiedostoja.", "ERROR")
            return
        if len(input_paths) > 1:
            self.log(messages, f"Tuonti — {len(input_paths)} tiedostoa peräkkäin.")

        try:
            for idx, input_path in enumerate(input_paths, 1):
                if len(input_paths) > 1:
                    self.log(messages, f"Tuonti — ({idx}/{len(input_paths)}) {input_path}")
                try:
                    ext = os.path.splitext(input_path)[1].lower()

                    if ext == ".gpkg":
                        self.process_geopackage(input_path, output_loc, is_folder, messages)
                    elif ext in [".geojson", ".json"]:
                        self.process_geojson_flattened(input_path, output_loc, is_folder, messages)
                    elif ext in [".kml", ".kmz"]:
                        self.process_kml_flattened(input_path, output_loc, is_folder, messages)
                    elif ext == ".gpx":
                        self.process_gpx_flattened(input_path, output_loc, is_folder, messages)
                    elif ext == ".dfsu":
                        # DFSU tuonti suodattimella
                        self.process_dfsu(input_path, output_loc, is_folder, messages,
                                        filter_enabled=dfsu_filter_enabled,
                                        filter_column=dfsu_filter_column,
                                        filter_operator=dfsu_filter_operator,
                                        filter_value=dfsu_filter_value,
                                        target_sr=target_sr)
                    elif ext in [".dwg", ".dxf"]:
                        self.process_cad(input_path, output_loc, is_folder, use_mapper, input_sr, target_sr, messages)
                    else:
                        self.process_generic(input_path, output_loc, is_folder, messages)

                except Exception as e:
                    self.log(messages, f"Kriittinen virhe (tiedosto {input_path}): {str(e)}", "ERROR")
                    messages.addErrorMessage(traceback.format_exc())
                    raise
        finally:
            self._run_deferred_cleanup(messages)

    def _execute_export(self, parameters, messages, input_paths=None):
        """Vienti: yksi tai useampi ArcGIS-taso / FC → tiedosto(t) vientikansioon."""
        if input_paths is None:
            input_param = parameters[15]
            input_paths = self._export_paths_from_param(
                input_param,
                self._input_paths_from_param(input_param),
            )  # Index shifted from 0 to 1
        folder = (parameters[6].valueAsText or "").strip()  # Index shifted from 5 to 6
        fmt = (parameters[7].valueAsText or "GPKG").strip()  # Index shifted from 6 to 7
        target_sr = self._spatial_ref_from_param(parameters[5].value)  # Index shifted from 4 to 5
        gpkg_packaging = self._gpkg_export_packaging_from_param(
            parameters[16] if len(parameters) > 16 else None,
            len(input_paths),
        )

        if not folder:
            self.log(messages, "Vientikansio puuttuu.", "ERROR")
            return
        if fmt not in EXPORT_FORMAT_TO_EXT:
            self.log(messages, f"Tuntematon vientiformaatti: {fmt}", "ERROR")
            return
        folder = os.path.realpath(folder)
        if not os.path.isdir(folder):
            self.log(messages, f"Vientikansio ei ole olemassa tai ei ole hakemisto: {folder}", "ERROR")
            return

        combined_label = self._export_combined_stamp_label(input_paths)
        separate_gpkg = (
            fmt == "GPKG"
            and len(input_paths) > 1
            and gpkg_packaging == GPKG_EXPORT_PACKAGING_SEPARATE
        )
        out_path = None if separate_gpkg else self._unique_export_path(
            self._build_export_path_in_folder(folder, fmt, combined_label)
        )

        cad_label_field = ""
        use_map_symbology = True  # aina päällä
        cad_text_height = 10.0    # aina 10
        emit_attr_table = False
        attr_text_fields = []
        try:
            cad_label_field = (parameters[8].valueAsText or "").strip()  # Index shifted from 7 to 8
            emit_attr_table = bool(parameters[9].value) if len(parameters) > 9 else False  # Index shifted from 8 to 9
            if emit_attr_table and len(parameters) > 10:  # Updated length check
                attr_text_fields = self._multi_value_strings(parameters[10])  # Index shifted from 9 to 10
        except Exception:
            pass

        self.log(messages, "Vienti — lähteet: " + "; ".join(input_paths))
        self.log(messages, f"Vienti — kansio: {folder}")
        if separate_gpkg:
            self.log(messages, "Vienti — formaatti: GPKG → oma tiedosto jokaiselle tasolle")
        else:
            self.log(messages, f"Vienti — formaatti: {fmt} → {os.path.basename(out_path)}")
        if len(input_paths) > 1:
            if fmt == "GPKG":
                packaging_label = (
                    "oma GPKG jokaiselle tasolle"
                    if separate_gpkg
                    else "kaikki tasot samaan GPKG-tiedostoon"
                )
                self.log(messages, f"  > Tasoja valittuna: {len(input_paths)} ({packaging_label}).")
            else:
                self.log(messages, f"  > Tasoja valittuna: {len(input_paths)} (yksi tiedosto tasoa kohden).")

        try:
            written_paths = []
            fc_pairs = []

            if fmt in ("DWG", "DXF"):
                for in_src in input_paths:
                    fc_pairs.append((self._prepare_export_feature_class(in_src, target_sr, messages), in_src))
                written_paths = [
                    self._export_to_cad(
                        fc_pairs,
                        out_path,
                        messages,
                        cad_label_field=cad_label_field,
                        use_map_symbology=use_map_symbology,
                        cad_text_height=cad_text_height,
                        emit_attr_table=emit_attr_table,
                        attr_text_fields=attr_text_fields,
                    )
                ]

            elif len(input_paths) == 1:
                in_src = input_paths[0]
                fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                src_one = self._export_source_label(in_src)
                if fmt == "GeoJSON":
                    written_paths = [self._export_to_geojson(fc_work, out_path, messages)]
                elif fmt == "Shapefile":
                    written_paths = [self._export_to_shapefile(fc_work, out_path, messages)]
                elif fmt == "GPKG":
                    written_paths = [self._export_to_geopackage(fc_work, out_path, messages, source_label=src_one)]
                elif fmt in ("KML", "KMZ"):
                    written_paths = [self._export_to_kml(fc_work, out_path, messages)]
                else:
                    self.log(messages, f"Tuntematon vientiformaatti: {fmt}", "ERROR")
                    return

            else:
                if fmt == "GPKG":
                    written_paths = []
                    if separate_gpkg:
                        for in_src in input_paths:
                            fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                            sub_src = self._export_source_label(in_src)
                            out_one = self._unique_export_path(
                                self._build_export_path_in_folder(folder, "GPKG", sub_src)
                            )
                            written_paths.append(
                                self._export_to_geopackage(fc_work, out_one, messages, source_label=sub_src)
                            )
                    else:
                        for in_src in input_paths:
                            fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                            sub_src = self._export_source_label(in_src)
                            written_paths.append(
                                self._export_to_geopackage(fc_work, out_path, messages, source_label=sub_src)
                            )

                elif fmt == "GeoJSON":
                    for in_src in input_paths:
                        fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                        sub_nm = self.sanitize_name(self._export_source_label(in_src))[:35] or "layer"
                        out_one = self._unique_export_path(
                            self._build_export_path_in_folder(folder, fmt, combined_label + "_" + sub_nm)
                        )
                        written_paths.append(self._export_to_geojson(fc_work, out_one, messages))
                elif fmt == "Shapefile":
                    for in_src in input_paths:
                        fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                        sub_nm = self.sanitize_name(self._export_source_label(in_src))[:35] or "layer"
                        out_one = self._unique_export_path(
                            self._build_export_path_in_folder(folder, fmt, combined_label + "_" + sub_nm)
                        )
                        written_paths.append(self._export_to_shapefile(fc_work, out_one, messages))
                elif fmt in ("KML", "KMZ"):
                    for in_src in input_paths:
                        fc_work = self._prepare_export_feature_class(in_src, target_sr, messages)
                        sub_nm = self.sanitize_name(self._export_source_label(in_src))[:35] or "layer"
                        out_one = self._unique_export_path(
                            self._build_export_path_in_folder(folder, fmt, combined_label + "_" + sub_nm)
                        )
                        written_paths.append(self._export_to_kml(fc_work, out_one, messages))
                else:
                    self.log(messages, f"Tuntematon vientiformaatti: {fmt}", "ERROR")
                    return

            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                if aprx.activeMap and written_paths:
                    for wp in written_paths:
                        try:
                            if wp and os.path.exists(str(wp)):
                                aprx.activeMap.addDataFromPath(wp)
                            elif wp:
                                try:
                                    if arcpy.Exists(wp):
                                        aprx.activeMap.addDataFromPath(wp)
                                except Exception:
                                    pass
                        except Exception:
                            pass
            except Exception:
                pass

        except Exception as e:
            self.log(messages, f"Vientivirhe: {str(e)}", "ERROR")
            messages.addErrorMessage(traceback.format_exc())
            raise

    def _resolve_export_catalog_path(self, in_src):
        """Palauttaa polun feature classiin (ei layer-nimeä ilman polkua)."""
        d = arcpy.Describe(in_src)
        if d.dataType == "FeatureLayer" and getattr(d, "catalogPath", None):
            return d.catalogPath
        return in_src

    def _export_source_label(self, in_src):
        """Lyhyt nimi tiedostonimeä varten (taso / FC)."""
        try:
            d = arcpy.Describe(in_src)
            nm = getattr(d, "name", None) or ""
            if nm:
                return nm
            cp = getattr(d, "catalogPath", None) or ""
            if cp:
                return os.path.splitext(os.path.basename(cp))[0]
        except Exception:
            pass
        return os.path.basename(str(in_src).split("\\")[-1].split("/")[-1]) or "export"

    def _build_export_path_in_folder(self, folder, fmt, src_label):
        """Koko polku vientitiedostoon: kansio + pääte + aikaleima (ei koskaan tyhjennä vanhaa automaattisesti)."""
        ext = EXPORT_FORMAT_TO_EXT[fmt]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.sanitize_name(src_label or "export")[:50].strip("_") or "export"
        fname = f"{base}_{stamp}"
        return os.path.normpath(os.path.join(folder, fname + ext))

    def _unique_export_path(self, path):
        """Jos sama polku jo olemassa, lisää _2, _3, …"""
        if not os.path.exists(path) and not arcpy.Exists(path):
            return path
        root, ext = os.path.splitext(path)
        n = 2
        while n < 10000:
            cand = f"{root}_{n}{ext}"
            if not os.path.exists(cand) and not arcpy.Exists(cand):
                return cand
            n += 1
        return path

    def _spatial_ref_from_param(self, value):
        """GPCoordinateSystem-parametrin arvo voi olla ValueObject ilman factoryCode — normalisoidaan."""
        if value is None:
            return None
        if isinstance(value, arcpy.SpatialReference):
            return value
        txt = None
        try:
            if hasattr(value, "WKT"):
                txt = getattr(value, "WKT", None)
        except Exception:
            pass
        if not txt:
            try:
                txt = str(value)
            except Exception:
                return None
        txt = (txt or "").strip()
        if not txt or txt.lower() in ("none", "<null>"):
            return None
        try:
            sr = arcpy.SpatialReference()
            sr.loadFromString(txt)
            return sr
        except Exception:
            try:
                return arcpy.SpatialReference(txt)
            except Exception:
                return None

    def _sr_factory_code(self, sr):
        if sr is None:
            return None
        try:
            return int(sr.factoryCode)
        except Exception:
            return None

    def _prepare_export_feature_class(self, in_src, target_sr, messages):
        """Kopio scratchGDB:hen (ei muokata lähdettä), valinnainen projisointi."""
        scratch = arcpy.env.scratchGDB
        stamp = datetime.datetime.now().strftime("%H%M%S")
        base_name = f"muuntaja_vienti_{stamp}"
        out_fc = os.path.join(scratch, base_name)

        catalog = self._resolve_export_catalog_path(in_src)
        if arcpy.Exists(out_fc):
            arcpy.management.Delete(out_fc)
        arcpy.management.CopyFeatures(catalog, out_fc)

        desc = arcpy.Describe(catalog)
        src_sr = getattr(desc, "spatialReference", None)
        tgt_sr = self._spatial_ref_from_param(target_sr) if target_sr is not None else None

        if tgt_sr and src_sr and getattr(src_sr, "name", "") != "Unknown":
            try:
                c_src = self._sr_factory_code(src_sr)
                c_tgt = self._sr_factory_code(tgt_sr)
                need_proj = False
                if c_src is not None and c_tgt is not None:
                    need_proj = c_src != c_tgt
                else:
                    try:
                        need_proj = src_sr.exportToString() != tgt_sr.exportToString()
                    except Exception:
                        need_proj = str(src_sr) != str(tgt_sr)
                if need_proj:
                    proj_fc = out_fc + "_proj"
                    if arcpy.Exists(proj_fc):
                        arcpy.management.Delete(proj_fc)
                    try:
                        tname = tgt_sr.name
                    except Exception:
                        tname = "kohde-CRS"
                    self.log(messages, f"  > Projisoidaan vientiin: {tname}...")
                    arcpy.management.Project(out_fc, proj_fc, tgt_sr)
                    arcpy.management.Delete(out_fc)
                    out_fc = proj_fc
            except Exception as e:
                self.log(messages, f"  > Projisointi epäonnistui, käytetään alkuperäistä: {e}", "WARNING")

        return out_fc

    def _cad_ensure_gis_objectid_field(self, fc_path, messages):
        """Kopioi lähteen OID (OBJECTID / FID) kenttään GIS_OBJECTID CAD-vientiin.

        Käyttäjä haluaa OBJECTID:n mukaan DWG:hen; järjestelmä-OID ei aina näy Object Datassa
        samalla tavalla kuin tavallinen attribuuttikenttä.
        """
        target = "GIS_OBJECTID"
        try:
            desc = arcpy.Describe(fc_path)
            oid_name = getattr(desc, "OIDFieldName", None) or "OBJECTID"
        except Exception:
            oid_name = "OBJECTID"

        try:
            field_names = [f.name for f in arcpy.ListFields(fc_path)]
        except Exception:
            return

        if oid_name not in field_names:
            self.log(messages, f"  > OID-kenttää ({oid_name}) ei löytynyt — GIS_OBJECTID ohitetaan.", "WARNING")
            return

        if target not in field_names:
            try:
                arcpy.management.AddField(fc_path, target, "LONG")
            except Exception:
                try:
                    arcpy.management.AddField(fc_path, target, "TEXT", field_length=32)
                except Exception as e:
                    self.log(messages, f"  > Kenttää {target} ei voitu lisätä: {e}", "WARNING")
                    return

        try:
            tgt_def = next((f for f in arcpy.ListFields(fc_path) if f.name == target), None)
            use_text = tgt_def is not None and tgt_def.type in ("String", "Text")
            if use_text:
                with arcpy.da.UpdateCursor(fc_path, [oid_name, target]) as cur:
                    for row in cur:
                        row[1] = str(row[0]) if row[0] is not None else ""
                        cur.updateRow(row)
            else:
                with arcpy.da.UpdateCursor(fc_path, [oid_name, target]) as cur:
                    for row in cur:
                        v = row[0]
                        row[1] = int(v) if v is not None else None
                        cur.updateRow(row)
            self.log(messages, f"  > Kopioitu {oid_name} → {target} (mukana CAD-attribuuteissa).")
        except Exception as e:
            self.log(messages, f"  > GIS_OBJECTID-kopiointi epäonnistui: {e}", "WARNING")

    def _cad_copy_gis_to_reserved_display_fields(self, fc_path, messages):
        """Kopioi tutut GIS-kentät Esri-CAD varattuihin kenttiin (AddCADFields jälkeen).

        AutoCADin Properties ei listaa GDB-sarakkeita suoraan; Layer / Color / Text jne. näkyvät
        CAD-puolella. Täytetään tyhjä Layer tunnetuista kentistä (Category, SourceLyr, …).
        """
        try:
            fields = [f.name for f in arcpy.ListFields(fc_path)]
        except Exception:
            return
        lower = {n.lower(): n for n in fields}

        def fname(*candidates):
            for c in candidates:
                k = c.lower()
                if k in lower:
                    return lower[k]
            return None

        layer_f = fname("layer")
        if not layer_f:
            return
        for src in (
            "Category",
            "Kategoria",
            "SourceLyr",
            "Sourcelyr",
            "SOURCELYR",
            "LAYER_NAME",
            "Tasonimi",
        ):
            src_f = fname(src)
            if not src_f or src_f == layer_f:
                continue
            try:
                filled = 0
                with arcpy.da.UpdateCursor(fc_path, [layer_f, src_f]) as cur:
                    for row in cur:
                        cur_layer = row[0]
                        if cur_layer is not None and str(cur_layer).strip():
                            continue
                        v = row[1]
                        row[0] = str(v) if v is not None else ""
                        cur.updateRow(row)
                        filled += 1
                if filled:
                    self.log(
                        messages,
                        f"  > CAD-kenttä '{layer_f}' täytettiin kentästä '{src_f}' ({filled} tyhjää riviä) — näkyy CAD Layer -kentässä.",
                    )
                break
            except Exception as e:
                self.log(messages, f"  > Layer-kopiointi ({src_f}): {e}", "WARNING")

    def _cad_expose_gis_objectid_in_hyperlink(self, fc_path, messages):
        """Kirjoita OBJECTID Hyperlink-kenttään (AutoCAD Properties → General).

        AddCADFields voi täyttää Hyperlinkin oletusarvolla — vanha logiikka ohitti rivit ja mitään ei näkynyt.
        Ylikirjoitetaan aina luettavalla OBJECTID=<arvo> -tekstillä.
        """
        try:
            fields = [f.name for f in arcpy.ListFields(fc_path)]
        except Exception:
            return
        lower = {n.lower(): n for n in fields}

        hname = lower.get("hyperlink")
        if not hname:
            for nm in fields:
                if nm.lower() == "hyperlink":
                    hname = nm
                    break
        if not hname:
            try:
                arcpy.management.AddField(fc_path, "Hyperlink", "TEXT", field_length=255)
                hname = "Hyperlink"
                self.log(messages, "  > Lisätty Hyperlink-kenttä (OID näkyvyyttä varten).")
            except Exception as e:
                self.log(messages, f"  > Hyperlink-kenttää ei voitu lisätä: {e}", "WARNING")
                return

        try:
            desc = arcpy.Describe(fc_path)
            oid_nm = getattr(desc, "OIDFieldName", None) or "OBJECTID"
        except Exception:
            oid_nm = "OBJECTID"

        oid_actual = lower.get(oid_nm.lower()) if oid_nm else None
        gid = lower.get("gis_objectid")

        if not oid_actual and not gid:
            self.log(messages, "  > Ei OID- eikä GIS_OBJECTID -kenttää — Hyperlink jätetään.", "WARNING")
            return

        try:
            n = 0
            sample = None
            if gid and oid_actual:
                with arcpy.da.UpdateCursor(fc_path, [hname, gid, oid_actual]) as cur:
                    for row in cur:
                        v = row[1]
                        if v is None:
                            v = row[2]
                        row[0] = (f"OBJECTID={v}" if v is not None else "")[:255]
                        if sample is None and row[0]:
                            sample = row[0]
                        cur.updateRow(row)
                        n += 1
            elif gid:
                with arcpy.da.UpdateCursor(fc_path, [hname, gid]) as cur:
                    for row in cur:
                        v = row[1]
                        row[0] = (f"OBJECTID={v}" if v is not None else "")[:255]
                        if sample is None and row[0]:
                            sample = row[0]
                        cur.updateRow(row)
                        n += 1
            elif oid_actual:
                with arcpy.da.UpdateCursor(fc_path, [hname, oid_actual]) as cur:
                    for row in cur:
                        v = row[1]
                        row[0] = (f"OBJECTID={v}" if v is not None else "")[:255]
                        if sample is None and row[0]:
                            sample = row[0]
                        cur.updateRow(row)
                        n += 1
            self.log(
                messages,
                f"  > Hyperlink-kenttä kirjoitettu ({n} riviä): "
                f"({sample or 'OBJECTID=<id>'}) (lähde: "
                f"{'GIS_OBJECTID+OID' if gid and oid_actual else gid or oid_actual}).",
            )
        except Exception as e:
            self.log(messages, f"  > Hyperlink-täyttö epäonnistui: {e}", "WARNING")

    def _cad_create_point_seed_dxf(self, pdsize, pdmode=35):
        """Luo minimaalinen DXF-seed-tiedosto, jossa $PDSIZE ja $PDMODE asetettu.

        AutoCAD käyttää $PDSIZE-arvoa POINT-entiteettien näyttökokona (karttakoordinaatistossa).
        PDMODE=35 näyttää pisteen ristinä ympyrässä (+O), mikä on hyvin näkyvä.
        Palautetaan polku väliaikaiseen tiedostoon (siivottava käytön jälkeen).
        """
        import tempfile
        content = (
            "  0\nSECTION\n  2\nHEADER\n"
            "  9\n$PDMODE\n 70\n{pdmode:5d}\n"
            "  9\n$PDSIZE\n 40\n{pdsize:.6f}\n"
            "  0\nENDSEC\n"
            "  0\nSECTION\n  2\nENTITIES\n"
            "  0\nENDSEC\n"
            "  0\nEOF\n"
        ).format(pdmode=int(pdmode), pdsize=float(pdsize))
        tmp_path = os.path.join(tempfile.gettempdir(), "_muuntaja_point_seed.dxf")
        try:
            with open(tmp_path, "w", encoding="ascii") as f:
                f.write(content)
            return tmp_path
        except Exception:
            return None

    def _cad_get_point_pdsize(self, fc_source_pairs, scale_factor=10.0, messages=None):
        """Laske sopiva $PDSIZE pisteviennille karttasymbolin perusteella × scale_factor.

        Lukee markkerikoon pistetasojen karttatason rendereristä (pt) ja muuntaa
        karttayksiköiksi (m) referenssimittakaavan avulla.
        Palauttaa koon metreinä tai None jos syötteessä ei ole pistetasoja.
        """
        marker_pts = []
        has_point = False
        for fc_path, in_src in fc_source_pairs:
            try:
                desc = arcpy.Describe(fc_path)
                if (desc.shapeType or "").lower() != "point":
                    continue
                has_point = True
            except Exception:
                continue
            try:
                map_lyr = self._cad_find_matching_map_layer(in_src)
                if map_lyr:
                    sym = map_lyr.symbology
                    if hasattr(sym, "supports") and sym.supports("renderer"):
                        r = sym.renderer
                        rt = (getattr(r, "type", None) or "").lower()
                        if "simple" in rt and hasattr(r, "symbol") and hasattr(r.symbol, "size"):
                            marker_pts.append(float(r.symbol.size))
                        elif "unique" in rt:
                            for grp in getattr(r, "groups", []):
                                for cls in getattr(grp, "classes", []):
                                    if hasattr(cls, "symbol") and hasattr(cls.symbol, "size"):
                                        marker_pts.append(float(cls.symbol.size))
                                        break
                                if marker_pts:
                                    break
            except Exception:
                pass

        if not has_point:
            return None

        marker_pt = (sum(marker_pts) / len(marker_pts)) if marker_pts else 8.0

        ref_scale = 0.0
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            m = aprx.activeMap
            if m:
                ref_scale = float(m.referenceScale or 0.0)
        except Exception:
            pass
        if ref_scale <= 0.0:
            ref_scale = 1000.0  # oletusarvo 1:1000

        # 1 pt = 0.352778 mm; mittakaavassa 1:N → 1 mm paperilla = N mm maastossa
        size_m = marker_pt * 0.000352778 * ref_scale * scale_factor

        if messages:
            src_label = "karttatason symboli" if marker_pts else "oletuskoko 8 pt"
            self.log(
                messages,
                f"  > POINT $PDSIZE: {marker_pt:.1f} pt × {scale_factor:.0f} × (1:{ref_scale:.0f}) = {size_m:.3f} m ({src_label})",
            )
        return size_m

    def _cad_force_point_entity_type(self, fc_path, messages):
        """Pakota Export To CAD käyttämään POINT-entiteettiä pistetasoille (varattu CadType-kenttä).

        Ilman CadType-arvoa jotkin lähteet vievät pisteet ympyröinä tai vääränä entiteettinä.
        Jos geometria on polygon (esim. puskuroitu piste), POINT-pakotus ei auta — varoitetaan.
        """
        try:
            desc = arcpy.Describe(fc_path)
        except Exception:
            return
        st = (desc.shapeType or "").lower()
        if st == "polygon":
            self.log(
                messages,
                "  > Huom: lähteen geometria on polygon (esim. buffer/puskuri). DWG:hen tulee ympyrä — "
                "muuta lähteessä oikeaksi pistetasoksi jos haluat CAD-POINTin.",
                "WARNING",
            )
            return
        if st != "point":
            return

        field_names = [f.name for f in arcpy.ListFields(fc_path)]
        existing = None
        for fn in field_names:
            if fn.lower() in ("cadtype", "entity"):
                existing = fn
                break

        if existing:
            changed = 0
            try:
                with arcpy.da.UpdateCursor(fc_path, [existing]) as cur:
                    for row in cur:
                        v = row[0]
                        vv = "" if v is None else str(v).strip().upper()
                        if vv != "POINT":
                            row[0] = "POINT"
                            cur.updateRow(row)
                            changed += 1
                self.log(
                    messages,
                    f"  > Pakotettiin {existing}=POINT pistetasolle ({changed} riviä muutettiin). "
                    "Tämä estää liian suuret CIRCLE-rinkulat CADissa.",
                )
            except Exception as e:
                self.log(messages, f"  > CadType-täyttö epäonnistui: {e}", "WARNING")
            return

        try:
            arcpy.management.AddField(fc_path, "CadType", "TEXT", field_length=32)
            with arcpy.da.UpdateCursor(fc_path, ["CadType"]) as cur:
                for row in cur:
                    row[0] = "POINT"
                    cur.updateRow(row)
            self.log(messages, "  > Lisätty CadType=POINT — vienti CAD-POINT-entiteetteinä.")
        except Exception as e:
            self.log(messages, f"  > CadType-kentän lisäys epäonnistui: {e}", "WARNING")

    def _cad_log_attribute_schema(self, fc_path, messages):
        """Listaa attribuuttitaulun kentät (AddCADFields ei lue rivejä — tämä dokumentoi mitä viedään)."""
        try:
            fds = [
                f.name
                for f in arcpy.ListFields(fc_path)
                if f.type not in ("OID", "Geometry") and getattr(f, "name", "") != "Shape"
            ]
        except Exception:
            return
        if not fds:
            return
        preview = ", ".join(fds[:35])
        if len(fds) > 35:
            preview += f", … (+{len(fds) - 35} kenttää)"
        self.log(messages, f"  > Vientiin lähtee {len(fds)} attribuuttikenttää: {preview}")

    def _cad_field_name_needs_cad_clone(self, name):
        """True jos kenttänimi voi sakata CAD/Object Data -polussa (kloonataan cad_*-tekstiksi)."""
        if not name or len(name) > 28:
            return True
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name):
            return True
        return False

    def _cad_unique_field_name(self, fc_path, base_name):
        existing = {f.name.lower() for f in arcpy.ListFields(fc_path)}
        cand = base_name[:32]
        n = 2
        while cand.lower() in existing:
            suffix = f"_{n}"
            cand = (base_name[: 32 - len(suffix)] + suffix)[:32]
            n += 1
            if n > 999:
                break
        return cand

    def _cad_add_portable_field_clones_for_attributes(self, fc_path, messages):
        """Attribuuttitaulun perusteella: lisää cad_*-TEKSTIKENTTä, jos alkuperäisen nimi on riskialtis.

        AddCADFields ei voi luoda kenttiä dynaamisesti jokaisesta sarakkeesta — se lisää Esri-varatut
        kenttäryhmät. Tämä täydentää: helpompi nimi + arvo kopioitu tekstinä (max 255 merkkiä).
        """
        skip_lower = {
            "shape", "shape_length", "shape_area", "shape.stlength()", "shape.starea()",
            "objectid", "fid", "globalid", "gis_objectid",
        }
        try:
            fields = arcpy.ListFields(fc_path)
        except Exception:
            return
        cloned = 0
        for f in fields:
            nm = f.name
            if not nm or nm.lower() in skip_lower:
                continue
            if f.type in ("OID", "Geometry"):
                continue
            if f.type == "Blob":
                self.log(messages, f"  > Ohitettu Blob-kenttä (ei kloonia): {nm}", "WARNING")
                continue
            if nm.lower().startswith("cad_"):
                continue
            if not self._cad_field_name_needs_cad_clone(nm):
                continue
            body = self.sanitize_name(nm.replace(".", "_"))[:22] or "fld"
            base = f"cad_{body}"[:28]
            alias = self._cad_unique_field_name(fc_path, base)
            try:
                arcpy.management.AddField(fc_path, alias, "TEXT", field_length=255)
            except Exception as e:
                self.log(messages, f"  > Ei voitu lisätä kloonikenttää {alias} ({nm}): {e}", "WARNING")
                continue
            try:
                with arcpy.da.UpdateCursor(fc_path, [nm, alias]) as cur:
                    for row in cur:
                        v = row[0]
                        row[1] = "" if v is None else str(v)[:255]
                        cur.updateRow(row)
                cloned += 1
                self.log(messages, f"  > Kenttä '{nm}' → '{alias}' (CAD-yhteensopiva tekstikopio).")
            except Exception as e:
                try:
                    arcpy.management.DeleteField(fc_path, alias)
                except Exception:
                    pass
                self.log(messages, f"  > Kloonin täyttö epäonnistui ({nm}): {e}", "WARNING")
        if cloned:
            self.log(messages, f"  > Yhteensä {cloned} kenttää kloonattiin cad_*-nimiin attribuuttitaulun perusteella.")

    def _cad_apply_add_cad_fields_full(self, fc_path, messages):
        """AddCADFields: Esri-varatut kenttäryhmät (ei dynaaminen lista sarakkeista — API on kiinteä)."""
        try:
            arcpy.conversion.AddCADFields(
                fc_path,
                "ADD_ENTITY_PROPERTIES",
                "ADD_LAYER_PROPERTIES",
                "ADD_TEXT_PROPERTIES",
                "ADD_DOCUMENT_PROPERTIES",
                "ADD_XDATA_PROPERTIES",
            )
            self.log(
                messages,
                "  > AddCADFields: entiteetti-, taso-, teksti-, dokumentti- ja XData-kenttäryhmät (ADD).",
            )
        except Exception as e:
            self.log(messages, f"  > AddCADFields epäonnistui: {e}", "WARNING")

    def _cad_resolve_field_name(self, fc_path, requested):
        rq = (requested or "").strip().lower()
        if not rq:
            return None
        if rq in ("objectid", "oid", "fid"):
            try:
                desc = arcpy.Describe(fc_path)
                oid_name = getattr(desc, "OIDFieldName", None)
                if oid_name:
                    return oid_name
            except Exception:
                pass
            for fallback in ("GIS_OBJECTID",):
                for f in arcpy.ListFields(fc_path):
                    if f.name.lower() == fallback.lower():
                        return f.name
        for f in arcpy.ListFields(fc_path):
            if f.name.lower() == rq:
                return f.name
        return None

    def _cad_pick_reserved_field(self, fc_path, candidates):
        low = {f.name.lower(): f.name for f in arcpy.ListFields(fc_path)}
        for cand in candidates:
            if cand.lower() in low:
                return low[cand.lower()]
        return None

    def _cad_renderer_field_value_norm(self, v):
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, float):
            if abs(v - round(v)) < 1e-7:
                return int(round(v))
            return round(v, 6)
        if isinstance(v, bool):
            return int(v)
        try:
            return int(v)
        except Exception:
            return str(v).strip()

    def _cad_find_matching_map_layer(self, in_src):
        """Etsi sama FC kuin karttataso aktiiviselta kartalta catalogPath-/nimelle."""
        target_cat = None
        tgt_name = ""
        try:
            target_cat = os.path.normpath(self._resolve_export_catalog_path(in_src)).lower()
            tgt_name = os.path.splitext(os.path.basename(target_cat))[0].lower()
        except Exception:
            pass
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            m = aprx.activeMap
            if not m:
                return None
            for lyr in m.listLayers():
                try:
                    if getattr(lyr, "isBasemapLayer", False):
                        continue
                    if lyr.isGroupLayer or lyr.isBroken:
                        continue
                    if not lyr.isFeatureLayer:
                        continue
                except Exception:
                    continue
                try:
                    dc = arcpy.Describe(lyr)
                    cp = getattr(dc, "catalogPath", None)
                    if cp and target_cat:
                        if os.path.normpath(str(cp)).lower() == target_cat:
                            return lyr
                except Exception:
                    pass
                try:
                    nm = (lyr.name or "").strip()
                    if tgt_name and nm.lower() == tgt_name:
                        return lyr
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _cad_rgb_tuple_from_symbol_color(self, col):
        """Palauttaa (r,g,b) Esri-symbolin väriobjektista (dict tai tuple)."""
        if not col:
            return None
        try:
            if isinstance(col, dict):
                rgb = col.get("RGB") or col.get("rgb")
                if rgb and len(rgb) >= 3:
                    return int(rgb[0]), int(rgb[1]), int(rgb[2])
                # CIM-värimuoto: {"type":"CIMRGBColor","values":[r,g,b,a]}
                vals = col.get("values")
                ctype = str(col.get("type") or "").upper()
                if isinstance(vals, (list, tuple)) and len(vals) >= 3:
                    if "RGB" in ctype or not ctype:
                        return int(vals[0]), int(vals[1]), int(vals[2])
                return None
        except Exception:
            pass
        try:
            if isinstance(col, (list, tuple)) and len(col) >= 3:
                return int(col[0]), int(col[1]), int(col[2])
        except Exception:
            pass
        return None

    def _cad_symbol_primary_rgb(self, sym):
        """Yritä löytää ensisijainen RGB symbolista tai sen kerroksista."""
        if not sym:
            return None
        c = getattr(sym, "color", None)
        t = self._cad_rgb_tuple_from_symbol_color(c)
        if t:
            return t
        try:
            for sl in getattr(sym, "symbolLayers", []) or []:
                c2 = getattr(sl, "color", None)
                t2 = self._cad_rgb_tuple_from_symbol_color(c2)
                if t2:
                    return t2
        except Exception:
            pass
        return None

    def _cad_nearest_aci(self, r, g, b):
        best_aci = 7
        best_d = 1e12
        for aci, rr, gg, bb in (
            [(t[0], t[1], t[2], t[3]) for t in _CAD_ACI_SAMPLES]
        ):
            d = (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
            if d < best_d:
                best_d = d
                best_aci = aci
        return int(best_aci)

    def _cad_rgb_dict_to_aci(self, col):
        tup = None
        if isinstance(col, dict):
            tup = self._cad_rgb_tuple_from_symbol_color(col)
        elif isinstance(col, (list, tuple)) and len(col) >= 3:
            try:
                tup = (int(col[0]), int(col[1]), int(col[2]))
            except Exception:
                tup = None
        if not tup:
            return 7
        r = max(0, min(255, tup[0]))
        g = max(0, min(255, tup[1]))
        b = max(0, min(255, tup[2]))
        return self._cad_nearest_aci(r, g, b)

    def _cad_fuzzy_lut_get(self, lut, key):
        if key in lut:
            return lut[key]
        if not key:
            return None
        key2 = tuple(str(x) if x is not None else "" for x in key)
        if key2 in lut:
            return lut[key2]
        for kstored, val in lut.items():
            if len(kstored) != len(key):
                continue
            match = True
            for a, b in zip(kstored, key):
                if a == b:
                    continue
                if str(a) == str(b):
                    continue
                match = False
                break
            if match:
                return val
        return None

    def _cad_lut_unique_value_from_renderer(self, r, messages):
        """Rakennetaan arvo→(aci, Layer) lukittain UniqueValueRendereristä."""
        lut = {}
        fields_renderer = getattr(r, "fields", None) or []
        groups = getattr(r, "groups", None) or []
        try:
            for grp in groups:
                for itm in getattr(grp, "items", None) or []:
                    lbl = getattr(itm, "label", None)
                    lay_safe = self.sanitize_name(str(lbl))[:50] if lbl else "Class"
                    if not lay_safe:
                        lay_safe = "Layer"
                    sym = getattr(itm, "symbol", None)
                    rgbt = self._cad_symbol_primary_rgb(sym)
                    if rgbt:
                        aci = self._cad_nearest_aci(*rgbt)
                    else:
                        raw_col = getattr(sym, "color", None) if sym else None
                        aci = self._cad_rgb_dict_to_aci(raw_col)
                    vals_outer = getattr(itm, "values", None)
                    if vals_outer is None:
                        continue
                    tup_orig = vals_outer[0]
                    if tup_orig is None:
                        continue
                    if not isinstance(tup_orig, (list, tuple)):
                        tup_orig = (tup_orig,)
                    n = len(fields_renderer) if fields_renderer else len(tup_orig)
                    tup_fix = tup_orig[:n] if n else tup_orig
                    key_norm = tuple(self._cad_renderer_field_value_norm(x) for x in tup_fix)
                    lut[key_norm] = (aci, lay_safe[:80])
                    key_str = tuple(str(x).strip() if x is not None else "" for x in tup_fix)
                    lut[key_str] = (aci, lay_safe[:80])
            return lut, fields_renderer
        except Exception as e:
            self.log(messages, f"  > UniqueValue-renderöijän lukeminen epäonnistui: {e}", "WARNING")
            return {}, []

    def _cad_apply_symbology_from_map_layer(self, fc_path, lyr, messages):
        try:
            sym = lyr.symbology
            if hasattr(sym, "supports") and not sym.supports("renderer"):
                self.log(messages, "  > Karttatasolla ei ole symbologiarenderer-tukea.", "WARNING")
                return
            r = sym.renderer
        except Exception as e:
            self.log(messages, f"  > Symbologiarenderer puuttuu: {e}", "WARNING")
            return

        rt = (getattr(r, "type", None) or "").lower()
        color_f = self._cad_pick_reserved_field(fc_path, ("Color",))
        layer_f = self._cad_pick_reserved_field(fc_path, ("Layer", "Level"))
        fld_names_fc = [f.name for f in arcpy.ListFields(fc_path)]

        if not color_f and not layer_f:
            self.log(messages, "  > Color-/Layer-kenttää ei löytynyt — karttasymbologia ohitettu.", "WARNING")
            return

        if "simple" in rt:
            rgb_t = self._cad_symbol_primary_rgb(getattr(r, "symbol", None))
            col_any = getattr(r.symbol, "color", None) if getattr(r, "symbol", None) else None
            aci = self._cad_rgb_dict_to_aci(rgb_t) if rgb_t else self._cad_rgb_dict_to_aci(col_any)
            try:
                lay_nm = (lyr.name or "Symbologia")[:120]
                lay_safe = self.sanitize_name(lay_nm)[:50] or "Layer"
            except Exception:
                lay_safe = "Layer"
            fields_upd = [x for x in [color_f, layer_f] if x]
            if not fields_upd:
                return
            with arcpy.da.UpdateCursor(fc_path, fields_upd) as cur:
                for row in cur:
                    i = 0
                    if color_f:
                        row[i] = int(aci)
                        i += 1
                    if layer_f:
                        row[i] = lay_safe[:255]
                    cur.updateRow(row)
            self.log(messages, f"  > SimpleRenderer → Color={aci}, Layer≈{lay_safe} (kaikille riveille).")
            return

        if "unique" in rt:
            lut, fields_renderer = self._cad_lut_unique_value_from_renderer(r, messages)
            if not lut or not fields_renderer:
                self.log(messages, "  > UniqueValue: ei luokkia tai kenttiä — symbologiaa ei sovellettu.", "WARNING")
                return
            key_fields_resolved = []
            for fn in fields_renderer:
                actual = self._cad_resolve_field_name(fc_path, fn)
                if not actual:
                    self.log(messages, f"  > UniqueValue: kenttää '{fn}' ei löydy feature classista.", "WARNING")
                    return
                key_fields_resolved.append(actual)
            fields_upd = key_fields_resolved + [x for x in [color_f, layer_f] if x]
            with arcpy.da.UpdateCursor(fc_path, fields_upd) as cur:
                nkey = len(key_fields_resolved)
                for row in cur:
                    key = tuple(self._cad_renderer_field_value_norm(row[i]) for i in range(nkey))
                    hit = self._cad_fuzzy_lut_get(lut, key)
                    if not hit:
                        continue
                    aci, lay_lbl = hit
                    j = nkey
                    if color_f:
                        row[j] = int(aci)
                        j += 1
                    if layer_f:
                        row[j] = str(lay_lbl)[:255]
                    cur.updateRow(row)
            self.log(
                messages,
                f"  > UniqueValueRenderer: kentät {', '.join(key_fields_resolved)} → Color/Layer (luokkahakemisto).",
            )
            return

        self.log(
            messages,
            "  > Renderer-tyyppi '%s' ei ole tuettu (tuettu: simple / unique value)." % (rt if rt else "?"),
            "WARNING",
        )

    def _cad_prepare_cad_text_layer_copy(self, fc_path, label_requested, messages, text_height=10.0):
        """Erillinen feature class: sama geometria mutta CadType TEXT + TxtValue (kartta-labelit CAD-tekteinä)."""
        fn = self._cad_resolve_field_name(fc_path, label_requested)
        if not fn:
            self.log(messages, f"  > Labelkenttää '{label_requested}' ei löytynyt — tekstivienti puuttuu.", "WARNING")
            return None
        parent = os.path.dirname(fc_path)
        base = os.path.basename(fc_path)
        lbl_fc = os.path.join(parent, base + "__cadlbl")
        if arcpy.Exists(lbl_fc):
            try:
                arcpy.management.Delete(lbl_fc)
            except Exception:
                pass
        try:
            arcpy.management.CopyFeatures(fc_path, lbl_fc)
        except Exception as e:
            self.log(messages, f"  > Kopio CAD-teksteille epäonnistui: {e}", "WARNING")
            return None
        cad_tf = self._cad_pick_reserved_field(lbl_fc, ("CadType", "CADType"))
        txt_f = self._cad_pick_reserved_field(lbl_fc, ("TxtValue", "Text"))
        lyr_f = self._cad_pick_reserved_field(lbl_fc, ("Layer", "Level"))
        label_layer_name = "LABELIT_TEXT"
        if not cad_tf or not txt_f:
            self.log(messages, "  > CadType/TxtValue-varattuja kenttiä ei löydy.", "WARNING")
            try:
                arcpy.management.Delete(lbl_fc)
            except Exception:
                pass
            return None
        txth_f = self._cad_pick_reserved_field(lbl_fc, ("TxtHt", "TextHt", "Height"))
        if not txth_f:
            try:
                arcpy.management.AddField(lbl_fc, "TxtHt", "DOUBLE")
                txth_f = "TxtHt"
            except Exception:
                txth_f = None
        dropped = 0
        wrote = 0
        try:
            fields = [fn, cad_tf, txt_f] + ([lyr_f] if lyr_f else []) + ([txth_f] if txth_f else [])
            with arcpy.da.UpdateCursor(lbl_fc, fields) as uc:
                for row in uc:
                    raw = row[0]
                    s = "" if raw is None else str(raw).strip()
                    if not s:
                        uc.deleteRow()
                        dropped += 1
                        continue
                    row[1] = "TEXT"
                    row[2] = s[:255]
                    idx = 3
                    if lyr_f:
                        row[idx] = label_layer_name
                        idx += 1
                    if txth_f:
                        row[idx] = float(text_height)
                    uc.updateRow(row)
                    wrote += 1
        except Exception as e:
            self.log(messages, f"  > CAD-TEXT-kerroksen täyttö epäonnistui: {e}", "WARNING")
            try:
                arcpy.management.Delete(lbl_fc)
            except Exception:
                pass
            return None
        if wrote == 0:
            try:
                arcpy.management.Delete(lbl_fc)
            except Exception:
                pass
            self.log(messages, "  > Yhdelläkään rivillä ei ollut label-tekstiä — TXT-kerrosta ei viedä.", "WARNING")
            return None
        self.log(messages, f"  > CAD label-tekstitaso '{label_layer_name}': {wrote} tekstiä, {dropped} tyhjää riviä poistettiin kopiolta.")
        return lbl_fc

    def _cad_prepare_attribute_table_text_layer_copy(
        self,
        fc_path,
        field_names,
        messages,
        text_height=10.0,
        layer_name="ATTRIBUUTIT",
    ):
        """Luo DWG:hen visuaalinen taulukko erillisistä viiva- ja tekstikerroksista."""
        if not field_names:
            return []
        actual = []
        for fn in field_names:
            af = self._cad_resolve_field_name(fc_path, fn)
            if af:
                actual.append(af)
        if not actual:
            self.log(messages, "  > Attribuuttitaulukkoon ei löytynyt yhtään validia kenttää.", "WARNING")
            return []

        parent = os.path.dirname(fc_path)
        base = os.path.basename(fc_path)
        out_fc = os.path.join(parent, base + "__cadattrtxt")
        grid_fc = os.path.join(parent, base + "__cadattrgrid")
        if arcpy.Exists(out_fc):
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
        if arcpy.Exists(grid_fc):
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass

        try:
            dsrc = arcpy.Describe(fc_path)
            sr = getattr(dsrc, "spatialReference", None)
            ext = getattr(dsrc, "extent", None)
            width = float(ext.width) if ext else 0.0
            height = float(ext.height) if ext else 0.0
            x_max = float(ext.XMax) if ext else 0.0
            y_max = float(ext.YMax) if ext else 0.0
        except Exception:
            sr = None
            width = height = x_max = y_max = 0.0

        dx = max(100.0, width * 0.25)
        dy = max(100.0, height * 0.10)
        anchor_x = x_max + dx
        anchor_y = y_max + dy
        default_text_height = float(text_height)
        row_height = max(16.0, default_text_height * 2.1)
        text_x_pad = max(2.5, float(text_height) * 0.45)
        min_text_height = max(2.5, default_text_height * 0.55)
        min_col_width = max(24.0, float(text_height) * 4.0)
        body_char_width = max(2.0, float(text_height) * 0.72)
        header_char_width = max(2.4, float(text_height) * 0.92)
        fit_char_width_factor_body = 0.84
        fit_char_width_factor_header = 1.02

        try:
            arcpy.management.CreateFeatureclass(parent, os.path.basename(out_fc), "POINT", spatial_reference=sr)
            self._cad_apply_add_cad_fields_full(out_fc, messages)
            arcpy.management.CreateFeatureclass(parent, os.path.basename(grid_fc), "POLYLINE", spatial_reference=sr)
            self._cad_apply_add_cad_fields_full(grid_fc, messages)
        except Exception as e:
            self.log(messages, f"  > Attribuuttitaulukon FC:n luonti epäonnistui: {e}", "WARNING")
            return []

        cad_tf = self._cad_pick_reserved_field(out_fc, ("CadType", "CADType"))
        txt_f = self._cad_pick_reserved_field(out_fc, ("TxtValue", "Text"))
        lyr_f = self._cad_pick_reserved_field(out_fc, ("Layer", "Level"))
        txt_color_f = self._cad_pick_reserved_field(out_fc, ("Color",))
        txth_f = self._cad_pick_reserved_field(out_fc, ("TxtHt", "TextHt", "Height"))
        grid_lyr_f = self._cad_pick_reserved_field(grid_fc, ("Layer", "Level"))
        grid_color_f = self._cad_pick_reserved_field(grid_fc, ("Color",))
        if not txth_f:
            try:
                arcpy.management.AddField(out_fc, "TxtHt", "DOUBLE")
                txth_f = "TxtHt"
            except Exception:
                txth_f = None
        if not cad_tf or not txt_f:
            self.log(messages, "  > Attribuuttitaulukko: CadType/TxtValue puuttuu.", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        resolved_specs = []
        header_labels = []
        for fn in field_names:
            af = self._cad_resolve_field_name(fc_path, fn)
            if af:
                resolved_specs.append((fn, af))
                if (fn or "").strip().lower() in ("objectid", "oid", "fid"):
                    header_labels.append("OBJECTID")
                else:
                    header_labels.append(af)
        if not resolved_specs:
            self.log(messages, "  > Attribuuttitaulukkoon ei löytynyt yhtään validia kenttää.", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        actual = [spec[1] for spec in resolved_specs]
        table_rows = [header_labels]
        try:
            with arcpy.da.SearchCursor(fc_path, actual) as cur:
                for row in cur:
                    vals = [("" if v is None else str(v)) for v in row]
                    table_rows.append(vals)
        except Exception as e:
            self.log(messages, f"  > Attribuuttitaulukon luku epäonnistui: {e}", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        if len(table_rows) <= 1:
            self.log(messages, "  > Attribuuttitaulukko: ei rivejä vietäväksi.", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        col_widths = []
        for col_idx in range(len(actual)):
            header_len = len(str(table_rows[0][col_idx]))
            body_len = max(len(str(r[col_idx])) for r in table_rows[1:]) if len(table_rows) > 1 else 0
            header_width = (header_len * header_char_width) + (text_x_pad * 2.0)
            body_width = (body_len * body_char_width) + (text_x_pad * 2.0)
            col_widths.append(max(min_col_width, header_width, body_width))

        col_edges = [anchor_x]
        for width_one in col_widths:
            col_edges.append(col_edges[-1] + width_one)
        total_rows = len(table_rows)
        table_top = anchor_y
        table_bottom = table_top - (total_rows * row_height)
        table_layer_name = (layer_name + "_TABLE")[:255]

        max_len = 255
        try:
            fdef = next((f for f in arcpy.ListFields(out_fc) if f.name.lower() == txt_f.lower()), None)
            if fdef and getattr(fdef, "length", None):
                max_len = int(fdef.length)
        except Exception:
            pass

        wrote = 0
        truncated = 0
        ins_fields = ["SHAPE@XY", cad_tf, txt_f] + ([lyr_f] if lyr_f else []) + ([txt_color_f] if txt_color_f else []) + ([txth_f] if txth_f else [])
        try:
            with arcpy.da.InsertCursor(out_fc, ins_fields) as ic:
                for row_idx, row_values in enumerate(table_rows):
                    row_top = table_top - (row_idx * row_height)
                    row_bottom = row_top - row_height
                    for col_idx, txt in enumerate(row_values):
                        txt = "" if txt is None else str(txt)
                        if len(txt) > max_len:
                            txt = txt[:max_len]
                            truncated += 1
                        usable_width = max(6.0, col_widths[col_idx] - (text_x_pad * 2.0))
                        char_count = max(1, len(txt))
                        if row_idx == 0:
                            fit_height = usable_width / (char_count * fit_char_width_factor_header)
                        else:
                            fit_height = usable_width / (char_count * fit_char_width_factor_body)
                        cell_text_height = min(default_text_height, row_height * 0.62, fit_height)
                        cell_text_height = max(min_text_height, cell_text_height)
                        baseline_y = row_bottom + ((row_height - cell_text_height) * 0.5) + (cell_text_height * 0.18)
                        row = [
                            (col_edges[col_idx] + text_x_pad, baseline_y),
                            "TEXT",
                            txt,
                        ]
                        if lyr_f:
                            row.append(table_layer_name)
                        if txt_color_f:
                            row.append(7)
                        if txth_f:
                            row.append(cell_text_height)
                        ic.insertRow(row)
                        wrote += 1
        except Exception as e:
            self.log(messages, f"  > Attribuuttitaulukon tekstin kirjoitus epäonnistui: {e}", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        grid_fields = ["SHAPE@"] + ([grid_lyr_f] if grid_lyr_f else []) + ([grid_color_f] if grid_color_f else [])
        grid_count = 0
        try:
            with arcpy.da.InsertCursor(grid_fc, grid_fields) as ic:
                for row_idx in range(total_rows + 1):
                    y = table_top - (row_idx * row_height)
                    geom = arcpy.Polyline(
                        arcpy.Array([
                            arcpy.Point(anchor_x, y),
                            arcpy.Point(col_edges[-1], y),
                        ]),
                        sr,
                    )
                    row = [geom]
                    if grid_lyr_f:
                        row.append(table_layer_name)
                    if grid_color_f:
                        row.append(7)
                    ic.insertRow(row)
                    grid_count += 1
                for x in col_edges:
                    geom = arcpy.Polyline(
                        arcpy.Array([
                            arcpy.Point(x, table_top),
                            arcpy.Point(x, table_bottom),
                        ]),
                        sr,
                    )
                    row = [geom]
                    if grid_lyr_f:
                        row.append(table_layer_name)
                    if grid_color_f:
                        row.append(7)
                    ic.insertRow(row)
                    grid_count += 1
        except Exception as e:
            self.log(messages, f"  > Attribuuttitaulukon viivojen kirjoitus epäonnistui: {e}", "WARNING")
            try:
                arcpy.management.Delete(out_fc)
            except Exception:
                pass
            try:
                arcpy.management.Delete(grid_fc)
            except Exception:
                pass
            return []

        self.log(
            messages,
            f"  > ATTRIBUUTIT-taulukko luotu DWG:hen ({total_rows} riviä, {len(actual)} saraketta, {grid_count} viivaa) "
            f"kohtaan X={anchor_x:.2f}, Y={anchor_y:.2f}. Taso: {table_layer_name} (tekstit + ruudukko)."
            + (f" Leikattuja pitkiä solutekstejä: {truncated}." if truncated else ""),
        )
        return [grid_fc, out_fc]

    def _cad_prepare_pair_for_export(
        self,
        fc_path,
        in_src,
        messages,
        cad_label_field,
        use_map_symbology,
        cad_text_height=10.0,
        emit_attr_table=False,
        attr_text_fields=None,
    ):
        """Valmistelee yhden tason DWG-vientiä varten; palauttaa (pää-FC, valinnainen teksti-FC kopio)."""
        self._cad_ensure_gis_objectid_field(fc_path, messages)
        self._cad_log_attribute_schema(fc_path, messages)
        self._cad_add_portable_field_clones_for_attributes(fc_path, messages)
        self._cad_apply_add_cad_fields_full(fc_path, messages)

        if use_map_symbology and in_src:
            map_lyr = self._cad_find_matching_map_layer(in_src)
            if map_lyr:
                self._cad_apply_symbology_from_map_layer(fc_path, map_lyr, messages)
            else:
                try:
                    lbl = os.path.basename(str(in_src))
                except Exception:
                    lbl = str(in_src)
                self.log(
                    messages,
                    f"  > Karttatasoa ei löydy aktiivisesta kartasta ({lbl}) — symbologiavienti ohitettiin.",
                    "WARNING",
                )

        self._cad_copy_gis_to_reserved_display_fields(fc_path, messages)
        self._cad_expose_gis_objectid_in_hyperlink(fc_path, messages)
        self._cad_force_point_entity_type(fc_path, messages)

        label_fc = None
        if cad_label_field:
            label_fc = self._cad_prepare_cad_text_layer_copy(
                fc_path,
                cad_label_field.strip(),
                messages,
                text_height=cad_text_height,
            )
        attrs_fcs = []
        if emit_attr_table and attr_text_fields:
            attrs_fcs = self._cad_prepare_attribute_table_text_layer_copy(
                fc_path,
                attr_text_fields,
                messages,
                text_height=cad_text_height,
                layer_name="ATTRIBUUTIT",
            )
        return fc_path, label_fc, attrs_fcs

    def _export_to_cad(
        self,
        fc_source_pairs,
        out_path,
        messages,
        cad_label_field="",
        use_map_symbology=True,
        cad_text_height=10.0,
        emit_attr_table=False,
        attr_text_fields=None,
    ):
        """DWG/DXF: yksi tai useampi (fc_scratch, in_src) — Export To CAD samaan tiedostoon."""
        if arcpy.Exists(out_path):
            try:
                arcpy.management.Delete(out_path)
            except Exception:
                pass
        ext = os.path.splitext(out_path)[1].lower()
        out_type = "DWG_R2018" if ext == ".dwg" else "DXF_R2018"

        cad_stack = []
        label_cleanup = []
        for fc_path, in_src in fc_source_pairs:
            main_fc, label_fc, attrs_fcs = self._cad_prepare_pair_for_export(
                fc_path,
                in_src,
                messages,
                cad_label_field,
                use_map_symbology,
                cad_text_height,
                emit_attr_table,
                attr_text_fields,
            )
            cad_stack.append(main_fc)
            if label_fc:
                cad_stack.append(label_fc)
                label_cleanup.append(label_fc)
            for attrs_fc in attrs_fcs or []:
                cad_stack.append(attrs_fc)
                label_cleanup.append(attrs_fc)

        cad_inputs = cad_stack

        # Laske $PDSIZE pistetasoille (symbolin koko × 10) ja luo DXF-seed-tiedosto.
        seed_file = None
        try:
            pdsize = self._cad_get_point_pdsize(fc_source_pairs, scale_factor=10.0, messages=messages)
            if pdsize and pdsize > 0:
                seed_file = self._cad_create_point_seed_dxf(pdsize, pdmode=35)
        except Exception as _seed_err:
            self.log(messages, f"  > Seed-tiedoston valmistelu epäonnistui: {_seed_err}", "WARNING")

        try:
            if seed_file:
                try:
                    arcpy.conversion.ExportCAD(
                        cad_inputs,
                        out_type,
                        out_path,
                        "Ignore_Filenames_in_Tables",
                        "Overwrite_Existing_Files",
                        seed_file,
                    )
                except Exception as _cad_err:
                    self.log(messages, f"  > ExportCAD seed-tiedostolla epäonnistui ({_cad_err}), yritetään ilman seediä.", "WARNING")
                    arcpy.conversion.ExportCAD(
                        cad_inputs,
                        out_type,
                        out_path,
                        "Ignore_Filenames_in_Tables",
                        "Overwrite_Existing_Files",
                    )
            else:
                arcpy.conversion.ExportCAD(
                    cad_inputs,
                    out_type,
                    out_path,
                    "Ignore_Filenames_in_Tables",
                    "Overwrite_Existing_Files",
                )
        finally:
            if seed_file and os.path.exists(seed_file):
                try:
                    os.remove(seed_file)
                except Exception:
                    pass

        self.log(messages, f"CAD-vienti valmis: {out_path} ({len(fc_source_pairs)} lähdettä).")

        for lbl in label_cleanup:
            if lbl and arcpy.Exists(lbl):
                try:
                    arcpy.management.Delete(lbl)
                except Exception:
                    pass

        self.log(
            messages,
            "  > Vinkki: Pistetasot käyttävät CadType POINT; $PDSIZE asetettu 10× symbolin kokoon (PDMODE=35 = risti+ympyrä).",
        )
        return out_path

    def _export_to_geojson(self, fc_path, out_path, messages):
        if arcpy.Exists(out_path):
            try:
                arcpy.management.Delete(out_path)
            except Exception:
                pass
        arcpy.conversion.FeaturesToJSON(fc_path, out_path)
        self.log(messages, f"GeoJSON-vienti valmis: {out_path}")
        return out_path

    def _export_to_shapefile(self, fc_path, out_path, messages):
        out_dir = os.path.dirname(out_path) or "."
        base = os.path.splitext(os.path.basename(out_path))[0]
        if not base:
            base = "export"
        shp_path = os.path.join(out_dir, base + ".shp")
        if arcpy.Exists(shp_path):
            try:
                arcpy.management.Delete(shp_path)
            except Exception:
                base = base + "_" + datetime.datetime.now().strftime("%H%M%S")
        arcpy.conversion.FeatureClassToFeatureClass(fc_path, out_dir, base)
        final_shp = os.path.join(out_dir, base + ".shp")
        self.log(messages, f"Shapefile-vienti valmis: {final_shp}")
        return final_shp

    def _export_to_geopackage(self, fc_path, out_path, messages, source_label=None):
        d = arcpy.Describe(fc_path)
        raw = source_label or getattr(d, "name", "export") or "export"
        layer_name = self.sanitize_name(raw)[:30]
        if not layer_name:
            layer_name = "export"
        # GeoPackage-säiliö on luotava ennen feature classin kirjoittamista — arcpy ei luo .gpkg:ta automaattisesti.
        if not arcpy.Exists(out_path):
            try:
                arcpy.management.CreateSQLiteDatabase(out_path, "GEOPACKAGE")
                self.log(messages, f"  > Luotiin GeoPackage-säiliö: {os.path.basename(out_path)}")
            except Exception as e:
                self.log(messages, f"  > GeoPackage-säiliön luonti epäonnistui: {e}", "ERROR")
                raise
        target = os.path.join(out_path, layer_name)
        if arcpy.Exists(target):
            try:
                arcpy.management.Delete(target)
            except Exception:
                layer_name = layer_name + "_" + datetime.datetime.now().strftime("%H%M%S")
                target = os.path.join(out_path, layer_name)
        arcpy.management.CopyFeatures(fc_path, target)
        self.log(messages, f"GeoPackage-vienti valmis: {target}")
        return target

    def _export_to_kml(self, fc_path, out_path, messages):
        lyr_name = "muuntaja_kml_lyr"
        if arcpy.Exists(lyr_name):
            arcpy.management.Delete(lyr_name)
        arcpy.management.MakeFeatureLayer(fc_path, lyr_name)
        try:
            # LayerToKML: kolmas parametri on kartan mittakaava (esim. 10 000)
            arcpy.conversion.LayerToKML(lyr_name, out_path, 10000)
        finally:
            try:
                arcpy.management.Delete(lyr_name)
            except Exception:
                pass
        self.log(messages, f"KML/KMZ-vienti valmis: {out_path}")
        return out_path

    # --- SUOMEN KOORDINAATISTON PÄÄTTELY ---
    def detect_finnish_crs(self, feature_class, messages):
        """Päättelee koordinaatiston useasta pisteestä enemmistöäänellä.
        Käyttää SEKÄ X että Y -tarkastelua, kattaa TM35FIN, GK-kaistat (prefiksoidut ja kompaktit),
        KKJ-kaistat 1-4, YKJ ja WGS84 lat/lon.
        """
        from collections import Counter
        MAX_SAMPLES = 200

        def classify(x, y):
            """Palauttaa EPSG-koodin tai None."""
            if not x or not y: return None
            if abs(x) < 1e-6 and abs(y) < 1e-6: return None

            # WGS84 lat/lon (Suomi: lon 19-32, lat 59-71)
            if 19.0 <= x <= 32.5 and 59.0 <= y <= 71.5:
                return 4326

            # Suomen pohjoiskoordinaatti (Y) on aina tässä haarukassa metrijärjestelmissä.
            # Jos Y ei osu tähän, ei voida varmuudella tunnistaa Suomen CRS:ää.
            if not (6_400_000 <= y <= 7_900_000):
                return None

            # TM35FIN: X 20k-800k, ei prefiksiä (EPSG:3067)
            if 20_000 <= x <= 800_000:
                return 3067

            # KKJ-kaistat (X = Kxxxxxxx jossa K = kaistanumero 1-4)
            # KKJ1 (EPSG:2391): X ~1.0M-1.8M, keskimeridiaani 21E
            # KKJ2 (EPSG:2392): X ~2.0M-2.8M, keskimeridiaani 24E
            # KKJ3 / YKJ (EPSG:2393): X ~3.0M-3.8M, keskimeridiaani 27E (Yhtenäiskoordinaatisto)
            # KKJ4 (EPSG:2394): X ~4.0M-4.8M, keskimeridiaani 30E
            if 1_000_000 <= x <= 1_900_000: return 2391
            if 2_000_000 <= x <= 2_900_000: return 2392
            if 3_000_000 <= x <= 3_900_000: return 2393
            if 4_000_000 <= x <= 4_900_000: return 2394

            # ETRS-GKn prefiksoituna (X = ZZxxxxxx, ZZ = 19-31)
            if 19_000_000 <= x <= 32_000_000:
                zone = int(str(int(x))[:2])
                gk_epsg = {
                    19: 3873, 20: 3874, 21: 3875, 22: 3876, 23: 3877, 24: 3878,
                    25: 3879, 26: 3880, 27: 3881, 28: 3882, 29: 3883, 30: 3884, 31: 3885
                }
                return gk_epsg.get(zone)

            return None

        epsg_labels = {
            3067: "ETRS-TM35FIN",
            2391: "KKJ kaista 1", 2392: "KKJ kaista 2",
            2393: "KKJ / YKJ (Yhtenäiskoordinaatisto)", 2394: "KKJ kaista 4",
            3873: "ETRS-GK19", 3874: "ETRS-GK20", 3875: "ETRS-GK21",
            3876: "ETRS-GK22", 3877: "ETRS-GK23", 3878: "ETRS-GK24",
            3879: "ETRS-GK25", 3880: "ETRS-GK26", 3881: "ETRS-GK27",
            3882: "ETRS-GK28", 3883: "ETRS-GK29", 3884: "ETRS-GK30",
            3885: "ETRS-GK31",
            4326: "WGS 84 (lat/lon)"
        }

        try:
            votes = Counter()
            sampled = 0
            sample_x = sample_y = None
            with arcpy.da.SearchCursor(feature_class, ["SHAPE@XY"]) as cursor:
                for row in cursor:
                    if not row[0]: continue
                    x, y = row[0]
                    epsg = classify(x, y)
                    if epsg:
                        votes[epsg] += 1
                        if sample_x is None:
                            sample_x, sample_y = x, y
                    sampled += 1
                    if sampled >= MAX_SAMPLES: break

            if not votes:
                self.log(messages, f"  > Ei voitu tunnistaa automaattisesti ({sampled} näytettä).", "WARNING")
                return None

            # Enemmistön voittaja, mutta vain jos vähintään 60% äänistä
            top_epsg, top_count = votes.most_common(1)[0]
            total_votes = sum(votes.values())
            confidence = top_count / total_votes if total_votes else 0

            if confidence < 0.6:
                self.log(messages, f"  > Tunnistus epävarma (paras osuus {confidence:.0%}, äänet: {dict(votes)}).", "WARNING")
                return None

            label = epsg_labels.get(top_epsg, f"EPSG:{top_epsg}")
            self.log(messages, f"  > Tunnistettu koordinaatisto: {label} (EPSG:{top_epsg}, näyte X={sample_x:.2f} Y={sample_y:.2f}, {top_count}/{total_votes} pistettä)")
            return arcpy.SpatialReference(top_epsg)
        except Exception as e:
            self.log(messages, f"  > Tunnistus epäonnistui: {e}", "WARNING")
            return None

    def _is_remote_output(self, output_loc):
        """True jos kohde on UNC-verkkopolku tai mapped network drive."""
        if not output_loc:
            return False
        p = os.path.abspath(str(output_loc).strip())
        if p.startswith("\\\\") or p.startswith("//"):
            return True
        drive, _ = os.path.splitdrive(p)
        if drive and len(drive) >= 2 and drive[1] == ":":
            try:
                import ctypes
                dt = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
                return dt == 4  # DRIVE_REMOTE
            except Exception:
                pass
        return False

    def _list_datum_transform(self, from_sr, to_sr):
        """Palauttaa ensimmäisen saatavilla olevan datummuunnoksen tai None."""
        try:
            trs = arcpy.ListTransformations(from_sr, to_sr)
            return trs[0] if trs else None
        except Exception:
            return None

    def _needs_projection(self, input_sr, target_sr):
        if not target_sr or not input_sr:
            return False
        try:
            c_in = int(input_sr.factoryCode) if input_sr.factoryCode else None
            c_out = int(target_sr.factoryCode) if target_sr.factoryCode else None
            if c_in is not None and c_out is not None:
                return c_in != c_out
        except Exception:
            pass
        return str(input_sr) != str(target_sr)

    def _project_cad_data(self, input_data, output_data, input_sr, target_sr):
        """Projisoi CAD-tason ja anna lähtö-CRS vain, jos aineiston CRS on tuntematon.

        CADToGeodatabase tallentaa tasot feature datasetin sisään. ArcGIS ei tue
        DefineProjection-kutsua tällaiselle feature classille, joten tunnistettu
        lähtökoordinaatisto annetaan tarvittaessa suoraan Project-työkalulle.
        """
        source_sr = None
        try:
            source_sr = getattr(arcpy.Describe(input_data), "spatialReference", None)
        except Exception:
            pass

        source_name = str(getattr(source_sr, "name", "") or "").strip().lower()
        source_is_known = bool(source_sr) and source_name not in ("", "unknown")
        transform = self._list_datum_transform(input_sr, target_sr)

        if source_is_known:
            arcpy.management.Project(input_data, output_data, target_sr, transform)
        else:
            arcpy.management.Project(input_data, output_data, target_sr, transform, input_sr)

    def _resolve_output_path(self, output_loc, output_name, is_folder):
        """Palauttaa (output_name, check_path) ArcGIS-yhteensopivalla nimellä."""
        def validate_name(candidate):
            try:
                validated = arcpy.ValidateTableName(candidate, output_loc)
                if validated:
                    return validated
            except Exception:
                pass
            return candidate

        def build_path(candidate):
            if is_folder:
                return os.path.join(output_loc, candidate + ".shp")
            else:
                return os.path.join(output_loc, candidate)

        output_name = validate_name(str(output_name or "output"))
        base_name = output_name
        check_path = build_path(output_name)

        # Kansioajoissa usealla lähteellä voi olla sama tiedostonimi (tai
        # GPKG:n sisäisillä tasoilla sama nimi). Älä käytä sekuntitason
        # aikaleimaa, koska monta osumaa voi syntyä saman sekunnin aikana.
        # Peräkkäinen tunniste tekee jokaisesta tuotoksesta varmasti oman
        # feature classin eikä aiempaa tuotosta ylikirjoiteta.
        suffix_number = 2
        while arcpy.Exists(check_path):
            suffix = f"_{suffix_number}"
            candidate_base = base_name[: max(1, 50 - len(suffix))]
            candidate = validate_name(candidate_base + suffix)
            candidate_path = build_path(candidate)
            if candidate_path == check_path:
                # Jos ValidateTableName lyhentää nimen niin, että tunniste
                # katoaa, vaihdetaan seuraavaan ehdokkaaseen.
                candidate = validate_name(f"output_{suffix_number}")
                candidate_path = build_path(candidate)
            output_name, check_path = candidate, candidate_path
            suffix_number += 1

        return output_name, check_path

    def _log_elapsed(self, messages, label, start_time):
        elapsed = time.perf_counter() - start_time
        self.log(messages, f"  > {label} valmis {elapsed:.0f} s.")

    def _is_non_simple_cad_input(self, input_data):
        """True annotaatio- tai multipatch-tasoille (Project ei toimi suoraan CAD-lähteestä)."""
        try:
            desc = arcpy.Describe(input_data)
            if getattr(desc, "featureType", "") == "Annotation":
                return True
            if (getattr(desc, "shapeType", "") or "").lower() == "multipatch":
                return True
        except Exception:
            pass
        return False

    def _scratch_fc_path(self, scratch, prefix, output_name):
        stamp = datetime.datetime.now().strftime("%H%M%S%f")
        name = self.sanitize_name(f"{prefix}_{output_name}_{stamp}")[:50]
        return os.path.join(scratch, name), name

    def _delete_if_exists(self, path):
        if path and arcpy.Exists(path):
            try:
                arcpy.management.Delete(path)
            except Exception:
                pass

    def _cad_layer_sort_key(self, fc, dataset_path):
        """Järjestys: point ensin, sitten line/polygon, lopuksi annotaatio/multipatch."""
        try:
            desc = arcpy.Describe(os.path.join(dataset_path, fc))
            if getattr(desc, "featureType", "") == "Annotation":
                return 2
            shape = (getattr(desc, "shapeType", "") or "").lower()
            if shape == "multipatch":
                return 2
            if shape == "point":
                return 0
            return 1
        except Exception:
            return 1

    def _save_cad_layer_non_simple(self, work_input, check_path, scratch, input_sr, target_sr,
                                   remote, messages, do_projection, scratch_intermediate=None,
                                   source_in_scratch=False):
        """Annotaatio/multipatch: CopyFeatures → scratch → DefineProjection → Project → kohde."""
        self.log(messages, "  > Annotaatio/multipatch: kopioidaan scratchGDB:hen ennen projisointia...")

        ns_input = scratch_intermediate
        scratch_copy = None
        if not ns_input:
            # Myös CADToGeodatabase-lähde kopioidaan feature datasetin ulkopuolelle,
            # jotta DefineProjection on ArcGISin tukema tälle väliaineistolle.
            scratch_copy, scratch_name = self._scratch_fc_path(scratch, "cad_ns", os.path.basename(check_path))
            self._delete_if_exists(scratch_copy)
            t0 = time.perf_counter()
            arcpy.management.CopyFeatures(work_input, scratch_copy)
            self._log_elapsed(messages, "Kopiointi scratchGDB:hen", t0)
            ns_input = scratch_copy

        if input_sr:
            arcpy.management.DefineProjection(ns_input, input_sr)

        if do_projection and input_sr:
            try:
                out_name_log = target_sr.name
            except Exception:
                out_name_log = "Kohdekoordinaatisto"
            self.log(messages, f"  > Muunnetaan koordinaatistoon: {out_name_log}...")

            t0 = time.perf_counter()
            arcpy.management.Project(ns_input, check_path, target_sr)
            self._log_elapsed(messages, "Projisointi", t0)
            if scratch_copy:
                self._delete_if_exists(scratch_copy)
        else:
            if do_projection and not input_sr:
                self.log(messages, "  > VAROITUS: Projisointi ohitettu (lähtö-CRS tuntematon).", "WARNING")
            if ns_input != check_path:
                t0 = time.perf_counter()
                arcpy.management.CopyFeatures(ns_input, check_path)
                self._log_elapsed(messages, "Kopiointi", t0)
            if scratch_copy:
                self._delete_if_exists(scratch_copy)

        if scratch_intermediate:
            self._delete_if_exists(scratch_intermediate)

        return check_path

    def _add_layers_to_map(self, paths, messages):
        if not paths:
            return
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            if not active_map:
                return
            for path in paths:
                if path and arcpy.Exists(path):
                    active_map.addDataFromPath(path)
        except Exception as e:
            self.log(messages, f"  > Karttalisäys epäonnistui: {e}", "WARNING")

    def _save_cad_layer_fallback(self, input_data, output_loc, output_name, is_folder,
                                 field_mappings, input_sr, target_sr, messages, check_path, feat_count=None):
        """Vanha Copy + DefineProjection + Project -ketju (fallback)."""
        count_str = f" ({feat_count} kohdetta)" if feat_count else ""
        self.log(messages, f"  > Perinteinen tallennusketju{count_str}...")

        remote = self._is_remote_output(output_loc)
        scratch = arcpy.env.scratchGDB
        scratch_copy = None

        try:
            t0 = time.perf_counter()
            if remote and not field_mappings:
                scratch_copy, _ = self._scratch_fc_path(scratch, "fb", output_name)
                self._delete_if_exists(scratch_copy)
                arcpy.management.CopyFeatures(input_data, scratch_copy)
                self._log_elapsed(messages, "Kopiointi scratchGDB:hen (fallback)", t0)
                work_path = scratch_copy
            elif field_mappings:
                try:
                    arcpy.conversion.FeatureClassToFeatureClass(
                        input_data, output_loc, output_name, field_mapping=field_mappings
                    )
                except arcpy.ExecuteError as e:
                    self.log(
                        messages,
                        f"  > FeatureClassToFeatureClass epäonnistui ({e.__class__.__name__}), kokeillaan CopyFeatures-fallbackia.",
                        "WARNING",
                    )
                    arcpy.management.CopyFeatures(input_data, check_path)
                self._log_elapsed(messages, "Kopiointi (fallback)", t0)
                work_path = check_path
            else:
                arcpy.management.CopyFeatures(input_data, check_path)
                self._log_elapsed(messages, "Kopiointi (fallback)", t0)
                work_path = check_path

            if input_sr and work_path:
                try:
                    arcpy.management.DefineProjection(work_path, input_sr)
                except Exception as _dp_err:
                    self.log(messages, f"  > DefineProjection epäonnistui: {_dp_err}", "WARNING")

            if self._needs_projection(input_sr, target_sr):
                try:
                    out_name_log = target_sr.name
                except Exception:
                    out_name_log = "Kohdekoordinaatisto"
                self.log(messages, f"  > Muunnetaan koordinaatistoon: {out_name_log}...")
                _tr = self._list_datum_transform(input_sr, target_sr)

                t1 = time.perf_counter()
                if remote and not field_mappings:
                    arcpy.management.Project(work_path, check_path, target_sr, _tr)
                    self._log_elapsed(messages, "Projisointi (fallback)", t1)
                    return check_path

                projected_name = output_name + "_proj"
                try:
                    validated_projected = arcpy.ValidateTableName(projected_name, output_loc)
                    if validated_projected:
                        projected_name = validated_projected
                except Exception:
                    pass
                if is_folder:
                    projected_path = os.path.join(output_loc, projected_name + ".shp")
                else:
                    projected_path = os.path.join(output_loc, projected_name)

                arcpy.management.Project(work_path, projected_path, target_sr, _tr)
                self._log_elapsed(messages, "Projisointi (fallback)", t1)

                if work_path != projected_path and work_path != check_path:
                    self._delete_if_exists(work_path)
                elif work_path == check_path:
                    try:
                        arcpy.management.Delete(check_path)
                    except Exception as del_err:
                        self.log(messages, f"  > Projisoimattoman välitason poisto epäonnistui: {del_err}", "WARNING")
                return projected_path

            if remote and not field_mappings and work_path != check_path:
                arcpy.management.CopyFeatures(work_path, check_path)
            return check_path
        finally:
            self._delete_if_exists(scratch_copy)

    def _save_cad_layer(self, input_data, output_loc, output_name, is_folder,
                        field_mappings, input_sr, target_sr, messages, feat_count=None,
                        is_non_simple=False, source_in_scratch=False):
        """Optimoidtu CAD-tallennus: yksi Project-kutsu tai scratchGDB väli verkkokohteelle."""
        output_name, check_path = self._resolve_output_path(output_loc, output_name, is_folder)
        count_str = f" ({feat_count} kohdetta)" if feat_count else ""
        self.log(messages, f"Tallennetaan: {output_name}{count_str}...")

        do_projection = self._needs_projection(input_sr, target_sr)
        remote = self._is_remote_output(output_loc)
        scratch = arcpy.env.scratchGDB
        scratch_intermediate = None

        try:
            work_input = input_data

            if field_mappings:
                stamp = datetime.datetime.now().strftime("%H%M%S%f")
                scratch_name = self.sanitize_name(f"cad_{output_name}_{stamp}")[:50]
                scratch_intermediate = os.path.join(scratch, scratch_name)
                if arcpy.Exists(scratch_intermediate):
                    arcpy.management.Delete(scratch_intermediate)
                t0 = time.perf_counter()
                try:
                    arcpy.conversion.FeatureClassToFeatureClass(
                        input_data, scratch, scratch_name, field_mapping=field_mappings
                    )
                except arcpy.ExecuteError as e:
                    self.log(
                        messages,
                        f"  > FeatureClassToFeatureClass epäonnistui ({e.__class__.__name__}), kokeillaan CopyFeatures-fallbackia.",
                        "WARNING",
                    )
                    arcpy.management.CopyFeatures(input_data, scratch_intermediate)
                self._log_elapsed(messages, "Kenttäsuodatus", t0)
                work_input = scratch_intermediate

            if not is_non_simple:
                is_non_simple = self._is_non_simple_cad_input(work_input)

            if is_non_simple:
                return self._save_cad_layer_non_simple(
                    work_input, check_path, scratch, input_sr, target_sr,
                    remote, messages, do_projection, scratch_intermediate,
                    source_in_scratch=source_in_scratch,
                )

            if do_projection and input_sr:
                try:
                    out_name_log = target_sr.name
                except Exception:
                    out_name_log = "Kohdekoordinaatisto"
                self.log(messages, f"  > Muunnetaan koordinaatistoon: {out_name_log}...")

                t0 = time.perf_counter()
                self._project_cad_data(work_input, check_path, input_sr, target_sr)
                self._log_elapsed(messages, "Projisointi", t0)

            elif do_projection and not input_sr:
                self.log(messages, "  > VAROITUS: Projisointi ohitettu (lähtö-CRS tuntematon).", "WARNING")
                t0 = time.perf_counter()
                arcpy.management.CopyFeatures(work_input, check_path)
                self._log_elapsed(messages, "Kopiointi", t0)

            else:
                t0 = time.perf_counter()
                arcpy.management.CopyFeatures(work_input, check_path)
                self._log_elapsed(messages, "Kopiointi", t0)

            if scratch_intermediate and arcpy.Exists(scratch_intermediate):
                try:
                    arcpy.management.Delete(scratch_intermediate)
                except Exception:
                    pass

            return check_path

        except Exception as e:
            self.log(messages, f"  > Optimointi epäonnistui ({e}), kokeillaan perinteistä ketjua.", "WARNING")
            if scratch_intermediate and arcpy.Exists(scratch_intermediate):
                try:
                    arcpy.management.Delete(scratch_intermediate)
                except Exception:
                    pass
            return self._save_cad_layer_fallback(
                input_data, output_loc, output_name, is_folder,
                field_mappings, input_sr, target_sr, messages, check_path, feat_count,
            )

    # --- CAD PROCESSOR ---
    def process_cad(self, input_path, output_loc, is_folder, use_mapper, input_sr, target_sr, messages):
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        sanitized_name = self.sanitize_name(base_name)
        self.log(messages, f"Analysoidaan CAD-tiedostoa: {base_name}...")
        process_start = time.perf_counter()
        remote_output = self._is_remote_output(output_loc)

        prev_gp_env = {}
        for key, value in (
            ("parallelProcessingFactor", "100%"),
            ("buildStats", "NONE"),
            ("maintainSpatialIndex", False),
            ("autoCommit", 1000),
        ):
            try:
                prev_gp_env[key] = getattr(arcpy.env, key)
            except Exception:
                prev_gp_env[key] = None
            try:
                setattr(arcpy.env, key, value)
            except Exception:
                pass

        saved_paths = []

        # Yritetään ensin lukea DWG/DXF suoraan workspacena (nopea polku).
        # Tämä ohittaa raskaan CADToGeodatabase + annotaatioiden generoinnin.
        prev_ws = arcpy.env.workspace  # palautetaan lopuksi, ettei globaali tila vuoda seuraavaan tiedostoon
        dataset_path = None
        temp_gdb = None
        ds_name = None
        used_fast_path = False
        source_in_scratch = False
        fcs_direct = []

        try:
            arcpy.env.workspace = input_path
            fcs_direct = arcpy.ListFeatureClasses() or []
        except Exception as e:
            self.log(messages, f"Suora DWG-luku ei onnistunut ({e}), kokeillaan CADToGeodatabase-reittiä.", "WARNING")
            fcs_direct = []

        # Suorituskyky: jos useita CAD-tasoja projisoidaan, tehdään yksi CADToGeodatabase
        # scratchGDB:hen ja projisoidaan siitä. Tämä vähentää toistuvaa DWG-lukua.
        use_bulk_scratch = len(fcs_direct) >= 2 and (remote_output or target_sr is not None)

        if use_bulk_scratch:
            temp_gdb = arcpy.env.scratchGDB
            ds_name = f"cad_{sanitized_name}_{datetime.datetime.now().strftime('%H%M%S')}"
            if remote_output:
                self.log(
                    messages,
                    f"Verkkokohde: konvertoidaan DWG kerran scratchGDB:hen ({len(fcs_direct)} tasoa)...",
                )
            else:
                self.log(
                    messages,
                    f"Projisointioptimoitu reitti: konvertoidaan DWG kerran scratchGDB:hen ({len(fcs_direct)} tasoa)...",
                )
            try:
                t0 = time.perf_counter()
                arcpy.conversion.CADToGeodatabase(input_path, temp_gdb, ds_name, 1000)
                self._log_elapsed(messages, "CADToGeodatabase", t0)
                dataset_path = os.path.join(temp_gdb, ds_name)
                arcpy.env.workspace = dataset_path
                fcs = arcpy.ListFeatureClasses() or []
                source_in_scratch = True
            except Exception as e:
                self.log(messages, f"CADToGeodatabase epäonnistui: {e}", "ERROR")
                raise
        elif fcs_direct:
            self.log(messages, f"Luetaan DWG suoraan ({len(fcs_direct)} tasoa) - ohitetaan CADToGeodatabase.")
            dataset_path = input_path
            fcs = fcs_direct
            used_fast_path = True
        else:
            fcs = []

        # Fallback: CADToGeodatabase, jos suora luku ei antanut tasoja
        if not use_bulk_scratch and not used_fast_path:
            temp_gdb = arcpy.env.scratchGDB
            ds_name = f"cad_{sanitized_name}_{datetime.datetime.now().strftime('%H%M%S')}"
            self.log(messages, "Suoritetaan CADToGeodatabase (hitaampi reitti)...")
            try:
                arcpy.conversion.CADToGeodatabase(input_path, temp_gdb, ds_name, 1000)
                dataset_path = os.path.join(temp_gdb, ds_name)
                arcpy.env.workspace = dataset_path
                fcs = arcpy.ListFeatureClasses() or []
                source_in_scratch = True
            except Exception as e:
                self.log(messages, f"CADToGeodatabase epäonnistui: {e}", "ERROR")
                raise

        try:
            if not fcs:
                self.log(messages, "Varoitus: Ei tasoja.", "WARNING"); return

            fcs = sorted(fcs, key=lambda fc: self._cad_layer_sort_key(fc, dataset_path))

            # Cache rivimäärille: vältetään saman tason GetCount-kutsu useaan kertaan.
            feat_count_cache = {}

            # Automaattitunnistus (ensimmäisestä EI-tyhjästä point/line/polygon-tasosta)
            detected_sr = None
            if not input_sr:
                for fc in fcs:
                    try:
                        desc_check = arcpy.Describe(fc)
                        if desc_check.shapeType in ['Point', 'Polyline', 'Polygon']:
                            fc_path = os.path.join(dataset_path, fc)
                            fc_count = self._count_safe(fc_path)
                            feat_count_cache[fc_path] = fc_count
                            if fc_count > 0:
                                detected_sr = self.detect_finnish_crs(fc_path, messages)
                                if detected_sr: break
                    except Exception:
                        continue

            final_input_sr = input_sr if input_sr else detected_sr
            if not final_input_sr:
                self.log(messages, "VAROITUS: Koordinaatistoa ei voitu tunnistaa.", "WARNING")

            self.log(messages, f"Käsitellään {len(fcs)} tasoa...")

            for fc in fcs:
                try:
                    desc_fc = arcpy.Describe(fc)
                except Exception as e:
                    self.log(messages, f"  > Ohitetaan taso {fc} (kuvausvirhe: {e})", "WARNING")
                    continue

                geom_type = (desc_fc.shapeType or "").lower()
                is_anno = (getattr(desc_fc, 'featureType', '') == 'Annotation')

                suffix = geom_type or "unknown"
                if geom_type == 'polyline': suffix = 'line'
                if geom_type == 'multipatch': suffix = 'multipatch'
                if is_anno: suffix = 'anno'
                final_name = f"{sanitized_name}_{suffix}"

                # Shapefile-kansio ei tue annotation/multipatch hyvin
                if is_anno and is_folder: continue
                if geom_type == 'multipatch' and is_folder: continue

                is_non_simple = is_anno or geom_type == 'multipatch'

                full_input_path = os.path.join(dataset_path, fc)

                # Ohitetaan tyhjät featureclassit (estää "empty geometry" -virheen)
                feat_count = feat_count_cache.get(full_input_path)
                if feat_count is None:
                    feat_count = self._count_safe(full_input_path)
                    feat_count_cache[full_input_path] = feat_count
                if feat_count == 0:
                    self.log(messages, f"  > Ohitetaan tyhjä taso: {fc}")
                    continue

                if use_mapper:
                    temp_lyr_name = f"lyr_{suffix}"
                    if arcpy.Exists(temp_lyr_name): arcpy.management.Delete(temp_lyr_name)
                    try:
                        arcpy.management.MakeFeatureLayer(full_input_path, temp_lyr_name, "Layer NOT IN ('0', 'Defpoints')")
                    except Exception as e:
                        self.log(messages, f"  > MakeFeatureLayer epäonnistui tasolle {fc}: {e}", "WARNING")
                        continue
                    if int(arcpy.management.GetCount(temp_lyr_name).getOutput(0)) == 0:
                        arcpy.management.Delete(temp_lyr_name); continue

                    lyr_to_process = temp_lyr_name
                    field_mappings = arcpy.FieldMappings()
                    field_mappings.addTable(lyr_to_process)
                    keep = ['Layer', 'Color', 'RefName', 'Text', 'Elevation', 'DocPath']
                    keep_lower = [k.lower() for k in keep]
                    for f in list(field_mappings.fields):
                        if f.name not in keep and f.name.lower() not in keep_lower and not f.required:
                            idx = field_mappings.findFieldMapIndex(f.name)
                            if idx >= 0:
                                field_mappings.removeFieldMap(idx)

                    saved_path = self._save_cad_layer(
                        lyr_to_process, output_loc, final_name, is_folder,
                        field_mappings, final_input_sr, target_sr, messages, feat_count,
                        is_non_simple=is_non_simple,
                        source_in_scratch=source_in_scratch,
                    )
                    if saved_path:
                        saved_paths.append(saved_path)
                    try: arcpy.management.Delete(temp_lyr_name)
                    except: pass
                else:
                    saved_path = self._save_cad_layer(
                        full_input_path, output_loc, final_name, is_folder,
                        None, final_input_sr, target_sr, messages, feat_count,
                        is_non_simple=is_non_simple,
                        source_in_scratch=source_in_scratch,
                    )
                    if saved_path:
                        saved_paths.append(saved_path)

            if saved_paths:
                self._add_layers_to_map(saved_paths, messages)

            total_elapsed = time.perf_counter() - process_start
            self.log(messages, f"CAD-tuonti valmis {total_elapsed:.0f} s ({len(saved_paths)} tasoa).")
            if remote_output and total_elapsed > 120:
                self.log(
                    messages,
                    "  > Vinkki: varmista että ArcGIS Pro:n scratchGDB on paikallisella SSD:llä "
                    "(Project → Options → Geoprocessing → Scratch Workspace).",
                    "WARNING",
                )

        except Exception as e:
            self.log(messages, f"Virhe: {str(e)}", "ERROR")
            raise
        finally:
            for key, value in prev_gp_env.items():
                try:
                    setattr(arcpy.env, key, value)
                except Exception:
                    pass
            arcpy.env.workspace = prev_ws  # palauta globaali workspace
            # Siivoa väliaikainen dataset eräajon lopussa, jotta seuraava tiedosto voi alkaa heti.
            if temp_gdb and ds_name:
                full_ds = os.path.join(temp_gdb, ds_name)
                self._queue_deferred_cleanup(full_ds)

    def _count_safe(self, fc_path):
        """Palauttaa rivimäärän, 0 jos ei saada luettua."""
        try:
            return int(arcpy.management.GetCount(fc_path).getOutput(0))
        except Exception:
            return 0

    def _parse_input_sr(self, s):
        """Muuntaa dropdown-stringin SpatialReference-objektiksi.
        "Automaattinen" / tyhjä -> None (automaattitunnistus).
        "... (EPSG)" -> SpatialReference(EPSG).
        """
        if not s or s.strip().lower() == "automaattinen":
            return None
        m = re.search(r'\((\d+)\)', s)
        if m:
            try:
                return arcpy.SpatialReference(int(m.group(1)))
            except Exception:
                return None
        return None

    # --- TALLENNUS JA MUUNNOS (KORJATTU) ---
    def save_and_reproject(self, input_data, output_loc, output_name, is_folder, field_mappings, input_sr, target_sr, messages, add_to_map=True):
        output_name, check_path = self._resolve_output_path(output_loc, output_name, is_folder)
        feat_count = self._count_safe(input_data)
        count_str = f" ({feat_count} kohdetta)" if feat_count else ""
        self.log(messages, f"Tallennetaan: {output_name}{count_str}...")
        
        try:
            # 1. Tuodaan data (Raw geometry)
            t0 = time.perf_counter()
            if field_mappings:
                try:
                    arcpy.conversion.FeatureClassToFeatureClass(input_data, output_loc, output_name, field_mapping=field_mappings)
                except arcpy.ExecuteError as e:
                    # Tyypillisesti "empty geometry" -virhe yhdeltä riviltä kaataa koko muunnoksen.
                    # Yritetään uudelleen CopyFeaturesilla ilman mappingia, jolloin saadaan edes geometriat talteen.
                    self.log(messages, f"  > FeatureClassToFeatureClass epäonnistui ({e.__class__.__name__}), kokeillaan CopyFeatures-fallbackia.", "WARNING")
                    arcpy.management.CopyFeatures(input_data, check_path)
            else:
                # Ilman mappingia CopyFeatures on sekä nopeampi että sietää tyhjät geometriat.
                arcpy.management.CopyFeatures(input_data, check_path)
            self._log_elapsed(messages, "Kopiointi", t0)
            
            # 2. Leimataan lähtökoordinaatisto (DefineProjection)
            if input_sr:
                arcpy.management.DefineProjection(check_path, input_sr)
            
            # 3. Muunnetaan, jos kohde annettu ja eri kuin lähtö (Project)
            if self._needs_projection(input_sr, target_sr):
                # Turvallinen nimen haku lokia varten
                try: out_name_log = target_sr.name 
                except: out_name_log = "Kohdekoordinaatisto"
                
                self.log(messages, f"  > Muunnetaan koordinaatistoon: {out_name_log}...")
                
                projected_name = output_name + "_proj"
                try:
                    validated_projected = arcpy.ValidateTableName(projected_name, output_loc)
                    if validated_projected:
                        projected_name = validated_projected
                except Exception:
                    pass
                if is_folder: projected_path = os.path.join(output_loc, projected_name + ".shp")
                else: projected_path = os.path.join(output_loc, projected_name)
                
                t1 = time.perf_counter()
                arcpy.management.Project(check_path, projected_path, target_sr)
                self._log_elapsed(messages, "Projisointi", t1)

                # Poista projisoimaton välitaso — vain projisoitu jää kohteeseen ja kartalle.
                unprojected_path = check_path
                try:
                    arcpy.management.Delete(unprojected_path)
                except Exception as del_err:
                    self.log(messages, f"  > Projisoimattoman välitason poisto epäonnistui: {del_err}", "WARNING")

                # Kartalle lisätään vain projisoitu
                check_path = projected_path
            
            # 4. Lisää kartalle
            if add_to_map:
                try:
                    aprx = arcpy.mp.ArcGISProject("CURRENT")
                    if aprx.activeMap:
                        aprx.activeMap.addDataFromPath(check_path)
                except Exception:
                    pass

            return check_path

        except Exception as e:
            self.log(messages, f"Tallennusvirhe: {str(e)}", "ERROR")
            return None

    def _bulk_convert_and_add(self, source_items, output_loc, is_folder, messages, input_sr=None, target_sr=None):
        """Eräkirjoitus usealle tasolle: yksi karttalisäys lopuksi, GP-ympäristö viritetään suorituskykyyn."""
        if not source_items:
            return []

        saved_paths = []
        prev_gp_env = {}
        for key, value in (("parallelProcessingFactor", "100%"), ("autoCommit", 1000)):
            try:
                prev_gp_env[key] = getattr(arcpy.env, key)
            except Exception:
                prev_gp_env[key] = None
            try:
                setattr(arcpy.env, key, value)
            except Exception:
                pass

        try:
            for src_path, out_name in source_items:
                saved = self.save_and_reproject(
                    src_path,
                    output_loc,
                    out_name,
                    is_folder,
                    None,
                    input_sr,
                    target_sr,
                    messages,
                    add_to_map=False,
                )
                if saved:
                    saved_paths.append(saved)
        finally:
            for key, value in prev_gp_env.items():
                try:
                    setattr(arcpy.env, key, value)
                except Exception:
                    pass

        if saved_paths:
            self._add_layers_to_map(saved_paths, messages)
        return saved_paths

    # --- MUUT PARSERIT (Lyhennetty, kopioi tarvittaessa vanhat jos muutit niitä) ---
    def process_gpx_flattened(self, input_path, output_loc, is_folder, messages):
        """GPX-tuonti: tuo kaikki ei-tyhjät GPX-tasot (tracks/routes/points/waypoints)."""
        base_name = self.sanitize_name(os.path.splitext(os.path.basename(input_path))[0])
        self.log(messages, f"Tuodaan GPX: {os.path.basename(input_path)}...")

        prev_ws = arcpy.env.workspace
        batch_items = []
        try:
            # Yritä lukea GPX suoraan workspacena (näkyvät tasot: tracks/routes/points/waypoints).
            arcpy.env.workspace = input_path
            fcs = arcpy.ListFeatureClasses() or []

            if fcs:
                suffix_map = {
                    "track_points": "track_points",
                    "route_points": "route_points",
                    "tracks": "tracks",
                    "routes": "routes",
                    "waypoints": "waypoints",
                }

                for fc in fcs:
                    fc_path = os.path.join(input_path, fc)
                    cnt = self._count_safe(fc_path)
                    if cnt == 0:
                        continue

                    key = str(fc).strip().lower()
                    suffix = suffix_map.get(key)
                    if not suffix:
                        try:
                            geom = (arcpy.Describe(fc_path).shapeType or "").lower()
                        except Exception:
                            geom = ""
                        suffix = {
                            "point": "point",
                            "polyline": "line",
                            "polygon": "polygon",
                        }.get(geom, self.sanitize_name(fc) or "gpx")

                    batch_items.append((fc_path, f"{base_name}_{suffix}"))

                if batch_items:
                    self.log(messages, f"  > GPX: löydettiin {len(batch_items)} ei-tyhjää tasoa.")
                    self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
                    return
        except Exception as e:
            self.log(messages, f"  > GPX-suoraluku epäonnistui ({e}); käytetään GPXtoFeatures-fallbackia.", "WARNING")
        finally:
            arcpy.env.workspace = prev_ws

        # Fallback vanhemmille ympäristöille: tuo pisteet GPXtoFeaturesilla.
        scratch = arcpy.env.scratchGDB
        stamp = datetime.datetime.now().strftime("%H%M%S%f")
        tmp_fc = os.path.join(scratch, f"gpx_{base_name[:28]}_{stamp}")
        if arcpy.Exists(tmp_fc):
            try:
                arcpy.management.Delete(tmp_fc)
            except Exception:
                pass
        try:
            arcpy.conversion.GPXtoFeatures(input_path, tmp_fc)
        except Exception as e:
            self.log(messages, f"  > GPXtoFeatures epäonnistui: {e}", "ERROR")
            raise
        if self._count_safe(tmp_fc) == 0:
            self.log(messages, f"  > GPX-tuonti: tiedostosta '{input_path}' ei löytynyt geometriaa.", "WARNING")
            try:
                arcpy.management.Delete(tmp_fc)
            except Exception:
                pass
            return
        self.convert_and_add(tmp_fc, output_loc, f"{base_name}_point", is_folder, messages)
        try:
            arcpy.management.Delete(tmp_fc)
        except Exception:
            pass
        self._gpx_extract_tracks(input_path, output_loc, base_name, is_folder, messages)

    def _gpx_extract_tracks(self, input_path, output_loc, base_name, is_folder, messages):
        """Luo viiva-FC GPX-radoista ja -reiteistä (trk/rte) XML-analyysillä."""
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(input_path)
            root = tree.getroot()
            ns = root.tag[1:root.tag.index('}')] if root.tag.startswith('{') else ''
            p = f'{{{ns}}}' if ns else ''

            sr = arcpy.SpatialReference(4326)
            scratch = arcpy.env.scratchGDB
            stamp = datetime.datetime.now().strftime("%H%M%S%f")
            tmp_fc = os.path.join(scratch, f"gpx_ln_{base_name[:22]}_{stamp}")
            if arcpy.Exists(tmp_fc):
                arcpy.management.Delete(tmp_fc)
            arcpy.management.CreateFeatureclass(
                scratch, os.path.basename(tmp_fc), "POLYLINE", spatial_reference=sr
            )
            count = 0
            with arcpy.da.InsertCursor(tmp_fc, ["SHAPE@"]) as cur:
                for trk in root.findall(f'{p}trk'):
                    for seg in trk.findall(f'{p}trkseg'):
                        pts = [
                            arcpy.Point(float(pt.get('lon')), float(pt.get('lat')))
                            for pt in seg.findall(f'{p}trkpt')
                            if pt.get('lat') and pt.get('lon')
                        ]
                        if len(pts) >= 2:
                            cur.insertRow([arcpy.Polyline(arcpy.Array(pts), sr)])
                            count += 1
                for rte in root.findall(f'{p}rte'):
                    pts = [
                        arcpy.Point(float(pt.get('lon')), float(pt.get('lat')))
                        for pt in rte.findall(f'{p}rtept')
                        if pt.get('lat') and pt.get('lon')
                    ]
                    if len(pts) >= 2:
                        cur.insertRow([arcpy.Polyline(arcpy.Array(pts), sr)])
                        count += 1
            if count > 0:
                self.convert_and_add(tmp_fc, output_loc, f"{base_name}_tracks", is_folder, messages)
            try:
                arcpy.management.Delete(tmp_fc)
            except Exception:
                pass
        except Exception as e:
            self.log(messages, f"  > GPX-viivoja ei voitu luoda: {e}", "WARNING")

    def process_kml_flattened(self, input_path, output_loc, is_folder, messages):
        """KML/KMZ-tuonti: KMLToLayer purkaa väli-GDB:hen, ei-tyhjät tasot viedään kohteeseen."""
        import tempfile
        import shutil
        base_name = self.sanitize_name(os.path.splitext(os.path.basename(input_path))[0])
        self.log(messages, f"Tuodaan KML/KMZ: {os.path.basename(input_path)}...")
        work_dir = tempfile.mkdtemp(prefix="muuntaja_kml_")
        prev_ws = arcpy.env.workspace
        made_any = False
        merge_cleanup = []
        try:
            try:
                arcpy.conversion.KMLToLayer(input_path, work_dir, base_name)
            except Exception as e:
                self.log(messages, f"  > KMLToLayer epäonnistui: {e}", "ERROR")
                raise
            # KMLToLayer luo work_dir\<nimi>.gdb, jossa feature dataset (Points/Polylines/Polygons).
            gdb = os.path.join(work_dir, base_name + ".gdb")
            if not arcpy.Exists(gdb):
                gdb = None
                for entry in os.listdir(work_dir):
                    if entry.lower().endswith(".gdb"):
                        gdb = os.path.join(work_dir, entry)
                        break
            if not gdb or not arcpy.Exists(gdb):
                self.log(messages, "  > KML-tuonti: KMLToLayer ei tuottanut geodatabasea.", "WARNING")
                return
            arcpy.env.workspace = gdb
            fc_paths = []
            for ds in (arcpy.ListDatasets() or []):
                for fc in (arcpy.ListFeatureClasses(feature_dataset=ds) or []):
                    fc_paths.append(os.path.join(gdb, ds, fc))
            for fc in (arcpy.ListFeatureClasses() or []):  # mahdolliset GDB-juuren tasot
                fc_paths.append(os.path.join(gdb, fc))

            grouped = {}
            for fc_path in fc_paths:
                if self._count_safe(fc_path) == 0:
                    continue
                try:
                    geom = (arcpy.Describe(fc_path).shapeType or "").lower()
                except Exception:
                    geom = ""
                suffix = {"point": "point", "polyline": "line", "polygon": "polygon"}.get(geom, geom or "kml")
                made_any = True
                grouped.setdefault(suffix, []).append(fc_path)

            if not made_any:
                self.log(messages, f"  > KML-tuonti: tiedostosta '{input_path}' ei saatu yhtään geometriaa.", "WARNING")
                return

            batch_items = []
            scratch = arcpy.env.scratchGDB
            stamp = datetime.datetime.now().strftime("%H%M%S%f")
            for suffix, group_paths in grouped.items():
                out_name = f"{base_name}_{suffix}"
                if len(group_paths) == 1:
                    batch_items.append((group_paths[0], out_name))
                    continue
                merged_name = self.sanitize_name(f"kml_merge_{base_name[:18]}_{suffix}_{stamp}")[:50]
                merged_fc = os.path.join(scratch, merged_name)
                if arcpy.Exists(merged_fc):
                    arcpy.management.Delete(merged_fc)
                arcpy.management.Merge(group_paths, merged_fc)
                merge_cleanup.append(merged_fc)
                batch_items.append((merged_fc, out_name))

            self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
        finally:
            arcpy.env.workspace = prev_ws
            for p in merge_cleanup:
                try:
                    if arcpy.Exists(p):
                        arcpy.management.Delete(p)
                except Exception:
                    pass
            try: shutil.rmtree(work_dir, ignore_errors=True)
            except Exception: pass

    def _detect_geojson_geometry_types(self, input_path):
        """Palauttaa löydetyt geometriatyypit joukkona: {'POINT','POLYLINE','POLYGON'} tai None."""
        try:
            with open(input_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            return None

        found = set()

        def _add_type(geom_type):
            gt = (geom_type or "").strip().lower()
            if gt in ("point", "multipoint", "esrigeometrypoint"):
                found.add("POINT")
            elif gt in ("linestring", "multilinestring", "esrigeometrypolyline"):
                found.add("POLYLINE")
            elif gt in ("polygon", "multipolygon", "esrigeometrypolygon"):
                found.add("POLYGON")

        try:
            if isinstance(data, dict):
                _add_type(data.get("geometryType"))
                top_type = (data.get("type") or "").lower()
                if top_type == "featurecollection":
                    for feat in data.get("features", []) or []:
                        if not isinstance(feat, dict):
                            continue
                        geom = feat.get("geometry")
                        if isinstance(geom, dict):
                            _add_type(geom.get("type"))
                elif top_type == "feature":
                    geom = data.get("geometry")
                    if isinstance(geom, dict):
                        _add_type(geom.get("type"))
                else:
                    _add_type(data.get("type"))
        except Exception:
            return None

        return found if found else None

    def process_geojson_flattened(self, input_path, output_loc, is_folder, messages):
        """GeoJSON/JSON-tuonti: geometriatyypit (piste/viiva/polygon) eriytetään omiksi tasoiksi."""
        base_name = self.sanitize_name(os.path.splitext(os.path.basename(input_path))[0])
        scratch = arcpy.env.scratchGDB
        stamp = datetime.datetime.now().strftime("%H%M%S%f")
        self.log(messages, f"Tuodaan GeoJSON/JSON: {os.path.basename(input_path)}...")
        made_any = False
        detected_types = self._detect_geojson_geometry_types(input_path)
        if detected_types:
            self.log(messages, f"  > GeoJSON-analyysi: löytyneet geometriat: {', '.join(sorted(detected_types))}")
            candidates = [("POINT", "point"), ("POLYLINE", "line"), ("POLYGON", "polygon")]
            candidates = [c for c in candidates if c[0] in detected_types]
        else:
            candidates = [("POINT", "point"), ("POLYLINE", "line"), ("POLYGON", "polygon")]

        batch_items = []
        for geom_type, suffix in candidates:
            tmp_fc = os.path.join(scratch, f"json_{base_name[:22]}_{suffix}_{stamp}")
            if arcpy.Exists(tmp_fc):
                try: arcpy.management.Delete(tmp_fc)
                except Exception: pass
            try:
                # JSONToFeatures tukee sekä GeoJSONia että Esri-JSONia; geometry_type rajaa yhteen tyyppiin.
                arcpy.conversion.JSONToFeatures(input_path, tmp_fc, geom_type)
            except Exception:
                # Tätä geometriatyyppiä ei tiedostossa — ohitetaan hiljaa (sekamuotoinen GeoJSON sallittu).
                continue
            if self._count_safe(tmp_fc) == 0:
                try: arcpy.management.Delete(tmp_fc)
                except Exception: pass
                continue
            made_any = True
            batch_items.append((tmp_fc, f"{base_name}_{suffix}"))
        if batch_items:
            self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
            for tmp_fc, _out_name in batch_items:
                try:
                    if arcpy.Exists(tmp_fc):
                        arcpy.management.Delete(tmp_fc)
                except Exception:
                    pass
        if not made_any:
            self.log(messages, f"  > GeoJSON-tuonti: tiedostosta '{input_path}' ei saatu yhtään geometriaa.", "WARNING")
    def process_geopackage(self, input_path, output_loc, is_folder, messages):
        prev_ws = arcpy.env.workspace
        try:
            arcpy.env.workspace = input_path
            fcs = []
            # Varmista monitasoinen luku myös mahdollisista dataset-rakenteista.
            for ds in (arcpy.ListDatasets() or []):
                for fc in (arcpy.ListFeatureClasses(feature_dataset=ds) or []):
                    fcs.append(os.path.join(ds, fc))
            for fc in (arcpy.ListFeatureClasses() or []):
                fcs.append(fc)

            # Poista duplikaatit säilyttäen järjestys.
            fcs = list(dict.fromkeys(fcs))

            batch_items = []
            for fc in fcs:
                src_path = os.path.join(input_path, fc)
                if self._count_safe(src_path) == 0:
                    self.log(messages, f"  > Ohitetaan tyhjä GPKG-taso: {fc}")
                    continue
                out_name = self.sanitize_name(os.path.splitext(os.path.basename(fc))[0])
                batch_items.append((src_path, out_name))
            if batch_items:
                self.log(messages, f"  > GPKG-eräajo: {len(batch_items)} tasoa.")
                self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
            else:
                self.log(messages, "  > GPKG-tuonti: ei löytynyt ei-tyhjiä tasoja.", "WARNING")
        finally:
            arcpy.env.workspace = prev_ws  # palauta globaali workspace, ettei vuoda seuraavaan tiedostoon

    def process_generic(self, input_path, output_loc, is_folder, messages):
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        self.convert_and_add(input_path, output_loc, self.sanitize_name(base_name), is_folder, messages)

    def _detect_dfsu_shape_type(self, geometry):
        """Tunnista DFSU-geometrian ArcGIS-muoto: POINT, POLYLINE tai POLYGON.

        Perustuu elementin solmumäärään (mikeio element_table):
        - 1 solmu/elementti -> piste
        - 2 solmua/elementti -> viiva
        - 3+ solmua/elementti -> polygon (esim. kolmiomesh)
        """
        geom_type_name = type(geometry).__name__
        if geom_type_name in ("GeometryPoint2D", "GeometryPoint3D"):
            return "POINT"

        element_table = getattr(geometry, "element_table", None)
        if element_table is None or len(element_table) == 0:
            return "POINT"

        try:
            max_nodes = int(geometry.max_nodes_per_element)
        except Exception:
            max_nodes = max(len(element_table[i]) for i in range(min(len(element_table), 1000)))

        min_nodes = max_nodes
        sample_size = min(len(element_table), 5000)
        for i in range(sample_size):
            n = len(element_table[i])
            if n < min_nodes:
                min_nodes = n
            if min_nodes == 1 and max_nodes >= 3:
                break

        if max_nodes == 1:
            return "POINT"
        if max_nodes == 2:
            return "POLYLINE"
        if min_nodes >= 3:
            return "POLYGON"
        if max_nodes >= 3:
            return "POLYGON"
        if max_nodes == 2:
            return "POLYLINE"
        return "POINT"

    def _make_dfsu_arcpy_geometry(self, idx, node_coords, element_table, shape_type, spatial_ref, element_coordinates=None):
        """Muodosta yhden elementin ArcGIS-geometria tunnistetun tyypin mukaan."""
        if shape_type in ("POLYGON", "POLYLINE"):
            if element_table is None or node_coords is None:
                raise ValueError(f"Elementti {idx}: {shape_type}-geometriaa ei voitu muodostaa ilman element_table/node_coordinates.")
            nodes = element_table[idx]
            point_array = arcpy.Array()
            for node_id in nodes:
                nc = node_coords[int(node_id)]
                point_array.add(arcpy.Point(float(nc[0]), float(nc[1])))
            if shape_type == "POLYLINE":
                return arcpy.Polyline(point_array, spatial_ref)
            return arcpy.Polygon(point_array, spatial_ref)

        if element_table is not None and node_coords is not None:
            nodes = element_table[idx]
            if nodes is not None and len(nodes) == 1:
                nc = node_coords[int(nodes[0])]
                return arcpy.PointGeometry(arcpy.Point(float(nc[0]), float(nc[1])), spatial_ref)
            if nodes is not None and len(nodes) > 1:
                xs = [float(node_coords[int(n)][0]) for n in nodes]
                ys = [float(node_coords[int(n)][1]) for n in nodes]
                return arcpy.PointGeometry(
                    arcpy.Point(sum(xs) / len(xs), sum(ys) / len(ys)), spatial_ref
                )
        if element_coordinates is not None:
            coords = element_coordinates[idx]
            return arcpy.PointGeometry(arcpy.Point(float(coords[0]), float(coords[1])), spatial_ref)
        raise ValueError(f"Elementti {idx}: pistegeometriaa ei voitu muodostaa.")

    def process_dfsu(self, input_path, output_loc, is_folder, messages,
                     filter_enabled=False, filter_column="", filter_operator="=",
                     filter_value="", target_sr=None):
        """DFSU-tiedoston tuonti suodattimella.
        
        DFSU (DHI File System) on binäärimuoto hydrologisille malleille.
        Tämä on perustotutus joka lukee DFSU-datan ja muuntaa sen GDB-feature classiksi.
        Geometriatyyppi (piste/viiva/polygon) tunnistetaan automaattisesti element_tablesta.
        
        Parametrit:
        - filter_enabled: Jos True, käytetään suodatinta
        - filter_column: Suodatettavan sarakkeen nimi
        - filter_operator: Operaattori (=, ≠, >, >=, <, <=, contains, starts with, ends with)
        - filter_value: Suodatusarvo
        - target_sr: Kohde-koordinaatisto (valinnainen)
        """
        temp_fc = None
        try:
            try:
                import math
                mikeio = self._ensure_python_module("mikeio", package_name="mikeio", messages=messages, auto_install=False)
            except Exception as e:
                raise RuntimeError(
                    "DFSU-tuonti vaatii mikeio-kirjaston ArcGIS Pron Python-ympäristöön. "
                    f"Kirjastoa ei löytynyt: {e}"
                )

            base_name = os.path.splitext(os.path.basename(input_path))[0]
            safe_name = self.sanitize_name(base_name)
            self.log(messages, f"DFSU-tiedoston '{input_path}' tuonti aloitettu...")
            if filter_enabled and filter_column:
                self.log(messages, f"DFSU-tuonti: Suodatin käytössä: sarake='{filter_column}', operaattori='{filter_operator}', arvo='{filter_value}'")
            else:
                self.log(messages, "DFSU-tuonti: Ei suodatinta")

            self.log(messages, "  > Luetaan DFSU-metatiedot...")
            dfs = mikeio.open(input_path)
            self.log(messages, "  > Luetaan DFSU-itemien arvot muistiin (vain 1. aika-askel)...")
            try:
                # Tuonti käyttää vain ensimmäistä aika-askelta — luetaan vain se (säästää muistia isoilla malleilla).
                dataset = mikeio.read(input_path, time=0)
            except Exception:
                dataset = mikeio.read(input_path)
            item_names = [getattr(item, "name", "") for item in getattr(dataset, "items", []) or []]
            if not item_names:
                raise RuntimeError("DFSU-tiedostosta ei löytynyt item-kenttiä.")
            self.log(messages, f"  > DFSU-itemit: {len(item_names)} kpl.")

            geometry = getattr(dataset, "geometry", None) or getattr(dfs, "geometry", None)
            element_table = getattr(geometry, "element_table", None)
            element_coordinates = getattr(geometry, "element_coordinates", None)
            if element_table is None or len(element_table) == 0:
                if element_coordinates is None or len(element_coordinates) == 0:
                    raise RuntimeError("DFSU-geometriasta ei löytynyt elementtien topologiaa eikä koordinaatteja.")
                total_elements = len(element_coordinates)
            else:
                total_elements = len(element_table)
            shape_type = self._detect_dfsu_shape_type(geometry)
            shape_labels = {"POINT": "piste", "POLYLINE": "viiva (polyline)", "POLYGON": "polygon"}
            self.log(messages, f"  > Elementtejä yhteensä: {total_elements}.")
            self.log(messages, f"  > Tunnistettu geometriatyyppi: {shape_labels.get(shape_type, shape_type)} ({shape_type}).")
            node_coords = getattr(geometry, "node_coordinates", None)
            if shape_type in ("POLYGON", "POLYLINE") and node_coords is None:
                raise RuntimeError("DFSU-polygon/viiva-tuonti vaatii node_coordinates-tiedot.")

            source_sr = None
            projection_string = getattr(geometry, "projection_string", None)
            if projection_string:
                try:
                    source_sr = arcpy.SpatialReference()
                    source_sr.loadFromString(str(projection_string))
                except Exception:
                    source_sr = None
            create_sr = source_sr or target_sr

            scratch = arcpy.env.scratchGDB
            stamp = datetime.datetime.now().strftime("%H%M%S%f")
            temp_fc = os.path.join(scratch, f"dfsu_{safe_name[:32]}_{stamp}")
            if arcpy.Exists(temp_fc):
                arcpy.management.Delete(temp_fc)
            self.log(messages, f"  > Luodaan väliaikainen {shape_type}-feature class...")
            arcpy.management.CreateFeatureclass(scratch, os.path.basename(temp_fc), shape_type, spatial_reference=create_sr)
            arcpy.management.AddField(temp_fc, "element_id", "LONG")

            field_map = []
            used_fields = {"element_id"}
            for item_name in item_names:
                field_name = self.sanitize_field_name(item_name)[:30] or "value"
                base_field_name = field_name
                suffix = 2
                while field_name.lower() in used_fields:
                    trimmed = base_field_name[: max(1, 27 - len(str(suffix)))]
                    field_name = f"{trimmed}_{suffix}"
                    suffix += 1
                used_fields.add(field_name.lower())
                arcpy.management.AddField(temp_fc, field_name, "DOUBLE")
                field_map.append((str(item_name), field_name))
            self.log(messages, f"  > Luotiin {len(field_map)} attribuuttikenttää.")

            values_by_item = {}
            for item_name, field_name in field_map:
                arr = dataset[item_name].to_numpy()
                if getattr(arr, "ndim", 0) >= 2:
                    arr = arr[0]
                try:
                    if hasattr(arr, "reshape"):
                        arr = arr.reshape(-1)
                except Exception:
                    pass
                # Store float64 numpy array directly; NaN→None conversion is done inline during insertion.
                try:
                    import numpy as _np
                    values_by_item[item_name] = _np.asarray(arr, dtype="float64")
                except Exception:
                    converted = []
                    for v in list(arr):
                        try:
                            fv = float(v)
                            converted.append(None if fv != fv else fv)
                        except Exception:
                            converted.append(None)
                    values_by_item[item_name] = converted

            resolved_filter_column = filter_column
            if filter_enabled and filter_column:
                col_lc = filter_column.strip().lower()
                for item_name in item_names:
                    if str(item_name).strip().lower() == col_lc:
                        resolved_filter_column = str(item_name)
                        break

            filter_values = values_by_item.get(resolved_filter_column) if filter_enabled and resolved_filter_column else None
            if filter_enabled and filter_column and filter_values is None:
                self.log(
                    messages,
                    f"  > VAROITUS: suodatussaraketta '{filter_column}' ei löytynyt DFSU-itemeistä "
                    f"({', '.join(item_names)}). Suodatin ei osu yhteenkään riviin — tarkista sarakkeen nimi.",
                    "WARNING",
                )
            elif filter_enabled and filter_column:
                if resolved_filter_column != filter_column:
                    self.log(messages, f"  > Suodatus kohdistuu itemiin '{resolved_filter_column}' (valittu: '{filter_column}').")
                else:
                    self.log(messages, f"  > Suodatus kohdistuu itemiin '{resolved_filter_column}'.")

            def _coerce_scalar(raw_value):
                v = raw_value
                for _ in range(4):
                    if v is None:
                        return None
                    try:
                        if isinstance(v, str):
                            return v
                    except Exception:
                        pass
                    try:
                        if hasattr(v, "item"):
                            vv = v.item()
                            if vv is not v:
                                v = vv
                                continue
                    except Exception:
                        pass
                    try:
                        if isinstance(v, (list, tuple)) and len(v) == 1:
                            v = v[0]
                            continue
                    except Exception:
                        pass
                    try:
                        if hasattr(v, "shape") and hasattr(v, "size") and int(v.size) == 1:
                            if hasattr(v, "reshape"):
                                v = v.reshape(-1)[0]
                                continue
                    except Exception:
                        pass
                    break
                return v

            def _to_float(raw_value):
                v = _coerce_scalar(raw_value)
                if v is None:
                    return None
                if isinstance(v, str):
                    v = v.strip().replace(",", ".")
                    if v == "":
                        return None
                try:
                    num = float(v)
                except Exception:
                    return None
                try:
                    if math.isnan(num):
                        return None
                except Exception:
                    pass
                return num

            if filter_enabled and filter_values is not None:
                sample_limit = min(total_elements, 50000)
                step = max(1, total_elements // sample_limit)
                cnt_numeric = 0
                cnt_positive = 0
                min_num = None
                max_num = None
                for i in range(0, total_elements, step):
                    try:
                        num = _to_float(filter_values[i])
                    except Exception:
                        num = None
                    if num is None:
                        continue
                    cnt_numeric += 1
                    if num > 0:
                        cnt_positive += 1
                    if min_num is None or num < min_num:
                        min_num = num
                    if max_num is None or num > max_num:
                        max_num = num
                self.log(
                    messages,
                    f"  > Suodatin-diagnostiikka (otanta): numeerisia={cnt_numeric}, >0={cnt_positive}, min={min_num}, max={max_num}."
                )

            def _passes_filter(raw_value):
                if not filter_enabled or not filter_column:
                    return True
                op = (filter_operator or "=").strip().lower()
                target_text = str(filter_value or "")
                left_value = _coerce_scalar(raw_value)
                if left_value is None:
                    return False
                left_text = str(left_value)
                if op in ("contains", "starts with", "ends with"):
                    left_cmp = left_text.lower()
                    right_cmp = target_text.lower()
                    if op == "contains":
                        return right_cmp in left_cmp
                    if op == "starts with":
                        return left_cmp.startswith(right_cmp)
                    return left_cmp.endswith(right_cmp)
                left_num = _to_float(left_value)
                right_num = _to_float(target_text)
                if left_num is not None and right_num is not None:
                    if op == "=":
                        return left_num == right_num
                    if op == "≠":
                        return left_num != right_num
                    if op == ">":
                        return left_num > right_num
                    if op == ">=":
                        return left_num >= right_num
                    if op == "<":
                        return left_num < right_num
                    if op == "<=":
                        return left_num <= right_num
                if op == "=":
                    return left_text == target_text
                if op == "≠":
                    return left_text != target_text
                return False

            candidate_indices = None
            if filter_enabled and filter_column and filter_values is not None:
                try:
                    import numpy as _np

                    op = (filter_operator or "=").strip().lower()
                    right_num = _to_float(filter_value)
                    # Numeerisissa suodattimissa voidaan esilaskenta tehdä vektorina.
                    if op in ("=", "≠", ">", ">=", "<", "<=") and right_num is not None:
                        vals = _np.asarray(filter_values, dtype="float64")
                        valid = ~_np.isnan(vals)
                        if op == "=":
                            mask = valid & (vals == right_num)
                        elif op == "≠":
                            mask = valid & (vals != right_num)
                        elif op == ">":
                            mask = valid & (vals > right_num)
                        elif op == ">=":
                            mask = valid & (vals >= right_num)
                        elif op == "<":
                            mask = valid & (vals < right_num)
                        else:
                            mask = valid & (vals <= right_num)
                        candidate_indices = _np.nonzero(mask)[0]
                        self.log(
                            messages,
                            f"  > DFSU-suodatin esivalitsi {int(candidate_indices.size)}/{total_elements} elementtiä (vektorisuodatus)."
                        )
                except Exception:
                    candidate_indices = None

            inserted = 0
            processed = 0
            progress_step = 250000
            geom_action = {
                "POINT": "pisteitä",
                "POLYLINE": "viivoja",
                "POLYGON": "polygoneja",
            }.get(shape_type, "geometrioita")
            self.log(messages, f"  > Kirjoitetaan elementeistä {geom_action} feature classiin...")
            insert_fields = ["SHAPE@", "element_id"] + [field_name for _, field_name in field_map]

            if candidate_indices is not None:
                iterable_indices = candidate_indices.tolist()
                total_scan = len(iterable_indices)
            else:
                iterable_indices = range(total_elements)
                total_scan = total_elements

            with arcpy.da.InsertCursor(temp_fc, insert_fields) as cursor:
                for idx in iterable_indices:
                    processed += 1
                    raw_filter_value = None if filter_values is None else filter_values[idx]
                    if candidate_indices is None and not _passes_filter(raw_filter_value):
                        if processed % progress_step == 0:
                            self.log(messages, f"  > Eteneminen: käsitelty {processed}/{total_scan} elementtiä, osumia {inserted}.")
                        continue
                    geom = self._make_dfsu_arcpy_geometry(
                        idx, node_coords, element_table, shape_type, create_sr, element_coordinates
                    )
                    row = [geom, idx]
                    for item_name, _field_name in field_map:
                        _v = values_by_item[item_name][idx]
                        row.append(None if (_v is None or _v != _v) else float(_v))
                    cursor.insertRow(row)
                    inserted += 1
                    if processed % progress_step == 0:
                        self.log(messages, f"  > Eteneminen: käsitelty {processed}/{total_scan} elementtiä, osumia {inserted}.")

            self.log(messages, f"DFSU-tuonti: muodostettiin {inserted} {geom_action}.")
            if filter_enabled and filter_column and inserted == 0:
                self.log(messages, "DFSU-suodatin ei tuottanut yhtään osumaa; tasoa ei luoda.", "WARNING")
                return

            self.log(messages, f"  > Tallennetaan lopullinen taso nimellä '{safe_name}'...")
            self.save_and_reproject(temp_fc, output_loc, safe_name, is_folder, None, source_sr, target_sr, messages)
        except Exception as e:
            self.log(messages, f"DFSU-tuonti epäonnistui: {str(e)}", "ERROR")
            self.log(messages, traceback.format_exc(), "ERROR")
            raise
        finally:
            if temp_fc and arcpy.Exists(temp_fc):
                try:
                    arcpy.management.Delete(temp_fc)
                except Exception:
                    pass

    # --- HELPER FUNCTIONS ---
    def convert_and_add(self, input_data, output_loc, output_name, is_folder, messages, add_to_map=True):
        # Yksinkertainen tallennus muille formaateille
        return self.save_and_reproject(
            input_data,
            output_loc,
            output_name,
            is_folder,
            None,
            None,
            None,
            messages,
            add_to_map=add_to_map,
        )

    def sanitize_name(self, name):
        name = name.lower().replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
        name = re.sub(r'[^a-z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')
        if not name:
            name = "layer"
        if name[0].isdigit():
            name = "n_" + name
        return name[:50]
    def sanitize_field_name(self, name):
        name = name.replace(":", "_").replace("-", "_").replace(" ", "_")
        name = re.sub(r'[^a-zA-Z0-9_]', '', name)
        if name and name[0].isdigit(): name = "f_" + name
        return name[:64]
    def log(self, messages, text, level="INFO"):
        msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {text}"
        if level == "ERROR": messages.addErrorMessage(msg)
        elif level == "WARNING": messages.addWarningMessage(msg)
        else: messages.addMessage(msg)
