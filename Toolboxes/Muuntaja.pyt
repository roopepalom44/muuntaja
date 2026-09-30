# -*- coding: utf-8 -*-
# Tekijä: Roope Palomaa
import arcpy
import os
import re
import time
import datetime
import traceback
import importlib
import json
import shutil
import struct

class Toolbox(object):
    def __init__(self):
        self.label = "Muuntaja Toolkit"
        self.alias = "Muuntaja"
        self.tools = [UniversalImportTool]

# Tuonti: nämä tiedostopäätteet → syöte tulkitaan tiedostoksi (tuonti)
VECTOR_IMPORT_FILE_EXTENSIONS = (
    ".gpkg", ".geojson", ".json", ".kml", ".kmz", ".gpx", ".dwg", ".dxf", ".dfsu", ".shp"
)
# Rasterit lisätään työtilaan viittauksina alkuperäisiin tiedostoihin ja
# ryhmitellään ryhmätasoihin (esim. MML:n taustakartta_20k / taustakartta_5k).
RASTER_IMPORT_FILE_EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".jp2", ".img")
# Näissä muodoissa ei ole omaa sijaintitietoa: kansioskannaus ottaa ne mukaan
# vain, jos vieressä on world-tiedosto (.pgw/.jgw/.wld) tai .aux.xml. Muuten
# kansiosta tulisi mukaan esim. kuvakaappaukset ja logot.
RASTER_WORLD_FILE_REQUIRED_EXTENSIONS = (".png", ".jpg", ".jpeg")
RASTER_GROUP_FOLDER_PREFIX = "taustakartta_"
RASTER_PROGRESS_INTERVAL = 10
RASTER_MOSAIC_DATASET_PREFIX = "raster_"
MML_DOWNLOAD_FOLDER_PREFIX = "maanmittauslaitos_tiedostopalvelu"
IMPORT_FILE_EXTENSIONS = VECTOR_IMPORT_FILE_EXTENSIONS + RASTER_IMPORT_FILE_EXTENSIONS
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
# Usean tason GPKG-/DWG-/DXF-viennin paketointitavat. Yhteinen tiedosto
# säilyttää nykyisen oletustoiminnan.
MULTI_EXPORT_PACKAGING_COMBINED = "Kaikki tasot yhteen tiedostoon"
MULTI_EXPORT_PACKAGING_SEPARATE = "Oma tiedosto jokaiselle tasolle"
MULTI_EXPORT_PACKAGING_OPTIONS = [
    MULTI_EXPORT_PACKAGING_COMBINED,
    MULTI_EXPORT_PACKAGING_SEPARATE,
]
MULTI_EXPORT_PACKAGING_FORMATS = ("GPKG", "DWG", "DXF")
# Shapefilen dBASE-attribuuttitaulun rajoitus on 4 000 tavua/rivi. Jätetään
# pieni varmuusvara ArcGISin omille kenttämäärittelyille.
SHAPEFILE_MAX_RECORD_LENGTH = 4000
SHAPEFILE_SAFE_RECORD_LENGTH = SHAPEFILE_MAX_RECORD_LENGTH - 100
IMPORT_MODE_LABEL = "Tuonti (gpkg, geojson, json, kml, kmz, gpx, dwg, dxf, dfsu, shp, rasterit)"
EXPORT_MODE_LABEL = "Vienti (gpkg, shapefile, geojson, dwg, dxf, kml, kmz)"
# Viennin kohdekoordinaatisto. KML/KMZ on standardin mukaan aina WGS84.
EXPORT_CRS_KEEP = "Lähteen koordinaatisto (ei muunnosta)"
EXPORT_CRS_LIST = [EXPORT_CRS_KEEP, "ETRS-TM35FIN (3067)"] + [
    f"ETRS-GK{zone} ({3873 + zone - 19})" for zone in range(19, 32)
] + [
    "KKJ kaista 1 (2391)",
    "KKJ kaista 2 (2392)",
    "KKJ Yhtenäiskoordinaatisto (2393)",
    "KKJ kaista 4 (2394)",
    "WGS 84 (4326)",
    "WGS 84 / Pseudo-Mercator (3857)",
]
EXPORT_WGS84_ONLY_FORMATS = ("KML", "KMZ")
# Näihin vienteihin kirjoitetaan tason tyyli .lyrx-tiedostona. KML/KMZ saa
# tyylin LayerToKML:ltä. GeoJSONille ei ole tyylistandardia, eikä ArcGIS avaa
# GeoJSONia geoprosessointitasoksi; ExportCAD ei kirjoita symbologiaa.
STYLE_FILE_FORMATS = ("GPKG", "Shapefile")


def classify_finnish_xy(x, y):
    """Palauttaa Suomessa käytetyn koordinaatiston EPSG-koodin tai None."""
    if not x or not y: return None
    if abs(x) < 1e-6 and abs(y) < 1e-6: return None

    # WGS84 lat/lon (Suomi: lon 19-32, lat 59-71)
    if 19.0 <= x <= 32.5 and 59.0 <= y <= 71.5:
        return 4326

    # Web Mercator (EPSG:3857) Suomen alueella; sama sääntö kuin QGIS-versiossa.
    if 2_000_000 <= x <= 3_700_000 and 8_000_000 <= y <= 11_800_000:
        return 3857

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


def looks_like_geojson(path, sample_bytes=65536):
    """True, jos JSON-tiedoston alku näyttää GeoJSONilta tai Esri JSONilta."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(sample_bytes).decode("utf-8", errors="ignore")
    except OSError:
        return False
    compact = re.sub(r"\s+", "", head)
    markers = (
        '"type":"FeatureCollection"', '"type":"Feature"', '"features":[',
        '"geometryType":"esriGeometry', '"coordinates":[',
    )
    return any(marker in compact for marker in markers)


def vote_finnish_epsg(points, minimum_share=0.6):
    """Enemmistöäänestys Suomen koordinaatistoista; None jos epävarma."""
    votes = {}
    for x, y in points or []:
        epsg = classify_finnish_xy(x, y)
        if epsg:
            votes[epsg] = votes.get(epsg, 0) + 1
    if not votes:
        return None
    best, count = max(votes.items(), key=lambda item: item[1])
    return best if count / float(sum(votes.values())) >= minimum_share else None


class UniversalImportTool(object):
    def __init__(self):
        self.label = "Muuntaja"
        self.description = (
            "Tuonti tai vienti — syötteenä voi valita useita tiedostoja tai tasoja. "
            "Tuonti: valitse tiedostoja tai kansio; kansio skannataan myös alikansioineen ja kaikki tuetut muodot "
            "tuodaan tiedosto kerrallaan GDB:hen (CAD, GPKG, GeoJSON, KML, GPX, DFSU ja Shapefile). "
            "Rasterit (tif, png/jpg + world-tiedosto, jp2, img) lisätään työtilaan ryhmätasoihin "
            "taustakartta_-alkuisen kansion mukaan (esim. MML:n latauskansio sellaisenaan). "
            "DFSU-tuontiin voi lisätä suodattimen sarake-arvo-operaattorilla. "
            "Vienti: feature-tasot valitaan ArcGIS Pron omalla monitasovalitsimella. "
            "CAD-vienti vie DWG/DXF-tiedostoihin vain valittujen tasojen geometriat. "
            "Muut viennit: GeoJSON, Shapefile ja KML taso kerrallaan; GPKG/DWG/DXF-viennissä "
            "usealle tasolle voi valita yhteisen tai oman tiedoston."
        )
        self.canRunInBackground = False
        # DFSU-sarakelistan cache UI:lle (polku+mtime -> sarakkeet); updateParameters kutsuu usein.
        self._dfsu_col_cache = {}
        # Kansiopolkujen laajennus cachetetaan UI-päivitysten ajaksi. Varsinainen
        # suoritus tekee aina tuoreen skannauksen, jotta ajon aikana lisätyt
        # tiedostotkin tulevat mukaan.
        self._import_expansion_cache_key = None
        self._import_expansion_cache_value = None
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
            IMPORT_MODE_LABEL,
            EXPORT_MODE_LABEL,
        ]
        param0.value = IMPORT_MODE_LABEL

        # 1. Tuonnin syöte: tiedosto(t) tai kansio(t)
        param1 = arcpy.Parameter(
            displayName="Syöte - tiedosto(t) tai kansio(t) (kansio skannataan alikansioineen)",
            name="input_file",
            datatype=["DEFile", "DEFolder", "DEFeatureClass", "DEFeatureDataset", "DECadDrawingDataset", "GPFeatureLayer"],
            # Moodista riippuvaa pakollisuutta ei saa jättää ArcGISin
            # staattisen validaattorin hoidettavaksi: piilotettu Required-
            # parametri estää toisen moodin ajon. updateMessages tarkistaa
            # aktiivisen syötteen itse.
            parameterType="Optional",
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
            displayName="[CAD/rasteri/DFSU] Lähtökoordinaatisto",
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
            "KKJ kaista 1 (2391)",
            "KKJ kaista 2 (2392)",
            "KKJ Yhtenäiskoordinaatisto (2393)",
            "KKJ kaista 4 (2394)"
        ]
        param4.value = "Automaattinen"

        # 5. Target SR (vain DWG-tuonnissa näkyvissä)
        param5 = arcpy.Parameter(
            displayName="[Valinnainen] Kohde-CRS (CAD- ja DFSU-tuonti, tyhjä = alkuperäinen CRS)",
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

        # 8. DFSU-suodatin: käytössä?
        param8 = arcpy.Parameter(
            displayName="[DFSU] Suodata rivejä?",
            name="dfsu_enable_filter",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        param8.value = False
        param8.enabled = False

        # 9. DFSU-suodatin: sarake
        param9 = arcpy.Parameter(
            displayName="[DFSU] Suodatettava sarake",
            name="dfsu_filter_column",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param9.filter.type = "ValueList"
        param9.filter.list = []
        param9.enabled = False

        # 10. DFSU-suodatin: operaattori
        param10 = arcpy.Parameter(
            displayName="[DFSU] Operaattori",
            name="dfsu_filter_operator",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param10.filter.type = "ValueList"
        param10.filter.list = ["=", "≠", ">", ">=", "<", "<=", "contains", "starts with", "ends with"]
        param10.value = "="
        param10.enabled = False

        # 11. DFSU-suodatin: arvo
        param11 = arcpy.Parameter(
            displayName="[DFSU] Arvo tai teksti",
            name="dfsu_filter_value",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param11.enabled = False

        # 12. Vientiin vietävät tasot. ArcGIS Pron oma GPFeatureLayer-
        # monivalitsin tarjoaa aktiivisen kartan tasot ja selaamisen ilman
        # omaa arcpy.mp-karttatasojen skannausta. Oma skannaus GP-työkalun
        # avaus-/validointivaiheessa voi kaataa koko ArcGIS Pro -prosessin.
        param12 = arcpy.Parameter(
            displayName="Vienti - valitse mukaan vietävät tasot",
            name="export_layers",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input")
        param12.multiValue = True
        param12.enabled = False

        # 13. Usean tason GPKG-/DWG-/DXF-viennin paketointitapa.
        param13 = arcpy.Parameter(
            displayName="Vienti: monitasoviennin paketointi (GPKG/DWG/DXF)",
            name="multi_export_packaging",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param13.filter.type = "ValueList"
        param13.filter.list = MULTI_EXPORT_PACKAGING_OPTIONS
        param13.value = MULTI_EXPORT_PACKAGING_COMBINED
        param13.enabled = False

        # 14. Viennin kohdekoordinaatisto. Lisätty viimeiseksi, jotta aiempien
        # parametrien indeksit ja tallennetut työkaluasetukset säilyvät.
        param14 = arcpy.Parameter(
            displayName="Vienti: Kohdekoordinaatisto (KML/KMZ aina WGS84)",
            name="export_target_sr",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        param14.filter.type = "ValueList"
        param14.filter.list = EXPORT_CRS_LIST
        param14.value = EXPORT_CRS_KEEP
        param14.enabled = False

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9, param10, param11,
                param12, param13, param14]

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
        p_dfsu_filter_en = parameters[8]  # DFSU: enable filter
        p_dfsu_filter_col = parameters[9] # DFSU: column
        p_dfsu_filter_op = parameters[10]  # DFSU: operator
        p_dfsu_filter_val = parameters[11] # DFSU: value
        p_export_layers = parameters[12]  # Vienti: ArcGISin monitasovalitsin
        p_multi_packaging = parameters[13]  # Vienti: GPKG/DWG/DXF-paketointi
        p_export_sr = parameters[14] if len(parameters) > 14 else None  # Vienti: kohdekoordinaatisto

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
            # Tiedostopolut ja vientitason valinnat eivät ole
            # keskenään yhteensopivia.
            self._clear_multivalue_parameter(p_input)
            self._clear_multivalue_parameter(p_export_layers)
            p_dfsu_filter_en.value = False
            p_dfsu_filter_col.value = None
            p_dfsu_filter_val.value = None
            p_multi_packaging.value = MULTI_EXPORT_PACKAGING_COMBINED
            raw_paths = []

        # UI-suorituskyky: vältä kansioiden sisältöjen laajaa skannausta jokaisella näppäilyllä/dragilla.
        if is_import:
            if any(os.path.isdir(p) for p in raw_paths):
                paths = self._expand_import_paths(raw_paths, use_cache=True)
            else:
                paths = list(raw_paths)
        else:
            # ArcGIS Pron oma GPFeatureLayer-monivalitsin palauttaa valitut
            # tasot suoraan. Karttaa ei avata validaatiokierroksella.
            paths = self._export_paths_from_param(p_export_layers, raw_paths)
        has_dfsu = any(str(p).lower().endswith(".dfsu") for p in paths) if paths else False
        has_dwg = (
            any(self._path_contains_extension(p, (".dwg", ".dxf")) for p in paths)
            if is_import
            else bool(paths)
        )
        has_raster = is_import and any(self._is_raster_import_path(p) for p in paths)

        # ===== TUONTI-HAARA =====
        if is_import:
            p_input.enabled = True
            p_export_layers.enabled = False

            p_output_loc.enabled = True
            self._ensure_project_default_output_location(p_output_loc)
            # DWG-parametrit näkyvät vain jos on DWG-tiedostoja
            p_mapper.enabled = has_dwg
            # Lähtökoordinaatistolla voi myös määrätä rasterien CRS:n, jos
            # tiedostossa ei ole sitä eikä sitä voi päätellä world-tiedostosta.
            p_input_sr.enabled = has_dwg or has_raster or has_dfsu
            p_target_sr.enabled = has_dwg or has_dfsu
            
            p_export_folder.enabled = False
            p_export_fmt.enabled = False
            p_multi_packaging.enabled = False
            if p_export_sr is not None:
                p_export_sr.enabled = False

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
            p_export_layers.enabled = True
            p_output_loc.enabled = False
            p_mapper.enabled = False
            p_input_sr.enabled = False
            p_target_sr.enabled = False
            p_export_folder.enabled = True
            p_export_fmt.enabled = True
            current_fmt = (p_export_fmt.valueAsText or "").strip()
            if p_export_sr is not None:
                # KML/KMZ on aina WGS84, joten valinta ei koske niitä.
                p_export_sr.enabled = current_fmt not in EXPORT_WGS84_ONLY_FORMATS
                if (p_export_sr.valueAsText or "").strip() not in EXPORT_CRS_LIST:
                    p_export_sr.value = EXPORT_CRS_KEEP
            p_multi_packaging.enabled = (
                current_fmt in MULTI_EXPORT_PACKAGING_FORMATS
                and len(paths) > 1
            )
            if p_multi_packaging.enabled:
                p_multi_packaging.filter.type = "ValueList"
                p_multi_packaging.filter.list = MULTI_EXPORT_PACKAGING_OPTIONS
                current_packaging = (p_multi_packaging.valueAsText or "").strip()
                if current_packaging not in MULTI_EXPORT_PACKAGING_OPTIONS:
                    p_multi_packaging.value = MULTI_EXPORT_PACKAGING_COMBINED
            
            # DFSU-parametrit piilotetaan viennissä
            p_dfsu_filter_en.enabled = False
            p_dfsu_filter_col.enabled = False
            p_dfsu_filter_op.enabled = False
            p_dfsu_filter_val.enabled = False
            
            # DFSU-suodatin pois päältä viennissä
            p_dfsu_filter_en.enabled = False
            p_dfsu_filter_en.value = False
            p_dfsu_filter_col.enabled = False
            p_dfsu_filter_col.filter.list = []
            p_dfsu_filter_op.enabled = False
            p_dfsu_filter_val.enabled = False

        self._last_operation_mode = mode

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
        """Lue DFSU-tiedoston item-nimet mikeio-kirjastolla.

        DFSU on DHI MIKE -mallien binäärimuoto. Ainoa luotettava tapa lukea
        item-nimet on mikeio. Aiempi versio arvaili nimiä binääriheaderin
        ASCII-pätkistä ja palautti viime kädessä keksityt nimet
        ``["Element ID", "X", "Y", "Z"]``. Käyttäjä valitsi niistä suodattimeen
        kentän, jota ei ollut olemassa, ja sai nolla osumaa ilman selitystä.
        Nyt puuttuva kirjasto näkyy tyhjänä listana ja selkeänä virheenä
        ajon yhteydessä.

        Returns: lista item-nimistä, tai tyhjä lista jos niitä ei voi lukea.
        """
        try:
            import mikeio
        except Exception:
            return []
        try:
            dfs = mikeio.open(dfsu_path)
            cols = []
            for item in getattr(dfs, "items", []) or []:
                name = getattr(item, "name", None)
                if name:
                    cols.append(str(name).strip())
            return [c for c in cols if c]
        except Exception:
            return []

    def _ensure_python_module(self, import_name):
        """Tuo valinnainen Python-kirjasto tai anna asennusohje.

        Kirjastoja ei asenneta ajon aikana: pip-asennus ArcGIS Pron jaettuun
        Python-ympäristöön muuttaisi sitä huomaamatta ja epäonnistuisi
        lukituilla työasemilla.
        """
        try:
            return importlib.import_module(import_name)
        except ImportError as error:
            raise RuntimeError(
                f"Python-kirjasto '{import_name}' puuttuu ArcGIS Pron Python-ympäristöstä. "
                "Kloonaa ympäristö (Project → Package Manager → Environment Manager) ja asenna "
                f"siihen: conda install -c conda-forge {import_name}"
            ) from error

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
            self.log(messages, f"  > Siivottiin {removed} väliaikaista aineistoa ajon lopussa.")

    def updateMessages(self, parameters):
        # Poista edellisen validointikierroksen omat virheet ennen nykyisen
        # tilan tarkistusta. Muuten ArcGIS Pro voi jättää jo korjatun kentän
        # tilaan "missing or invalid parameter" erityisesti usean tason
        # valinnan ja tuonti/vienti-moodin vaihdon jälkeen.
        self._clear_parameter_messages(parameters, range(len(parameters)))

        p_mode = parameters[0]
        p_input = parameters[1]
        p_export_folder = parameters[6]
        p_export_fmt = parameters[7]
        p_export_layers = parameters[12]
        p_multi_packaging = parameters[13]
        
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
        # DFSU-suodattimen sarakelista on tyhjä, jos mikeio puuttuu. Kerro se
        # heti dialogissa sen sijaan, että käyttäjä valitsisi kentän, jota ei
        # ole, ja ihmettelisi nolla osumaa vasta ajon jälkeen.
        if is_import and len(parameters) > 9 and bool(parameters[8].value):
            has_dfsu_selection = any(
                str(path).lower().endswith(".dfsu") for path in (import_paths or [])
            )
            if has_dfsu_selection and not (parameters[9].filter.list or []):
                parameters[9].setErrorMessage(
                    "DFSU-itemien lukeminen ei onnistunut. Suodatus vaatii "
                    "mikeio-kirjaston ArcGIS Pron kloonattuun Python-ympäristöön "
                    "(conda install -c conda-forge mikeio)."
                )

        if not paths:
            if is_import:
                p_input.setErrorMessage(
                    "Valitse vähintään yksi tuettu tiedosto tai kansio. "
                    "Kansio skannataan myös alikansioineen."
                )
            else:
                p_export_layers.setErrorMessage(
                    "Valitse vähintään yksi aktiivisen kartan taso vientiin."
                )
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
            if fmt in MULTI_EXPORT_PACKAGING_FORMATS and len(paths) > 1:
                packaging = (p_multi_packaging.valueAsText or "").strip()
                if packaging not in MULTI_EXPORT_PACKAGING_OPTIONS:
                    p_multi_packaging.setErrorMessage(
                        "Valitse, viedäänkö kaikki tasot yhteen tiedostoon "
                        "vai tehdäänkö jokaiselle oma tiedosto."
                    )
                    return
            # GPFeatureLayer-monivalitsin tekee tyyppitarkistuksen itse.
            # Älä kutsu Describea tässä UI-validointikierroksessa: ryhmien
            # sisäiset tasot voivat olla hetkellisesti vain karttaniminä,
            # jolloin Describe antaa väärän negatiivisen tuloksen ja Pro
            # merkitsee koko muuten kelvollisen monivalinnan virheelliseksi.
        
        # TUONTI-VALIDOINTI
        else:
            for pv in paths:
                if os.path.isdir(pv):
                    # Käytä jo laajennettua (välimuistissa olevaa) listaa, jotta
                    # isoa kansiopuuta ei käydä läpi uudelleen joka näppäilyllä.
                    if not self._count_files_under(pv, import_paths):
                        p_input.setErrorMessage(
                            f"Tuonti: kansiosta '{pv}' ei löytynyt tuettuja tiedostoja ({', '.join(IMPORT_FILE_EXTENSIONS)})."
                        )
                        return
                    continue
                if self._is_supported_import_catalog_path(pv):
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
                dfsu_filter_enabled = bool(parameters[8].value)
                dfsu_filter_column = (parameters[9].valueAsText or "").strip()
                if dfsu_filter_enabled and not dfsu_filter_column:
                    parameters[9].setErrorMessage("Valitse DFSU-suodattimelle sarake.")
                    return

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        p_input = parameters[1]  # Input file/layer is now at index 1 (after mode parameter)
        p_export_layers = parameters[12]
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

    def _clear_multivalue_parameter(self, param):
        """Tyhjennä moniarvoparametri ArcGIS Pron vakaalla tavalla.

        ``None`` ei ole multivalue-parametrin arvo vaan puuttuva objektiarvo,
        ja sen asettaminen dynaamiselle GPString-kontrollille on aiheuttanut
        Prossa kaatumisia. Tyhjä lista on ArcGISin dokumentoitu muoto.
        """
        try:
            param.values = []
        except Exception:
            try:
                param.value = None
            except Exception:
                pass

    def _clear_parameter_messages(self, parameters, indexes):
        """Poista piilotettujen/pois kytkettyjen parametrien vanhat virheet."""
        for index in indexes:
            try:
                parameters[index].clearMessage()
            except Exception:
                pass

    def _ensure_project_default_output_location(self, param):
        """Aseta tuonnin oletuskohteeksi aktiivisen projektin oletus-GDB.

        ``getParameterInfo`` asettaa oletuksen yleensä jo työkalun avautuessa,
        mutta ArcGIS Pro voi tyhjentää valinnaisen parametrin moodinvaihdossa.
        Täytä arvo vain silloin, kun käyttäjä ei ole itse valinnut muuta
        kohdetta.
        """
        try:
            current = (getattr(param, "valueAsText", None) or "").strip()
        except Exception:
            current = ""
        if current:
            return

        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            default_gdb = str(getattr(aprx, "defaultGeodatabase", "") or "").strip()
        except Exception:
            default_gdb = ""
        if not default_gdb:
            return

        try:
            param.value = default_gdb
        except Exception:
            pass

    def _export_paths_from_param(self, param, values=None):
        """Palauta ArcGIS Pron GPFeatureLayer-monivalitsimen tasot listana."""
        if values is None:
            values = self._input_paths_from_param(param)
        out = []
        seen = set()
        for value in values or []:
            text = str(value).strip()
            if not text:
                continue
            key = self._export_source_text_key(text)
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    def _export_source_text_key(self, value):
        """Vakaa tekstivertailu ArcGISin layer-nimille ja catalogPath-poluille."""
        text = str(value or "").strip().strip("'\"")
        return text.replace("/", "\\").casefold()

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
                    if (
                        extension in RASTER_WORLD_FILE_REQUIRED_EXTENSIONS
                        and not self._raster_has_georeference(full_path)
                    ):
                        continue
                    # Kansiossa on usein asetus- ja metatieto-JSONeita; niistä
                    # otetaan mukaan vain paikkatietoa sisältävät.
                    if extension == ".json" and not looks_like_geojson(full_path):
                        continue
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

    def _count_files_under(self, folder, expanded_paths):
        """Laske jo laajennetuista poluista kansion alla olevat tiedostot."""
        prefix = self._normalized_path_key(folder).rstrip("\\/") + os.sep
        return sum(
            1 for path in expanded_paths or []
            if self._normalized_path_key(path).startswith(prefix)
        )

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
            # Kansion sisältö tarkistetaan laajennuksen yhteydessä.
            return True
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

    def _multi_export_packaging_from_param(self, param, input_count, fmt=None):
        """Palauta usean tason GPKG/DWG/DXF-viennin paketointitapa.

        Yhden tason viennissä valinta ei vaikuta toimintaan. Puuttuva arvo
        käyttää nykyistä oletusta eli kaikkien tasojen yhteistä tiedostoa.
        Muut formaatit viedään aina taso kerrallaan.
        """
        if input_count <= 1:
            return MULTI_EXPORT_PACKAGING_COMBINED
        if fmt and fmt not in MULTI_EXPORT_PACKAGING_FORMATS:
            return MULTI_EXPORT_PACKAGING_SEPARATE
        try:
            value = (getattr(param, "valueAsText", None) or "").strip()
        except Exception:
            value = ""
        if value in MULTI_EXPORT_PACKAGING_OPTIONS:
            return value
        return MULTI_EXPORT_PACKAGING_COMBINED

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

    def _log_batch_summary(self, messages, operation, total, succeeded, failures):
        """Raportoi eräajon tulos ja kaada ajo vasta, jos mikään ei onnistunut.

        Aiemmin ensimmäinen virhe keskeytti koko erän, jolloin sen jälkeiset
        tiedostot jäivät käsittelemättä ilman että käyttäjä sai tietää mitkä
        olisivat onnistuneet.
        """
        succeeded = list(succeeded or [])
        failures = list(failures or [])
        if not failures:
            if total > 1:
                self.log(messages, f"{operation} valmis: {len(succeeded)}/{total} onnistui.")
            return

        self.log(
            messages,
            f"{operation} valmis osittain: {len(succeeded)}/{total} onnistui, "
            f"{len(failures)} epäonnistui.",
            "WARNING",
        )
        for path, reason in failures:
            self.log(messages, f"  > EPÄONNISTUI: {path} — {reason}", "WARNING")

        if not succeeded:
            # Kaikki epäonnistuivat: ajo on aidosti virheellinen.
            self.log(
                messages,
                f"{operation} epäonnistui: yksikään {total} kohteesta ei onnistunut.",
                "ERROR",
            )
            raise arcpy.ExecuteError(
                f"{operation} epäonnistui kaikkien {total} kohteen osalta."
            )

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
        dfsu_filter_enabled = bool(parameters[8].value)
        dfsu_filter_column = (parameters[9].valueAsText or "").strip()
        dfsu_filter_operator = (parameters[10].valueAsText or "=").strip()
        dfsu_filter_value = (parameters[11].valueAsText or "").strip()

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
        
        for raw_path in raw_input_paths:
            if os.path.isdir(raw_path):
                self.log(
                    messages,
                    f"Tuonti — kansio '{raw_path}' skannattu alikansioineen: "
                    f"{self._count_files_under(raw_path, input_paths)} tuettua tiedostoa.",
                )
        if not input_paths:
            self.log(messages, "Tuonti: valituista kansioista/tiedostoista ei löytynyt käsiteltäviä tuontitiedostoja.", "ERROR")
            return
        if len(input_paths) > 1:
            self.log(messages, f"Tuonti — {len(input_paths)} tiedostoa peräkkäin.")

        # Rasterit käsitellään yhtenä eränä vektorien jälkeen, jotta ne voidaan
        # ryhmitellä ryhmätasoihin kansiorakenteen mukaan.
        raster_paths = [p for p in input_paths if self._is_raster_import_path(p)]
        file_paths = [p for p in input_paths if not self._is_raster_import_path(p)]
        folder_roots = [p for p in raw_input_paths if os.path.isdir(p)]

        succeeded = []
        failures = []
        try:
            for idx, input_path in enumerate(file_paths, 1):
                if len(file_paths) > 1:
                    self.log(messages, f"Tuonti — ({idx}/{len(file_paths)}) {input_path}")
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
                                        target_sr=target_sr,
                                        input_sr=input_sr)
                    elif ext in [".dwg", ".dxf"]:
                        self.process_cad(input_path, output_loc, is_folder, use_mapper, input_sr, target_sr, messages)
                    else:
                        self.process_generic(input_path, output_loc, is_folder, messages)

                    succeeded.append(input_path)

                except Exception as e:
                    # Yksi rikkinäinen tiedosto ei saa hukata koko eräajoa.
                    # Virhe kirjataan ja käsittely jatkuu seuraavaan tiedostoon;
                    # yhteenveto ajon lopussa kertoo mikä epäonnistui.
                    failures.append((input_path, str(e)))
                    self.log(
                        messages,
                        f"Tiedoston '{input_path}' tuonti epäonnistui: {str(e)}. "
                        f"Jatketaan seuraavaan tiedostoon.",
                        "WARNING",
                    )
                    self.log(messages, traceback.format_exc(), "WARNING")

            if raster_paths:
                raster_ok, raster_failures = self._import_rasters(
                    raster_paths, folder_roots, input_sr, messages,
                    output_loc=output_loc, is_folder=is_folder,
                )
                succeeded.extend(raster_ok)
                failures.extend(raster_failures)

            self._log_batch_summary(
                messages, "Tuonti", len(input_paths), succeeded, failures
            )
        finally:
            self._run_deferred_cleanup(messages)

    def _execute_export(self, parameters, messages, input_paths=None):
        """Vienti: yksi tai useampi ArcGIS-taso / FC → tiedosto(t) vientikansioon."""
        if input_paths is None:
            input_param = parameters[12]
            input_paths = self._export_paths_from_param(
                input_param,
                self._input_paths_from_param(input_param),
            )  # Index shifted from 0 to 1
        else:
            input_paths = self._export_paths_from_param(None, input_paths)
        folder = (parameters[6].valueAsText or "").strip()  # Index shifted from 5 to 6
        fmt = (parameters[7].valueAsText or "GPKG").strip()  # Index shifted from 6 to 7
        # Parametri 5 kuuluu vain tuontiin. Piilotettu aiempi arvo ei saa
        # projisoida vientiaineistoja huomaamatta, joten vienti ei lue sitä;
        # viennin kohdekoordinaatisto on oma parametrinsa (14).
        multi_packaging = self._multi_export_packaging_from_param(
            parameters[13] if len(parameters) > 13 else None,
            len(input_paths),
            fmt,
        )
        export_sr_text = (parameters[14].valueAsText or "").strip() if len(parameters) > 14 else ""
        export_sr = self._parse_input_sr(export_sr_text)

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
        if fmt in EXPORT_WGS84_ONLY_FORMATS:
            if export_sr is not None:
                self.log(messages, f"  > {fmt} viedään aina WGS84:ään (KML-standardi); "
                                   "kohdekoordinaatiston valinta ei koske sitä.", "WARNING")
            export_sr = None
        elif export_sr is not None:
            self.log(messages, f"Vienti — kohdekoordinaatisto: {export_sr_text} ({export_sr.name})")

        combined_label = self._export_combined_stamp_label(input_paths)
        separate_outputs = (
            len(input_paths) > 1
            and (
                fmt not in MULTI_EXPORT_PACKAGING_FORMATS
                or multi_packaging == MULTI_EXPORT_PACKAGING_SEPARATE
            )
        )
        out_path = None if separate_outputs else self._unique_export_path(
            self._build_export_path_in_folder(folder, fmt, combined_label)
        )

        self.log(messages, "Vienti — lähteet: " + "; ".join(input_paths))
        self.log(messages, f"Vienti — kansio: {folder}")
        if separate_outputs:
            self.log(messages, f"Vienti — formaatti: {fmt} → oma tiedosto jokaiselle tasolle")
        else:
            self.log(messages, f"Vienti — formaatti: {fmt} → {os.path.basename(out_path)}")
        if len(input_paths) > 1:
            if fmt in MULTI_EXPORT_PACKAGING_FORMATS:
                packaging_label = (
                    "oma tiedosto jokaiselle tasolle"
                    if separate_outputs
                    else "kaikki tasot yhteen tiedostoon"
                )
                self.log(messages, f"  > Tasoja valittuna: {len(input_paths)} ({packaging_label}).")
            else:
                self.log(messages, f"  > Tasoja valittuna: {len(input_paths)} (yksi tiedosto tasoa kohden).")

        export_succeeded = []
        export_failures = []
        try:
            written_paths = []
            fc_pairs = []

            if fmt in ("DWG", "DXF"):
                if separate_outputs:
                    for in_src in input_paths:
                        sub_src = self._export_source_label(in_src)
                        try:
                            self.log(messages, f"  > Viedään tasoa '{sub_src}'...")
                            fc_work = self._prepare_export_feature_class(in_src, messages, target_sr=export_sr)
                            out_one = self._unique_export_path(
                                self._build_export_path_in_folder(folder, fmt, sub_src)
                            )
                            written_paths.append(
                                self._export_to_cad(
                                    [(fc_work, in_src)],
                                    out_one,
                                    messages,
                                )
                            )
                            export_succeeded.append(sub_src)
                        except Exception as layer_error:
                            export_failures.append((sub_src, str(layer_error)))
                            self.log(
                                messages,
                                f"Tason '{sub_src}' CAD-vienti epäonnistui: {layer_error}. "
                                f"Jatketaan seuraavaan tasoon.",
                                "WARNING",
                            )
                            self.log(messages, traceback.format_exc(), "WARNING")
                else:
                    for in_src in input_paths:
                        fc_pairs.append((self._prepare_export_feature_class(in_src, messages, target_sr=export_sr), in_src))
                    written_paths = [
                        self._export_to_cad(
                            fc_pairs,
                            out_path,
                            messages,
                        )
                    ]

            elif len(input_paths) == 1:
                in_src = input_paths[0]
                fc_work = self._prepare_export_feature_class(
                    in_src, messages, copy_source=False, target_sr=export_sr
                )
                src_one = self._export_source_label(in_src)
                if fmt == "GeoJSON":
                    written_paths = [self._export_to_geojson(
                        fc_work, out_path, messages, keep_input_sr=export_sr is not None
                    )]
                elif fmt == "Shapefile":
                    written_paths = [self._export_to_shapefile(fc_work, out_path, messages)]
                elif fmt == "GPKG":
                    written_paths = [self._export_to_geopackage(fc_work, out_path, messages, source_label=src_one)]
                elif fmt in ("KML", "KMZ"):
                    written_paths = [self._export_to_kml(fc_work, out_path, messages)]
                else:
                    self.log(messages, f"Tuntematon vientiformaatti: {fmt}", "ERROR")
                    return
                if fmt in STYLE_FILE_FORMATS:
                    self._write_style_file(in_src, written_paths[0], messages)

            else:
                # Monitasovienti: GPKG voi mennä yhteiseen tai omiin tiedostoihin,
                # muut formaatit aina omaan tiedostoonsa. Kaikki kulkevat saman
                # suojatun kierroksen läpi, jotta yksi rikkinäinen taso ei
                # hukkaa muita.
                simple_exporters = {
                    "GeoJSON": lambda fc, out, msg: self._export_to_geojson(
                        fc, out, msg, keep_input_sr=export_sr is not None
                    ),
                    "Shapefile": self._export_to_shapefile,
                    "KML": self._export_to_kml,
                    "KMZ": self._export_to_kml,
                }
                if fmt != "GPKG" and fmt not in simple_exporters:
                    self.log(messages, f"Tuntematon vientiformaatti: {fmt}", "ERROR")
                    return

                written_paths = []
                for in_src in input_paths:
                    sub_src = self._export_source_label(in_src)
                    try:
                        self.log(messages, f"  > Viedään tasoa '{sub_src}'...")
                        fc_work = self._prepare_export_feature_class(
                            in_src, messages, copy_source=False, target_sr=export_sr
                        )
                        if fmt == "GPKG":
                            gpkg_target = out_path
                            if separate_outputs:
                                gpkg_target = self._unique_export_path(
                                    self._build_export_path_in_folder(folder, "GPKG", sub_src)
                                )
                            written_paths.append(
                                self._export_to_geopackage(
                                    fc_work, gpkg_target, messages, source_label=sub_src
                                )
                            )
                        else:
                            sub_nm = self.sanitize_name(sub_src)[:35] or "layer"
                            out_one = self._unique_export_path(
                                self._build_export_path_in_folder(
                                    folder, fmt, combined_label + "_" + sub_nm
                                )
                            )
                            written_paths.append(
                                simple_exporters[fmt](fc_work, out_one, messages)
                            )
                        if fmt in STYLE_FILE_FORMATS:
                            self._write_style_file(in_src, written_paths[-1], messages)
                        export_succeeded.append(sub_src)
                    except Exception as layer_error:
                        export_failures.append((sub_src, str(layer_error)))
                        self.log(
                            messages,
                            f"Tason '{sub_src}' vienti epäonnistui: {layer_error}. "
                            f"Jatketaan seuraavaan tasoon.",
                            "WARNING",
                        )
                        self.log(messages, traceback.format_exc(), "WARNING")

            output_files = self._export_output_file_paths(written_paths)
            self.log(messages, f"Vienti valmis: {len(output_files)} tiedostoa.")
            if export_failures:
                self._log_batch_summary(
                    messages, "Vienti", len(input_paths),
                    export_succeeded, export_failures,
                )

        except Exception as e:
            self.log(messages, f"Vientivirhe: {str(e)}", "ERROR")
            messages.addErrorMessage(traceback.format_exc())
            raise
        finally:
            self._run_deferred_cleanup(messages)

    def _log_layer_subset(self, in_src, desc, messages):
        """Kerro, jos vientitaso rajautuu valintaan tai määrityskyselyyn.

        Vienti käyttää tasoa sellaisenaan, joten ArcGIS vie vain valitut
        kohteet ja määrityskyselyn (definition query) läpäisevät kohteet –
        samat, jotka kartalla näkyvät.
        """
        if getattr(desc, "dataType", "") != "FeatureLayer":
            return
        try:
            fid_set = str(getattr(desc, "FIDSet", "") or "").strip()
        except Exception:
            fid_set = ""
        selected = len([part for part in fid_set.split(";") if part.strip()]) if fid_set else 0
        if selected:
            self.log(messages, f"  > Tasolla '{in_src}' on valinta: viedään vain {selected} valittua kohdetta.")
        try:
            where = str(getattr(desc, "whereClause", "") or "").strip()
        except Exception:
            where = ""
        if where:
            self.log(messages, f"  > Tason '{in_src}' määrityskysely rajaa vientiä: {where}")

    def _export_output_file_paths(self, written_paths):
        """Muunna mahdolliset GPKG:n sisäiset tasopolut tiedostopoluiksi."""
        files = []
        seen = set()
        for value in written_paths or []:
            if not value:
                continue
            text = str(value)
            match = re.search(r"\.gpkg(?:[\\/]|$)", text, flags=re.IGNORECASE)
            if match:
                text = text[:match.start() + len(".gpkg")]
            key = os.path.normcase(os.path.normpath(text))
            if key in seen:
                continue
            seen.add(key)
            files.append(text)
        return files

    def _export_source_label(self, in_src):
        """Lyhyt nimi tiedostonimeä varten (taso / FC)."""
        try:
            d = arcpy.Describe(in_src)
            nm = getattr(d, "name", None) or ""
            if nm:
                if "." in nm:
                    schema, unqualified = nm.split(".", 1)
                    if schema.casefold() in ("main", "temp") and unqualified:
                        nm = unqualified
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

    def _prepare_export_feature_class(self, in_src, messages, copy_source=True, target_sr=None):
        """Valmistele vientitaso; tarvittaessa scratchGDB-kopio.

        Lukuun perustuvissa viennissä lähdetasoa käytetään suoraan. CAD-vienti
        käyttää scratch-kopiota, koska CAD-valmistelu voi lisätä tai muuttaa
        kenttiä. Taso käytetään sellaisenaan (ei catalogPathia), jotta valinta
        ja määrityskysely rajaavat viennin kuten ArcGISin omissa työkaluissa.
        Tuonnin kohde-CRS ei kuulu vientiin; viennin oma kohdekoordinaatisto
        (``target_sr``) projisoi tason scratch-kopioksi ennen vientiä.
        """
        desc = arcpy.Describe(in_src)
        self._log_layer_subset(in_src, desc, messages)
        if target_sr is not None and self._export_needs_projection(desc, target_sr, in_src):
            out_fc = self._new_export_scratch_path()
            transform = self._list_datum_transform(desc.spatialReference, target_sr)
            detail = f", muunnos {transform}" if transform else ""
            self.log(messages, f"  > Muunnetaan koordinaatistosta {desc.spatialReference.name} "
                               f"koordinaatistoon {target_sr.name}{detail}...")
            # Project noudattaa tason valintaa ja määrityskyselyä kuten muutkin työkalut.
            arcpy.management.Project(in_src, out_fc, target_sr, transform)
            self._queue_deferred_cleanup(out_fc)
            return out_fc
        if not copy_source:
            return in_src

        out_fc = self._new_export_scratch_path()
        self.log(messages, "  > Luodaan vientiä varten väliaikainen scratch-kopio...")
        arcpy.management.CopyFeatures(in_src, out_fc)
        self._queue_deferred_cleanup(out_fc)
        return out_fc

    def _new_export_scratch_path(self):
        scratch = arcpy.env.scratchGDB
        sequence = int(getattr(self, "_export_temp_sequence", 0) or 0) + 1
        self._export_temp_sequence = sequence
        stamp = datetime.datetime.now().strftime("%H%M%S_%f")
        out_fc = os.path.join(scratch, f"muuntaja_vienti_{stamp}_{sequence}")
        while arcpy.Exists(out_fc):
            sequence += 1
            self._export_temp_sequence = sequence
            out_fc = os.path.join(scratch, f"muuntaja_vienti_{stamp}_{sequence}")
        return out_fc

    def _export_needs_projection(self, desc, target_sr, in_src):
        """True, jos taso pitää projisoida kohdekoordinaatistoon; tuntematon lähde on virhe."""
        source_sr = getattr(desc, "spatialReference", None)
        source_name = str(getattr(source_sr, "name", "") or "").strip().lower()
        if not source_sr or source_name in ("", "unknown"):
            raise RuntimeError(
                f"Tason '{in_src}' koordinaatisto on tuntematon, joten sitä ei voi muuntaa "
                f"koordinaatistoon {target_sr.name}. Määritä tason koordinaatisto ensin."
            )
        return self._needs_projection(source_sr, target_sr)


    def _cad_force_point_entity_type(self, fc_path, messages):
        """Pakota Export To CAD käyttämään POINT-entiteettiä pistetasoille (varattu CadType-kenttä).

        Ilman CadType-arvoa jotkin lähteet vievät pisteet ympyröinä tai vääränä entiteettinä.
        Muiden geometriatyyppien CAD-esitykseen ei puututa.
        """
        try:
            desc = arcpy.Describe(fc_path)
        except Exception:
            return
        st = (desc.shapeType or "").lower()
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

    def _export_to_cad(
        self,
        fc_source_pairs,
        out_path,
        messages,
    ):
        """Vie yksi tai useampi geometriataso samaan DWG/DXF-tiedostoon."""
        if arcpy.Exists(out_path):
            try:
                arcpy.management.Delete(out_path)
            except Exception:
                pass
        ext = os.path.splitext(out_path)[1].lower()
        out_type = "DWG_R2018" if ext == ".dwg" else "DXF_R2018"

        cad_inputs = []
        for fc_path, _in_src in fc_source_pairs:
            # Pisteet viedään CADin POINT-entiteetteinä. Muiden tasojen
            # geometriaan tai esitystapaan ei tehdä muutoksia.
            self._cad_force_point_entity_type(fc_path, messages)
            cad_inputs.append(fc_path)

        arcpy.conversion.ExportCAD(
            cad_inputs,
            out_type,
            out_path,
            "Ignore_Filenames_in_Tables",
            "Overwrite_Existing_Files",
        )

        self.log(messages, f"CAD-vienti valmis: {out_path} ({len(fc_source_pairs)} lähdettä).")
        return out_path

    def _export_to_geojson(self, fc_path, out_path, messages, keep_input_sr=False):
        """GeoJSON on oletuksena WGS84 (RFC 7946); valittu kohdekoordinaatisto säilytetään."""
        if arcpy.Exists(out_path):
            try:
                arcpy.management.Delete(out_path)
            except Exception:
                pass
        arcpy.conversion.FeaturesToJSON(
            fc_path, out_path, geoJSON="GEOJSON",
            outputToWGS84="KEEP_INPUT_SR" if keep_input_sr else "WGS84",
        )
        if not os.path.isfile(out_path):
            raise RuntimeError(
                f"ArcGIS Pro ei luonut pyydettyä GeoJSON-tiedostoa: {out_path}"
            )
        self.log(messages, f"GeoJSON-vienti valmis: {out_path}")
        return out_path

    def _shapefile_field_width(self, field):
        """Arvioi shapefilen dBASE-kentän määrittelypituuden tavuina."""
        field_type = (getattr(field, "type", "") or "").casefold()
        try:
            length = max(int(getattr(field, "length", 0) or 0), 0)
        except Exception:
            length = 0

        if field_type in ("geometry", "oid", "blob", "raster"):
            return 0
        if field_type in ("string", "text"):
            return min(max(length, 1), 254)
        if field_type in ("smallinteger", "short"):
            return 6
        if field_type in ("integer", "long"):
            return 11
        if field_type in ("biginteger", "big integer"):
            return 20
        if field_type in ("single", "float"):
            return 14
        if field_type in ("double",):
            return 20
        if field_type in ("date", "dateonly"):
            return 8
        if field_type in ("timeonly",):
            return 13
        if field_type in ("timestampoffset",):
            return 29
        if field_type in ("guid", "globalid"):
            return 38
        return max(length, 1)

    def _is_shapefile_record_length_error(self, error):
        text = str(error or "").casefold()
        return "001337" in text or "maximum record length" in text

    def _build_shapefile_field_mappings(
        self, fc_path, out_dir, messages, force=False, minimal=False
    ):
        """Rajaa Shapefilen kentät dBASE:n 4 000 tavun rivirajoitukseen."""
        try:
            source_fields = list(arcpy.ListFields(fc_path) or [])
        except Exception as e:
            self.log(messages, f"  > Shapefilen kenttien tarkistus epäonnistui: {e}", "WARNING")
            return None

        field_types_without_width = {"geometry", "oid", "blob", "raster"}
        estimated_length = 1
        needs_mapping = False
        for field in source_fields:
            field_type = (getattr(field, "type", "") or "").casefold()
            estimated_length += self._shapefile_field_width(field)
            try:
                raw_length = int(getattr(field, "length", 0) or 0)
            except Exception:
                raw_length = 0
            if field_type in ("string", "text") and raw_length > 254:
                needs_mapping = True

        if not force and estimated_length <= SHAPEFILE_SAFE_RECORD_LENGTH and not needs_mapping:
            return None

        try:
            field_mappings = arcpy.FieldMappings()
            # Tämä saa ArcGISin sovittamaan nimet Shapefilen enintään 10 merkkiin.
            field_mappings.fieldValidationWorkspace = out_dir
            field_mappings.addTable(fc_path)
        except Exception as e:
            self.log(messages, f"  > Shapefilen kenttäkartan luonti epäonnistui: {e}", "WARNING")
            return None

        # Shapefile-tekstikenttä ei voi olla yli 254 merkkiä. FieldMap.outputField
        # on kopioitava, muutettava ja asetettava takaisin ArcGISin API-ohjeen
        # mukaisesti.
        for output_field in list(field_mappings.fields):
            field_type = (getattr(output_field, "type", "") or "").casefold()
            if field_type not in ("string", "text"):
                continue
            try:
                output_length = int(getattr(output_field, "length", 0) or 0)
            except Exception:
                output_length = 0
            if output_length <= 254:
                continue
            try:
                field_index = field_mappings.findFieldMapIndex(output_field.name)
                if field_index < 0:
                    continue
                field_map = field_mappings.getFieldMap(field_index)
                mapped_field = field_map.outputField
                mapped_field.length = 254
                field_map.outputField = mapped_field
                field_mappings.replaceFieldMap(field_index, field_map)
            except Exception:
                # Kentän poisto alla pienentää rakennetta silti tarvittaessa.
                pass

        current_length = 1
        removable = []
        for output_field in list(field_mappings.fields):
            field_type = (getattr(output_field, "type", "") or "").casefold()
            width = self._shapefile_field_width(output_field)
            current_length += width
            if (
                field_type not in field_types_without_width
                and (
                    minimal
                    or not getattr(output_field, "required", False)
                )
            ):
                removable.append((width, str(getattr(output_field, "name", "") or "")))

        if minimal:
            keep_candidates = [
                (width, field_name)
                for width, field_name in removable
            ]
            keep_name = min(keep_candidates)[1] if keep_candidates else None
            removable = [
                (width, field_name)
                for width, field_name in removable
                if field_name != keep_name
            ]

        removed = []
        for width, field_name in sorted(removable, key=lambda item: (-item[0], item[1].casefold())):
            if current_length <= SHAPEFILE_SAFE_RECORD_LENGTH:
                break
            try:
                field_index = field_mappings.findFieldMapIndex(field_name)
                if field_index < 0:
                    continue
                field_mappings.removeFieldMap(field_index)
                current_length -= width
                removed.append(field_name)
            except Exception:
                continue

        if removed:
            preview = ", ".join(removed[:12])
            if len(removed) > 12:
                preview += f", … (+{len(removed) - 12})"
            self.log(
                messages,
                "  > Shapefile: dBASE:n 4 000 tavun rivirajan vuoksi "
                f"jätettiin pois {len(removed)} kenttää ({preview}).",
                "WARNING",
            )
        if current_length > SHAPEFILE_SAFE_RECORD_LENGTH:
            self.log(
                messages,
                "  > Shapefile: kenttärakenne ylittää edelleen dBASE:n rivirajan; "
                "säilytetään mahdollisimman vähän ei-järjestelmäkenttiä.",
                "WARNING",
            )
        return field_mappings

    def _export_to_shapefile(self, fc_path, out_path, messages):
        out_dir = os.path.dirname(out_path) or "."
        base = os.path.splitext(os.path.basename(out_path))[0]
        if not base:
            base = "export"
        shp_path = os.path.join(out_dir, base + ".shp")

        def remove_partial_output():
            try:
                if arcpy.Exists(shp_path):
                    arcpy.management.Delete(shp_path)
            except Exception:
                pass
            for extension in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx"):
                candidate = os.path.join(out_dir, base + extension)
                try:
                    if os.path.isfile(candidate):
                        os.remove(candidate)
                except Exception:
                    pass

        if arcpy.Exists(shp_path):
            remove_partial_output()
            if arcpy.Exists(shp_path):
                base = base + "_" + datetime.datetime.now().strftime("%H%M%S")
                shp_path = os.path.join(out_dir, base + ".shp")
        field_mappings = self._build_shapefile_field_mappings(fc_path, out_dir, messages)

        def convert(mapping):
            if mapping is None:
                arcpy.conversion.FeatureClassToFeatureClass(fc_path, out_dir, base)
            else:
                arcpy.conversion.FeatureClassToFeatureClass(
                    fc_path, out_dir, base, field_mapping=mapping
                )

        try:
            convert(field_mappings)
        except Exception as first_error:
            if not self._is_shapefile_record_length_error(first_error):
                raise
            # Jos ArcGISin oma kenttäleveyspäätelmä poikkeaa arviosta, rakenna
            # varmistuskartta ja yritä vielä kerran rajatuilla kentillä.
            remove_partial_output()
            fallback_mappings = self._build_shapefile_field_mappings(
                fc_path, out_dir, messages, force=True
            )
            if fallback_mappings is None:
                raise
            self.log(
                messages,
                "  > Shapefile: ensimmäinen vientiyritys ylitti dBASE-rivin; "
                "yritetään kenttäkartalla.",
                "WARNING",
            )
            try:
                convert(fallback_mappings)
            except Exception as second_error:
                if not self._is_shapefile_record_length_error(second_error):
                    raise
                remove_partial_output()
                minimal_mappings = self._build_shapefile_field_mappings(
                    fc_path, out_dir, messages, force=True, minimal=True
                )
                if minimal_mappings is None:
                    raise
                self.log(
                    messages,
                    "  > Shapefile: kenttärivi ylitti rajan edelleen; "
                    "yritetään geometriaa ja yhtä lyhyttä attribuuttikenttää.",
                    "WARNING",
                )
                convert(minimal_mappings)
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
            base_layer_name = layer_name
            suffix = 2
            while arcpy.Exists(target) and suffix < 10000:
                suffix_text = f"_{suffix}"
                layer_name = (base_layer_name[:max(1, 30 - len(suffix_text))] + suffix_text)
                target = os.path.join(out_path, layer_name)
                suffix += 1
        arcpy.management.CopyFeatures(fc_path, target)
        self.log(messages, f"GeoPackage-vienti valmis: {target}")
        return target

    def _export_to_kml(self, fc_path, out_path, messages):
        # Karttataso viedään sellaisenaan, jotta sen symbologia kulkee KML:n
        # tyyleiksi. Pelkästä feature classista tehdään väliaikainen taso.
        try:
            is_layer = arcpy.Describe(fc_path).dataType == "FeatureLayer"
        except Exception:
            is_layer = False
        lyr_name = fc_path if is_layer else "muuntaja_kml_lyr"
        if not is_layer:
            if arcpy.Exists(lyr_name):
                arcpy.management.Delete(lyr_name)
            arcpy.management.MakeFeatureLayer(fc_path, lyr_name)
        try:
            # LayerToKML: kolmas parametri on kartan mittakaava (esim. 10 000)
            arcpy.conversion.LayerToKML(lyr_name, out_path, 10000)
        finally:
            if not is_layer:
                try:
                    arcpy.management.Delete(lyr_name)
                except Exception:
                    pass
        self.log(messages, f"KML/KMZ-vienti valmis: {out_path}")
        return out_path

    def _style_file_path(self, written_path):
        """Tyylitiedoston polku: <tiedosto>.lyrx, GeoPackagessa <gpkg>_<taso>.lyrx."""
        text = str(written_path)
        match = re.search(r"\.gpkg[\\/]", text, flags=re.IGNORECASE)
        if match:
            gpkg = text[:match.start() + len(".gpkg")]
            layer_name = text[match.end():]
            return os.path.splitext(gpkg)[0] + "_" + self.sanitize_name(layer_name) + ".lyrx"
        return os.path.splitext(text)[0] + ".lyrx"

    def _write_style_file(self, in_src, written_path, messages):
        """Kirjoita lähdetason symbologia .lyrx-tiedostoksi viedyn aineiston viereen.

        ArcGIS ei lue GeoPackageen tai Shapefileen tallennettua tyyliä, joten
        tyyli kulkee .lyrx-tasotiedostona, joka viittaa viedyn tiedoston
        dataan suhteellisella polulla. Tyylin puuttuminen ei kaada vientiä.
        """
        style_path = self._style_file_path(written_path)
        temp_dir = None
        out_layer = None
        try:
            import tempfile
            label = self.sanitize_name(self._export_source_label(in_src))[:50] or "vienti"
            sequence = int(getattr(self, "_style_layer_sequence", 0) or 0) + 1
            self._style_layer_sequence = sequence
            stamp = datetime.datetime.now().strftime("%H%M%S%f")
            out_layer = f"{label[:30]}_tyyli_{stamp}_{sequence}"
            arcpy.management.MakeFeatureLayer(written_path, out_layer)
            if getattr(arcpy.Describe(in_src), "dataType", "") == "FeatureLayer":
                temp_dir = tempfile.mkdtemp(prefix="muuntaja_tyyli_")
                source_style = os.path.join(temp_dir, "lahde.lyrx")
                arcpy.management.SaveToLayerFile(in_src, source_style, "ABSOLUTE")
                arcpy.management.ApplySymbologyFromLayer(out_layer, source_style)
            if os.path.exists(style_path):
                os.remove(style_path)
            arcpy.management.SaveToLayerFile(out_layer, style_path, "RELATIVE")
            self.log(messages, f"  > Tyyli tallennettu: {os.path.basename(style_path)}")
            return style_path
        except Exception as error:
            self.log(messages, f"  > Tyylitiedoston kirjoitus epäonnistui ({error}); aineisto vietiin ilman tyyliä.",
                     "WARNING")
            return None
        finally:
            if out_layer:
                try:
                    arcpy.management.Delete(out_layer)
                except Exception:
                    pass
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    # --- SUOMEN KOORDINAATISTON PÄÄTTELY ---
    def detect_finnish_crs(self, feature_class, messages, input_path=None):
        """Päättelee koordinaatiston useasta pisteestä enemmistöäänellä.
        Käyttää SEKÄ X että Y -tarkastelua, kattaa TM35FIN, GK-kaistat (prefiksoidut ja kompaktit),
        KKJ-kaistat 1-4, YKJ ja WGS84 lat/lon. Tukee myös .prj-sivutiedostoja.
        """
        # Tarkistetaan ensin mahdollinen .prj-sivutiedosto CAD-tiedoston vierestä
        if input_path:
            base, _ = os.path.splitext(input_path)
            for prj_candidate in (base + ".prj", input_path + ".prj"):
                if os.path.isfile(prj_candidate):
                    try:
                        sr = arcpy.SpatialReference(prj_candidate)
                        if sr and getattr(sr, "name", "") and sr.name != "Unknown":
                            code = self._sr_factory_code(sr)
                            label = f"EPSG:{code}" if code else sr.name
                            self.log(messages, f"  > Luettu koordinaatisto .prj-sivutiedostosta: {sr.name} ({label})")
                            return sr
                    except Exception:
                        pass
        from collections import Counter
        MAX_SAMPLES = 200

        classify = classify_finnish_xy

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

    def _has_known_spatial_reference(self, path):
        try:
            sr = getattr(arcpy.Describe(path), "spatialReference", None)
        except Exception:
            return False
        name = str(getattr(sr, "name", "") or "").strip().lower()
        return bool(sr) and name not in ("", "unknown")

    def _define_missing_crs(self, path, input_sr, messages):
        """Leimaa lähtö-CRS tulokseen, jos sillä ei ole omaa koordinaatistoa."""
        if input_sr is None or self._has_known_spatial_reference(path):
            return False
        arcpy.management.DefineProjection(path, input_sr)
        self.log(messages, f"  > Koordinaatisto leimattu: {getattr(input_sr, 'name', input_sr)}")
        return True

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

    # --- RASTERIT ---
    def _is_raster_import_path(self, path):
        return os.path.splitext(str(path or ""))[1].lower() in RASTER_IMPORT_FILE_EXTENSIONS

    def _world_file_candidates(self, path):
        """World-tiedoston mahdolliset nimet: R4324.pgw, R4324.pngw, R4324.wld."""
        base, ext = os.path.splitext(str(path))
        ext = ext.lower()
        candidates = []
        if len(ext) >= 3:
            candidates.append(base + "." + ext[1] + ext[-1] + "w")
        candidates.append(base + ext + "w")
        candidates.append(base + ".wld")
        return candidates

    def _raster_has_georeference(self, path):
        """True jos kuvatiedoston vieressä on world-tiedosto tai .aux.xml."""
        candidates = self._world_file_candidates(path) + [str(path) + ".aux.xml"]
        return any(os.path.isfile(candidate) for candidate in candidates)

    def _read_world_file_origin(self, path):
        """Palauta world-tiedoston vasemman yläkulman (X, Y) tai None."""
        for candidate in self._world_file_candidates(path):
            if not os.path.isfile(candidate):
                continue
            try:
                with open(candidate, "r", encoding="ascii", errors="ignore") as handle:
                    values = [
                        float(line.strip().replace(",", "."))
                        for line in handle
                        if line.strip()
                    ]
            except (OSError, ValueError):
                continue
            if len(values) >= 6:
                return values[4], values[5]
        return None

    def _guess_raster_epsg(self, path):
        """Päättele rasterin EPSG world-tiedostosta tai kansiopolusta.

        Palauttaa (epsg, lähde) tai (None, None). MML:n latauksissa
        koordinaatisto näkyy myös polussa (…/etrs89/png/…), mutta
        world-tiedoston koordinaatit ovat luotettavampi ensisijainen lähde.
        """
        origin = self._read_world_file_origin(path)
        if origin:
            epsg = classify_finnish_xy(*origin)
            if epsg:
                return epsg, "world-tiedosto"
        parts = [part.lower() for part in re.split(r"[\\/]+", str(path)) if part]
        if "etrs89" in parts or any("tm35" in part for part in parts):
            return 3067, "kansiopolku"
        if "kkj" in parts or "ykj" in parts:
            return 2393, "kansiopolku"
        return None, None

    def _ensure_raster_spatial_reference(self, path, input_sr, messages):
        """Määritä koordinaatisto rasterille, jolta se puuttuu.

        MML:n PNG-karttalehdissä on vain .pgw ilman koordinaatistoa, jolloin Pro
        piirtäisi ne tuntemattomina. DefineProjection kirjoittaa .aux.xml:n
        rasterin viereen. Palauttaa määritetyn koordinaatiston nimen tai None.
        """
        try:
            current = arcpy.Describe(path).spatialReference
            if current is not None and (getattr(current, "name", "") or "Unknown") != "Unknown":
                return None
        except Exception:
            pass

        if input_sr is not None:
            target = input_sr
        else:
            epsg, _source = self._guess_raster_epsg(path)
            if not epsg:
                self.log(
                    messages,
                    f"  > Rasterin '{os.path.basename(path)}' koordinaatistoa ei tunnistettu. "
                    "Valitse tarvittaessa Lähtökoordinaatisto.",
                    "WARNING",
                )
                return None
            target = arcpy.SpatialReference(epsg)

        try:
            arcpy.management.DefineProjection(path, target)
        except Exception as e:
            self.log(
                messages,
                f"  > Koordinaatiston määritys epäonnistui ({os.path.basename(path)}): {e}",
                "WARNING",
            )
            return None
        return getattr(target, "name", None) or "määritetty"

    def _normalized_path_key(self, path):
        try:
            return os.path.normcase(os.path.abspath(str(path)))
        except Exception:
            return str(path).casefold()

    def _raster_group_name(self, path, folder_roots=None):
        """Ryhmätason nimi rasterille.

        1) Lähin taustakartta_-alkuinen yläkansio (taustakartta_20k, _5k …).
        2) Muuten ensimmäinen kansio syötekansion alla, ohittaen MML:n
           latauskohtaiset Maanmittauslaitos_Tiedostopalvelu_*-kansiot.
        3) Yksittäin valitulle tiedostolle sen oma kansio.
        """
        directory = os.path.dirname(os.path.abspath(str(path)))
        parts = [part for part in re.split(r"[\\/]+", directory) if part]
        for part in reversed(parts):
            if part.lower().startswith(RASTER_GROUP_FOLDER_PREFIX):
                return part

        path_key = self._normalized_path_key(path)
        best_root = None
        for root in folder_roots or []:
            root_key = self._normalized_path_key(root).rstrip("\\/")
            if path_key.startswith(root_key + os.sep):
                if best_root is None or len(root_key) > len(self._normalized_path_key(best_root)):
                    best_root = root
        if best_root is not None:
            relative = os.path.relpath(directory, os.path.abspath(best_root))
            components = [
                part for part in re.split(r"[\\/]+", relative)
                if part and part != "."
                and not part.lower().startswith(MML_DOWNLOAD_FOLDER_PREFIX)
            ]
            if components:
                return components[0]
            return os.path.basename(os.path.abspath(best_root).rstrip("\\/")) or "Rasterit"

        return os.path.basename(directory) or "Rasterit"

    def _group_raster_paths(self, raster_paths, folder_roots=None):
        """Ryhmittele rasterit {ryhmän nimi: [polut]}; saman niminen ryhmä
        eri latauksista yhdistetään."""
        groups = {}
        names_by_key = {}
        for path in raster_paths or []:
            name = self._raster_group_name(path, folder_roots)
            name = names_by_key.setdefault(name.casefold(), name)
            groups.setdefault(name, []).append(path)
        return groups

    def _raster_group_sort_key(self, name):
        """Lisäysjärjestys: tarkin mittakaava lisätään viimeisenä, jolloin se
        jää sisällysluettelossa ylimmäksi (5k yli 20k:n)."""
        lowered = str(name).lower()
        match = re.search(r"(\d+)\s*k(?![a-z])", lowered)
        if match:
            scale = int(match.group(1)) * 1000
        else:
            match = re.search(r"(\d+)", lowered)
            scale = int(match.group(1)) if match else None
        return (0 if scale is None else 1, -(scale or 0), lowered)

    def _get_or_create_group_layer(self, active_map, name):
        """Käytä olemassa olevaa ylätason ryhmätasoa tai luo uusi."""
        for layer in active_map.listLayers():
            if (
                getattr(layer, "isGroupLayer", False)
                and layer.name == name
                and getattr(layer, "longName", name) == name
            ):
                return layer
        create = getattr(active_map, "createGroupLayer", None)
        if callable(create):
            return create(name)
        return self._add_group_layer_from_lyrx(active_map, name)

    def _add_group_layer_from_lyrx(self, active_map, name):
        """Varatapa vanhemmille Pro-versioille, joissa ei ole createGroupLayeria."""
        import tempfile
        document = {
            "type": "CIMLayerDocument",
            "version": "3.0.0",
            "layers": ["CIMPATH=muuntaja/group.json"],
            "layerDefinitions": [{
                "type": "CIMGroupLayer",
                "name": name,
                "uRI": "CIMPATH=muuntaja/group.json",
                "layerType": "Operational",
                "showLegends": True,
                "visibility": True,
                "expanded": False,
                "layers": [],
            }],
        }
        handle, lyrx_path = tempfile.mkstemp(suffix=".lyrx")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(document, out)
            added = active_map.addLayer(arcpy.mp.LayerFile(lyrx_path), "TOP")
        finally:
            try:
                os.remove(lyrx_path)
            except OSError:
                pass
        if isinstance(added, (list, tuple)):
            added = added[0] if added else None
        if added is None:
            raise RuntimeError("ryhmätason lisäys ei palauttanut tasoa")
        return added

    def _group_layer_data_sources(self, group_layer):
        sources = set()
        try:
            layers = group_layer.listLayers()
        except Exception:
            return sources
        for layer in layers:
            try:
                if layer.supports("DATASOURCE"):
                    sources.add(self._normalized_path_key(layer.dataSource))
            except Exception:
                continue
        return sources

    def _supports_mosaic_raster_import(self, output_loc, is_folder):
        """Mosaiikkiaineisto vaatii GDB-kohteen ja Standard/Advanced-lisenssin."""
        if not output_loc or is_folder:
            return False
        try:
            product = str(arcpy.ProductInfo()).strip().casefold()
        except Exception:
            return False
        return product in {"arceditor", "arcinfo", "standard", "advanced"}

    def _common_raster_spatial_reference(self, paths, input_sr):
        """Palauta yhteinen CRS nopeaa mosaiikkituontia varten tai None.

        Automaattitilassa nopeaa reittiä käytetään vain, kun jokaisen
        rasterin EPSG voidaan päätellä ja se on koko ryhmässä sama.
        """
        if input_sr is not None:
            return input_sr
        epsg_codes = set()
        for path in paths:
            epsg, _source = self._guess_raster_epsg(path)
            if not epsg:
                return None
            epsg_codes.add(epsg)
            if len(epsg_codes) > 1:
                return None
        if not epsg_codes:
            return None
        return arcpy.SpatialReference(epsg_codes.pop())

    def _is_mosaic_dataset(self, path):
        try:
            data_type = str(arcpy.Describe(path).dataType)
        except Exception:
            return False
        return data_type.replace(" ", "").casefold() == "mosaicdataset"

    def _mosaic_dataset_path(self, output_loc, group_name):
        """Palauta ryhmän olemassa oleva mosaiikki tai vapaa GDB-nimi."""
        base_name = self.sanitize_name(RASTER_MOSAIC_DATASET_PREFIX + group_name)
        try:
            base_name = arcpy.ValidateTableName(base_name, output_loc)
        except Exception:
            pass
        candidate_name = base_name
        suffix = 2
        while True:
            candidate_path = os.path.join(output_loc, candidate_name)
            if not arcpy.Exists(candidate_path):
                return candidate_path, candidate_name, False
            if self._is_mosaic_dataset(candidate_path):
                return candidate_path, candidate_name, True
            candidate_name = f"{base_name}_{suffix}"
            suffix += 1

    def _import_raster_group_as_mosaic(
        self, active_map, group_layer, group_name, paths, output_loc, source_sr, messages
    ):
        """Lisää rasteriryhmän GDB-mosaiikkiin yhdellä eräoperaatiolla."""
        mosaic_path, mosaic_name, existed = self._mosaic_dataset_path(
            output_loc, group_name
        )
        if not existed:
            arcpy.management.CreateMosaicDataset(
                output_loc, mosaic_name, source_sr
            )

        self.log(
            messages,
            f"  > Ryhmä '{group_name}': lisätään {len(paths)} rasteria "
            "mosaiikkiaineistoon yhtenä eränä...",
        )
        arcpy.management.AddRastersToMosaicDataset(
            in_mosaic_dataset=mosaic_path,
            raster_type="Raster Dataset",
            input_path=list(paths),
            update_cellsize_ranges="UPDATE_CELL_SIZES",
            update_boundary="UPDATE_BOUNDARY",
            update_overviews="NO_OVERVIEWS",
            spatial_reference=source_sr,
            sub_folder="NO_SUBFOLDERS",
            duplicate_items_action="EXCLUDE_DUPLICATES",
            build_pyramids="NO_PYRAMIDS",
            calculate_statistics="NO_STATISTICS",
            build_thumbnails="NO_THUMBNAILS",
            force_spatial_reference="FORCE_SPATIAL_REFERENCE",
            estimate_statistics="NO_STATISTICS",
            enable_pixel_cache="NO_PIXEL_CACHE",
        )

        existing_sources = self._group_layer_data_sources(group_layer)
        if self._normalized_path_key(mosaic_path) not in existing_sources:
            try:
                layer = active_map.addDataFromPath(mosaic_path)
                active_map.addLayerToGroup(group_layer, layer)
                active_map.removeLayer(layer)
            except Exception as e:
                self.log(
                    messages,
                    f"  > Mosaiikkiaineisto '{mosaic_name}' luotiin, mutta sen "
                    f"lisääminen kartalle epäonnistui: {e}",
                    "WARNING",
                )
        self.log(
            messages,
            f"  > Ryhmä '{group_name}': {len(paths)} rasteria käsitelty "
            f"mosaiikkiaineistoon '{mosaic_name}'.",
        )

    def _import_rasters(
        self, raster_paths, folder_roots, input_sr, messages,
        output_loc=None, is_folder=True,
    ):
        """Lisää rasterit aktiiviseen karttaan ryhmätasoihin.

        Rasterit lisätään viittauksina alkuperäisiin tiedostoihin: satojen
        karttalehtien kopiointi GDB:hen olisi hidasta eikä paranna näyttöä.
        Jo ryhmässä oleva sama tiedosto ohitetaan, joten uudelleenajo ei
        tuplaa karttalehtiä. Palauttaa (onnistuneet, [(polku, syy)]).
        """
        succeeded = []
        failures = []
        try:
            active_map = arcpy.mp.ArcGISProject("CURRENT").activeMap
        except Exception:
            active_map = None
        if active_map is None:
            reason = "aktiivista karttaa ei ole (avaa kartta ennen rasterien tuontia)"
            self.log(messages, f"Rasterit: {reason}.", "WARNING")
            return succeeded, [(path, reason) for path in raster_paths]

        groups = self._group_raster_paths(raster_paths, folder_roots)
        self.log(
            messages,
            f"Rasterit — {len(raster_paths)} tiedostoa {len(groups)} ryhmään. "
            "Rasterit lisätään viittauksina alkuperäisiin tiedostoihin (ei kopioida tallennuspaikkaan).",
        )
        mosaic_import_enabled = self._supports_mosaic_raster_import(
            output_loc, is_folder
        )
        for group_name in sorted(groups, key=self._raster_group_sort_key):
            paths = groups[group_name]
            try:
                group_layer = self._get_or_create_group_layer(active_map, group_name)
            except Exception as e:
                reason = f"ryhmätason '{group_name}' luonti epäonnistui: {e}"
                self.log(messages, f"  > {reason}", "WARNING")
                failures.extend((path, reason) for path in paths)
                continue

            if mosaic_import_enabled:
                source_sr = self._common_raster_spatial_reference(paths, input_sr)
                if source_sr is not None:
                    try:
                        self._import_raster_group_as_mosaic(
                            active_map, group_layer, group_name, paths,
                            output_loc, source_sr, messages,
                        )
                        succeeded.extend(paths)
                        continue
                    except Exception as e:
                        self.log(
                            messages,
                            f"  > Ryhmän '{group_name}' nopea mosaiikkituonti "
                            f"epäonnistui ({e}). Jatketaan rasterit yksitellen.",
                            "WARNING",
                        )

            existing = self._group_layer_data_sources(group_layer)
            added = skipped = 0
            defined_crs = set()
            group_total = len(paths)
            for processed, path in enumerate(paths, 1):
                key = self._normalized_path_key(path)
                if key in existing:
                    skipped += 1
                    succeeded.append(path)
                else:
                    try:
                        crs_name = self._ensure_raster_spatial_reference(path, input_sr, messages)
                        if crs_name:
                            defined_crs.add(crs_name)
                        layer = active_map.addDataFromPath(path)
                        active_map.addLayerToGroup(group_layer, layer)
                        active_map.removeLayer(layer)
                        existing.add(key)
                        added += 1
                        succeeded.append(path)
                    except Exception as e:
                        failures.append((path, str(e)))
                        self.log(
                            messages,
                            f"  > Rasterin '{path}' lisäys epäonnistui: {e}",
                            "WARNING",
                        )

                if group_total >= RASTER_PROGRESS_INTERVAL and (
                    processed % RASTER_PROGRESS_INTERVAL == 0 or processed == group_total
                ):
                    failed = processed - added - skipped
                    status = (
                        f"  > Ryhmä '{group_name}': {processed}/{group_total} rasteria käsitelty "
                        f"({added} lisätty"
                    )
                    if skipped:
                        status += f", {skipped} ohitettu"
                    if failed:
                        status += f", {failed} epäonnistui"
                    self.log(messages, status + ").")

            summary = f"  > Ryhmä '{group_name}': {added} rasteria lisätty"
            if skipped:
                summary += f", {skipped} oli jo ryhmässä"
            if defined_crs:
                summary += f"; koordinaatisto määritetty: {', '.join(sorted(defined_crs))}"
            self.log(messages, summary + ".")
        return succeeded, failures

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
            if str(e).strip() == "CURRENT":
                pass  # Headless-ajo ilman aktiivista ArcGIS Pro -käyttöliittymäprojektia
            else:
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

                # Vapaa nimi: saman geometriatyypin toinen CAD-taso ei saa
                # ylikirjoittaa edellisen tason projisoitua tulosta.
                _projected_name, projected_path = self._resolve_output_path(
                    output_loc, output_name + "_proj", is_folder
                )

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
                if not do_projection and not remote:
                    # Nopea suora kirjoitus: FeatureClassToFeatureClass suoraan kohteeseen
                    # ilman turhaa scratchGDB-välitallennusta ja toista CopyFeatures-kutsua!
                    t0 = time.perf_counter()
                    try:
                        arcpy.conversion.FeatureClassToFeatureClass(
                            input_data, output_loc, output_name, field_mapping=field_mappings
                        )
                        self._log_elapsed(messages, "Tallennus (kenttäsuodatus)", t0)
                        self._define_missing_crs(check_path, input_sr, messages)
                        return check_path
                    except Exception as e:
                        self.log(
                            messages,
                            f"  > Suora FeatureClassToFeatureClass epäonnistui ({e}), kokeillaan scratch-reittiä.",
                            "WARNING",
                        )

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
                # Ilman projisointia tunnistettu lähtö-CRS pitää silti leimata
                # tulokseen; muuten CAD-taso jää tuntemattomaan koordinaatistoon.
                self._define_missing_crs(check_path, input_sr, messages)

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

        # Cache rivimäärille: vältetään saman tason GetCount-kutsu useaan kertaan.
        feat_count_cache = {}
        detected_sr = None
        crs_detection_done = False
        cad_dataset_sr = input_sr

        if use_bulk_scratch:
            # CADToGeodatabase tekee tuntemattomaan koordinaatistoon feature
            # datasetin, jonka tasoja ArcGIS ei suostu projisoimaan edes
            # lähtö-CRS:n kanssa (ERROR 000289/000599). Tunnistetaan CRS siksi
            # jo suoraan luetuista tasoista ja annetaan se muunnokselle.
            if not input_sr:
                detected_sr = self._detect_cad_source_sr(
                    fcs_direct, input_path, input_path, messages, feat_count_cache
                )
                crs_detection_done = True
                cad_dataset_sr = detected_sr
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
                cad_args = [input_path, temp_gdb, ds_name, 1000]
                if cad_dataset_sr is not None:
                    cad_args.append(cad_dataset_sr)
                arcpy.conversion.CADToGeodatabase(*cad_args)
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
                raise RuntimeError("CAD-tiedostosta ei löytynyt tasoja.")

            fcs = sorted(fcs, key=lambda fc: self._cad_layer_sort_key(fc, dataset_path))

            # Automaattitunnistus (ensimmäisestä EI-tyhjästä point/line/polygon-tasosta)
            if not input_sr and not crs_detection_done:
                detected_sr = self._detect_cad_source_sr(
                    fcs, dataset_path, input_path, messages, feat_count_cache
                )

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

                fc_name_lower = str(fc).lower()
                suffix = geom_type or "unknown"
                if geom_type == 'polyline': suffix = 'line'
                elif geom_type == 'multipatch': suffix = 'multipatch'
                elif is_anno: suffix = 'anno'
                elif 'textpoint' in fc_name_lower: suffix = 'textpoint'
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

            if not saved_paths:
                raise RuntimeError("CAD-tiedostossa ei ollut tuotavia kohteita.")
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

    def _detect_cad_source_sr(self, fcs, dataset_path, input_path, messages, feat_count_cache):
        """Tunnista CAD-aineiston CRS ensimmäisestä ei-tyhjästä piste-/viiva-/aluetasosta."""
        for fc in sorted(fcs, key=lambda name: self._cad_layer_sort_key(name, dataset_path)):
            try:
                fc_path = os.path.join(dataset_path, fc)
                if arcpy.Describe(fc_path).shapeType not in ("Point", "Polyline", "Polygon"):
                    continue
                fc_count = self._count_safe(fc_path)
                feat_count_cache[fc_path] = fc_count
                if fc_count > 0:
                    detected = self.detect_finnish_crs(fc_path, messages, input_path=input_path)
                    if detected:
                        return detected
            except Exception:
                continue
        return None

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
                
                # Vapaa nimi, jottei aiemman tuonnin projisoitu taso ylikirjoitu.
                _projected_name, projected_path = self._resolve_output_path(
                    output_loc, output_name + "_proj", is_folder
                )

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
            # Virhe välitetään kutsujalle, jotta eräajon yhteenveto ei laske
            # epäonnistunutta tallennusta onnistuneeksi.
            self.log(messages, f"Tallennusvirhe ({output_name}): {str(e)}", "WARNING")
            raise

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

        failed = []
        try:
            for src_path, out_name in source_items:
                try:
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
                except Exception as e:
                    failed.append((out_name, str(e)))
                    continue
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
        if failed and not saved_paths:
            raise RuntimeError(
                "Yhtään tasoa ei voitu tallentaa: "
                + "; ".join(f"{name}: {reason}" for name, reason in failed)
            )
        for name, reason in failed:
            self.log(messages, f"  > Taso '{name}' jäi tuomatta: {reason}", "WARNING")
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
            try:
                arcpy.management.Delete(tmp_fc)
            except Exception:
                pass
            raise RuntimeError("GPX-tiedostosta ei löytynyt geometriaa.")
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
            try:
                arcpy.management.AddField(tmp_fc, "name", "TEXT", field_length=255)
            except Exception:
                pass
            count = 0
            with arcpy.da.InsertCursor(tmp_fc, ["SHAPE@", "name"]) as cur:
                for trk in root.findall(f'{p}trk'):
                    trk_name = (trk.findtext(f'{p}name') or "").strip()
                    for seg in trk.findall(f'{p}trkseg'):
                        pts = [
                            arcpy.Point(float(pt.get('lon')), float(pt.get('lat')))
                            for pt in seg.findall(f'{p}trkpt')
                            if pt.get('lat') and pt.get('lon')
                        ]
                        if len(pts) >= 2:
                            cur.insertRow([arcpy.Polyline(arcpy.Array(pts), sr), trk_name])
                            count += 1
                for rte in root.findall(f'{p}rte'):
                    rte_name = (rte.findtext(f'{p}name') or "").strip()
                    pts = [
                        arcpy.Point(float(pt.get('lon')), float(pt.get('lat')))
                        for pt in rte.findall(f'{p}rtept')
                        if pt.get('lat') and pt.get('lon')
                    ]
                    if len(pts) >= 2:
                        cur.insertRow([arcpy.Polyline(arcpy.Array(pts), sr), rte_name])
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
                raise RuntimeError("KMLToLayer ei tuottanut geodatabasea.")
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
                raise RuntimeError("KML/KMZ-tiedostosta ei saatu yhtään geometriaa.")

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
            try:
                arcpy.management.ClearWorkspaceCache()
            except Exception:
                pass
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

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
            try:
                self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
            finally:
                for tmp_fc, _out_name in batch_items:
                    try:
                        if arcpy.Exists(tmp_fc):
                            arcpy.management.Delete(tmp_fc)
                    except Exception:
                        pass
        if not made_any:
            raise RuntimeError("GeoJSON/JSON-tiedostosta ei saatu yhtään geometriaa.")
    def _geopackage_import_output_name(self, input_path, feature_class_name):
        """Poista ArcGISin ``main.``-skeema GPKG-tason tuontinimestä.

        ArcGIS listaa esimerkiksi tason ``Nopeusrajoitus`` usein muodossa
        ``main.Nopeusrajoitus``. ``os.path.splitext`` tulkitsisi loppuosan
        tiedostopäätteeksi ja palauttaisi virheellisesti nimeksi ``main``.
        """
        raw = str(feature_class_name or "").strip().replace("/", "\\")
        leaf = raw.rsplit("\\", 1)[-1]
        if "." in leaf:
            schema, qualified_name = leaf.split(".", 1)
            if schema.casefold() in ("main", "temp") and qualified_name.strip():
                leaf = qualified_name.strip()

        if not leaf or leaf.casefold() in ("main", "temp"):
            leaf = self._file_stem(input_path)

        result = self.sanitize_name(leaf)
        if not result:
            result = self.sanitize_name(self._file_stem(input_path)) or "gpkg_taso"
        return result

    @staticmethod
    def _file_stem(path):
        """Tiedostonimi ilman päätettä; tunnistaa sekä \\- että /-erottimet."""
        leaf = re.split(r"[\\/]", str(path or "").rstrip("\\/"))[-1]
        return os.path.splitext(leaf)[0]

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
                out_name = self._geopackage_import_output_name(input_path, fc)
                batch_items.append((src_path, out_name))
            if batch_items:
                self.log(messages, f"  > GPKG-eräajo: {len(batch_items)} tasoa.")
                self._bulk_convert_and_add(batch_items, output_loc, is_folder, messages)
            else:
                raise RuntimeError("GeoPackagesta ei löytynyt ei-tyhjiä tasoja.")
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

    @staticmethod
    def _dfsu_element_xy(idx, node_coords, element_table, shape_type, element_coordinates=None):
        """Palauta yhden elementin (x, y) -pisteet tunnistetun tyypin mukaan."""
        if element_table is not None and node_coords is not None:
            nodes = element_table[idx]
            if nodes is not None and len(nodes) > 0:
                return [
                    (float(node_coords[int(n)][0]), float(node_coords[int(n)][1]))
                    for n in nodes
                ]
        if element_coordinates is not None:
            coords = element_coordinates[idx]
            return [(float(coords[0]), float(coords[1]))]
        return []

    @staticmethod
    def _wkb_point(x, y):
        # 1 = little endian, 1 = wkbPoint
        return struct.pack("<BIdd", 1, 1, x, y)

    @staticmethod
    def _wkb_linestring(points):
        parts = [struct.pack("<BII", 1, 2, len(points))]
        for x, y in points:
            parts.append(struct.pack("<dd", x, y))
        return b"".join(parts)

    @staticmethod
    def _wkb_polygon(points):
        ring = list(points)
        # WKB-polygonin rengas on suljettava eksplisiittisesti.
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        parts = [struct.pack("<BIII", 1, 3, 1, len(ring))]
        for x, y in ring:
            parts.append(struct.pack("<dd", x, y))
        return b"".join(parts)

    def _make_dfsu_wkb(self, idx, node_coords, element_table, shape_type,
                       element_coordinates=None):
        """Muodosta elementin geometria suoraan WKB-tavuina.

        Aiemmin jokaiselle elementille rakennettiin arcpy.Array ja N kpl
        arcpy.Point-olioita. Miljoonan elementin meshissä se tarkoitti
        miljoonia COM-rajapinnan yli meneviä olioita, ja hallitsi tuonnin
        kokonaisaikaa. SHAPE@WKB ohittaa koko olioketjun.
        """
        points = self._dfsu_element_xy(
            idx, node_coords, element_table, shape_type, element_coordinates
        )
        if not points:
            raise ValueError(f"Elementti {idx}: geometriaa ei voitu muodostaa.")

        if shape_type == "POLYGON":
            if len(points) < 3:
                raise ValueError(f"Elementti {idx}: polygon vaatii vähintään 3 solmua.")
            return self._wkb_polygon(points)
        if shape_type == "POLYLINE":
            if len(points) < 2:
                raise ValueError(f"Elementti {idx}: viiva vaatii vähintään 2 solmua.")
            return self._wkb_linestring(points)

        if len(points) == 1:
            return self._wkb_point(points[0][0], points[0][1])
        # Monisolmuisesta elementistä piste = solmujen keskipiste, kuten ennen.
        mean_x = sum(px for px, _ in points) / float(len(points))
        mean_y = sum(py for _, py in points) / float(len(points))
        return self._wkb_point(mean_x, mean_y)

    def _dfsu_source_spatial_reference(self, geometry, node_coords, element_coordinates,
                                       input_sr, messages):
        """Selvitä DFSU:n lähtö-CRS: valittu > tiedoston projektio > koordinaatit.

        MIKE käyttää projektiona esim. ``LONG/LAT`` tai ``NON-UTM``; jälkimmäinen
        ei kerro koordinaatistoa. Tuntematonta CRS:ää ei korvata hiljaa kartan
        tai kohteen koordinaatistolla, vaan pyydetään valitsemaan lähtö-CRS.
        """
        if input_sr is not None:
            self.log(messages, f"  > DFSU:n lähtö-CRS valittu: {getattr(input_sr, 'name', input_sr)}")
            return input_sr

        projection = str(getattr(geometry, "projection_string", "") or "").strip()
        if projection.upper() in ("LONG/LAT", "LONGLAT", "GEOGRAPHIC"):
            return arcpy.SpatialReference(4326)
        if projection and projection.upper() != "NON-UTM":
            try:
                sr = arcpy.SpatialReference()
                sr.loadFromString(projection)
                if (getattr(sr, "name", "") or "Unknown") != "Unknown":
                    return sr
            except Exception:
                pass

        points = []
        if node_coords is not None:
            count = len(node_coords)
            step = max(1, count // 200)
            points = [(float(node_coords[i][0]), float(node_coords[i][1])) for i in range(0, count, step)]
        elif element_coordinates is not None:
            count = len(element_coordinates)
            step = max(1, count // 200)
            points = [
                (float(element_coordinates[i][0]), float(element_coordinates[i][1]))
                for i in range(0, count, step)
            ]
        epsg = vote_finnish_epsg(points)
        if epsg:
            self.log(messages, f"  > DFSU:n koordinaatisto tunnistettiin koordinaateista: EPSG:{epsg}")
            return arcpy.SpatialReference(epsg)
        raise RuntimeError(
            f"DFSU:n koordinaatistoa ei tunnistettu (projektio: {projection or 'puuttuu'}). "
            "Valitse Lähtökoordinaatisto."
        )

    def process_dfsu(self, input_path, output_loc, is_folder, messages,
                     filter_enabled=False, filter_column="", filter_operator="=",
                     filter_value="", target_sr=None, input_sr=None):
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
        direct_target_path = None
        import_completed = False
        restore_gp_env = {}
        try:
            import math
            # Puuttuva mikeio kaataa vain DFSU-tiedostot; muu eräajo jatkuu.
            mikeio = self._ensure_python_module("mikeio")

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

            source_sr = self._dfsu_source_spatial_reference(
                geometry, node_coords, element_coordinates, input_sr, messages
            )
            # Aineisto leimataan aina omaan koordinaatistoonsa; kohde-CRS on
            # vain projisoinnin kohde eikä koskaan arvaus lähteen CRS:ksi.
            create_sr = source_sr

            # Iso InsertCursor hyötyy samoista GP-asetuksista kuin CAD-polku:
            # harvempi commit ja ilman spatiaali-indeksin ylläpitoa kirjoituksen
            # aikana.
            prev_gp_env = {}
            for env_key, env_value in (
                ("autoCommit", 10000),
                ("maintainSpatialIndex", False),
                ("buildStats", "NONE"),
                ("parallelProcessingFactor", "100%"),
            ):
                try:
                    prev_gp_env[env_key] = getattr(arcpy.env, env_key)
                except Exception:
                    prev_gp_env[env_key] = None
                try:
                    setattr(arcpy.env, env_key, env_value)
                except Exception:
                    pass
            restore_gp_env = prev_gp_env

            # Kun kohde on file GDB eikä projisointia tarvita, kirjoitetaan
            # suoraan lopulliseen tasoon. Muuten iso mesh kirjoitettaisiin
            # levylle kahdesti: ensin scratchiin ja heti perässä CopyFeaturesilla
            # kohteeseen.
            direct_target_path = None
            if not is_folder and not self._needs_projection(source_sr, target_sr):
                try:
                    direct_name, direct_path = self._resolve_output_path(
                        output_loc, safe_name, is_folder
                    )
                    direct_target_path = direct_path
                    self.log(
                        messages,
                        f"  > Kirjoitetaan suoraan kohteeseen '{direct_name}' "
                        f"(ei erillistä välikopiota).",
                    )
                except Exception as resolve_error:
                    self.log(
                        messages,
                        f"  > Suoran kirjoituksen valmistelu epäonnistui ({resolve_error}); "
                        f"käytetään väliaikaista feature classia.",
                        "WARNING",
                    )
                    direct_target_path = None

            if direct_target_path:
                work_fc = direct_target_path
                work_workspace = os.path.dirname(direct_target_path)
                self.log(messages, f"  > Luodaan {shape_type}-feature class...")
            else:
                scratch = arcpy.env.scratchGDB
                stamp = datetime.datetime.now().strftime("%H%M%S%f")
                temp_fc = os.path.join(scratch, f"dfsu_{safe_name[:32]}_{stamp}")
                work_fc = temp_fc
                work_workspace = scratch
                if arcpy.Exists(temp_fc):
                    arcpy.management.Delete(temp_fc)
                self.log(messages, f"  > Luodaan väliaikainen {shape_type}-feature class...")

            arcpy.management.CreateFeatureclass(
                work_workspace, os.path.basename(work_fc), shape_type,
                spatial_reference=create_sr,
            )
            arcpy.management.AddField(work_fc, "element_id", "LONG")

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
                arcpy.management.AddField(work_fc, field_name, "DOUBLE")
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
                raise RuntimeError(
                    f"DFSU-suodatinsaraketta '{filter_column}' ei löytynyt "
                    f"(itemit: {', '.join(item_names)})."
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
            # SHAPE@WKB ohittaa arcpy.Point/arcpy.Array-olioketjun kokonaan.
            insert_fields = ["SHAPE@WKB", "element_id"] + [field_name for _, field_name in field_map]

            if candidate_indices is not None:
                iterable_indices = candidate_indices.tolist()
                total_scan = len(iterable_indices)
            else:
                iterable_indices = range(total_elements)
                total_scan = total_elements

            # numpy-taulukon indeksointi palauttaa boksatun skalaarin joka
            # kutsulla. Listaksi muuntaminen kerran on selvästi halvempaa kuin
            # miljoona indeksointia silmukassa.
            column_values = []
            for item_name, _field_name in field_map:
                values = values_by_item[item_name]
                try:
                    column_values.append(values.tolist())
                except AttributeError:
                    column_values.append(list(values))
            filter_list = filter_values
            if filter_values is not None:
                try:
                    filter_list = filter_values.tolist()
                except AttributeError:
                    filter_list = list(filter_values)

            geometry_errors = 0
            with arcpy.da.InsertCursor(work_fc, insert_fields) as cursor:
                for idx in iterable_indices:
                    processed += 1
                    raw_filter_value = None if filter_list is None else filter_list[idx]
                    if candidate_indices is None and not _passes_filter(raw_filter_value):
                        if processed % progress_step == 0:
                            self.log(messages, f"  > Eteneminen: käsitelty {processed}/{total_scan} elementtiä, osumia {inserted}.")
                        continue
                    try:
                        geom = self._make_dfsu_wkb(
                            idx, node_coords, element_table, shape_type, element_coordinates
                        )
                    except Exception:
                        # Yksittäinen viallinen elementti ei saa kaataa koko
                        # meshin tuontia.
                        geometry_errors += 1
                        continue
                    row = [geom, idx]
                    for column in column_values:
                        _v = column[idx]
                        row.append(None if (_v is None or _v != _v) else float(_v))
                    cursor.insertRow(row)
                    inserted += 1
                    if processed % progress_step == 0:
                        self.log(messages, f"  > Eteneminen: käsitelty {processed}/{total_scan} elementtiä, osumia {inserted}.")

            if geometry_errors:
                self.log(
                    messages,
                    f"  > VAROITUS: {geometry_errors} elementin geometriaa ei voitu muodostaa; "
                    f"ne ohitettiin.",
                    "WARNING",
                )

            self.log(messages, f"DFSU-tuonti: muodostettiin {inserted} {geom_action}.")
            if inserted == 0:
                if filter_enabled and filter_column:
                    raise RuntimeError("DFSU-suodatin ei tuottanut yhtään osumaa; tasoa ei luotu.")
                raise RuntimeError("DFSU-tiedostosta ei saatu muodostettua yhtään geometriaa.")

            if direct_target_path:
                # Taso on jo kohteessa: leimataan vain koordinaatisto ja
                # lisätään kartalle.
                if source_sr:
                    try:
                        arcpy.management.DefineProjection(work_fc, source_sr)
                    except Exception as define_error:
                        self.log(
                            messages,
                            f"  > Koordinaatiston leimaus epäonnistui: {define_error}",
                            "WARNING",
                        )
                self._add_layers_to_map([work_fc], messages)
                self.log(messages, f"DFSU-tuonti valmis: {work_fc}")
            else:
                self.log(messages, f"  > Tallennetaan lopullinen taso nimellä '{safe_name}'...")
                self.save_and_reproject(work_fc, output_loc, safe_name, is_folder, None, source_sr, target_sr, messages)
            import_completed = True
        except Exception as e:
            self.log(messages, f"DFSU-tuonti epäonnistui: {str(e)}", "ERROR")
            self.log(messages, traceback.format_exc(), "ERROR")
            raise
        finally:
            # Palauta globaalit GP-asetukset, jottei tila vuoda seuraavaan
            # tiedostoon eräajossa.
            for env_key, env_value in (restore_gp_env or {}).items():
                try:
                    setattr(arcpy.env, env_key, env_value)
                except Exception:
                    pass
            if temp_fc and arcpy.Exists(temp_fc):
                try:
                    arcpy.management.Delete(temp_fc)
                except Exception:
                    pass
            # Keskeneräistä tasoa ei jätetä kohteeseen näyttämään valmiilta.
            if direct_target_path and not import_completed:
                try:
                    if arcpy.Exists(direct_target_path):
                        arcpy.management.Delete(direct_target_path)
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
