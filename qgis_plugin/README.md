# Muuntaja QGIS (esijulkaisu 0.4.1)

QGIS 3.44:lle tehty erillinen, natiivi Python-lisäosa. ArcGIS Pro -laajennus pysyy samassa projektissa.

## Asennus

**Windows, suoraviivainen asennus:** Lataa uusin [Muuntaja-QGIS-Windows.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS-Windows.zip), pura ZIP ja kaksoisnapsauta `install_windows.bat`. Sulje QGIS ennen asennusta. Asennin kopioi lisäosan käyttäjän kaikkiin olemassa oleviin QGIS 3 -profiileihin (tai luo `default`-profiilin) ja ottaa lisäosan käyttöön. Käynnistä QGIS asennuksen jälkeen.

**QGISin oma asennus:** Lataa [Muuntaja-QGIS.zip](https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja-QGIS.zip) ja valitse QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**. Jos vanhan projektin asetuksissa lukee **Ei koordinaattijärjestelmää**, valitse projektin CRS:ksi **EPSG:3067**, kun tasot ovat tässä järjestelmässä.

## Toimii tässä versiossa

- Kansion ja alikansioiden sekä yksittäisten tiedostojen tuonti: GPKG, GeoJSON, KML/KMZ, GPX, SHP, DXF, DWG ja georeferoidut rasterit.
- **DWG/DXF kuin QGISin oma taso:** piirustus tuodaan ryhmäksi (tekstit, pisteet, viivat, alueet), CAD-värit säilyvät, CAD-tasot ovat sisällysluettelossa päälle/pois kytkettäviä sääntöjä ja tekstit nimiöitä CAD-korkeudella ja -kulmalla. DWG:n voi raahata QGIS-ikkunaan tai lisätä valikosta **Taso → Lisää taso → Lisää DWG/DXF-taso (Muuntaja)**; tulos tallentuu projektikansion `muuntaja_tuonti.gpkg`:hen (tallentamattomassa projektissa DWG:n viereen). Kentät `cad_layer`, `cad_color`, `entity`, `handle`, `linetype` ja tekstitiedot säilyvät ominaisuustietoina.
- **DWG toimii Windowsissa ilman asennuksia:** lisäosan mukana tulee avoimen lähdekoodin [LibreDWG 0.14](https://github.com/LibreDWG/libredwg) (GPL-3, kansio `muuntaja_qgis/libredwg`), joka lukee DWG-versiot AutoCAD 2000–2018. Testattu ArcGIS Pron kirjoittamilla DWG 2000-, 2004-, 2007-, 2010-, 2013- ja 2018-tiedostoilla: tekstit, CAD-tasot, värit ja täytöt säilyvät. Linuxissa ja macOS:ssä käytetään järjestelmään asennettua LibreDWG:tä (`dwg2dxf`); ilman sitä avautuu vain AutoCAD 2000 -DWG GDAL:n CAD-ajurilla, joka jättää täytöt (HATCH) ja lohkoviittaukset (INSERT) pois.
- Vektorien tuonti GeoPackageen, FileGDB:hen tai kohdekansion erillisiin GeoPackage-tiedostoihin.
- Rasterien ryhmittely `taustakartta_`-kansion mukaan, yhden VRT-mosaiikin rakentaminen ryhmää kohti, viittaus alkuperäisiin rastereihin ja duplikaattien ohitus.
- Suomen koordinaatiston tunnistus koordinaateista sekä valinnainen lähtö- ja kohde-CRS. Jos aineisto on merkitty väärään koordinaatistoon, valitse **Lisäasetukset → Lähtö-CRS (pakota)** ja anna aineiston todellinen järjestelmä, esimerkiksi `EPSG:3067`. Epäselvästä tai ristiriitaisesta CRS:stä näytetään virhe ennen tason lisäämistä. Jos itse aineiston CRS-merkintä oli väärä, aiemmin väärään paikkaan tallennetut tasot pitää tuoda uudelleen alkuperäisestä aineistosta.
- DFSU-tuonti ensimmäisestä aika-askeleesta ja sarakesuodatus. Tämä vaatii erikseen `mikeio`-kirjaston QGISin Python-ympäristöön.
- Projektin vektoritasojen vienti GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-muotoon. Yhdistetty GPKG- ja DXF-vienti.
- DXF-vienti käyttää QGISin omaa DXF-vientiä: tasojen symbologia (kartan nykyisessä mittakaavassa), nimiöt tekstikohteina ja tuotujen CAD-tasojen alkuperäiset nimet säilyvät, ja kaikki tasot muunnetaan projektin koordinaatistoon. Vienti on myös valikossa **Projekti → Tuo/Vie**.
- **DWG-vientiä ei ole.** QGIS ei kirjoita DWG:tä, eikä LibreDWG kirjoita siihen viivoja, pisteitä eikä tekstejä (testattu LibreDWG 0.14:llä). Vie CAD-aineisto DXF-muotoon: AutoCAD, ArcGIS ja QGIS avaavat sen sellaisenaan.
- **Kohdekoordinaatisto viennissä:** vientiin voi valita koordinaatiston, johon aineisto muunnetaan: ETRS-TM35FIN, ETRS-GK19–GK31 (esim. EUREF-FIN / ETRS-GK23), KKJ-kaistat, WGS 84, Web Mercator tai **Muu koordinaatisto…** QGISin omasta valitsimesta. Muunnos koskee GPKG-, Shapefile-, GeoJSON- ja DXF-vientiä; KML/KMZ on standardin mukaan aina WGS84. Oletus on **Tason oma**; GeoJSON viedään ilman valintaa WGS84:ään, kuten ArcGIS Pro -versio. Usean tason viennissä jokainen taso säilyttää oman koordinaatistonsa ("Tason oma"), eikä tasoja projisoida ensimmäisen tason koordinaatistoon. Yhteen DXF-tiedostoon mahtuu vain yksi koordinaatisto, joten eri koordinaatistoissa olevat tasot vaativat joko kohdekoordinaatiston tai oman tiedoston jokaiselle tasolle; muuten vienti pysähtyy ja kertoo tämän.
- **Tyyli mukaan:** valinta **Pakkaa tasojen tyylit mukaan** (oletuksena päällä). GeoPackageen tason tyyli tallennetaan sisäisesti (`layer_styles`, oletustyyli), joten QGIS avaa tason samalla tyylillä. Shapefilen ja GeoJSONin viereen kirjoitetaan samanniminen `.qml`, jonka QGIS lataa automaattisesti, ja KML/KMZ saa tyylit mukaan. QGIS ei osaa kirjoittaa ArcGISin `.lyrx`-tiedostoa; ArcGIS-tyylin saa ArcGIS Pro -version viennistä.
- **Tyyli tuonnissa:** kun tuotavalla Shapefilellä tai GeoJSONilla on vieressään samanniminen `.qml` tai GeoPackagessa on tasolle tallennettu tyyli, tuotu taso saa saman tyylin, ja tyyli tallennetaan myös tuonnin GeoPackageen oletustyyliksi. Muuntajan omat viennit tuodaan siis takaisin tyyleineen. (QGIS lataa `.qml`:n ja GeoPackagen tyylin automaattisesti myös, kun tiedoston avaa QGISissä suoraan.)
- Tallennetun QGIS-projektin kansio ehdotetaan oletukseksi sekä tuonnissa että viennissä. Tallentamaton projekti ei vielä anna oletuskansiota.

## Erot ArcGIS Pro -versioon

- DWG luetaan LibreDWG:llä, koska QGIS ei tarjoa DWG-lukua lisäosille: GDAL lukee vain AutoCAD 2000 -DWG:n, ja QGISin oma **Projekti → Tuo/Vie → Tuo tasot DWG/DXF:stä** ei ole Python-rajapinnassa eikä lue AutoCAD 2018 -muotoa (testattu QGIS 3.44:llä: tyhjä tulos). ODA File Converteria ei käytetä: se on suljettu ohjelma, jota ei saa jakaa lisäosan mukana.
- ArcGIS Pro -versio vie myös DWG-muotoon; QGIS-lisäosa vie CAD-aineiston DXF-muotoon.
- QGISin VRT-mosaiikki on eri tallennusmuoto kuin ArcGIS Pron FileGDB-mosaiikkiaineisto. Se viittaa alkuperäisiin rasteritiedostoihin.
- DFSU-tuontia on testattu jäljitellyllä `mikeio`-aineistolla, ei oikealla DFSU-tiedostolla.
- QGISin ja ArcGIS Pron vientiajurien erot voivat muuttaa joidenkin attribuuttien nimiä ja tyyppejä.

Lisäosa on merkitty esijulkaisuksi, koska käyttöliittymä, aineiston käsittely ja käytettävissä olevat formaattiajurit eroavat ArcGIS Pro -versiosta. Molempien versioiden muutoksia ei voi olettaa automaattisesti samoiksi.

## Kehitys ja testaus

Paketointi: `python qgis_plugin/package.py` (ZIPiin tulee myös LibreDWG:n Windows-lukija; päivitysohje ja tarkistussummat: `muuntaja_qgis/libredwg/README.txt`). Yksikkötestit ajetaan QGISin Pythonilla: `python -m unittest discover -s tests` (Linuxissa `QT_QPA_PLATFORM=offscreen`); CI ajaa ne jokaisessa pull requestissa. Lisäksi `qgis_plugin/smoke_spatial_imports.py` tarkistaa, että jokainen tuontimuoto osuu Suomeen (Windowsissa QGISin asennuspolun voi antaa ympäristömuuttujalla `QGIS_PREFIX_PATH`).
