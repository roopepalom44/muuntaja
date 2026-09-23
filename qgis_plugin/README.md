# Muuntaja QGIS (esijulkaisu 0.2.1)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Lataa [Muuntaja-QGIS-0.2.1-Windows.zip](https://github.com/roopepalom44/muuntaja/releases/download/qgis-v0.2.1/Muuntaja-QGIS-0.2.1-Windows.zip), pura ZIP ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen.

**QGISin oma asennus:** Lataa [Muuntaja-QGIS-0.2.1.zip](https://github.com/roopepalom44/muuntaja/releases/download/qgis-v0.2.1/Muuntaja-QGIS-0.2.1.zip) ja valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG (jos QGISin GDAL avaa tiedoston) ja georeferoidut rasterit.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti. DWG-vienti toimii valinnaisen ODA File Converter -ohjelman avulla: valitse ohjelman `.exe` vientinäkymässä. Myös yhdistetty DWG-vienti on käytettävissä.

## Erot ArcGIS Pro -versioon

- DWG-vienti tekee ensin DXF:n ja muuntaa sen ODA File Converterilla. Muuntimen komentorivikäyttö on testattu jäljitellyllä muuntimella; oikeaa ODA-asennusta ei ollut saatavilla paikalliseen lopputestiin.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska se ei vielä täytä tavoitetta täysin identtisestä toiminnasta.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. QGIS 3.44:n Python-ympäristössä tehty toimintatesti: `qgis_plugin/smoke.py`.
