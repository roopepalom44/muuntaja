# Muuntaja QGIS (kehitysversio 0.2.8)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Rakenna paketti komennolla `python qgis_plugin/package.py`, pura `qgis_plugin/dist/Muuntaja-QGIS-0.2.8-Windows.zip` ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen. Paketti sisältää DWG-tuontimuuntimen.

**QGISin oma asennus:** Valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta** ja osoita `qgis_plugin/dist/Muuntaja-QGIS-0.2.8.zip`. Windowsissa myös tämä paketti sisältää DWG-tuontimuuntimen. Jos vanhan projektin asetuksissa lukee **Ei koordinaattijärjestelmää**, valitse projektin CRS:ksi **EPSG:3067**, kun tasot ovat tässä järjestelmässä.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG ja georeferoidut rasterit. DWG avataan ensin QGISin CAD-ajurilla. Jos ajuri ei tue tiedostoa, Windows-pakettiin sisältyvä LibreDWG muuntaa sen automaattisesti tilapäiseksi DXF:ksi. Muuntimen polkua ei tarvitse valita.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS. Jos aineisto on merkitty väärään koordinaatistoon, valitse **Lisäasetukset → Lähtö-CRS (pakota)** ja anna aineiston todellinen järjestelmä, esimerkiksi `EPSG:3067`. Epäselvästä tai ristiriitaisesta CRS:stä näytetään virhe ennen tason lisäämistä. Jos itse aineiston CRS-merkintä oli väärä, aiemmin väärään paikkaan tallennetut tasot pitää tuoda uudelleen alkuperäisestä aineistosta.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti. DWG-vienti käyttää automaattisesti asennettua ODA File Converteria; sen polkua ei valita käyttöliittymässä. Myös yhdistetty DWG-vienti on käytettävissä, kun ODA on asennettu.
- GeoJSON-vienti muuntaa tunnetun lähtökoordinaatiston WGS84:ään, kuten ArcGIS Pro -versio.
- Tallennetun QGIS-projektin kansio ehdotetaan oletukseksi sekä tuonnissa että viennissä. Tallentamaton projekti ei vielä anna oletuskansiota.

## Erot ArcGIS Pro -versioon

- DWG-vienti tekee ensin DXF:n ja muuntaa sen automaattisesti löydetyllä ODA File Converterilla. Muuntimen komentorivikäyttö on testattu jäljitellyllä muuntimella; oikeaa ODA-asennusta ei ollut saatavilla paikalliseen lopputestiin. Paketoitua LibreDWG:tä ei käytetä vientiin, koska sen kirjoittama testitiedosto ei auennut QGISissä.
- Uudemman DWG:n tuonti käyttää paketoitua LibreDWG 0.14 -ohjelmaa, jos QGISin CAD-ajuri ei avaa tiedostoa. ODA:ta käytetään tuonnissa automaattisena varavaihtoehtona vain, jos LibreDWG-muunnos epäonnistuu ja ODA on jo asennettu. Monimutkaiset CAD-objektit eivät välttämättä siirry täydellisesti.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska käyttöliittymä, aineiston käsittely ja käytettävissä olevat formaattiajurit eroavat ArcGIS Pro -versiosta. Molempien versioiden muutoksia ei voi olettaa automaattisesti samoiksi.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. Skripti hakee LibreDWG 0.14:n viralliset Windows-binaarit ja lähdekoodin, tarkistaa SHA-256-tiivisteet ja sisällyttää DWG-tuonnin tarvitsemat tiedostot sekä GPLv3-lisenssin ja lähdekoodin kumpaankin ZIP-pakettiin. QGIS 3.44:n Python-ympäristön toimintatestit: `qgis_plugin/smoke.py` ja `qgis_plugin/smoke_spatial_imports.py`.
