## Muuntaja QGIS 0.1.0 — esijulkaisu

Asenna lataamalla `Muuntaja-QGIS-0.1.0.zip` ja valitsemalla QGISissä **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta**. Vaatii QGIS 3.44:n.

Tässä versiossa toimivat kansio- ja tiedostotuonti, FileGDB/GPKG-kohteet, rasterien ryhmittely, DFSU-tuonti `mikeio`-kirjastolla sekä GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-vienti. QGIS 3.44:ssä on testattu näiden formaattien vienti, yhdistetty GPKG/DXF-vienti, CAD-tuonti, rasteriryhmä ja jäljitelty DFSU-suodatus.

**Tämä ei vielä ole toiminnallisesti identtinen ArcGIS Pro -version kanssa.** DWG-vienti tarvitsee erillisen DWG-kirjoittimen; automaattinen rasterimosaiikki puuttuu. Tarkempi tilanne: [QGIS-ohje](https://github.com/roopepalom44/muuntaja/blob/main/qgis_plugin/README.md).
