## Muuntaja QGIS 0.2.2

- Jäsensi tuonnin tallennustavat erillisiksi GeoPackage-tiedostoiksi, yhdeksi GeoPackageksi tai File Geodatabaseksi. Tiedostonvalitsin ja kentän ohjeteksti vaihtuvat tallennustavan mukaan.
- Siirsi CRS-, CAD- ja DFSU-valinnat lisäasetuksiin ja ottaa tiedostokohtaiset asetukset käyttöön vain, kun syöte voi sisältää kyseistä aineistoa.
- Selkeytti vientiasetuksia: yhdistetty tiedosto on tarjolla vain GPKG-, DXF- ja DWG-muodoille, ja ODA-muunnin näkyy vain DWG-viennissä.

## Muuntaja QGIS 0.2.1 — esijulkaisu

Uusi Windows-asennus: lataa `Muuntaja-QGIS-0.2.1-Windows.zip`, pura se ja suorita `install_windows.bat` QGISin ollessa suljettu. Asennin kopioi lisäosan QGIS-profiileihin ja aktivoi sen. Vaihtoehtoisesti asenna `Muuntaja-QGIS-0.2.1.zip` QGISin **Lisäosat → Hallitse ja asenna lisäosia → Asenna ZIP-tiedostosta** -toiminnolla. Vaatii QGIS 3.44:n.

Tässä versiossa toimivat kansio- ja tiedostotuonti, FileGDB/GPKG-kohteet, rasterien VRT-mosaiikki ryhmittäin, DFSU-tuonti `mikeio`-kirjastolla sekä GPKG-, GeoJSON-, Shapefile-, KML-, KMZ- ja DXF-vienti. Valinnainen DWG-vienti muuntaa DXF:n DWG:ksi ODA File Converterilla. QGIS 3.44:ssä on testattu näiden formaattien vienti, yhdistetty GPKG/DXF-vienti, CAD-tuonti, rasterimosaiikin uudelleenajo ja jäljitelty DFSU-suodatus. DWG-työnkulku on testattu jäljitellyllä ODA-muuntimella, ei oikealla asennuksella.

**Tämä ei vielä ole toiminnallisesti identtinen ArcGIS Pro -version kanssa.** DWG-vienti tarvitsee erillisen ODA File Converter -asennuksen. QGISin VRT-mosaiikki käyttää eri tallennusmuotoa kuin ArcGIS Pron FileGDB-mosaiikki. Tarkempi tilanne: [QGIS-ohje](https://github.com/roopepalom44/muuntaja/blob/main/qgis_plugin/README.md).
## Muuntaja QGIS 0.2.3

- Julkaistaan samassa GitHub-releasessa ArcGIS Pro AddInX:n kanssa sekä QGISin omana asennus-ZIPinä että Windows-asennus-ZIPinä.
- GeoJSON-vienti muuntaa koordinaatit WGS84:ään ja hylkää puuttuvan lähtökoordinaatiston. Tarkistettu QGIS 3.44:llä.
## Muuntaja QGIS 0.2.4

- Tallennetun QGIS-projektin kansio täyttyy oletuksena tuonnin ja viennin tallennuspaikaksi. GeoPackage- ja FileGDB-tallennustavat saavat tiedostonimen samasta kansiosta.

## Muuntaja QGIS 0.2.5

- Uudemman DWG:n tuonti käyttää ODA File Converteria varapolkuna, kun QGISin CAD-ajuri ei avaa tiedostoa. Virhe ilmoittaa DWG-version ja tarvittavan toimenpiteen.
- Lähtö-CRS voidaan pakottaa myös aineistolle, jolla on virheellinen CRS-merkintä. Puuttuva tai Suomen koordinaattiarvojen kanssa ristiriitainen CRS pysäyttää tuonnin selkeään virheeseen.

## Muuntaja QGIS 0.2.6

- Virheellinen CRS-merkintä tunnistetaan myös muista koordinaatistoista kuin EPSG:3857 ja EPSG:4326, kun aineiston koordinaatit osoittavat Suomeen mutta merkitty järjestelmä vie ne muualle.
- Suomen alueen EPSG:3857-koordinaatit tunnistetaan myös aineistoista, joilla CRS-merkintä puuttuu.

## Muuntaja QGIS 0.2.7

- Jos QGIS-projektilta puuttuu koordinaattijärjestelmä, tuonti asettaa sen ensimmäisen tuodun tason mukaan ennen tason lisäämistä. Tämä koskee vektori-, rasteri- ja DFSU-tasoja.
- Tuonnin valmistumisviesti kertoo, kun projektin CRS asetettiin automaattisesti.

## Muuntaja QGIS 0.3.0

- **DWG ja DXF natiivisti QGISissä.** Piirustus tuodaan ryhmäksi, jossa ovat tekstit, pisteet, viivat ja alueet omina tasoinaan. CAD-värit säilyvät, CAD-tasot näkyvät sisällysluettelossa päälle/pois kytkettävinä sääntöinä ja tekstit nimiöinä CAD-korkeudella, -kulmalla ja -ankkurilla. Paperitilan kohteet ohitetaan.
- DWG:n voi raahata suoraan QGIS-ikkunaan tai lisätä valikosta **Taso → Lisää taso → Lisää DWG/DXF-taso (Muuntaja)**. Jos koordinaatistoa ei voi päätellä, QGIS kysyy sen tavalliseen tapaan.
- DWG luetaan ODA File Converterilla tai LibreDWG:llä; AutoCAD 2000 -DWG avautuu myös ilman muunninta. ODA löytyy automaattisesti myös versionumerollisesta asennuskansiosta, ja valittu muunnin muistetaan.
- **DXF-vienti käyttää QGISin omaa DXF-vientiä:** symbologia, nimiöt ja tuotujen CAD-tasojen nimet säilyvät, ja eri koordinaatistoissa olevat tasot muunnetaan samaan koordinaatistoon (aiemmin yhdistetty vienti sekoitti ne). DWG-vienti löytyy myös valikosta **Projekti → Tuo/Vie**.
- DWG-vienti tarkistaa tuloksen otsakkeesta (aiemmin oikean ODA-muuntimen AutoCAD 2018 -tulos hylättiin virheellisesti). LibreDWG:n kokeellinen DWG-kirjoitus luetaan takaisin, ja jos kohteita puuttuu, vienti pysähtyy virheeseen.
- Korjattu: DFSU-taso avattiin väärällä nimellä GeoPackageen, jossa oli jo muita tasoja; rasterituonti poisti käyttäjän omia tasoja samannimisestä ryhmästä; GeoPackage-tasonimet vertaillaan kirjainkoosta riippumatta; projektista poistettu taso kaatoi viennin; kansioskannaus otti mukaan muitakin kuin paikkatieto-JSONeja.
- Muuntimen aikakatkaisu ja puuttuva muunnin näytetään selkeänä suomenkielisenä virheenä, eikä Windows avaa konsoli-ikkunaa muunnoksen ajaksi.
