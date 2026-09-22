# Muuntaja QGIS (esijulkaisu 0.1.0)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

1. Lataa [Muuntaja-QGIS-0.1.0.zip](https://github.com/roopepalom44/muuntaja/releases/download/qgis-v0.1.0/Muuntaja-QGIS-0.1.0.zip).
2. Avaa QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**.
3. Valitse ladattu ZIP. Muuntaja näkyy lisäosavalikossa ja työkalurivillä.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG (jos QGISin GDAL avaa tiedoston) ja georeferoidut rasterit.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, viittaus alkuperäiseen rasteriin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti.

## Erot ArcGIS Pro -versioon

- DWG-vienti ei toimi QGISin mukana tulevalla GDALilla, joka tukee DWG-lukua mutta ei DWG-kirjoitusta. Vie DXF ja muunna se DWG:ksi erillisellä DWG-muuntimella.
- Rasterimosaiikkia ei vielä rakenneta automaattisesti; rasterit lisätään ryhmään yksittäisinä tasoina.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska se ei vielä täytä tavoitetta täysin identtisestä toiminnasta.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. QGIS 3.44:n Python-ympäristössä tehty toimintatesti: `qgis_plugin/smoke.py`.
