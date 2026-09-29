# Muuntaja QGIS (esijulkaisu 0.3.0)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Lataa uusin [Muuntaja-QGIS-Windows.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS-Windows.zip), pura ZIP ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen.

**QGISin oma asennus:** Lataa [Muuntaja-QGIS.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS.zip) ja valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**. Jos vanhan projektin asetuksissa lukee **Ei koordinaattijärjestelmää**, valitse projektin CRS:ksi **EPSG:3067**, kun tasot ovat tässä järjestelmässä.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG ja georeferoidut rasterit.
- **DWG/DXF kuin QGISin oma taso:** piirustus tuodaan ryhmäksi (tekstit, pisteet, viivat, alueet), CAD-värit säilyvät, CAD-tasot ovat sisällysluettelossa päälle/pois kytkettäviä sääntöjä ja tekstit nimiöitä CAD-korkeudella ja -kulmalla. DWG:n voi raahata QGIS-ikkunaan tai lisätä valikosta **Taso → Lisää taso → Lisää DWG/DXF-taso (Muuntaja)**; tulos tallentuu projektikansion `muuntaja_tuonti.gpkg`:hen (tallentamattomassa projektissa DWG:n viereen). Kentät `cad_layer`, `cad_color`, `entity`, `handle`, `linetype` ja tekstitiedot säilyvät ominaisuustietoina.
- DWG luetaan ilmaisella ODA File Converterilla (löytyy automaattisesti, myös versionumerollisesta kansiosta) tai LibreDWG:n `dwg2dxf`:llä. AutoCAD 2000 -DWG avautuu myös ilman muunninta, mutta silloin GDAL:n CAD-ajuri jättää täytöt (HATCH) ja lohkoviittaukset (INSERT) pois; täydelliseen tuontiin tarvitaan muunnin.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS. Jos aineisto on merkitty väärään koordinaatistoon, valitse **Lisäasetukset → Lähtö-CRS (pakota)** ja anna aineiston todellinen järjestelmä, esimerkiksi `EPSG:3067`. Epäselvästä tai ristiriitaisesta CRS:stä näytetään virhe ennen tason lisäämistä. Jos itse aineiston CRS-merkintä oli väärä, aiemmin väärään paikkaan tallennetut tasot pitää tuoda uudelleen alkuperäisestä aineistosta.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ-, DXF- ja DWG-muotoon. Yhdistetty GPKG-, DXF- ja DWG-vienti.
- DXF/DWG-vienti käyttää QGISin omaa DXF-vientiä: tasojen symbologia (kartan nykyisessä mittakaavassa), nimiöt tekstikohteina ja tuotujen CAD-tasojen alkuperäiset nimet säilyvät, ja kaikki tasot muunnetaan projektin koordinaatistoon. DWG tehdään DXF:stä ODA File Converterilla (AutoCAD 2018 -DWG) tai LibreDWG:n `dxf2dwg`:llä. LibreDWG:n DWG-kirjoitus on kokeellinen: tulos luetaan takaisin ja hylätään, jos kohteita puuttuu – luotettavaan DWG-vientiin suositellaan ODA File Converteria. LibreDWG:n kirjoittama DWG voi kaataa ArcGIS Pron (testattu ArcGIS Pro 3.7:llä), joten ArcGIS-käyttöön vie DXF tai käytä ODA-muunninta. Vienti on myös valikossa **Projekti → Tuo/Vie**.
- GeoJSON-vienti muuntaa tunnetun lähtökoordinaatiston WGS84:ään, kuten ArcGIS Pro -versio.
- Tallennetun QGIS-projektin kansio ehdotetaan oletukseksi sekä tuonnissa että viennissä. Tallentamaton projekti ei vielä anna oletuskansiota.

## Erot ArcGIS Pro -versioon

- DWG-tuki tarvitsee erillisen DWG-muuntimen (ODA File Converter tai LibreDWG), koska QGIS ja GDAL lukevat DWG:stä vain AutoCAD 2000 -version. Tuonti on testattu LibreDWG:llä ja oikeilla DWG/DXF-tiedostoilla; ODA File Converterin komentorivikäyttö on testattu jäljitellyllä muuntimella.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska käyttöliittymä, aineiston käsittely ja käytettävissä olevat formaattiajurit eroavat ArcGIS Pro -versiosta. Molempien versioiden muutoksia ei voi olettaa automaattisesti samoiksi.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py`. Yksikkötestit ajetaan QGISin Pythonilla: `python -m unittest discover -s tests` (Linuxissa `QT_QPA_PLATFORM=offscreen`); CI ajaa ne jokaisessa pull requestissa. Lisäksi `qgis_plugin/smoke_spatial_imports.py` tarkistaa, että jokainen tuontimuoto osuu Suomeen (Windowsissa QGISin asennuspolun voi antaa ympäristömuuttujalla `QGIS_PREFIX_PATH`).
