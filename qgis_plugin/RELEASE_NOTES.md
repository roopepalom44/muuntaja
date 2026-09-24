## Muuntaja QGIS 0.2.2

- Jäsensi tuonnin tallennustavat erillisiksi GeoPackage-tiedostoiksi, yhdeksi GeoPackageksi tai File Geodatabaseksi. Tiedostonvalitsin ja kentän ohjeteksti vaihtuvat tallennustavan mukaan.
- Siirsi CRS-, CAD- ja DFSU-valinnat lisäasetuksiin ja ottaa tiedostokohtaiset asetukset käyttöön vain, kun syöte voi sisältää kyseistä aineistoa.
- Selkeytti vientiasetuksia: yhdistetty tiedosto on tarjolla vain GPKG-, DXF- ja DWG-muodoille, ja ODA-muunnin näkyy vain DWG-viennissä.

## Muuntaja QGIS 0.2.1 — esijulkaisu

Uusi Windows-asennus: lataa `Muuntaja-QGIS-0.2.1-Windows.zip`, pura se ja suorita `install_windows.bat` QGISin ollessa suljettu. Asennin kopioi lisäosan QGIS-profiileihin ja aktivoi sen. Vaihtoehtoisesti asenna `Muuntaja-QGIS-0.2.1.zip` QGISin **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta** -toiminnolla. Vaatii QGIS 3.44:n.

Tässä versiossa toimivat kansio- ja tiedostotuonti, FileGDB/GPKG-kohteet, rasterien VRT-mosaiikki ryhmittäin, DFSU-tuonti `mikeio`-kirjastolla sekä GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-vienti. Valinnainen DWG-vienti muuntaa DXF:n DWG:ksi ODA File Converterilla. QGIS 3.44:ssä on testattu näiden formaattien vienti, yhdistetty GPKG/DXF-vienti, CAD-tuonti, rasterimosaiikin uudelleenajo ja jäljitelty DFSU-suodatus. DWG-työnkulku on testattu jäljitellyllä ODA-muuntimella, ei oikealla asennuksella.

**Tämä ei vielä ole toiminnallisesti identtinen ArcGIS Pro -version kanssa.** DWG-vienti tarvitsee erillisen ODA File Converter -asennuksen. QGISin VRT-mosaiikki käyttää eri tallennusmuotoa kuin ArcGIS Pron FileGDB-mosaiikki. Tarkempi tilanne: [QGIS-ohje](https://github.com/roopepalom44/muuntaja/blob/main/qgis_plugin/README.md).
