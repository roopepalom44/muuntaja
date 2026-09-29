# Muuntaja QGIS (esijulkaisu 0.2.7)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Lataa [QGIS 0.2.7 -julkaisusta](https://github.com/roopepalom44/muuntaja/releases/tag/qgis-v0.2.7) `Muuntaja-QGIS-0.2.7-Windows.zip`, pura ZIP ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen.

**QGISin oma asennus:** Lataa samasta julkaisusta `Muuntaja-QGIS-0.2.7.zip` ja valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**. Jos vanhan projektin asetuksissa lukee **Ei koordinaattijärjestelmää**, valitse projektin CRS:ksi **EPSG:3067**, kun tasot ovat tässä järjestelmässä.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG ja georeferoidut rasterit. Uudempi DWG voidaan muuntaa tuonnin yhteydessä DXF:ksi, jos ODA File Converter on asennettu ja sen `.exe` on valittu lisäasetuksista.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS. Jos aineisto on merkitty väärään koordinaatistoon, valitse **Lisäasetukset → Lähtö-CRS (pakota)** ja anna aineiston todellinen järjestelmä, esimerkiksi `EPSG:3067`. Epäselvästä tai ristiriitaisesta CRS:stä näytetään virhe ennen tason lisäämistä. Jos itse aineiston CRS-merkintä oli väärä, aiemmin väärään paikkaan tallennetut tasot pitää tuoda uudelleen alkuperäisestä aineistosta.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti. DWG-vienti toimii valinnaisen ODA File Converter -ohjelman avulla: valitse ohjelman `.exe` vientinäkymässä. Myös yhdistetty DWG-vienti on käytettävissä.
- GeoJSON-vienti muuntaa tunnetun lähtökoordinaatiston WGS84:ään, kuten ArcGIS Pro -versio.
- Tallennetun QGIS-projektin kansio ehdotetaan oletukseksi sekä tuonnissa että viennissä. Tallentamaton projekti ei vielä anna oletuskansiota.

## Erot ArcGIS Pro -versioon

- DWG-vienti tekee ensin DXF:n ja muuntaa sen ODA File Converterilla. Muuntimen komentorivikäyttö on testattu jäljitellyllä muuntimella; oikeaa ODA-asennusta ei ollut saatavilla paikalliseen lopputestiin.
- Uudemman DWG:n tuonti käyttää samaa erikseen asennettavaa ODA File Converteria, jos QGISin CAD-ajuri ei avaa tiedostoa suoraan. Ilman sitä tiedosto voidaan ensin tallentaa DXF-muotoon CAD-ohjelmassa.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska käyttöliittymä, aineiston käsittely ja käytettävissä olevat formaattiajurit eroavat ArcGIS Pro -versiosta. Molempien versioiden muutoksia ei voi olettaa automaattisesti samoiksi.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. QGIS 3.44:n Python-ympäristön toimintatestit: `qgis_plugin/smoke.py` ja `qgis_plugin/smoke_spatial_imports.py` (kymmenen tuontimuotoa, GeoPackage- ja FileGDB-kohteet sekä vanhan ilman CRS-merkintää olevan TIFFin sijainti).
