# Muuntaja QGIS (esijulkaisu 0.2.4)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Lataa uusimmasta [yhteisestä julkaisusta](https://github.com/roopepalom44/muuntaja/releases/latest) `Muuntaja-QGIS-0.2.4-Windows.zip`, pura ZIP ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen.

**QGISin oma asennus:** Lataa samasta julkaisusta `Muuntaja-QGIS-0.2.4.zip` ja valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG (jos QGISin GDAL avaa tiedoston) ja georeferoidut rasterit.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti. DWG-vienti toimii valinnaisen ODA File Converter -ohjelman avulla: valitse ohjelman `.exe` vientinäkymässä. Myös yhdistetty DWG-vienti on käytettävissä.
- GeoJSON-vienti muuntaa tunnetun lähtökoordinaatiston WGS84:ään, kuten ArcGIS Pro -versio.
- Tallennetun QGIS-projektin kansio ehdotetaan oletukseksi sekä tuonnissa että viennissä. Tallentamaton projekti ei vielä anna oletuskansiota.

## Erot ArcGIS Pro -versioon

- DWG-vienti tekee ensin DXF:n ja muuntaa sen ODA File Converterilla. Muuntimen komentorivikäyttö on testattu jäljitellyllä muuntimella; oikeaa ODA-asennusta ei ollut saatavilla paikalliseen lopputestiin.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska käyttöliittymä, aineiston käsittely ja käytettävissä olevat formaattiajurit eroavat ArcGIS Pro -versiosta. Molempien versioiden muutoksia ei voi olettaa automaattisesti samoiksi.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. QGIS 3.44:n Python-ympäristössä tehty toimintatesti: `qgis_plugin/smoke.py`.
